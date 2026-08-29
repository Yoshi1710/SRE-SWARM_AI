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

# Gemini Config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="SRE Swarm AI")

# CORS Allow (Browser connection block na ho)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request / Response Schemas
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

# Sandbox Code Runner
def execute_in_sandbox(code: str, language: str) -> tuple[bool, str]:
    lang = language.lower().strip()
    suffix_map = {"python": ".py", "javascript": ".js", "go": ".go"}
    suffix = suffix_map.get(lang, ".py")
    
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w', encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name

    try:
        cmd = ["python", temp_file] if lang == "python" else (["node", temp_file] if lang in ["javascript", "js"] else ["go", "run", temp_file])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return True, res.stdout.strip() or "All sandbox tests passed."
        return False, res.stderr.strip() or "Runtime execution failed."
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

# AI Nodes
def coder_node(state: AgentState) -> AgentState:
    model = genai.GenerativeModel("gemini-3.6-flash")
    memory = search_similar_incident(state["error_log"], state["language"])
    
    prompt = f"""
    You are an expert SRE Coder Agent. Fix this code crash.
    Language: {state['language']}
    Code: {state['broken_code']}
    Error: {state['error_log']}
    Past Similar Fix Reference: {memory}
    
    Output ONLY valid executable code without markdown tags. Include assertions at the bottom to verify.
    """
    res = model.generate_content(prompt)
    clean = res.text.replace("```python", "").replace("```javascript", "").replace("```go", "").replace("```", "").strip()
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
        res = model.generate_content(f"Provide 3-bullet SRE Root Cause Analysis:\nError: {state['error_log']}\nOutput: {state['test_output']}")
        state["rca_report"] = res.text.strip()
    else:
        state["rca_report"] = "ESCALATED: Max retries exceeded."
    return state

# LangGraph Workflow Setup
wf = StateGraph(AgentState)
wf.add_node("coder", coder_node)
wf.add_node("tester", tester_node)
wf.add_node("reporter", reporter_node)
wf.set_entry_point("coder")
wf.add_edge("coder", "tester")
wf.add_conditional_edges("tester", should_continue, {"coder": "coder", "reporter": "reporter"})
wf.add_edge("reporter", END)
sre_engine = wf.compile()

# Routes
@app.get("/")
def home():
    return FileResponse("index.html")

@app.post("/triage")
@app.post("/triage/")
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