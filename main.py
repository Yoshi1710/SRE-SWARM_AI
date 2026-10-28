import os
import re
import difflib
import subprocess
import tempfile
from typing import TypedDict
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

SUPPORTED_LANGUAGES = {
    "python", "javascript", "typescript", "go", "java", "c", "cpp"
}


def detect_language(code: str) -> dict:
    """
    Conservative syntax-based language detection.
    Returns 'unknown' when the code is too short or ambiguous.
    """
    code = code or ""

    patterns = {
        "python": [
            (r"(?m)^\s*def\s+\w+\s*\(", 3),
            (r"(?m)^\s*(from\s+\w+\s+import|import\s+\w+)", 2),
            (r"__name__\s*==", 3),
            (r"\bprint\s*\(", 1),
            (r"(?m)^\s*(elif|except)\b", 1),
        ],
        "typescript": [
            (r"(?m)^\s*(interface|type)\s+\w+", 3),
            (r":\s*(string|number|boolean|any|void|unknown)([;,)=]|\s*=>)", 2),
            (r"\bas\s+(string|number|boolean)\b", 2),
            (r"(?m)^\s*enum\s+\w+", 2),
        ],
        "javascript": [
            (r"\b(console\.log|const\s+|let\s+|var\s+|function\s+)", 2),
            (r"=>|module\.exports|require\s*\(", 2),
            (r"(?m)^\s*export\s+(default|const|function)", 2),
        ],
        "go": [
            (r"(?m)^\s*package\s+main\b", 3),
            (r"(?m)^\s*func\s+main\s*\(", 3),
            (r"\bfmt\.(Print|Printf|Println)\b", 2),
        ],
        "java": [
            (r"(?m)^\s*public\s+class\s+\w+", 3),
            (r"public\s+static\s+void\s+main\s*\(", 3),
            (r"System\.out\.(print|println)", 2),
            (r"(?m)^\s*package\s+[\w.]+;", 2),
        ],
        "cpp": [
            (r"#\s*include\s*<iostream>", 3),
            (r"std::(cout|cin|string)", 3),
            (r"using\s+namespace\s+std", 2),
        ],
        "c": [
            (r"#\s*include\s*<stdio\.h>", 3),
            (r"\bprintf\s*\(", 2),
            (r"(?m)^\s*int\s+main\s*\(", 2),
            (r"\bscanf\s*\(", 2),
        ],
    }

    scores = {
        language: sum(
            weight for pattern, weight in rules
            if re.search(pattern, code)
        )
        for language, rules in patterns.items()
    }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_language, best_score = ranked[0]
    second_score = ranked[1][1]

    # Do not guess when the snippet has weak or tied language signals.
    if best_score < 2 or best_score - second_score < 1:
        return {"language": "unknown", "confidence": 0.0}

    confidence = min(
        0.99,
        0.55 + (0.08 * best_score) + (0.06 * (best_score - second_score))
    )
    return {
        "language": best_language,
        "confidence": round(confidence, 2)
    }


def get_active_model_name() -> str:
    """Google API se available models dynamically discover karta hai."""
    global ACTIVE_MODEL_NAME
    if ACTIVE_MODEL_NAME:
        return ACTIVE_MODEL_NAME

    candidate_preferences = [
        "gemini-3.6-flash",
        "gemini-3.6-flash-lite",
        "gemini-3.8-flash",
        "gemini-flash-latest",
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
    fallbacks = [
        primary,
        "gemini-3.6-flash",
        "gemini-3.6-flash-lite",
        "gemini-3.8-flash",
        "gemini-flash-latest",
    ]

    seen = set()
    unique_models = [m for m in fallbacks if not (m in seen or seen.add(m))]

    last_error = None
    for model_id in unique_models:
        try:
            model = genai.GenerativeModel(
                model_id,
                generation_config={"temperature": 0.1}
            )
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
    language_warning: str = ""
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
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "go": ".go",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp",
    }
    suffix = suffix_map.get(lang, ".txt")

    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(code)
        temp_file = f.name

    try:
        if lang == "python":
            cmd = ["python3", temp_file]
        elif lang == "javascript":
            cmd = ["node", temp_file]
        elif lang == "typescript":
            # Requires the TypeScript compiler (tsc) to be installed in the runtime.
            compile_res = subprocess.run(
                ["tsc", temp_file, "--target", "ES2020", "--module", "commonjs",
                 "--outDir", os.path.dirname(temp_file)],
                capture_output=True, text=True, timeout=15
            )
            if compile_res.returncode != 0:
                return False, compile_res.stderr.strip() or compile_res.stdout.strip()
            js_file = os.path.splitext(temp_file)[0] + ".js"
            cmd = ["node", js_file]
        elif lang == "go":
            cmd = ["go", "run", temp_file]
        elif lang in ["c", "cpp"]:
            out_bin = temp_file + ".out"
            compiler = "g++" if lang == "cpp" else "gcc"
            compile_res = subprocess.run(
                [compiler, temp_file, "-o", out_bin],
                capture_output=True, text=True, timeout=15
            )
            if compile_res.returncode != 0:
                return False, compile_res.stderr.strip()
            cmd = [out_bin]
        elif lang == "java":
            # Java public class names must match the .java filename.
            match = re.search(r"\bpublic\s+class\s+([A-Za-z_]\w*)", code)
            class_name = match.group(1) if match else "Main"
            temp_dir = tempfile.mkdtemp(prefix="sre_java_")
            java_file = os.path.join(temp_dir, f"{class_name}.java")
            with open(java_file, "w", encoding="utf-8") as jf:
                jf.write(code)
            compile_res = subprocess.run(
                ["javac", java_file],
                capture_output=True, text=True, timeout=15
            )
            if compile_res.returncode != 0:
                return False, compile_res.stderr.strip()
            cmd = ["java", "-cp", temp_dir, class_name]
        else:
            return False, f"Unsupported or unknown language: {lang}"

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return True, res.stdout.strip() if res.stdout else "Executed successfully with 0 errors."
        return False, res.stderr.strip() or f"Runtime exit code: {res.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Execution timed out."
    except FileNotFoundError as e:
        return False, f"Required compiler/runtime is not installed: {e}"
    except Exception as e:
        return False, str(e)
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def coder_node(state: AgentState) -> AgentState:
    cached_incident = search_similar_incident(
        state["error_log"], state["language"]
    )
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
        clean_code = re.sub(
            r"^```[a-zA-Z]*\n|```$",
            "",
            raw_res,
            flags=re.MULTILINE
        ).strip()
        state["current_patch"] = clean_code

    orig_lines = state["broken_code"].splitlines(keepends=True)
    patch_lines = state["current_patch"].splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(
        orig_lines,
        patch_lines,
        fromfile="a/service_module",
        tofile="b/service_module"
    ))
    state["unified_diff"] = diff if diff else "# No structural changes required."
    return state


def tester_node(state: AgentState) -> AgentState:
    passed, out = execute_in_sandbox(
        state["current_patch"], state["language"]
    )
    state["test_output"] = out
    state["retries"] += 1
    state["status"] = "RESOLVED" if passed else "FAILED"
    return state


def should_continue(state: AgentState) -> str:
    return "reporter" if (
        state["status"] == "RESOLVED" or state["retries"] >= 3
    ) else "coder"


def reporter_node(state: AgentState) -> AgentState:
    if state["status"] == "RESOLVED":
        if not state.get("cached_hit"):
            prompt = f"""Write a 2-bullet SRE RCA:
- Root Cause: What failed
- Surgical Fix: What was changed
Error: {state['error_log']}"""
            state["rca_report"] = call_gemini_safe(prompt)
            store_incident(
                state["error_log"],
                state["current_patch"],
                state["language"],
                state["rca_report"]
            )
    else:
        state["rca_report"] = (
            "ESCALATED: Sandbox verification failed after maximum retries."
        )
    return state


wf = StateGraph(AgentState)
wf.add_node("coder", coder_node)
wf.add_node("tester", tester_node)
wf.add_node("reporter", reporter_node)
wf.set_entry_point("coder")
wf.add_edge("coder", "tester")
wf.add_conditional_edges(
    "tester",
    should_continue,
    {"coder": "coder", "reporter": "reporter"}
)
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


@app.post("/detect-language")
def detect_language_endpoint(payload: dict):
    return detect_language(str(payload.get("broken_code", "")))


@app.post("/triage", response_model=IncidentResponse)
@app.post("/triage/", response_model=IncidentResponse)
def triage(req: IncidentRequest):
    try:
        detected = detect_language(req.broken_code)
        selected_language = (req.language or "").lower().strip()
        warning = ""

        if (
            detected["language"] != "unknown"
            and detected["confidence"] >= 0.70
        ):
            if selected_language != detected["language"]:
                warning = (
                    f"Selected '{selected_language}', but code appears to be "
                    f"'{detected['language']}'. Automatically using "
                    f"'{detected['language']}'."
                )
            selected_language = detected["language"]
        else:
            if selected_language not in SUPPORTED_LANGUAGES:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Language is ambiguous. Please select the correct "
                        "language and try again."
                    )
                )
            warning = (
                "Language detection was uncertain; using your selected language."
            )

        init_state: AgentState = {
            "language": selected_language,
            "broken_code": req.broken_code,
            "error_log": req.error_log,
            "current_patch": "",
            "unified_diff": "",
            "test_output": "",
            "retries": 0,
            "status": "TRIAGING",
            "rca_report": "",
            "cached_hit": False,
        }
        res = sre_engine.invoke(init_state)
        return IncidentResponse(
            status=res["status"],
            language=res["language"],
            language_warning=warning,
            retries_used=res["retries"],
            sandbox_execution_output=res["test_output"],
            verified_code_patch=res["current_patch"],
            unified_diff=res["unified_diff"],
            rca_post_mortem=res["rca_report"],
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Triage Internal Error]: {e}")
        raise HTTPException(status_code=500, detail=str(e))
