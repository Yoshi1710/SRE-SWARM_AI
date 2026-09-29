# SRE Swarm AI

### LLM-Assisted SRE Incident Remediation and Verification

SRE Swarm AI is an SRE-oriented application that uses an LLM to analyze software failures, generate candidate code fixes, execute them, use execution feedback for bounded retries, retrieve similar previously resolved incidents, and return a structured remediation report.

The core idea is:

> An LLM-generated fix is a candidate remediation until execution provides evidence that the generated code runs successfully.

This project explores an SRE-specific workflow around LLM-assisted remediation rather than claiming that general-purpose coding agents cannot perform similar tasks.

---

## 🚀 Live Demo

**API:**  
https://sre-swarm-ai.onrender.com/

**Swagger:**  
https://sre-swarm-ai.onrender.com/docs

---

## 🎯 What It Does

The `/triage` endpoint accepts:

- Programming language
- Broken source code
- Error log

The workflow then:

1. Searches for a similar historical incident.
2. Reuses a previously verified remediation when a sufficiently similar incident is found.
3. Otherwise asks Gemini to generate a candidate fix.
4. Executes the generated code.
5. Feeds execution errors back into the remediation loop when needed.
6. Allows up to three remediation attempts.
7. Generates a unified diff.
8. Produces an RCA after successful verification.
9. Stores successfully processed incidents in ChromaDB.

### Workflow

    Incident
       ↓
    Historical Incident Search
       ↓
    Candidate Fix / Cached Fix
       ↓
    Execute
       ↓
    ┌───────────────┐
    │ Success       │────→ RCA → Incident Memory
    │               │
    │ Failure       │────→ Error Feedback → Retry
    └───────────────┘
                         ↓
                    Max 3 Attempts
                         ↓
                      Escalate

The workflow is orchestrated with LangGraph.

---

## 🧩 Architecture

    FastAPI
       │
       ▼
    /triage
       │
       ▼
    LangGraph Workflow
       │
       ├── Incident Retrieval ──→ ChromaDB
       │
       ├── Gemini Remediation
       │
       ├── Code Execution
       │
       ├── Retry Decision
       │
       └── RCA / Reporting
       │
       ▼
    Structured JSON Response

---

## 🧠 Incident Memory

ChromaDB is used to persist previously processed incidents.

Stored information includes:

- Error log
- Programming language
- Verified patch
- RCA

The application uses cosine similarity to retrieve similar incidents and attempts to use Gemini-supported embedding models when available.

Preferred embedding models include:

    models/text-embedding-004
    models/embedding-001

A deterministic local vector fallback exists when the embedding API is unavailable. This fallback is only an availability mechanism and is not equivalent to a semantic embedding model.

---

## 🤖 LLM Remediation

Gemini is used to generate candidate code corrections.

The remediation prompt is designed to encourage:

- Minimal changes
- Surgical fixes
- Executable source code
- Avoidance of unnecessary modifications
- Consideration of the supplied error

The current generation temperature is `0.1`.

The generated source is not treated as verified until it is executed.

The application dynamically discovers available Gemini models and selects an available model based on API configuration. The exact model selected at runtime may change as model availability changes.

---

## 🔄 Verification and Retries

A successful process exit is treated as **execution verification**.

This is intentionally different from claiming that the software is fully correct.

If execution fails, the resulting error is passed back into the remediation workflow for another attempt.

The current workflow allows a maximum of three attempts. If verification still fails, the incident is escalated.

---

## 📊 Unified Diff and RCA

The application compares the original and generated source using Python's `difflib` and returns a unified diff.

Example:

    - tax_rate = employee["tax_rate"]
    + tax_rate = float(employee["tax_rate"])

After successful execution, the system generates a concise root-cause analysis and returns it in the API response. The RCA is also stored with the incident.

---

## 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application |
| FastAPI | REST API |
| LangGraph | Workflow orchestration |
| Google Gemini | LLM-based remediation and RCA |
| ChromaDB | Incident memory |
| Pydantic | Request/response validation |
| Uvicorn | ASGI server |
| python-dotenv | Configuration |
| difflib | Unified diff generation |
| subprocess | Code execution |

---

## 🔄 Supported Execution Languages

The current primary execution implementation supports:

| Language | Execution |
|---|---|
| Python | Python interpreter |
| JavaScript | Node.js |
| Go | `go run` |
| Java | `javac` + `java` |
| C | GCC compilation + execution |
| C++ | G++ compilation + execution |

TypeScript is not listed as primary runtime support because the current implementation does not provide a dedicated TypeScript transpilation pipeline.

---

## 📡 API

### POST `/triage`

Example request:

    {
      "language": "python",
      "broken_code": "def add(a, b):\n    return a + b\n\nprint(add(10, '5'))",
      "error_log": "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
    }

Example response structure:

    {
      "status": "RESOLVED",
      "language": "python",
      "retries_used": 1,
      "execution_output": "15",
      "verified_code_patch": "...",
      "unified_diff": "...",
      "rca_post_mortem": "..."
    }

The exact response depends on the supplied code, error, execution result, and model response.

---

## 📁 Project Structure

    SRE-SWARM_AI/
    ├── main.py
    ├── graph.py
    ├── memory.py
    ├── tools.py
    ├── test_api.py
    ├── requirements.txt
    └── README.md

### Main files

**`main.py`** — Primary FastAPI application and deployed LangGraph workflow.

**`graph.py`** — Separate LangGraph workflow implementation using the execution tools; it is not imported by the current `main.py` deployment path.

**`memory.py`** — ChromaDB initialization, embeddings, similarity search, and incident storage.

**`tools.py`** — Polyglot execution helper used by the alternate workflow.

**`test_api.py`** — Basic API-level test client for `/triage`.

---

## 🚀 Local Setup

### 1. Clone

    git clone https://github.com/Yoshi1710/SRE-SWARM_AI.git
    cd SRE-SWARM_AI

### 2. Create a virtual environment

**Windows**

    python -m venv venv
    venv\Scripts\activate

**Linux / macOS**

    python3 -m venv venv
    source venv/bin/activate

### 3. Install dependencies

    pip install -r requirements.txt

### 4. Configure Gemini

Create `.env`:

    GEMINI_API_KEY=your_api_key_here

Do not commit API keys.

### 5. Run

    uvicorn main:app --reload

API:

    http://127.0.0.1:8000

Swagger:

    http://127.0.0.1:8000/docs

---

## ⚠️ Current Limitations

### Execution Isolation

The current implementation uses temporary files and local subprocess execution. It is **not a hardened security sandbox** and does not provide complete container or VM-level isolation.

Running arbitrary untrusted code in a production environment would require additional controls such as container isolation, resource limits, network restrictions, filesystem restrictions, and non-root execution.

### LLM Reliability

An LLM-generated patch can still be incorrect.

Successful execution only provides evidence that the process completed successfully; it does not prove correctness for every input or business requirement.

### Test Depth

Current verification primarily checks process execution success. A stronger production system would also run project-specific unit, integration, and regression tests, together with static and security analysis.

### Embedding Fallback

The deterministic local embedding fallback is not equivalent to a semantic embedding model.

### Repository-Level Remediation

The current workflow operates primarily on supplied source code. It does not perform unrestricted repository-wide analysis, multi-file remediation, or full project test execution.

### Production Observability

A production SRE platform would require stronger metrics, tracing, structured logging, alerting, and audit trails.

---

## 🔐 Security Considerations

Before exposing arbitrary code execution to untrusted users, the application would need production security controls including:

- Authentication and authorization
- Rate limiting
- Resource quotas
- Process/container isolation
- Network isolation
- Filesystem restrictions
- Dependency restrictions
- Secrets management
- Audit logging

The current CORS configuration is permissive and should be restricted for a production deployment.

---

## 🧭 Future Engineering Work

Potential next steps include:

- Container or microVM-based execution
- Test-aware verification
- Repository-level and multi-file remediation
- GitHub pull-request integration
- Static and security analysis
- Production observability
- Human approval gates
- Evaluation datasets and reproducible benchmarks

---

## 🧠 Engineering Principles

**Candidate ≠ Verified**

An LLM response is a candidate remediation until execution provides evidence that the generated code runs successfully.

**Bounded Automation**

Retries are deliberately limited to prevent uncontrolled remediation loops.

**Historical Knowledge**

Previously processed incidents can provide reusable context for future incidents.

**Human Oversight**

Automated remediation should not eliminate engineering review, especially for production systems.

---

## 👨‍💻 Author

**Deepak Singh Bisht**

B.Tech CSE (AI/ML)

GitHub: https://github.com/Yoshi1710

---

## 📄 Project Status

SRE Swarm AI is an engineering and learning project demonstrating an LLM-assisted SRE incident remediation workflow.

The current implementation focuses on:

**Incident → Remediation → Execution → Feedback → Verification → RCA → Memory**

It is not presented as a replacement for production SRE teams or general-purpose coding agents. The project demonstrates how an SRE-specific remediation pipeline can combine LLMs, workflow orchestration, execution feedback, retrieval, and incident memory.