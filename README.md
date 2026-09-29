# SRE Swarm AI

### LLM-Assisted SRE Incident Remediation and Verification System

SRE Swarm AI is an SRE-oriented automation system that uses a Large Language Model (LLM) to analyze software failures, generate a candidate code fix, execute the modified code, use execution feedback for bounded retries, retrieve previously resolved incidents, and return a structured remediation report.

The core engineering idea is simple:

> An LLM-generated fix is treated as a candidate remediation until execution provides evidence that the generated code runs successfully.

The project connects incident analysis, historical incident retrieval, code remediation, execution verification, retry logic, unified diff generation, root-cause analysis, and incident memory into a single workflow.

---

## 🚀 Live Demo

**Live API:**  
https://sre-swarm-ai.onrender.com/

**Swagger API Documentation:**  
https://sre-swarm-ai.onrender.com/docs

---

## 🎯 Problem Statement

When a software service fails, an engineer typically needs to:

1. Understand the error.
2. Identify the faulty part of the code.
3. Determine a possible remediation.
4. Apply the change.
5. Execute the modified code.
6. Inspect the resulting output or error.
7. Iterate if the remediation does not work.
8. Document the root cause and resolution.

Modern LLM-powered coding systems can assist with many of these tasks. SRE Swarm AI focuses specifically on implementing an SRE-oriented remediation workflow around an LLM.

The application therefore combines:

- LLM-assisted incident analysis
- Candidate code remediation
- Automated execution feedback
- Bounded retry-based correction
- Historical incident retrieval
- Verified patch generation
- Unified diff generation
- Structured incident reporting
- Root-cause analysis
- Escalation when verification fails

The project does not claim that general-purpose coding agents cannot perform similar operations. Its purpose is to demonstrate how an SRE-specific remediation and verification workflow can be designed and implemented as an independent application.

---

## 🧠 What Does SRE Swarm AI Do?

The system accepts three primary inputs:

- Programming language
- Broken source code
- Error log

It then follows this workflow:

Incident Input
→ Historical Incident Search
→ Candidate Fix Generation or Cached Fix Retrieval
→ Code Execution
→ Execution Result Analysis
→ Retry if Required
→ Verification
→ RCA Generation
→ Incident Memory Storage
→ Structured Response

The workflow is orchestrated using LangGraph.

---

## ⚙️ Core Workflow

### 1. Incident Intake

The `/triage` API endpoint receives the programming language, source code, and error log.

Example request structure:

    {
      "language": "python",
      "broken_code": "def add(a, b): return a + b",
      "error_log": "TypeError: unsupported operand type(s) for +"
    }

---

### 2. Historical Incident Retrieval

Before generating a new remediation, the system searches its persistent incident memory.

The memory layer uses:

- ChromaDB
- Persistent local storage
- Cosine similarity
- Gemini-supported embeddings when available

The search is performed using the reported error and programming language.

If a sufficiently similar previously verified incident is found, the stored verified patch and RCA can be reused.

This allows the system to use previously resolved incidents as a source of operational knowledge.

---

### 3. LLM-Assisted Code Remediation

If a suitable historical incident is not available, Gemini is used to generate a candidate code correction.

The remediation prompt is designed to encourage:

- Minimal changes
- Surgical fixes
- Executable source code
- Avoidance of unnecessary modifications
- Consideration of the supplied error

The current generation temperature is set to `0.1`.

The LLM-generated code is still considered a candidate until it passes execution verification.

---

### 4. Execution Verification

The generated source code is executed automatically.

The system does not simply assume that an LLM-generated response is correct.

Instead, it observes the actual process result.

A successful process exit is treated as successful execution verification.

If the generated code fails, the resulting execution error becomes feedback for another remediation attempt.

---

### 5. Bounded Retry Loop

The current workflow allows a maximum of three remediation attempts.

The process is conceptually:

    Generate Fix
          ↓
       Execute
          ↓
    ┌─────┴─────┐
    │           │
  Success     Failure
    │           │
    ▼           ▼
  Report    Use Error Feedback
                │
                ▼
          Generate New Fix
                │
                ▼
             Execute
                │
              ...

The retry limit prevents an uncontrolled autonomous loop.

If the maximum number of attempts is reached without successful execution, the incident is escalated.

---

### 6. Unified Diff Generation

The application compares the original source code with the generated source code using Python's `difflib`.

This produces a unified diff showing the actual modification.

Example:

    - tax_rate = employee["tax_rate"]
    + tax_rate = float(employee["tax_rate"])

The diff makes the remediation easier to inspect than returning only the complete modified source code.

---

### 7. Root Cause Analysis

After successful verification, the system generates a concise root-cause analysis and post-mortem using the LLM.

The RCA is returned as part of the structured API response and can also be stored with the incident.

---

### 8. Incident Memory

Successfully processed incidents can be stored in ChromaDB.

The stored information includes:

- Error log
- Programming language
- Verified patch
- RCA

A future incident with a sufficiently similar error can therefore retrieve an existing verified remediation.

---

# 🧩 Architecture

The current application follows this architecture:

    FastAPI
       │
       ▼
    /triage Endpoint
       │
       ▼
    LangGraph Workflow
       │
       ├── Historical Incident Search
       │          │
       │          ▼
       │      ChromaDB
       │
       ├── Gemini Code Remediation
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

# 🛠️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application language |
| FastAPI | REST API |
| LangGraph | Workflow orchestration |
| Google Gemini | LLM-based code analysis and remediation |
| ChromaDB | Persistent incident memory |
| Pydantic | Request/response validation |
| Uvicorn | ASGI server |
| python-dotenv | Environment configuration |
| difflib | Unified diff generation |
| subprocess | Program execution |

---

# 🤖 Gemini Configuration

The application dynamically discovers available Gemini models and uses a preferred model list.

Current preferred models include:

- `gemini-3.6-flash`
- `gemini-3.6-flash-lite`
- `gemini-3.8-flash`
- `gemini-flash-latest`

The application attempts to select an available model and includes fallback handling.

The exact model selected at runtime depends on model availability and API configuration.

The deployed service has been tested with the Gemini Flash model configuration available to the application.

---

# 💾 Incident Memory

SRE Swarm AI uses ChromaDB for persistent incident storage.

The collection used by the application is:

    sre_incident_memory

The configured similarity metric is:

    cosine

The system attempts to use Gemini-supported embedding models when available.

Preferred embedding models include:

    models/text-embedding-004
    models/embedding-001

A deterministic local fallback vector is also implemented when the embedding API is unavailable.

### Important limitation

The local fallback is a technical availability fallback and should not be considered equivalent to a semantic embedding model.

---

# 🔄 Supported Execution Languages

The current primary execution implementation supports:

| Language | Execution Method |
|---|---|
| Python | Python interpreter |
| JavaScript | Node.js |
| Go | `go run` |
| Java | `javac` + `java` |
| C | GCC compilation + execution |
| C++ | G++ compilation + execution |

TypeScript should not currently be described as independently verified runtime support because the primary execution implementation does not provide a dedicated TypeScript transpilation pipeline.

---

# ⚠️ Execution Environment

The current implementation uses temporary files and local subprocess execution.

This is suitable for demonstrating the remediation workflow, but it should not be considered a hardened security sandbox.

The current system does not provide complete container or VM-level isolation.

Running arbitrary untrusted code against a production deployment would therefore require additional security controls.

Potential production improvements include:

- Container isolation
- CPU limits
- Memory limits
- Network restrictions
- Filesystem restrictions
- Non-root execution
- Process isolation
- Seccomp/AppArmor-style controls
- Job-level authentication
- Authorization
- Resource quotas

---

# 📡 API

## POST `/triage`

The `/triage` endpoint is the primary incident remediation endpoint.

### Request

    {
      "language": "python",
      "broken_code": "def add_numbers(a, b):\n    return a + b\n\nprint(add_numbers(10, \"5\"))",
      "error_log": "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
    }

### Response Structure

    {
      "status": "RESOLVED",
      "language": "python",
      "retries_used": 1,
      "sandbox_execution_output": "15",
      "verified_code_patch": "...",
      "unified_diff": "...",
      "rca_post_mortem": "..."
    }

The exact response depends on the supplied source code, error, execution result, and model response.

---

# 🧪 Example Incident

Consider the following code:

    def calculate_salary(employee):
        base_salary = employee["base_salary"]
        bonus = employee["bonus"]
        tax_rate = employee["tax_rate"]

        gross_salary = base_salary + bonus
        tax = gross_salary * tax_rate / 100
        net_salary = gross_salary - tax

        return round(net_salary, 2)

Suppose the input contains:

    "tax_rate": "10"

The program can produce a type-related error because the tax rate is represented as a string.

A possible remediation generated by the system is:

    tax_rate = float(employee["tax_rate"])

The modified code is then executed.

If execution succeeds, the system can return:

- The verified code
- Unified diff
- Execution output
- Retry count
- RCA
- Resolution status

---

# 📁 Project Structure

    SRE-SWARM_AI/
    │
    ├── main.py
    ├── graph.py
    ├── memory.py
    ├── tools.py
    ├── test_api.py
    ├── requirements.txt
    ├── README.md
    ├── .env
    └── chroma_db/

### `main.py`

Primary FastAPI application and deployed LangGraph workflow.

Contains:

- API endpoint
- Gemini integration
- Incident remediation workflow
- Code execution
- Retry handling
- Diff generation
- RCA generation
- Structured response generation

### `graph.py`

Contains a separate LangGraph workflow implementation using the execution tools.

It is not imported by the current `main.py` deployed path.

### `memory.py`

Responsible for:

- ChromaDB initialization
- Embedding generation
- Similar incident search
- Incident storage

### `tools.py`

Contains the polyglot execution helper used by the alternate workflow.

### `test_api.py`

Contains a simple API-level test client for the `/triage` endpoint.

---

# 🚀 Local Setup

## 1. Clone the Repository

    git clone https://github.com/Yoshi1710/SRE-SWARM_AI.git
    cd SRE-SWARM_AI

## 2. Create a Virtual Environment

### Windows

    python -m venv venv
    venv\Scripts\activate

### Linux / macOS

    python3 -m venv venv
    source venv/bin/activate

## 3. Install Dependencies

    pip install -r requirements.txt

## 4. Configure Gemini API

Create a `.env` file:

    GEMINI_API_KEY=your_api_key_here

Do not commit the `.env` file to GitHub.

## 5. Start the Application

    uvicorn main:app --reload

The API will normally be available at:

    http://127.0.0.1:8000

Swagger documentation:

    http://127.0.0.1:8000/docs

---

# 🔍 Example API Request

Using cURL:

    curl -X POST "http://127.0.0.1:8000/triage" \
    -H "Content-Type: application/json" \
    -d "{\"language\":\"python\",\"broken_code\":\"def add(a, b): return a + b\\nprint(add(10, '5'))\",\"error_log\":\"TypeError: unsupported operand type(s) for +: 'int' and 'str'\"}"

---

# 🔐 Security Considerations

The current project is primarily a technical implementation demonstrating an automated remediation workflow.

Before exposing arbitrary code execution to untrusted users, additional security controls would be required.

Important areas include:

- Authentication
- Authorization
- Input validation
- Rate limiting
- Resource quotas
- Process isolation
- Containerized execution
- Network isolation
- Filesystem isolation
- Dependency restrictions
- Secrets management
- Audit logging

The current CORS configuration is permissive and should be restricted for a production deployment.

---

# ⚠️ Current Limitations

### 1. Execution Isolation

The current implementation relies on temporary files and subprocess execution rather than a hardened sandbox.

### 2. LLM Reliability

An LLM-generated patch can still be incorrect.

Successful execution does not automatically prove that the software behavior is correct for every possible input.

### 3. Test Depth

The current verification primarily checks process execution success.

A stronger production system would execute project-specific:

- Unit tests
- Integration tests
- Regression tests
- Static analysis
- Security checks

### 4. TypeScript Execution

There is currently no dedicated TypeScript transpilation pipeline in the primary execution implementation.

### 5. Embedding Fallback

The deterministic local embedding fallback is not equivalent to semantic embeddings.

### 6. Production Observability

A production SRE platform would require stronger:

- Metrics
- Tracing
- Structured logging
- Incident history
- Alerting
- Audit trails

### 7. Repository-Level Remediation

The current workflow primarily operates on supplied source code rather than performing unrestricted repository-wide codebase analysis.

---

# 🧭 Future Engineering Directions

## Secure Code Execution

Replace local subprocess execution with isolated containers or microVMs.

    API
     ↓
    Job Queue
     ↓
    Isolated Execution Worker
     ↓
    Tests
     ↓
    Result

## Test-Aware Verification

A stronger verification pipeline could become:

    Generated Patch
          ↓
        Build
          ↓
      Unit Tests
          ↓
    Integration Tests
          ↓
     Static Analysis
          ↓
     Security Checks
          ↓
    Verified Remediation

## Repository-Level Context

Future versions could support:

- Multiple files
- Dependency graphs
- Project configuration
- Existing tests
- Git history
- Service ownership
- Deployment configuration

## Better Incident Memory

Incident records could eventually include:

- Incident category
- Service
- Repository
- Commit
- Failure signature
- Root cause
- Resolution
- Verification tests
- Timestamp
- Resolution status

## Observability Integration

A future implementation could integrate with monitoring and incident-management systems to consume real incidents from production environments.

---

# 🧠 Engineering Principles

### Candidate ≠ Verified

An LLM response is a candidate remediation until execution provides evidence that the generated code runs successfully.

### Feedback Matters

Execution errors provide useful signals that can be passed back into the remediation workflow.

### Bounded Automation

Retries are deliberately bounded to prevent uncontrolled autonomous loops.

### Historical Knowledge

Previously verified incidents can provide useful context for future incidents.

### Human Oversight

Automated remediation should not remove the need for engineering review, particularly for production systems.

---

# 📊 What This Project Demonstrates

SRE Swarm AI demonstrates practical integration of:

- Large Language Models
- Google Gemini
- FastAPI
- LangGraph
- ChromaDB
- Embeddings
- Retrieval
- Code generation
- Automated code execution
- Retry-based workflows
- Unified diffs
- Structured API design
- Root-cause analysis
- Persistent incident memory
- Polyglot execution

The central engineering concept is not simply:

    LLM → Generate Code

Instead, the project implements:

    Incident
       ↓
    Understand
       ↓
    Retrieve Previous Knowledge
       ↓
    Generate Candidate Fix
       ↓
    Execute
       ↓
    Observe Result
       ↓
    Retry if Necessary
       ↓
    Verify
       ↓
    Generate RCA
       ↓
    Store Knowledge

---

# 📚 Learning Outcomes

The project provides practical experience with:

- LLM-powered application development
- Gemini API integration
- LangGraph state-based workflows
- FastAPI REST API development
- ChromaDB vector storage
- Embedding-based similarity search
- Subprocess execution
- Multi-language execution
- Automated feedback loops
- Retry strategies
- Error handling
- Unified diff generation
- Structured API responses
- Root-cause analysis
- Persistent incident memory
- SRE automation concepts
- Reliability considerations for LLM-generated code
- Security considerations for automated code execution

---

# 🔮 Future Scope

Potential future improvements include:

- Secure container-based execution
- Real unit-test-based verification
- Repository-level code analysis
- GitHub integration
- Pull-request generation
- Automated regression testing
- Static analysis integration
- Security scanning
- CI/CD integration
- Prometheus/Grafana observability
- Incident-management integrations
- Human approval gates
- Improved semantic incident retrieval
- Evaluation datasets
- Reproducible benchmarks
- Production-grade authentication and authorization

---

# 👨‍💻 Author

**Deepak Singh Bisht**

B.Tech CSE (AI/ML)

GitHub: https://github.com/Yoshi1710

---

# 📄 Project Status

SRE Swarm AI is an engineering and learning project demonstrating an LLM-assisted SRE incident remediation workflow.

The current implementation focuses on:

**Incident → Remediation → Execution → Feedback → Verification → RCA → Memory**

The system is not presented as a replacement for production SRE teams or general-purpose coding agents. Its purpose is to demonstrate the design and implementation of an SRE-specific automated remediation pipeline using modern LLM, workflow orchestration, execution, and retrieval technologies.