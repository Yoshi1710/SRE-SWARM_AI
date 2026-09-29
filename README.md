# SRE Swarm AI

### LLM-Assisted SRE Incident Remediation & Verification

SRE Swarm AI is an SRE-focused application that analyzes software incidents, retrieves similar historical incidents, generates a candidate code fix using an LLM, executes the fix, and uses execution feedback to retry failed remediations. The system returns the verified code patch, unified diff, execution result, and root-cause analysis.

## Live Demo

- **Web App:** https://sre-swarm-ai.onrender.com/
- **API Documentation:** https://sre-swarm-ai.onrender.com/docs

---

## Key Features

- **Incident Triage** — Accepts programming language, broken source code, and error logs.
- **Historical Incident Retrieval** — Searches ChromaDB for similar previously processed incidents.
- **LLM-Based Remediation** — Uses Google Gemini to generate a targeted candidate code fix.
- **Execution Verification** — Executes the generated code and uses the result as verification feedback.
- **Bounded Retry Loop** — Failed fixes are retried using execution errors as feedback, up to three attempts.
- **Unified Diff** — Shows the changes between the original and corrected code.
- **RCA Generation** — Generates a concise root-cause analysis after remediation.
- **Incident Memory** — Stores successful incidents, patches, and RCA information for future retrieval.

---

## How It Works

```text
Software Incident
(Code + Error Log)
        │
        ▼
Historical Incident Retrieval
        │
        ▼
Gemini Candidate Fix
        │
        ▼
Code Execution
        │
   ┌────┴────┐
   │         │
Success    Failure
   │         │
   ▼         ▼
RCA + Diff  Error Feedback
   │         │
   │         ▼
   │       Retry
   │         │
   │    Max 3 Attempts
   │         │
   └─────────┴──────► Escalation / Result
```

The workflow is orchestrated using **LangGraph**.

---

## Architecture

```text
                         FastAPI
                            │
                            ▼
                         /triage
                            │
                            ▼
                       LangGraph
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
      ChromaDB          Gemini LLM       Code Execution
   Incident Memory      Remediation       & Verification
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                            ▼
                     Retry / Decision
                            │
                            ▼
                       RCA + Diff
                            │
                            ▼
                    Structured Response
```

---

## Incident Memory

ChromaDB is used as the incident memory layer.

For successful incidents, the application stores:

- Error log
- Programming language
- Verified code patch
- Root-cause analysis

When a new incident is received, similarity search is used to retrieve relevant historical incidents before generating a new remediation.

---

## LLM Remediation

Google Gemini generates a candidate fix using:

- Source code
- Error log
- Programming language
- Relevant historical incident context

The remediation process is designed around minimal, targeted code changes rather than rewriting the complete application.

A generated patch is considered a **candidate fix until execution provides verification feedback**.

---

## Verification & Retry

The generated code is executed through the application's language-specific execution pipeline.

The remediation loop follows:

```text
Candidate Fix
     │
     ▼
Execute
     │
 ┌───┴────┐
 │        │
Pass     Fail
 │        │
 ▼        ▼
Result   Error Feedback
          │
          ▼
       New Fix
          │
          ▼
        Retry
```

The workflow allows a maximum of **three remediation attempts** before escalation.

> Execution success confirms that the supplied program completed successfully; it does not guarantee complete functional correctness for every possible input or requirement.

---

## API

### POST `/triage`

Example request:

```json
{
  "language": "python",
  "broken_code": "def add(a, b):\n    return a + b\n\nprint(add(10, '5'))",
  "error_log": "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
}
```

Example response:

```json
{
  "status": "RESOLVED",
  "language": "python",
  "retries_used": 1,
  "sandbox_execution_output": "15",
  "verified_code_patch": "def add(a, b):\n    return int(a) + int(b)",
  "unified_diff": "...",
  "rca_post_mortem": "..."
}
```

The actual response depends on the supplied incident and execution result.

---

## Output

| Field | Description |
|---|---|
| `status` | Remediation status |
| `language` | Programming language |
| `retries_used` | Number of remediation attempts |
| `sandbox_execution_output` | Execution result |
| `verified_code_patch` | Generated source after remediation |
| `unified_diff` | Difference between original and corrected code |
| `rca_post_mortem` | Root-cause analysis |

---

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application |
| FastAPI | REST API |
| LangGraph | Workflow orchestration |
| Google Gemini | Code remediation and RCA |
| ChromaDB | Incident memory and similarity retrieval |
| Pydantic | API validation |
| Uvicorn | Application server |
| Python `difflib` | Unified diff generation |
| Python `subprocess` | Code execution |

---

## Supported Languages

| Language | Runtime |
|---|---|
| Python | Python |
| JavaScript | Node.js |
| Go | Go |
| Java | JDK |
| C | GCC |
| C++ | G++ |

---

## Project Structure

```text
SRE-SWARM_AI/
│
├── main.py
├── memory.py
├── index.html
├── test_api.py
├── requirements.txt
├── Dockerfile
├── .gitignore
└── README.md
```

### Main Components

- **`main.py`** — FastAPI application, LangGraph workflow, Gemini integration, code execution, retry logic, diff generation, and API endpoints.
- **`memory.py`** — ChromaDB initialization, embedding configuration, similarity search, and incident storage.
- **`index.html`** — Web interface.
- **`test_api.py`** — Basic API smoke test.
- **`Dockerfile`** — Container configuration for deployment.

---

## Local Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Yoshi1710/SRE-SWARM_AI.git
cd SRE-SWARM_AI
```

### 2. Create Virtual Environment

**Windows**

```bash
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Gemini

Create a `.env` file:

```env
GEMINI_API_KEY=your_api_key_here
```

Do not commit API keys to the repository.

### 5. Run the Application

```bash
uvicorn main:app --reload
```

Open:

**Web App:** http://127.0.0.1:8000

**Swagger:** http://127.0.0.1:8000/docs

---

## Current Limitations

- Code execution currently uses subprocess-based execution rather than hardened container or VM isolation.
- Successful execution does not replace full unit, integration, or regression testing.
- Remediation currently operates primarily on supplied source code rather than unrestricted repository-wide changes.
- ChromaDB storage is local to the application environment.
- Production deployment would require authentication, rate limiting, stronger execution isolation, resource controls, and restricted CORS.

---

## Author

**Deepak Singh Bisht**

B.Tech CSE (AI/ML)

GitHub: https://github.com/Yoshi1710