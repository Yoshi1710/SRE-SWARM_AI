import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import TypedDict

try:
    import resource  
except ImportError:  
    resource = None

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import google.generativeai as genai
from groq import Groq

from langgraph.graph import StateGraph, END
from memory import search_similar_incident, store_incident

load_dotenv()
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1"),
    os.getenv("GROQ_API_KEY_2"),
    os.getenv("GROQ_API_KEY_3")
]
GROQ_KEYS = [k.strip() for k in GROQ_KEYS if k and k.strip()]

# Backup ke liye Gemini (Agar Groq ka server down ho)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Yahan humne fake openai model hata kar real Llama model daal diya h
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

# ==========================================

app = FastAPI(title="SRE Swarm AI Enterprise Diff Engine", version="2.0.0")

# Configure ALLOWED_ORIGINS as comma-separated origins in production.
_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False if "*" in _origins else True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "go", "java", "c", "cpp"}
MAX_CODE_CHARS = int(os.getenv("MAX_CODE_CHARS", "50000"))
MAX_LOG_CHARS = int(os.getenv("MAX_LOG_CHARS", "12000"))

@app.get("/")
def health_check():
    return {"status": "SRE-SWARM_AI is awake 24/7!"}

def detect_language(code: str) -> dict:
    code = code or ""
    patterns = {
        "python": [(r"(?m)^\s*def\s+\w+\s*\(", 3), (r"(?m)^\s*(from\s+\w+\s+import|import\s+\w+)", 2), (r"__name__\s*==", 3), (r"\bprint\s*\(", 1), (r"(?m)^\s*(elif|except)\b", 1)],
        "typescript": [(r"(?m)^\s*(interface|type)\s+\w+", 3), (r":\s*(string|number|boolean|any|void|unknown)([;,)=]|\s*=>)", 2), (r"\bas\s+(string|number|boolean)\b", 2), (r"(?m)^\s*enum\s+\w+", 2)],
        "javascript": [(r"\b(console\.log|const\s+|let\s+|var\s+|function\s+)", 2), (r"=>|module\.exports|require\s*\(", 2), (r"(?m)^\s*export\s+(default|const|function)", 2)],
        "go": [(r"(?m)^\s*package\s+main\b", 3), (r"(?m)^\s*func\s+main\s*\(", 3), (r"\bfmt\.(Print|Printf|Println)\b", 2)],
        "java": [(r"(?m)^\s*public\s+class\s+\w+", 3), (r"public\s+static\s+void\s+main\s*\(", 3), (r"System\.out\.(print|println)", 2), (r"(?m)^\s*package\s+[\w.]+;", 2)],
        "cpp": [(r"#\s*include\s*<iostream>", 3), (r"std::(cout|cin|string)", 3), (r"using\s+namespace\s+std", 2)],
        "c": [(r"#\s*include\s*<stdio\.h>", 3), (r"\bprintf\s*\(", 2), (r"(?m)^\s*int\s+main\s*\(", 2), (r"\bscanf\s*\(", 2)],
    }
    scores = {lang: sum(weight for pattern, weight in rules if re.search(pattern, code)) for lang, rules in patterns.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best, score = ranked[0]
    second = ranked[1][1]
    if score < 2 or score - second < 1:
        return {"language": "unknown", "confidence": 0.0}
    return {"language": best, "confidence": round(min(0.99, 0.55 + 0.08 * score + 0.06 * (score - second)), 2)}


# ==========================================
# NEW: THE SMART AI FALLBACK FUNCTION
# ==========================================
def call_ai_safe(prompt: str) -> str:
    """Yeh function line se sari keys try karega, limit khatam hone par agli key layega"""
    last_error = None

    # PLAN A: Groq API Key Rotation
    for index, key in enumerate(GROQ_KEYS):
        try:
            print(f"[Swarm AI] Trying Groq Key {index + 1} with model {GROQ_MODEL}...")
            client = Groq(api_key=key)
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            if completion and completion.choices:
                return completion.choices[0].message.content.strip()

        except Exception as exc:
            last_error = exc
            error_str = str(exc).lower()
            
            # Agar Error 429 hai (Limit Exceeded), toh aage badho agli key par
            if "429" in error_str or "rate limit" in error_str or "limit exceeded" in error_str:
                print(f"[Warning] Groq Key {index + 1} Limit Reached! Switching to next key...")
                continue
            # Agar password/key galat type hui hai, toh chhod do usko
            elif "401" in error_str or "invalid" in error_str:
                print(f"[Error] Groq Key {index + 1} is Invalid. Skipping...")
                continue
            else:
                print(f"[Error] Unknown Groq error: {exc}")
                continue

    # PLAN B: Gemini Fallback (Agar teeno Groq keys ki limit khatam ho jaye)
    if GEMINI_API_KEY:
        try:
            print("[Swarm AI] All Groq keys failed! Falling back to Gemini Model...")
            model = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.1})
            result = model.generate_content(prompt)
            if result and result.text and result.text.strip():
                return result.text.strip()
        except Exception as exc:
            last_error = exc
            print(f"[Gemini Fallback] Failed: {exc}")

    # Agar yahan tak aa gaya, matlab poora system haar gaya (Sab limits exhaust ho gayi)
    raise RuntimeError(f"All AI API Keys (Groq & Gemini) exhausted! Last error: {last_error}")


class IncidentRequest(BaseModel):
    language: str = Field(min_length=1, max_length=30)
    broken_code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    error_log: str = Field(min_length=1, max_length=MAX_LOG_CHARS)
    expected_output: str | None = Field(default=None, max_length=12000)


class IncidentResponse(BaseModel):
    status: str
    language: str
    language_warning: str = ""
    retries_used: int
    sandbox_execution_output: str
    verified_code_patch: str
    unified_diff: str
    rca_post_mortem: str
    verification_note: str = ""


class AgentState(TypedDict):
    language: str
    broken_code: str
    error_log: str
    expected_output: str
    current_patch: str
    unified_diff: str
    test_output: str
    verification_note: str
    retries: int
    status: str
    rca_report: str
    cached_hit: bool


def _limit_child_process() -> None:
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_FSIZE, (5 * 1024 * 1024, 5 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ValueError, OSError):
        pass


def execute_in_sandbox(code: str, language: str) -> tuple[bool, str]:
    lang = (language or "").lower().strip()
    suffixes = {"python": ".py", "javascript": ".js", "typescript": ".ts", "go": ".go", "java": ".java", "c": ".c", "cpp": ".cpp"}
    if lang not in suffixes:
        return False, f"Unsupported or unknown language: {lang}"
    temp_dir = tempfile.mkdtemp(prefix="sre_run_")
    source_path = os.path.join(temp_dir, "Main" + suffixes[lang])
    env = os.environ.copy()
    env.update({"TMPDIR": temp_dir, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    limit_hook = _limit_child_process if resource is not None else None
    try:
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write(code)
        if lang == "python":
            cmd = [sys.executable, "-I", source_path]
        elif lang == "javascript":
            cmd = ["node", source_path]
        elif lang == "typescript":
            compiled = subprocess.run(["tsc", source_path, "--target", "ES2020", "--module", "commonjs", "--skipLibCheck", "--outDir", temp_dir], capture_output=True, text=True, timeout=20, cwd=temp_dir, env=env)
            if compiled.returncode:
                return False, (compiled.stderr or compiled.stdout).strip()[-12000:]
            cmd = ["node", os.path.join(temp_dir, "Main.js")]
        elif lang in ("c", "cpp"):
            binary = os.path.join(temp_dir, "program.out")
            compiled = subprocess.run(["g++" if lang == "cpp" else "gcc", source_path, "-o", binary], capture_output=True, text=True, timeout=20, cwd=temp_dir, env=env)
            if compiled.returncode:
                return False, (compiled.stderr or compiled.stdout).strip()[-12000:]
            cmd = [binary]
        elif lang == "go":
            cmd = ["go", "run", source_path]
        else:
            match = re.search(r"\bpublic\s+class\s+([A-Za-z_]\w*)", code)
            class_name = match.group(1) if match else "Main"
            java_path = os.path.join(temp_dir, f"{class_name}.java")
            os.replace(source_path, java_path)
            compiled = subprocess.run(["javac", java_path], capture_output=True, text=True, timeout=20, cwd=temp_dir, env=env)
            if compiled.returncode:
                return False, (compiled.stderr or compiled.stdout).strip()[-12000:]
            cmd = ["java", "-Xmx256m", "-cp", temp_dir, class_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=temp_dir, env=env)
        stdout, stderr = (result.stdout or "")[-12000:].strip(), (result.stderr or "")[-12000:].strip()
        if result.returncode == 0:
            return True, stdout or "Process exited with code 0; no stdout was produced."
        return False, stderr or stdout or f"Runtime exit code: {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Execution timed out (configured time limit exceeded)."
    except FileNotFoundError as exc:
        return False, f"Required compiler/runtime is not installed: {exc}"
    except Exception as exc:
        return False, f"Execution failed: {type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def coder_node(state: AgentState) -> AgentState:
    state["cached_hit"] = False
    prompt = f"""You are a senior Site Reliability Engineer and production code repair agent.
Target language: {state['language']}
Incident/error log:
{state['error_log']}
Complete broken source file:
{state['broken_code']}
Previous verification attempt: {state.get('test_output', '') if state.get('retries', 0) else 'No previous attempt.'}
Attempt number: {state.get('retries', 0) + 1} of 3

Requirements:
- Diagnose only from supplied code/log; never invent infrastructure facts.
- Make the smallest maintainable fix supported by evidence. Consider validation, exception handling, cleanup.
- Preserve public interfaces and behavior unless the defect requires a change.
- Never hard-code secrets, suppress exceptions, or claim external systems are healthy.
- Return the COMPLETE corrected source file, not a diff, explanation or partial snippet.
- Output raw source code only, with no Markdown fences or prose.
"""
    # Yahan purana call_gemini_safe hatakar apna smart fallback function lagaya hai
    raw = call_ai_safe(prompt).strip()
    raw = re.sub(r"^```[a-zA-Z0-9_+-]*\s*|\s*```$", "", raw).strip()
    if not raw:
        raise RuntimeError("Model returned an empty code patch.")
    state["current_patch"] = raw
    state["unified_diff"] = "".join(difflib.unified_diff(state["broken_code"].splitlines(keepends=True), raw.splitlines(keepends=True), fromfile="a/service_module", tofile="b/service_module")) or "# No structural changes required."
    return state


def tester_node(state: AgentState) -> AgentState:
    passed, output = execute_in_sandbox(state["current_patch"], state["language"])
    expected = (state.get("expected_output") or "").strip()
    note = "Execution smoke test passed; this does not prove business correctness."
    if passed and expected:
        if output.strip() != expected:
            passed = False
            output = f"Expected-output assertion failed.\nExpected: {expected[:2000]}\nActual: {output[:2000]}"
            note = "Execution completed, but the exact expected-output assertion failed."
        else:
            note = "Execution and exact expected-output assertion passed."
    elif not passed:
        note = "Compilation or execution failed; candidate patch is not verified."
    state["test_output"] = output
    state["verification_note"] = note
    state["retries"] += 1
    state["status"] = "RESOLVED" if passed else "FAILED"
    return state


def should_continue(state: AgentState) -> str:
    return "reporter" if state["status"] == "RESOLVED" or state["retries"] >= 3 else "coder"


def reporter_node(state: AgentState) -> AgentState:
    if state["status"] == "RESOLVED":
        prompt = f"""Write a crisp and highly accurate Root Cause Analysis (RCA) strictly based on the provided error log and code change. DO NOT hallucinate or invent fake servers, databases, timestamps, or team names. Keep it simple and understandable for any developer. 

Use this strict format:
🚨 The Bug: (1 short sentence explaining what broke)
🔍 Root Cause: (1 short sentence explaining the exact coding mistake)
✅ The Fix: (1 short sentence explaining how it was resolved in the code)

Error log: {state['error_log']}"""
        state["rca_report"] = call_ai_safe(prompt)
        store_incident(state["error_log"], state["current_patch"], state["language"], state["rca_report"])
    else:
        state["rca_report"] = "ESCALATED: Candidate patch failed execution verification after maximum retries. Review the logs and add a regression test before deployment."
    return state


workflow = StateGraph(AgentState)
workflow.add_node("coder", coder_node)
workflow.add_node("tester", tester_node)
workflow.add_node("reporter", reporter_node)
workflow.set_entry_point("coder")
workflow.add_edge("coder", "tester")
workflow.add_conditional_edges("tester", should_continue, {"coder": "coder", "reporter": "reporter"})
workflow.add_edge("reporter", END)
sre_engine = workflow.compile()
HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")


@app.on_event("startup")
def startup_event():
    if not GROQ_KEYS and not GEMINI_API_KEY:
        print("[Startup warning] No AI API Keys configured. Server will fail on /triage.")
    else:
        print(f"[Startup] SRE Swarm AI Active! Loaded {len(GROQ_KEYS)} Groq keys.")
        print(f"[Startup] Using Model: {GROQ_MODEL}")


@app.get("/health")
def health():
    return {
        "status": "ok", 
        "service": "sre-swarm-ai", 
        "version": app.version,
        "groq_keys_active": len(GROQ_KEYS),
        "gemini_fallback_active": bool(GEMINI_API_KEY),
        "model_in_use": GROQ_MODEL
    }


@app.get("/")
def home():
    if os.path.exists(HTML_PATH):
        return FileResponse(HTML_PATH)
    return {"message": "SRE Swarm Backend active."}


@app.post("/detect-language")
def detect_language_endpoint(payload: dict):
    return detect_language(str(payload.get("broken_code", "")))


@app.post("/triage", response_model=IncidentResponse)
@app.post("/triage/", response_model=IncidentResponse)
def triage(req: IncidentRequest):
    if not GROQ_KEYS and not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Server is missing AI API Keys.")
    
    detected = detect_language(req.broken_code)
    selected = req.language.lower().strip()
    warning = ""
    if detected["language"] != "unknown" and detected["confidence"] >= 0.70:
        if selected != detected["language"]:
            warning = f"Selected '{selected}', but code appears to be '{detected['language']}'. Automatically using '{detected['language']}'."
        selected = detected["language"]
    elif selected not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Language is ambiguous. Select a supported language.")
    else:
        warning = "Language detection was uncertain; using your selected language."
        
    initial: AgentState = {"language": selected, "broken_code": req.broken_code, "error_log": req.error_log, "expected_output": req.expected_output or "", "current_patch": "", "unified_diff": "", "test_output": "", "verification_note": "", "retries": 0, "status": "TRIAGING", "rca_report": "", "cached_hit": False}
    try:
        result = sre_engine.invoke(initial)
        return IncidentResponse(status=result["status"], language=result["language"], language_warning=warning, retries_used=result["retries"], sandbox_execution_output=result["test_output"], verified_code_patch=result["current_patch"], unified_diff=result["unified_diff"], rca_post_mortem=result["rca_report"], verification_note=result.get("verification_note", ""))
    except Exception as exc:
        print(f"[Triage error] {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="Triage failed. API limits might be exhausted or system error.") from exc