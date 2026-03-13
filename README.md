# ⚙️ Configurable Workflow Decision Platform

> A production-ready, config-driven workflow engine that processes requests through multi-step workflows with rule evaluation, full audit trails, retry logic, and idempotency — **zero code changes needed to add new workflows**.

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-orange)](https://sqlalchemy.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Table of Contents

- [System Overview](#system-overview)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [How Workflows Work](#how-workflows-work)
- [How Rules are Configured](#how-rules-are-configured)
- [Quick Start (Local)](#quick-start-local)
- [API Documentation](#api-documentation)
- [Example Requests](#example-requests)
- [Deployment](#deployment)
- [Design Tradeoffs](#design-tradeoffs)
- [Hackathon Features](#hackathon-features)

---

## System Overview

The **Configurable Workflow Decision Platform** is a backend engine that:

1. **Receives** incoming requests via REST API
2. **Routes** them to the correct workflow (defined in YAML)
3. **Executes** multi-step workflows (validation → rules → external calls → decision)
4. **Evaluates** configurable business rules with AND/OR logic
5. **Calls** simulated external services (credit bureau, KYC, background check, etc.)
6. **Retries** failed steps with exponential backoff
7. **Records** every event in an immutable audit log
8. **Returns** a decision with full traceability

### Included Workflow Types

| Workflow | Description | Steps |
|----------|-------------|-------|
| `application_approval` | Loan/credit application processing | validate → rules → credit bureau → KYC → employment → decision |
| `claim_processing` | Insurance claim evaluation | validate → eligibility → policy check → fraud screening → decision |
| `employee_onboarding` | New hire setup and access provisioning | validate → background check → KYC → tax check → provision → notify |
| `vendor_approval` | Vendor onboarding and vetting | validate → rules → sanctions → document check → decision |
| `document_verification` | Document authenticity verification | validate → type check → authenticity → identity cross-check → decision |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLIENT (HTTP Request)                        │
└─────────────────────────────┬───────────────────────────────────┘
                               │ POST /process-request
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                         │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │  API Router  │  │ Idempotency    │  │   Config Loader      │ │
│  │  /process    │  │ Key Handler    │  │   (YAML Hot Reload)  │ │
│  │  /status     │  │ (dedup guard)  │  │                      │ │
│  │  /audit-log  │  └────────────────┘  └──────────────────────┘ │
│  └──────┬───────┘                                                │
└─────────┼───────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Engine                                │
│                                                                  │
│  Step 1: validate_input  ──► validates required fields           │
│  Step 2: rule_check      ──► RuleEngine evaluates conditions     │
│  Step 3: external_call   ──► ExternalServiceSimulator + retry    │
│  Step 4: decision        ──► Final approval/rejection            │
│  Step 5: notification    ──► Simulated notifications             │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │   Rule Engine    │  │  External Sim    │  │ Audit Logger  │  │
│  │  gte/lte/in/     │  │  credit_bureau   │  │  immutable    │  │
│  │  between/regex   │  │  kyc/background  │  │  trail every  │  │
│  │  AND/OR/NESTED   │  │  + retry logic   │  │  event        │  │
│  └──────────────────┘  └──────────────────┘  └───────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Database (SQLite / PostgreSQL)              │
│                                                                  │
│  workflow_instances    audit_logs    idempotency_records         │
│  (state + decision)   (event trail) (duplicate prevention)      │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| **API Router** | Receives HTTP requests, validates schemas, returns responses |
| **WorkflowEngine** | Orchestrates step execution, manages state transitions |
| **ConfigLoader** | Loads/hot-reloads YAML workflow definitions |
| **RuleEngine** | Evaluates business rules with AND/OR/composite logic |
| **ExternalServiceSimulator** | Simulates 8 external APIs with latency + failure rates |
| **AuditLogger** | Writes immutable event records for full traceability |
| **IdempotencyHandler** | Prevents duplicate processing via key tracking |

### Data Flow

```
Request → Idempotency Check → Load Config → Create Instance →
  For each step:
    → Execute step (validate/rule/external/decision/notify)
    → Write audit event
    → Update state
    → Handle failure/retry
→ Final Decision → Persist Result → Return Response
```

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **API** | FastAPI 0.115 | Async, auto-docs, Pydantic validation |
| **ORM** | SQLAlchemy 2.0 (async) | Type-safe, supports SQLite & PostgreSQL |
| **Database** | SQLite (dev) / PostgreSQL (prod) | Zero-config locally, production-grade on Render |
| **Config** | YAML + PyYAML | Human-readable, git-trackable, hot-reloadable |
| **Testing** | Pytest + pytest-asyncio | Async test support, clean fixtures |
| **Deployment** | Docker + Render/Railway | One-command deploy |

---

## Project Structure

```
workflow-engine/
│
├── app/
│   ├── main.py                   # FastAPI app, lifespan, middleware
│   ├── api/
│   │   └── routes.py             # All API endpoints
│   ├── workflows/
│   │   └── engine.py             # Core workflow orchestrator
│   ├── rules/
│   │   └── rule_engine.py        # Rule evaluation (AND/OR/composite)
│   ├── services/
│   │   ├── config_loader.py      # YAML config loader + hot reload
│   │   ├── database.py           # SQLAlchemy async engine + sessions
│   │   └── external_service.py   # External API simulator + retry
│   ├── models/
│   │   ├── database.py           # SQLAlchemy ORM models
│   │   └── schemas.py            # Pydantic request/response schemas
│   └── audit/
│       └── audit_logger.py       # Immutable audit trail writer
│
├── configs/
│   ├── application_approval.yaml # Loan approval workflow
│   └── workflows.yaml            # Claim, onboarding, vendor, doc workflows
│
├── tests/
│   ├── conftest.py               # Test DB setup
│   └── test_workflow.py          # Full test suite (50+ tests)
│
├── Dockerfile                    # Multi-stage production image
├── docker-compose.yml            # Local dev with PostgreSQL
├── render.yaml                   # One-click Render deployment
├── requirements.txt
└── README.md
```

---

## How Workflows Work

Workflows are defined in YAML. Each workflow has **steps**, and each step has a **type** that determines its behavior:

| Step Type | What it does |
|-----------|-------------|
| `validate` | Checks required fields exist and have correct types |
| `rule_check` | Evaluates business rules against payload data |
| `external_call` | Calls a simulated external service (with retry) |
| `decision` | Makes final approved/rejected determination |
| `notification` | Sends simulated email/SMS/audit notification |
| `process` | Generic data transformation/enrichment |

**Execution is sequential.** Each step can:
- Pass → continue to next step
- Fail on a **required** step → terminate workflow as `rejected`
- Fail on an **optional** step → skip and continue
- Produce **output data** that's available to all subsequent steps

### State Machine

```
pending → running → completed (approved)
                  → completed (rejected)
                  → failed
```

---

## How Rules are Configured

Rules are defined inline in YAML. No code changes required.

### Simple Rule

```yaml
rules:
  - name: minimum_salary
    field: salary
    operator: gte
    value: 50000
    fail_message: "Salary {actual} below minimum {expected}"
```

### Composite Rule (AND/OR)

```yaml
rules:
  - name: credit_check
    type: composite
    logic: AND          # all conditions must pass
    conditions:
      - name: score_ok
        field: credit_score
        operator: gte
        value: 650
      - name: debt_low
        field: debt_ratio
        operator: lte
        value: 0.43
```

### Supported Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` / `neq` | Equal / not equal | `salary eq 50000` |
| `gt` / `gte` | Greater than / or equal | `age gte 18` |
| `lt` / `lte` | Less than / or equal | `risk_score lte 0.7` |
| `in` / `not_in` | List membership | `dept in [eng, sales]` |
| `between` | Range check | `score between [580, 850]` |
| `is_true` / `is_false` | Boolean check | `document_submitted is_true` |
| `not_null` / `is_null` | Null check | `tax_id not_null` |
| `contains` | Substring match | `notes contains urgent` |
| `regex` | Regex pattern | `email regex ^.+@.+$` |

### Rule Logic

```yaml
rule_logic: AND   # All rules must pass (default)
rule_logic: OR    # Any rule passing is sufficient
```

---

## Quick Start (Local)

### Prerequisites
- Python 3.12+
- pip

### 1. Clone and Install

```bash
git clone https://github.com/your-username/workflow-engine.git
cd workflow-engine

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

The server starts at **http://localhost:8000**

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health/

### 3. Run Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=app --cov-report=html  # with coverage
```

### 4. Docker (Local)

```bash
# SQLite (simplest)
docker build -t workflow-engine .
docker run -p 8000:8000 workflow-engine

# With PostgreSQL
docker compose up -d
```

---

## API Documentation

### `POST /process-request`

Submit a request for workflow processing.

**Request Body:**
```json
{
  "workflow_type": "application_approval",
  "idempotency_key": "app-2024-001",
  "payload": {
    "applicant_name": "Jane Doe",
    "salary": 75000,
    "credit_score": 720,
    "loan_amount": 200000,
    "document_submitted": true
  }
}
```

**Response:**
```json
{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "message": "Workflow 'application_approval' completed. Decision: APPROVED",
  "idempotent": false,
  "result": {
    "decision": "approved",
    "decision_reason": "All conditions met",
    "steps_completed": ["validate_input", "eligibility_rules", "credit_bureau_check", "kyc_verification", "final_approval_decision"],
    "rules_triggered": [...],
    "retry_count": 0
  }
}
```

**Idempotency:** Send `X-Idempotency-Key: your-key` header or include `idempotency_key` in body. Duplicate requests return the original result instantly.

---

### `GET /workflow-status/{workflow_id}`

Get current workflow state.

```json
{
  "id": "550e8400-...",
  "workflow_type": "application_approval",
  "status": "completed",
  "current_step": null,
  "steps_completed": ["validate_input", "eligibility_rules", "..."],
  "decision": "approved",
  "decision_reason": "All conditions met",
  "rules_triggered": [...],
  "retry_count": 0,
  "created_at": "2024-01-15T10:30:00",
  "completed_at": "2024-01-15T10:30:02"
}
```

---

### `GET /audit-log/{workflow_id}`

Full immutable audit trail with decision traceability.

```json
{
  "workflow_id": "550e8400-...",
  "workflow_type": "application_approval",
  "workflow_status": "completed",
  "decision": "approved",
  "total_events": 18,
  "traceability_summary": {
    "execution_path": ["validate_input", "eligibility_rules", "credit_bureau_check", "..."],
    "rules_evaluated": [{"rule": "minimum_salary", "passed": true}, ...],
    "external_calls": [{"service": "credit_bureau", "success": true, "latency_ms": 342}],
    "final_decision": {"decision": "approved", "reason": "All conditions met"}
  },
  "events": [
    {"event_type": "workflow_started", "message": "Workflow started", "created_at": "..."},
    {"event_type": "step_completed", "step_name": "validate_input", "duration_ms": 2},
    {"event_type": "rule_evaluated", "rule_name": "minimum_salary", "rule_result": true},
    {"event_type": "external_call", "step_name": "credit_bureau", "duration_ms": 342},
    {"event_type": "decision_made", "message": "Decision: APPROVED"},
    {"event_type": "workflow_completed", "message": "Workflow completed in 1.2s"}
  ]
}
```

---

### Other Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Platform overview + available workflows |
| `GET` | `/health/` | Health check (DB status, loaded configs) |
| `GET` | `/workflows` | List all configured workflow types |
| `GET` | `/workflows/{type}/config` | Get raw YAML config for a workflow |
| `POST` | `/workflows/reload` | Hot reload all configs (no restart needed) |
| `GET` | `/workflows/instances/list` | List workflow instances with filtering |

---

## Example Requests

### Application Approval (Approved)

```bash
curl -X POST http://localhost:8000/process-request \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: app-001" \
  -d '{
    "workflow_type": "application_approval",
    "payload": {
      "applicant_name": "Jane Doe",
      "salary": 75000,
      "credit_score": 720,
      "loan_amount": 200000,
      "employment_years": 3,
      "document_submitted": true
    }
  }'
```

### Application Rejection (Low Credit Score)

```bash
curl -X POST http://localhost:8000/process-request \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "application_approval",
    "payload": {
      "applicant_name": "John Low",
      "salary": 80000,
      "credit_score": 400,
      "loan_amount": 200000,
      "document_submitted": true
    }
  }'
```
> **Decision: REJECTED** — credit_score 400 < minimum 620

### Duplicate Request (Idempotency)

```bash
# Send the same key twice — second call returns cached result
curl -X POST http://localhost:8000/process-request \
  -H "X-Idempotency-Key: dedup-key-123" \
  -d '{ "workflow_type": "claim_processing", "payload": {...} }'
# Second call → idempotent: true, same workflow_id
```

### Claim Processing

```bash
curl -X POST http://localhost:8000/process-request \
  -d '{
    "workflow_type": "claim_processing",
    "payload": {
      "claimant_name": "Bob Smith",
      "claim_amount": 5000,
      "incident_date": "2024-01-15",
      "policy_number": "POL-123456",
      "claim_type": "medical"
    }
  }'
```

---

## Deployment

### GitHub

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/workflow-engine.git
git add .
git commit -m "feat: initial workflow decision platform"
git push -u origin main
```

### Docker

```bash
# Build
docker build -t workflow-engine:latest .

# Run (SQLite)
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/configs:/app/configs \
  --name workflow-engine \
  workflow-engine:latest

# Run (PostgreSQL)
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db" \
  workflow-engine:latest
```

### Render (One-Click)

1. Push code to GitHub
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your GitHub repository
4. Render reads `render.yaml` and provisions API + PostgreSQL automatically
5. Your API is live at `https://workflow-engine-api.onrender.com`

### Railway

```bash
npm install -g @railway/cli
railway login
railway init
railway up

# Set environment variables
railway variables set DATABASE_URL="${{Postgres.DATABASE_URL}}"
railway variables set CONFIGS_DIR="configs"
```

---

## Design Tradeoffs

### SQLite vs PostgreSQL
- **SQLite** for local dev — zero config, single file, works on any machine
- **PostgreSQL** for production — concurrent writes, connection pooling, pgvector for future ML rules
- Swap with `DATABASE_URL` env var — no code changes

### Synchronous Steps vs Message Queue
- **Current**: Synchronous execution within request — simple, debuggable, immediate response
- **Scalable**: Add Celery + Redis for async execution if workflows take >10s or need background processing

### YAML vs Database-Stored Configs
- **YAML**: Git-tracked, reviewable, hot-reloadable, human-readable
- **Tradeoff**: No UI to edit configs; requires file access to change rules
- **Future**: Add a config management API to store/edit workflows in the DB

### Single Worker vs Horizontal Scale
- **Current**: Single uvicorn worker with async I/O handles hundreds of concurrent requests
- **Scale**: Add workers with `--workers 4` or deploy multiple containers behind a load balancer
- **Stateless**: All state is in the database, so horizontal scaling works without sticky sessions

### Retry Strategy
- Exponential backoff with configurable base delay and multiplier per step
- Max retries configurable per step (not just globally) for fine-grained control
- Tradeoff: Could implement circuit breaker pattern to stop calling failing services entirely

---

## Hackathon Features

### ✅ Decision Traceability
Every decision shows: Input → Rules triggered → Decision → Execution path → Full audit trail. Hit `GET /audit-log/{id}` for the complete story.

### ✅ Config Hot Reload
`POST /workflows/reload` reloads all YAML files without restarting. Change a threshold in YAML, hit reload, next request uses the new rule.

### ✅ Workflow Visualization
`GET /workflows/{type}/config` returns the full workflow graph. `GET /workflows` shows all workflows with step counts and metadata.

### ✅ Extensible Rule Engine
Add a new operator in 2 lines:
```python
OPERATORS["percentage"] = lambda a, b: (float(a) / float(b[0])) * 100 >= float(b[1])
```

### ✅ Idempotency
Send the same `X-Idempotency-Key` twice — get the same result instantly, no duplicate processing. Critical for payment/approval workflows.

### ✅ Full Audit Log
Every event (step started, rule evaluated, external call, retry, decision) is written to an immutable append-only log. Perfect for compliance and debugging.

### ✅ 8 Simulated External Services
`credit_bureau`, `kyc_verification`, `background_check`, `document_verification`, `sanctions_screening`, `employment_verification`, `insurance_check`, `tax_verification` — all with realistic latency and configurable failure rates.

### ✅ Zero Code for New Workflows
Drop a new YAML file into `configs/`, call `POST /workflows/reload`, and the new workflow is live.
