import os
import subprocess
import tempfile
from typing import TypedDict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
from langgraph.graph import StateGraph, END

from memory import search_similar_incident, store_incident

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="SRE Swarm AI Polyglot Engine")

# Universal CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request & Response Models
class IncidentRequest(BaseModel):
    language: str
    broken_code: str
    error_log: str

class IncidentResponse(BaseModel):
    status: str
    language: str
    retries_used: int
    sandbox_execution_output: str
    verified_code_patch: str
    rca_post_mortem: str

class AgentState(TypedDict):
    language: str
    broken_code: str
    error_log: str
    current_patch: str
    test_output: str
    retries: int
    status: str
    rca_report: str
    memory_context: Optional[str]

# ----------------- 7-Language Polyglot Sandbox Execution -----------------
def execute_in_sandbox(code: str, language: str) -> tuple[bool, str]:
    lang = language.lower().strip()
    suffix_map = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "go": ".go",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp"
    }
    suffix = suffix_map.get(lang, ".py")
    
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w', encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name

    try:
        if lang == "python":
            cmd = ["python", temp_file]
        elif lang in ["javascript", "js"]:
            cmd = ["node", temp_file]
        elif lang in ["typescript", "ts"]:
            cmd = ["npx", "ts-node", temp_file]
        elif lang == "go":
            cmd = ["go", "run", temp_file]
        elif lang in ["c", "cpp"]:
            out_bin = temp_file + ".out"
            compiler = "g++" if lang == "cpp" else "gcc"
            compile_res = subprocess.run([compiler, temp_file, "-o", out_bin], capture_output=True, text=True, timeout=10)
            if compile_res.returncode != 0:
                return False, f"Compilation Failed:\n{compile_res.stderr.strip()}"
            cmd = [out_bin]
        elif lang == "java":
            compile_res = subprocess.run(["javac", temp_file], capture_output=True, text=True, timeout=10)
            if compile_res.returncode != 0:
                return False, f"Java Compilation Failed:\n{compile_res.stderr.strip()}"
            class_name = os.path.splitext(os.path.basename(temp_file))[0]
            cmd = ["java", "-cp", os.path.dirname(temp_file), class_name]
        else:
            cmd = ["python", temp_file]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return True, res.stdout.strip() or "All sandbox verification tests passed."
        return False, res.stderr.strip() or f"Runtime execution failed with code {res.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Execution timed out (infinite loop protection triggered)."
    except Exception as e:
        return False, f"Sandbox error: {str(e)}"
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

# ----------------- Multi-Agent Nodes -----------------
def coder_node(state: AgentState) -> AgentState:
    model = genai.GenerativeModel("gemini-3.6-flash")
    memory = search_similar_incident(state["error_log"], state["language"])
    
    prompt = f"""
    You are an expert SRE Polyglot Coder Agent. Fix this production crash.
    Language: {state['language']}
    Code: {state['broken_code']}
    Error: {state['error_log']}
    Past Similar Fix Reference: {memory}
    
    RULES:
    1. Output ONLY valid executable raw code without markdown backticks.
    2. Add boundary checks, defensive fallbacks, and logging.
    3. Include self-verifying test cases with assertions at the bottom.
    """
    res = model.generate_content(prompt)
    clean = res.text.replace("```python", "").replace("```javascript", "").replace("```typescript", "").replace("```go", "").replace("```java", "").replace("```c", "").replace("```cpp", "").replace("```", "").strip()
    state["current_patch"] = clean
    return state

def tester_node(state: AgentState) -> AgentState:
    passed, out = execute_in_sandbox(state["current_patch"], state["language"])
    state["test_output"] = out
    state["retries"] += 1
    state["status"] = "RESOLVED" if passed else "FAILED"
    return state

def should_continue(state: AgentState) -> str:
    return "reporter" if (state["status"] == "RESOLVED" or state["retries"] >= 3) else "coder"

def reporter_node(state: AgentState) -> AgentState:
    if state["status"] == "RESOLVED":
        store_incident(state["error_log"], state["current_patch"], state["language"])
        model = genai.GenerativeModel("gemini-3.6-flash")
        res = model.generate_content(f"Provide concise 3-bullet SRE Root Cause Analysis:\nError: {state['error_log']}\nOutput: {state['test_output']}")
        state["rca_report"] = res.text.strip()
    else:
        state["rca_report"] = "ESCALATED: Max retries exceeded without resolution."
    return state

# ----------------- LangGraph Workflow -----------------
wf = StateGraph(AgentState)
wf.add_node("coder", coder_node)
wf.add_node("tester", tester_node)
wf.add_node("reporter", reporter_node)
wf.set_entry_point("coder")
wf.add_edge("coder", "tester")
wf.add_conditional_edges("tester", should_continue, {"coder": "coder", "reporter": "reporter"})
wf.add_edge("reporter", END)
sre_engine = wf.compile()

# Absolute path for HTML
HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")

@app.get("/")
def home():
    if os.path.exists(HTML_PATH):
        return FileResponse(HTML_PATH)
    return {"message": "SRE Swarm Backend is active."}

@app.post("/triage", response_model=IncidentResponse)
@app.post("/triage/", response_model=IncidentResponse)
def triage(req: IncidentRequest):
    try:
        init_state: AgentState = {
            "language": req.language, "broken_code": req.broken_code, "error_log": req.error_log,
            "current_patch": "", "test_output": "", "retries": 0, "status": "TRIAGING",
            "rca_report": "", "memory_context": ""
        }
        res = sre_engine.invoke(init_state)
        return IncidentResponse(
            status=res["status"], language=res["language"], retries_used=res["retries"],
            sandbox_execution_output=res["test_output"], verified_code_patch=res["current_patch"],
            rca_post_mortem=res["rca_report"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))