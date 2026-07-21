# AgentCare — Agentic AI for Patient Administration & Care Coordination

An agentic healthcare **administration** system that coordinates a patient's
non-clinical journey — registration → department routing → appointment booking →
document coordination → confirmation & reminders → follow-up — while keeping all
medical decisions under human supervision.

> **Safety boundary:** AgentCare performs administration and coordination only.
> It never diagnoses conditions, prescribes medicine, recommends dosages, or
> claims to replace a clinician. Emergency or clinical requests are escalated to
> a human.

**AgentCare Build Challenge 2026 submission.**

---

## Architecture (planned)

```
Patient request (natural language)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  LangGraph orchestration (state persisted via SQL checkpoint)│
│                                                               │
│  Coordinator → Safety → Routing → Appointment → Document      │
│                          → Follow-up → Confirmation           │
└─────────────────────────────────────────────────────────────┘
        │                          │
        ▼                          ▼
  Tools (real DB logic)      Persistent SQL database
  • patient records          (SQLite / PostgreSQL)
  • department lookup        • patients, departments, doctors
  • slot availability        • slots, appointments, documents
  • booking / conflict       • workflow_runs (agent state)
  • document classify/dedupe • reminders, escalations
  • reminders                • audit_events
  • escalation / approval
  • audit logging
```

### Agents (each with its own prompt + responsibility/tools)
| Agent | Responsibility |
|-------|----------------|
| **Coordinator** | Understands the goal, sequences agents, tracks completion |
| **Safety & Escalation** | Blocks diagnosis/prescription, escalates emergencies |
| **Department Routing** | Classifies request → maps to a department, handles uncertainty |
| **Appointment** | Slots, conflict checks, book / reschedule / cancel, persists |
| **Document** | Classify, checksum, dedupe, patient-mapping, missing-doc checks |
| **Follow-up** | Reminders and post-visit follow-up tasks |

---

## Tech stack
- **Orchestration:** LangGraph (stateful graph, SQL checkpointer)
- **LLM:** Groq (`llama-3.3-70b-versatile`, free tier)
- **Backend:** FastAPI (role-based access enforced server-side)
- **Database:** SQLAlchemy → SQLite (dev) / PostgreSQL (prod)
- **UI:** Streamlit (patient + staff views)

---

## Setup

### 1. Clone & create a virtual environment
```bash
git clone <your-repo-url>
cd agentcare
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (free at https://console.groq.com)
```

### 4. Initialize and seed the database
```bash
python init_db.py     # create all tables
python seed.py        # load synthetic departments, doctors, slots, demo users
```

### 5. Run tests
```bash
pytest -q
```

### Demo logins (synthetic)
| Role | Email | Password |
|------|-------|----------|
| Admin | admin@agentcare.local | admin123 |
| Staff | staff@agentcare.local | staff123 |
| Patient | patient@agentcare.local | patient123 |

*(Backend / UI run commands are added on Day 4–5.)*

---

## Project structure
```
agentcare/
├── app/
│   ├── config.py        # environment-based configuration
│   ├── database.py      # SQLAlchemy engine + session
│   ├── models.py        # all ORM models (persistent SQL schema)
│   ├── security.py      # password hashing
│   ├── tools/           # agent tools (Day 2)
│   ├── agents/          # LangGraph agents + graph (Day 3)
│   ├── api/             # FastAPI backend + RBAC (Day 4)
│   └── ui/              # Streamlit interface (Day 5)
├── tests/               # pytest suite
├── init_db.py           # create tables
├── seed.py              # synthetic seed data
├── requirements.txt
├── .env.example         # config template (no secrets)
└── .github/workflows/   # CI checks
```

---

## Data & secret safety
- No real patient data — all seed data is synthetic.
- Secrets live only in a local, gitignored `.env`; `.env.example` ships without values.
- Passwords are bcrypt-hashed; never stored in plaintext.

---

## Status
- [x] **Day 1** — project scaffold, full SQL schema, seed data, tests, config
- [ ] Day 2 — tools layer (DB-backed functions)
- [ ] Day 3 — LangGraph agents + orchestration
- [ ] Day 4 — FastAPI backend + role-based access + escalation approval
- [ ] Day 5 — Streamlit UI (patient + staff)
- [ ] Day 6 — hardening, edge cases, docs
- [ ] Day 7 — demo video, deploy, submit
