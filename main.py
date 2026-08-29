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

# Import Pure Python Vector Engine
from memory import search_similar_incident, store_incident

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(
    title="Autonomous SRE Swarm AI (Memory-Augmented)",
    description="Multi-Agent Incident Remediation Engine with Vector RAG"
)

# ----------------- Enable CORS -----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Data Models -----------------
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

# ----------------- LangGraph State -----------------
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

# ----------------- Sandbox Execution -----------------
def execute_in_sandbox(code: str, language: str) -> tuple[bool, str]:
    lang = language.lower().strip()
    suffix_map = {"python": ".py", "javascript": ".js", "go": ".go"}
    suffix = suffix_map.get(lang, ".py")
    
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w', encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name

    try:
        if lang == "python":
            cmd = ["python", temp_file]
        elif lang in ["javascript", "js"]:
            cmd = ["node", temp_file]
        elif lang == "go":
            cmd = ["go", "run", temp_file]
        else:
            cmd = ["python", temp_file]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return True, res.stdout.strip() if res.stdout else "Execution succeeded without stdout."
        else:
            return False, f"Runtime Exit Code {res.returncode}:\n{res.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "Execution timed out (infinite loop detected)."
    except Exception as e:
        return False, f"Sandbox failure: {str(e)}"
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

# ----------------- Multi-Agent Nodes -----------------
def coder_agent_node(state: AgentState) -> AgentState:
    model = genai.GenerativeModel("gemini-3.6-flash")
    
    similar_memory = search_similar_incident(state["error_log"], state["language"])
    memory_prompt = f"\n[RAG MEMORY - SIMILAR PAST INCIDENT FIX]:\n{similar_memory}\nUse this past fix as reference.\n" if similar_memory else ""
    retry_context = f"\n[PREVIOUS ATTEMPT FAILED]:\n{state['test_output']}\nFix logic accordingly." if state["retries"] > 0 else ""

    prompt = f"""
    You are an expert SRE Coder Agent. A production service crashed.
    Provide a self-healing, production-grade code patch.
    Language: {state['language']}
    Broken Code:
    {state['broken_code']}
    Stack Trace:
    {state['error_log']}
    {memory_prompt}
    {retry_context}
    RULES:
    1. Output ONLY executable raw code without markdown backticks.
    2. Add defensive coding, logging, and null checks.
    3. Include self-verifying test cases with assertions at the bottom.
    """
    
    response = model.generate_content(prompt)
    clean_code = response.text.replace("```python", "").replace("```javascript", "").replace("```go", "").replace("```", "").strip()
    
    state["current_patch"] = clean_code
    state["memory_context"] = similar_memory
    return state

def tester_agent_node(state: AgentState) -> AgentState:
    is_success, output = execute_in_sandbox(state["current_patch"], state["language"])
    state["test_output"] = output
    state["retries"] += 1
    state["status"] = "RESOLVED" if is_success else "FAILED"
    return state

def should_continue(state: AgentState) -> str:
    return "reporter" if (state["status"] == "RESOLVED" or state["retries"] >= 3) else "coder"

def reporter_agent_node(state: AgentState) -> AgentState:
    if state["status"] == "RESOLVED":
        store_incident(state["error_log"], state["current_patch"], state["language"])
        
        model = genai.GenerativeModel("gemini-3.6-flash")
        prompt = f"""
        Generate a 3-bullet SRE Root Cause Analysis (RCA):
        - Root Cause Analysis: What failed and why.
        - Fix Summary: What guard clauses were applied.
        - Verification: Confirm tests passed.
        Error Log: {state['error_log']}
        Sandbox Output: {state['test_output']}
        """
        res = model.generate_content(prompt)
        state["rca_report"] = res.text.strip()
    else:
        state["rca_report"] = "ESCALATED: Max retries exhausted without resolution."
        
    return state

# ----------------- LangGraph Workflow -----------------
workflow = StateGraph(AgentState)
workflow.add_node("coder", coder_agent_node)
workflow.add_node("tester", tester_agent_node)
workflow.add_node("reporter", reporter_agent_node)

workflow.set_entry_point("coder")
workflow.add_edge("coder", "tester")
workflow.add_conditional_edges("tester", should_continue, {"coder": "coder", "reporter": "reporter"})
workflow.add_edge("reporter", END)
sre_app = workflow.compile()

# ----------------- FastAPI Endpoints -----------------
@app.get("/")
def serve_dashboard():
    return FileResponse("index.html")

@app.post("/triage", response_model=IncidentResponse)
def triage_incident(req: IncidentRequest):
    try:
        initial_state: AgentState = {
            "language": req.language,
            "broken_code": req.broken_code,
            "error_log": req.error_log,
            "current_patch": "",
            "test_output": "",
            "retries": 0,
            "status": "TRIAGING",
            "rca_report": "",
            "memory_context": ""
        }
        final_state = sre_app.invoke(initial_state)
        return IncidentResponse(
            status=final_state["status"],
            language=final_state["language"],
            retries_used=final_state["retries"],
            sandbox_execution_output=final_state["test_output"],
            verified_code_patch=final_state["current_patch"],
            rca_post_mortem=final_state["rca_report"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRE Swarm Internal Error: {str(e)}")