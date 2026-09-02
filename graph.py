import os
from typing import TypedDict, Optional
from dotenv import load_dotenv
import google.generativeai as genai
from langgraph.graph import StateGraph, END
from tools import run_polyglot_sandbox

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# Working official Google Gemini models
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-pro"
]

def call_gemini(prompt: str) -> str:
    """Working models ke sath safe execution logic (Zero 404 guarantee)."""
    last_err = None

    for model_id in FALLBACK_MODELS:
        try:
            model = genai.GenerativeModel(
                model_id, 
                generation_config={"temperature": 0.1}
            )
            res = model.generate_content(prompt)
            if res and res.text:
                return res.text.strip()
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"All model fallbacks failed: {str(last_err)}")

class AgentState(TypedDict):
    language: str
    original_code: str
    error_log: str
    suggested_patch: Optional[str]
    execution_error: Optional[str]
    execution_output: Optional[str]
    retry_count: int
    is_resolved: bool
    final_report: Optional[str]

def coder_agent(state: AgentState) -> AgentState:
    retries = state.get("retry_count", 0)
    prev_error = state.get("execution_error")
    lang = state.get("language", "python").lower()

    prompt = f"You are an expert Autonomous Site Reliability Engineer (SRE).\n"
    prompt += f"Target Language: {lang}\n\n"
    prompt += f"Broken Code:\n{state['original_code']}\n\n"
    prompt += f"Error Stacktrace / Incident Log:\n{state['error_log']}\n\n"

    if prev_error:
        prompt += f"CRITICAL: Previous patch failed in execution sandbox with error:\n{prev_error}\nDebug and resolve completely.\n\n"

    prompt += "Rules:\n"
    prompt += "1. Output ONLY runnable complete code.\n"
    prompt += "2. Gracefully inject mock data/fallback logic for external network or DB calls.\n"
    prompt += "3. Include verification print/log statement at the end.\n"

    content = call_gemini(prompt)

    # Clean code patch extraction
    code_patch = content
    if "```" in content:
        parts = content.split("```")
        if len(parts) >= 3:
            raw_code = parts[1]
            lines = raw_code.splitlines()
            if lines and lines[0].strip().lower() in ["python", "javascript", "js", "cpp", "c", "java", "go", "typescript", "ts"]:
                code_patch = "\n".join(lines[1:]).strip()
            else:
                code_patch = raw_code.strip()

    return {**state, "suggested_patch": code_patch.strip(), "retry_count": retries + 1}

def sandbox_tester_node(state: AgentState) -> AgentState:
    patch = state["suggested_patch"]
    lang = state.get("language", "python")
    result = run_polyglot_sandbox(patch, lang)

    if result["success"]:
        return {
            **state,
            "is_resolved": True,
            "execution_output": result["output"],
            "execution_error": None
        }
    else:
        return {
            **state,
            "is_resolved": False,
            "execution_error": result["error"],
            "execution_output": None
        }

def reporter_agent(state: AgentState) -> AgentState:
    prompt = f"You are an SRE Incident Manager. Write a concise 3-bullet Root Cause Analysis (RCA) Post-Mortem:\n"
    prompt += f"- Root Cause Analysis: (1-2 sentences on what failed)\n"
    prompt += f"- Fix Summary: (1-2 sentences explaining technical patch)\n"
    prompt += f"- Verification: Sandbox output: {state.get('execution_output', 'Tested successfully')}\n"

    content = call_gemini(prompt)
    return {**state, "final_report": content}

def check_execution_status(state: AgentState) -> str:
    if state["is_resolved"] or state["retry_count"] >= 3:
        return "generate_report"
    return "retry_coder"

workflow = StateGraph(AgentState)
workflow.add_node("coder", coder_agent)
workflow.add_node("tester", sandbox_tester_node)
workflow.add_node("reporter", reporter_agent)

workflow.set_entry_point("coder")
workflow.add_edge("coder", "tester")
workflow.add_conditional_edges(
    "tester",
    check_execution_status,
    {
        "generate_report": "reporter",
        "retry_coder": "coder"
    }
)
workflow.add_edge("reporter", END)

sre_swarm_app = workflow.compile()