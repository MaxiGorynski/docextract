# DocExtract

**AI-Powered Document Field Extraction with Auditable Two-Phase Commit**

A production-grade Django application demonstrating enterprise patterns for AI-assisted document processing: proposal-based workflows, reversible state changes, async task orchestration, and comprehensive audit logging.

---

## Business Case

Organisations process thousands of documents daily — invoices, contracts, insurance claims, HR forms, purchase orders. Extracting structured data from these documents manually is slow, expensive, and error-prone.

**DocExtract** automates field extraction while keeping humans in control:

1. **Upload** — User uploads a document (PDF/DOCX)
2. **Extract** — AI analyzes the document and proposes extracted fields
3. **Review** — User reviews proposals with confidence scores
4. **Commit** — Approved extractions become canonical data via audited Action
5. **Rollback** — Any committed extraction can be reversed with full audit trail

This two-phase approach (propose → commit) ensures AI suggestions never directly mutate production data, providing safety, debuggability, and compliance.

### Example Use Cases

| Domain | Document Types | Extracted Fields |
|--------|---------------|------------------|
| **Finance** | Invoices, receipts, purchase orders | Vendor, amount, line items, due date, tax |
| **HR** | Resumes, employment contracts, timesheets | Name, skills, salary, dates, hours |
| **Insurance** | Claims, policies, medical records | Claimant, policy number, diagnosis, amounts |
| **Procurement** | Contracts, NDAs, SOWs | Parties, terms, obligations, dates |
| **Real Estate** | Leases, deeds, inspection reports | Address, parties, rent, conditions |

---

## Architecture Highlights

| Pattern | Implementation |
|---------|----------------|
| **Agent / Function / Action** | AI orchestration separated from auditable state changes |
| **Two-Phase Commit** | `ProposedExtraction` → review → `Action.commit()` |
| **Thin Views, Rich Domain** | Views handle auth + validation; Services own business logic |
| **Reversible State Changes** | `Action.rollback()` restores pre-mutation state |
| **Idempotent Async Tasks** | Celery tasks with idempotency keys prevent duplicate processing |
| **Feature Flags** | Toggle AI extraction vs. manual-only mode |
| **Observability** | Structured logging with `trace_id`, `actor_id`, `action_id` |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)
- OpenAI API key (optional — mock extraction works without it)

### Run with Docker Compose

```bash
# Clone and enter directory
git clone <repository-url>
cd docextract

# Configure environment
cp .env.example .env
# Edit .env with your settings (OPENAI_API_KEY is optional)

# Start all services
docker-compose up --build

# In another terminal, run migrations
docker-compose exec web python manage.py migrate

# Create superuser for admin access
docker-compose exec web python manage.py createsuperuser

# Access the application
# Admin: http://localhost:8000/admin
# API: http://localhost:8000/api/v1/
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis (via Docker)
docker-compose up -d db redis

# Run migrations
python manage.py migrate

# Start Django development server
python manage.py runserver

# Start Celery worker (separate terminal)
celery -A docextract worker -l info
```

---

## Project Structure

```
docextract/
├── config/                  # Django project settings
│   ├── settings/
│   │   ├── base.py         # Shared settings
│   │   ├── development.py  # Dev overrides
│   │   └── production.py   # Prod overrides
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── apps/
│   ├── documents/          # Document upload & storage
│   ├── extraction/         # AI extraction pipeline
│   ├── actions/            # Auditable state changes
│   ├── features/           # Feature flag system
│   └── common/             # Shared utilities
├── docs/                   # Documentation
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── API_CONTRACTS.md
│   ├── SERVICE_LAYER.md
│   ├── CELERY_TASKS.md
│   └── DEPLOYMENT.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System design, component boundaries, data flow |
| [Data Model](docs/DATA_MODEL.md) | Database schema, model relationships, field specifications |
| [API Contracts](docs/API_CONTRACTS.md) | REST endpoint specifications, request/response schemas |
| [Service Layer](docs/SERVICE_LAYER.md) | Services, Selectors, Actions — interface contracts |
| [Celery Tasks](docs/CELERY_TASKS.md) | Async task specifications, idempotency, retry policies |
| [Deployment](docs/DEPLOYMENT.md) | Hetzner VPS setup, Docker Compose production config |

---

## Key Design Decisions

### Why Two-Phase Commit?

AI outputs are probabilistic. Directly writing AI-generated data to canonical tables creates:
- **Debugging difficulty** — No visibility into what AI proposed vs. what was saved
- **Rollback complexity** — Hard to undo without knowing previous state
- **Compliance risk** — No audit trail of AI involvement

Our approach: AI writes to `ProposedExtraction`, humans review, explicit `Action.commit()` promotes to `ExtractedField`. Every step is logged.

### Why Actions for State Changes?

The `Action` model provides:
- **Actor tracking** — Who initiated the change (user or system)
- **Pre/post state capture** — Full snapshot for debugging and rollback
- **Idempotency** — Action ID prevents duplicate commits
- **Reversibility** — `rollback()` method restores previous state

This pattern is borrowed from event sourcing without the full complexity — we maintain current state in relational tables but log transitions as Actions.

### Why Feature Flags?

The extraction pipeline can be toggled:
- **Enabled** — Full AI extraction with proposal flow
- **Disabled** — Documents uploaded but no AI processing (manual entry only)
- **Kill switch** — Instantly disable if AI misbehaves in production

Flags are evaluated per-request via middleware and injected into request context.

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=apps --cov-report=html

# Run specific test module
pytest apps/extraction/tests/test_services.py

# Run tests matching pattern
pytest -k "test_action_commit"
```

### Test Categories

- **Unit tests** — Services, Selectors, Actions in isolation
- **Integration tests** — Full request/response cycles with database
- **Celery tests** — Task idempotency, retry behavior, failure handling

---

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/documents/` | POST | Upload document |
| `/api/v1/documents/{id}/` | GET | Retrieve document with extraction status |
| `/api/v1/documents/{id}/extract/` | POST | Trigger extraction (async) |
| `/api/v1/extractions/{id}/` | GET | View proposed extraction |
| `/api/v1/extractions/{id}/commit/` | POST | Commit proposed extraction |
| `/api/v1/extractions/{id}/reject/` | POST | Reject proposed extraction |
| `/api/v1/actions/{id}/` | GET | View action details |
| `/api/v1/actions/{id}/rollback/` | POST | Rollback committed action |

See [API Contracts](docs/API_CONTRACTS.md) for full specifications.

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

## Contributing

This is a demonstration project. For questions or discussions about the architecture patterns, please open an issue.