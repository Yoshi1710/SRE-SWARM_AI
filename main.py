import os
import re
import difflib
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

app = FastAPI(title="SRE Swarm AI Enterprise Diff Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ACTIVE_MODEL_NAME = None

def get_active_model_name() -> str:
    """Google API se available models dynamically discover karta hai."""
    global ACTIVE_MODEL_NAME
    if ACTIVE_MODEL_NAME:
        return ACTIVE_MODEL_NAME

    candidate_preferences = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-flash-latest",
        "gemini-1.5-pro-latest",
        "gemini-1.5-pro",
        "gemini-pro"
    ]

    try:
        available_models = [
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        print(f"[Gemini Discovery]: Available on this key: {available_models}")

        for pref in candidate_preferences:
            if pref in available_models:
                ACTIVE_MODEL_NAME = pref
                print(f"[Gemini Discovery]: Selected primary model -> {ACTIVE_MODEL_NAME}")
                return ACTIVE_MODEL_NAME

        if available_models:
            ACTIVE_MODEL_NAME = available_models[0]
            print(f"[Gemini Discovery]: Selected fallback model -> {ACTIVE_MODEL_NAME}")
            return ACTIVE_MODEL_NAME
    except Exception as e:
        print(f"[Gemini Discovery Error]: {e}")

    ACTIVE_MODEL_NAME = "gemini-1.5-flash-latest"
    return ACTIVE_MODEL_NAME

def call_gemini_safe(prompt: str) -> str:
    """Multi-model fallback logic taaki kabhi 404 ya crash na ho."""
    primary = get_active_model_name()
    fallbacks = [primary, "gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-pro"]
    
    seen = set()
    unique_models = [m for m in fallbacks if not (m in seen or seen.add(m))]

    last_error = None
    for model_id in unique_models:
        try:
            model = genai.GenerativeModel(model_id, generation_config={"temperature": 0.1})
            res = model.generate_content(prompt)
            if res and res.text:
                return res.text.strip()
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"All model fallbacks exhausted: {last_error}")

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
    unified_diff: str
    rca_post_mortem: str

class AgentState(TypedDict):
    language: str
    broken_code: str
    error_log: str
    current_patch: str
    unified_diff: str
    test_output: str
    retries: int
    status: str
    rca_report: str
    cached_hit: bool

def execute_in_sandbox(code: str, language: str) -> tuple[bool, str]:
    lang = language.lower().strip()
    suffix_map = {
        "python": ".py", "javascript": ".js", "typescript": ".js",
        "go": ".go", "java": ".java", "c": ".c", "cpp": ".cpp"
    }
    suffix = suffix_map.get(lang, ".py")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w', encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name

    try:
        if lang == "python":
            cmd = ["python3", temp_file]
        elif lang in ["javascript", "js", "typescript"]:
            cmd = ["node", temp_file]
        elif lang == "go":
            cmd = ["go", "run", temp_file]
        elif lang in ["c", "cpp"]:
            out_bin = temp_file + ".out"
            compiler = "g++" if lang == "cpp" else "gcc"
            compile_res = subprocess.run([compiler, temp_file, "-o", out_bin], capture_output=True, text=True, timeout=10)
            if compile_res.returncode != 0:
                return False, compile_res.stderr.strip()
            cmd = [out_bin]
        elif lang == "java":
            compile_res = subprocess.run(["javac", temp_file], capture_output=True, text=True, timeout=10)
            if compile_res.returncode != 0:
                return False, compile_res.stderr.strip()
            class_name = os.path.splitext(os.path.basename(temp_file))[0]
            cmd = ["java", "-cp", os.path.dirname(temp_file), class_name]
        else:
            cmd = ["python3", temp_file]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, res.stdout.strip() if res.stdout else "Executed successfully with 0 errors."
        return False, res.stderr.strip() or f"Runtime exit code: {res.returncode}"
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def coder_node(state: AgentState) -> AgentState:
    cached_incident = search_similar_incident(state["error_log"], state["language"])
    if cached_incident["found"] and state["retries"] == 0:
        state["current_patch"] = cached_incident["patch"]
        state["cached_hit"] = True
        state["rca_report"] = cached_incident["rca"]
    else:
        state["cached_hit"] = False
        prompt = f"""You are an expert SRE Code Fixer.
Target Language: {state['language']}
Broken Code:
{state['broken_code']}

Error Trace:
{state['error_log']}

INSTRUCTIONS:
1. Apply minimal surgical fix to eliminate runtime crash.
2. Output ONLY the raw executable fixed code without markdown fences.
"""
        raw_res = call_gemini_safe(prompt)
        clean_code = re.sub(r"^```[a-zA-Z]*\n|```$", "", raw_res, flags=re.MULTILINE).strip()
        state["current_patch"] = clean_code

    orig_lines = state["broken_code"].splitlines(keepends=True)
    patch_lines = state["current_patch"].splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        orig_lines, patch_lines,
        fromfile="a/service_module",
        tofile="b/service_module"
    ))
    state["unified_diff"] = diff if diff else "# No structural changes required."
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
        if not state.get("cached_hit"):
            prompt = f"Write a 2-bullet SRE RCA:\n- Root Cause: What failed\n- Surgical Fix: What was changed\nError: {state['error_log']}"
            state["rca_report"] = call_gemini_safe(prompt)
            store_incident(state["error_log"], state["current_patch"], state["language"], state["rca_report"])
    else:
        state["rca_report"] = "ESCALATED: Sandbox verification failed after maximum retries."
    return state

wf = StateGraph(AgentState)
wf.add_node("coder", coder_node)
wf.add_node("tester", tester_node)
wf.add_node("reporter", reporter_node)
wf.set_entry_point("coder")
wf.add_edge("coder", "tester")
wf.add_conditional_edges("tester", should_continue, {"coder": "coder", "reporter": "reporter"})
wf.add_edge("reporter", END)
sre_engine = wf.compile()

HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")

@app.on_event("startup")
def startup_event():
    print("[Startup]: Discovering active Gemini models...")
    model_name = get_active_model_name()
    print(f"[Startup]: Ready to serve using engine: {model_name}")

@app.get("/")
def home():
    if os.path.exists(HTML_PATH):
        return FileResponse(HTML_PATH)
    return {"message": "SRE Swarm Backend active."}

@app.post("/triage", response_model=IncidentResponse)
@app.post("/triage/", response_model=IncidentResponse)
def triage(req: IncidentRequest):
    try:
        init_state: AgentState = {
            "language": req.language, "broken_code": req.broken_code, "error_log": req.error_log,
            "current_patch": "", "unified_diff": "", "test_output": "", "retries": 0,
            "status": "TRIAGING", "rca_report": "", "cached_hit": False
        }
        res = sre_engine.invoke(init_state)
        return IncidentResponse(
            status=res["status"],
            language=res["language"],
            retries_used=res["retries"],
            sandbox_execution_output=res["test_output"],
            verified_code_patch=res["current_patch"],
            unified_diff=res["unified_diff"],
            rca_post_mortem=res["rca_report"]
        )
    except Exception as e:
        print(f"[Triage Internal Error]: {e}")
        raise HTTPException(status_code=500, detail=str(e))