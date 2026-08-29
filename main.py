from fastapi import FastAPI
from pydantic import BaseModel, Field
from graph import sre_swarm_app

app = FastAPI(
    title="SRE-SWARM-AI API",
    description="Autonomous Polyglot Self-Healing SRE Swarm powered by LangGraph, Gemini 1.5 Flash & Subprocess Sandbox",
    version="1.0.0"
)

class IncidentRequest(BaseModel):
    language: str = Field(default="python", example="python", description="Supported: python, javascript, cpp, c, java, go")
    broken_code: str = Field(..., example="def divide(a, b):\n    return a / b\nprint(divide(10, 0))")
    error_log: str = Field(..., example="ZeroDivisionError: division by zero at line 2")

@app.get("/")
def health_check():
    return {
        "status": "online",
        "supported_languages": ["python", "javascript", "c", "cpp", "java", "go"],
        "docs_url": "/docs"
    }

@app.post("/triage")
def triage_incident(request: IncidentRequest):
    initial_state = {
        "language": request.language,
        "original_code": request.broken_code,
        "error_log": request.error_log,
        "retry_count": 0,
        "is_resolved": False,
        "suggested_patch": None,
        "execution_error": None,
        "execution_output": None,
        "final_report": None
    }

    result = sre_swarm_app.invoke(initial_state)

    return {
        "status": "RESOLVED" if result["is_resolved"] else "FAILED_MAX_RETRIES",
        "language": request.language,
        "retries_used": result["retry_count"],
        "sandbox_execution_output": result["execution_output"],
        "verified_code_patch": result["suggested_patch"],
        "rca_post_mortem": result["final_report"]
    }