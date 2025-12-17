# Project Structure

**Complete File Tree for DocExtract**

This document provides a comprehensive overview of all files in the project, their purposes, and their relationships.

---

## Directory Overview
```
docextract/
├── config/                     # Django project configuration
├── apps/                       # Django applications (business logic)
├── frontend/                   # Vue.js SPA (TypeScript + Tailwind)
├── nginx/                      # Nginx reverse proxy configuration
├── scripts/                    # Deployment and operational scripts
├── docs/                       # Technical documentation
├── media/                      # User-uploaded files (gitignored)
├── staticfiles/                # Collected static files (gitignored)
├── backups/                    # Database and media backups (gitignored)
├── logs/                       # Application logs (gitignored)
├── certbot/                    # SSL certificates (gitignored)
└── [root files]                # Project-level configuration
```

---

## Complete File Tree
```
docextract/
│
├── .dockerignore               # Files excluded from Docker build context
├── .env                        # Environment variables (gitignored, local only)
├── .env.example                # Environment variable template (development)
├── .env.production.example     # Environment variable template (production)
├── .gitignore                  # Files excluded from version control
├── Dockerfile                  # Container image definition
├── docker-compose.yml          # Local development service orchestration
├── docker-compose.prod.yml     # Production service orchestration
├── Makefile                    # Convenience commands for dev and prod
├── manage.py                   # Django CLI entry point
├── requirements.txt            # Python package dependencies
├── README.md                   # Project overview and quick start
│
├── config/                     # ─── DJANGO PROJECT CONFIGURATION ───
│   ├── __init__.py             # Celery app import for Django integration
│   ├── celery.py               # Celery application configuration
│   ├── urls.py                 # Root URL routing (/admin, /api/v1/, /health/)
│   ├── wsgi.py                 # WSGI entry point for Gunicorn
│   └── settings/               # ─── Environment-specific settings ───
│       ├── __init__.py         # Settings package marker
│       ├── base.py             # Shared settings (apps, middleware, DRF, logging)
│       ├── development.py      # Development overrides (DEBUG=True, CSRF for frontend)
│       └── production.py       # Production settings (HTTPS, security, env-based)
│
├── nginx/                      # ─── NGINX REVERSE PROXY ───
│   ├── nginx.conf              # Main Nginx configuration (workers, gzip, upstream)
│   └── conf.d/                 # ─── Server configurations ───
│       └── default.conf        # HTTP/HTTPS server blocks, SSL, proxy settings
│
├── scripts/                    # ─── OPERATIONAL SCRIPTS ───
│   ├── deploy.sh               # Deployment automation (init, update, rollback)
│   ├── backup.sh               # Database and media backup with retention
│   ├── restore.sh              # Disaster recovery with confirmations
│   ├── ssl-setup.sh            # Let's Encrypt certificate automation
│   └── health-check.sh         # Service health monitoring (human/JSON output)
│
├── apps/                       # ─── DJANGO APPLICATIONS ───
│   │
│   ├── common/                 # ─── Shared Utilities ───
│   │   ├── __init__.py         # App description and metadata
│   │   ├── apps.py             # Django app configuration
│   │   ├── admin.py            # Tenant admin interface
│   │   ├── models.py           # TimestampMixin, TenantMixin, Tenant
│   │   ├── middleware.py       # TraceIDMiddleware - request correlation
│   │   ├── views.py            # health_check endpoint for monitoring
│   │   ├── services/           # ─── Service base classes ───
│   │   │   ├── __init__.py     # Package exports
│   │   │   └── base.py         # ServiceResult, ServiceContext, BaseService
│   │   └── tasks/              # ─── Celery task base classes ───
│   │       ├── __init__.py     # Package exports
│   │       └── base.py         # IdempotentTask base class
│   │
│   ├── documents/              # ─── Document Upload & Storage ───
│   │   ├── __init__.py         # App description, API endpoint docs
│   │   ├── apps.py             # Django app configuration
│   │   ├── admin.py            # Document admin with status badges, actions
│   │   ├── models.py           # Document, DocumentStatus
│   │   ├── urls.py             # URL routing for /api/v1/documents/
│   │   ├── views.py            # DocumentViewSet, Extract, Download, Extractions
│   │   ├── serialisers.py      # 8 DRF serialisers (British spelling)
│   │   ├── services.py         # DocumentService business logic
│   │   └── selectors.py        # DocumentSelector queries
│   │
│   ├── extraction/             # ─── AI Extraction Pipeline ───
│   │   ├── __init__.py         # App description, workflow docs
│   │   ├── apps.py             # Django app configuration
│   │   ├── admin.py            # Extraction review admin with inline fields
│   │   ├── models.py           # ProposedExtraction, ProposedField, ExtractedField
│   │   ├── prompt_models.py    # PromptTemplate model for custom prompts
│   │   ├── urls.py             # URL routing for /api/v1/extractions/
│   │   ├── prompt_urls.py      # URL routing for /api/v1/prompts/
│   │   ├── views.py            # ExtractionViewSet, Commit, Reject views
│   │   ├── prompt_views.py     # PromptTemplateViewSet, Active, Defaults views
│   │   ├── serialisers.py      # 10 DRF serialisers (British spelling)
│   │   ├── prompt_serialisers.py # 6 DRF serialisers for prompts
│   │   ├── services.py         # ExtractionService business logic
│   │   ├── selectors.py        # ExtractionSelector queries
│   │   ├── actions.py          # CommitExtractionAction, RejectExtractionAction
│   │   ├── tasks.py            # Celery task: process_extraction_task
│   │   └── agents.py           # ExtractionAgent with OpenAI + prompt loading
│   │
│   ├── actions/                # ─── Auditable State Changes ───
│   │   ├── __init__.py         # App description, Action pattern docs
│   │   ├── apps.py             # Django app configuration
│   │   ├── admin.py            # Action audit log admin (read-only)
│   │   ├── models.py           # Action, ActionType, ActionStatus
│   │   ├── urls.py             # URL routing for /api/v1/actions/
│   │   ├── views.py            # ActionViewSet, Rollback view
│   │   ├── serialisers.py      # 7 DRF serialisers (British spelling)
│   │   └── base.py             # BaseAction, ReversibleAction, ActionResult
│   │
│   └── features/               # ─── Feature Flag System ───
│       ├── __init__.py         # App description
│       ├── apps.py             # Django app configuration
│       ├── admin.py            # Feature flag admin with rollout display
│       ├── models.py           # FeatureFlag with tenant overrides
│       └── middleware.py       # FeatureFlagMiddleware - flag injection
│
├── frontend/                   # ─── VUE.JS SINGLE PAGE APPLICATION ───
│   ├── package.json            # NPM dependencies and scripts
│   ├── package-lock.json       # Locked dependency versions
│   ├── vite.config.js          # Vite dev server + API proxy config
│   ├── tailwind.config.js      # Tailwind CSS configuration
│   ├── postcss.config.js       # PostCSS plugins (Tailwind, Autoprefixer)
│   ├── tsconfig.json           # TypeScript config (strict mode, path aliases)
│   ├── tsconfig.node.json      # TypeScript config for Node/Vite
│   ├── index.html              # Entry HTML file
│   ├── node_modules/           # NPM packages (gitignored)
│   └── src/                    # ─── Source code ───
│       ├── main.ts             # Vue app bootstrap
│       ├── style.css           # Tailwind directives + custom component classes
│       ├── vite-env.d.ts       # Vite/Vue type declarations
│       ├── App.vue             # Root component with sidebar navigation
│       ├── api/                # ─── API client ───
│       │   └── client.ts       # Axios instance + CSRF handling + API helpers
│       ├── router/             # ─── Vue Router ───
│       │   └── index.ts        # Route definitions with lazy loading
│       └── pages/              # ─── Page components ───
│           ├── DocumentsPage.vue      # Document list with progress polling
│           ├── DocumentDetailPage.vue # Document detail + extractions
│           ├── PromptsPage.vue        # Extraction settings overview
│           └── PromptEditorPage.vue   # Configuration editor
│
├── docs/                       # ─── TECHNICAL DOCUMENTATION ───
│   ├── ARCHITECTURE.md         # System design, component diagrams, data flow
│   ├── DATA_MODEL.md           # Database schema, model specifications
│   ├── API_CONTRACTS.md        # REST endpoint specs, request/response schemas
│   ├── SERVICE_LAYER.md        # Services, Selectors, Actions interfaces
│   ├── CELERY_TASKS.md         # Async task specs, idempotency patterns
│   ├── DEPLOYMENT.md           # Hetzner VPS setup, production Docker config
│   ├── DEVELOPMENT.md          # Local development setup guide
│   ├── SECURITY.md             # Security considerations and practices
│   ├── TESTING.md              # Test strategy and patterns
│   ├── PROJECT_STRUCTURE.md    # This file
│   ├── PROMPT_FEATURE_INTEGRATION.md # Prompt template integration guide
│   ├── PROGRESS_UPDATE.md      # Session 3 progress
│   ├── PROGRESS_UPDATE_SESSION4.md # Session 4 progress
│   └── PROGRESS_UPDATE_SESSION5.md # Session 5 progress (current)
│
├── media/                      # ─── USER UPLOADS (gitignored) ───
│   └── documents/              # Uploaded document files
│       └── YYYY/MM/DD/         # Date-partitioned storage
│
├── staticfiles/                # ─── COLLECTED STATIC (gitignored) ───
│   └── [collected files]       # Output of collectstatic command
│
├── backups/                    # ─── BACKUPS (gitignored) ───
│   ├── db_YYYYMMDD_HHMMSS.sql.gz     # Database backups
│   ├── media_YYYYMMDD_HHMMSS.tar.gz  # Media file backups
│   └── env_YYYYMMDD_HHMMSS           # Environment file backups
│
├── logs/                       # ─── LOGS (gitignored) ───
│   └── deploy_YYYYMMDD_HHMMSS.log    # Deployment logs
│
└── certbot/                    # ─── SSL CERTIFICATES (gitignored) ───
    ├── conf/                   # Let's Encrypt configuration
    └── www/                    # ACME challenge files
```

---

## File Status Legend

| Status | Meaning |
|--------|---------|
| ✅ | Implemented and complete |
| 🔄 | Partially complete or needs enhancement |
| 🔲 | Stub/placeholder |

---

## Current Implementation Status

### Root Files
| File | Status | Description |
|------|--------|-------------|
| `.dockerignore` | ✅ | Docker build exclusions |
| `.env` | ✅ | Local environment (gitignored) |
| `.env.example` | ✅ | Development environment template |
| `.env.production.example` | ✅ | Production environment template |
| `.gitignore` | ✅ | Comprehensive git exclusions |
| `Dockerfile` | ✅ | Container with collectstatic + healthcheck |
| `docker-compose.yml` | ✅ | Dev orchestration with OpenAI |
| `docker-compose.prod.yml` | ✅ | Production orchestration (Gunicorn + Nginx) |
| `Makefile` | ✅ | Convenience commands |
| `manage.py` | ✅ | Django CLI |
| `requirements.txt` | ✅ | Dependencies (incl. openai, PyPDF2) |
| `README.md` | ✅ | Project overview |

### Nginx Configuration
| File | Status | Description |
|------|--------|-------------|
| `nginx/nginx.conf` | ✅ | Main config (workers, gzip, upstream) |
| `nginx/conf.d/default.conf` | ✅ | Server blocks, SSL, proxy settings |

### Operational Scripts
| File | Status | Description |
|------|--------|-------------|
| `scripts/deploy.sh` | ✅ | Deployment automation |
| `scripts/backup.sh` | ✅ | Backup with retention |
| `scripts/restore.sh` | ✅ | Disaster recovery |
| `scripts/ssl-setup.sh` | ✅ | Let's Encrypt automation |
| `scripts/health-check.sh` | ✅ | Service monitoring |

### Config Package
| File | Status | Description |
|------|--------|-------------|
| `config/__init__.py` | ✅ | Celery import |
| `config/celery.py` | ✅ | Celery config |
| `config/urls.py` | ✅ | URL routing |
| `config/wsgi.py` | ✅ | WSGI entry |
| `config/settings/base.py` | ✅ | Shared settings + OPENAI_API_KEY |
| `config/settings/development.py` | ✅ | Dev settings + CSRF for frontend |
| `config/settings/production.py` | ✅ | Prod settings with env-based HTTPS |

### Common App
| File | Status | Description |
|------|--------|-------------|
| `apps/common/__init__.py` | ✅ | App init |
| `apps/common/apps.py` | ✅ | App config |
| `apps/common/admin.py` | ✅ | Tenant admin |
| `apps/common/models.py` | ✅ | TimestampMixin, TenantMixin, Tenant |
| `apps/common/middleware.py` | ✅ | TraceIDMiddleware |
| `apps/common/views.py` | ✅ | health_check with DB/Redis checks |
| `apps/common/services/__init__.py` | ✅ | Package exports |
| `apps/common/services/base.py` | ✅ | ServiceResult, ServiceContext, BaseService |
| `apps/common/tasks/__init__.py` | ✅ | Package exports |
| `apps/common/tasks/base.py` | ✅ | IdempotentTask |

### Documents App
| File | Status | Description |
|------|--------|-------------|
| `apps/documents/__init__.py` | ✅ | App init with docs |
| `apps/documents/apps.py` | ✅ | App config |
| `apps/documents/admin.py` | ✅ | Document admin with status badges |
| `apps/documents/models.py` | ✅ | Document, DocumentStatus |
| `apps/documents/urls.py` | ✅ | Router + custom paths (ordered correctly) |
| `apps/documents/views.py` | ✅ | 4 API views with tenant fallbacks |
| `apps/documents/serialisers.py` | ✅ | 8 DRF serialisers |
| `apps/documents/services.py` | ✅ | DocumentService |
| `apps/documents/selectors.py` | ✅ | DocumentSelector |

### Extraction App
| File | Status | Description |
|------|--------|-------------|
| `apps/extraction/__init__.py` | ✅ | App init with docs |
| `apps/extraction/apps.py` | ✅ | App config |
| `apps/extraction/admin.py` | ✅ | Extraction admin with inline fields |
| `apps/extraction/models.py` | ✅ | ProposedExtraction, ProposedField, ExtractedField |
| `apps/extraction/prompt_models.py` | ✅ | PromptTemplate model |
| `apps/extraction/urls.py` | ✅ | Router + custom paths + prompt URLs |
| `apps/extraction/prompt_urls.py` | ✅ | Prompt template URL routing |
| `apps/extraction/views.py` | ✅ | 3 API views |
| `apps/extraction/prompt_views.py` | ✅ | 5 prompt API views |
| `apps/extraction/serialisers.py` | ✅ | 10 DRF serialisers |
| `apps/extraction/prompt_serialisers.py` | ✅ | 6 prompt DRF serialisers |
| `apps/extraction/services.py` | ✅ | ExtractionService |
| `apps/extraction/selectors.py` | ✅ | ExtractionSelector |
| `apps/extraction/actions.py` | ✅ | CommitExtractionAction, RejectExtractionAction |
| `apps/extraction/tasks.py` | ✅ | process_extraction_task |
| `apps/extraction/agents.py` | ✅ | ExtractionAgent with prompt template loading |

### Actions App
| File | Status | Description |
|------|--------|-------------|
| `apps/actions/__init__.py` | ✅ | App init with docs |
| `apps/actions/apps.py` | ✅ | App config |
| `apps/actions/admin.py` | ✅ | Action audit log admin |
| `apps/actions/models.py` | ✅ | Action, ActionType, ActionStatus |
| `apps/actions/urls.py` | ✅ | Router + rollback path |
| `apps/actions/views.py` | ✅ | 2 API views + rollback logic |
| `apps/actions/serialisers.py` | ✅ | 7 DRF serialisers |
| `apps/actions/base.py` | ✅ | BaseAction, ReversibleAction |

### Features App
| File | Status | Description |
|------|--------|-------------|
| `apps/features/__init__.py` | ✅ | App init |
| `apps/features/apps.py` | ✅ | App config |
| `apps/features/admin.py` | ✅ | Feature flag admin |
| `apps/features/models.py` | ✅ | FeatureFlag with tenant overrides |
| `apps/features/middleware.py` | ✅ | FeatureFlagMiddleware |

### Frontend App
| File | Status | Description |
|------|--------|-------------|
| `frontend/package.json` | ✅ | NPM config with Vue, Vite, Tailwind |
| `frontend/vite.config.js` | ✅ | Vite + proxy to Django |
| `frontend/tailwind.config.js` | ✅ | Tailwind with custom primary colour |
| `frontend/postcss.config.js` | ✅ | PostCSS plugins |
| `frontend/tsconfig.json` | ✅ | TypeScript strict + path aliases |
| `frontend/tsconfig.node.json` | ✅ | Node TypeScript config |
| `frontend/index.html` | ✅ | Entry HTML |
| `frontend/src/main.ts` | ✅ | Vue bootstrap |
| `frontend/src/style.css` | ✅ | Tailwind + badge-blue class |
| `frontend/src/vite-env.d.ts` | ✅ | Type declarations |
| `frontend/src/App.vue` | ✅ | Root with sidebar nav |
| `frontend/src/api/client.ts` | ✅ | Axios + CSRF + API helpers |
| `frontend/src/router/index.ts` | ✅ | Vue Router config |
| `frontend/src/pages/DocumentsPage.vue` | ✅ | Document list with progress polling |
| `frontend/src/pages/DocumentDetailPage.vue` | ✅ | Document detail page |
| `frontend/src/pages/PromptsPage.vue` | ✅ | Extraction settings page |
| `frontend/src/pages/PromptEditorPage.vue` | ✅ | Configuration editor |

### Documentation
| File | Status | Description |
|------|--------|-------------|
| `docs/ARCHITECTURE.md` | ✅ | System design |
| `docs/DATA_MODEL.md` | ✅ | Database schema |
| `docs/API_CONTRACTS.md` | ✅ | REST endpoint specs |
| `docs/SERVICE_LAYER.md` | ✅ | Services, Selectors, Actions |
| `docs/CELERY_TASKS.md` | ✅ | Async task specs |
| `docs/DEPLOYMENT.md` | ✅ | Production deployment guide |
| `docs/DEVELOPMENT.md` | ✅ | Local setup guide |
| `docs/SECURITY.md` | ✅ | Security practices |
| `docs/TESTING.md` | ✅ | Test strategy |
| `docs/PROJECT_STRUCTURE.md` | ✅ | This file |
| `docs/PROMPT_FEATURE_INTEGRATION.md` | ✅ | Prompt template guide |
| `docs/PROGRESS_UPDATE.md` | ✅ | Session 3 progress |
| `docs/PROGRESS_UPDATE_SESSION4.md` | ✅ | Session 4 progress |
| `docs/PROGRESS_UPDATE_SESSION5.md` | ✅ | Session 5 progress |

---

## API Endpoints

### Documents API
| Method | Endpoint | View | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/documents/` | DocumentViewSet | List documents (paginated) |
| POST | `/api/v1/documents/` | DocumentViewSet | Upload document |
| GET | `/api/v1/documents/{id}/` | DocumentViewSet | Document detail |
| DELETE | `/api/v1/documents/{id}/` | DocumentViewSet | Delete document |
| POST | `/api/v1/documents/{id}/extract/` | DocumentExtractView | Trigger extraction |
| GET | `/api/v1/documents/{id}/download/` | DocumentDownloadView | Download file |
| GET | `/api/v1/documents/{id}/extractions/` | DocumentExtractionsView | List extractions |

### Extractions API
| Method | Endpoint | View | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/extractions/{id}/` | ExtractionViewSet | Extraction detail |
| POST | `/api/v1/extractions/{id}/commit/` | ExtractionCommitView | Commit to canonical |
| POST | `/api/v1/extractions/{id}/reject/` | ExtractionRejectView | Reject extraction |

### Prompts API
| Method | Endpoint | View | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/prompts/` | PromptTemplateViewSet | List templates |
| POST | `/api/v1/prompts/` | PromptTemplateViewSet | Create template |
| GET | `/api/v1/prompts/{id}/` | PromptTemplateViewSet | Template detail |
| PUT | `/api/v1/prompts/{id}/` | PromptTemplateViewSet | Update template |
| DELETE | `/api/v1/prompts/{id}/` | PromptTemplateViewSet | Delete template |
| POST | `/api/v1/prompts/{id}/activate/` | PromptTemplateViewSet | Activate template |
| POST | `/api/v1/prompts/{id}/deactivate/` | PromptTemplateViewSet | Deactivate template |
| POST | `/api/v1/prompts/{id}/duplicate/` | PromptTemplateViewSet | Duplicate template |
| GET | `/api/v1/prompts/active/` | ActivePromptView | Get active prompt |
| GET | `/api/v1/prompts/placeholders/` | PromptPlaceholdersView | List placeholders |
| GET | `/api/v1/prompts/defaults/` | PromptDefaultsView | Get default prompts |
| POST | `/api/v1/prompts/create-default/` | CreateDefaultPromptView | Create from defaults |

### Actions API
| Method | Endpoint | View | Description |
|--------|----------|------|-------------|
| GET | `/api/v1/actions/` | ActionViewSet | List audit log |
| GET | `/api/v1/actions/{id}/` | ActionViewSet | Action detail |
| POST | `/api/v1/actions/{id}/rollback/` | ActionRollbackView | Rollback action |

### Other
| Method | Endpoint | View | Description |
|--------|----------|------|-------------|
| GET | `/health/` | health_check | Service health |
| * | `/admin/` | Django Admin | Admin interface |

---

## Key File Relationships

### Request Flow
```
Client Request
    │
    ▼
config/urls.py ─────────────────────────────────────┐
    │                                               │
    ├─► /admin/ ──► Django Admin                    │
    │                                               │
    ├─► /health/ ──► apps/common/views.health_check │
    │                                               │
    └─► /api/v1/ ──┬► apps/documents/urls.py        │
                   ├► apps/extraction/urls.py       │
                   │   └► prompt_urls.py            │
                   └► apps/actions/urls.py          │
```

### Production Architecture
```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Nginx (:80/:443)                                   │
│  ├─ SSL termination                                 │
│  ├─ Static/media serving                            │
│  └─ Proxy to Gunicorn                               │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Django (Gunicorn :8000)                            │
│  ├─ 3 workers, gthread                              │
│  └─ API + Admin                                     │
└─────────────────────────────────────────────────────┘
    │
    ├───────────────┬───────────────┐
    ▼               ▼               ▼
PostgreSQL      Redis           Celery
  :5432         :6379       (worker + beat)
```

### Frontend Architecture
```
frontend/
    │
    ├─► index.html ──► main.ts ──► App.vue
    │                                 │
    │                    ┌────────────┼────────────┐
    │                    ▼            ▼            ▼
    │              DocumentsPage  DetailPage  PromptsPage
    │                    │            │            │
    │                    └────────────┴────────────┘
    │                                 │
    │                                 ▼
    └─► api/client.ts ──► Axios ──► Django API (via Vite proxy)
```

### Service Layer Flow
```
View (thin)
    │
    ▼
ServiceContext ──► Service ──┬──► Selector (read)
                             │
                             └──► Action (write + audit)
                                      │
                                      ▼
                                   Model
```

### Extraction Workflow
```
DocumentService.trigger_extraction()
    │
    ▼
Celery: process_extraction_task
    │
    ▼
ExtractionAgent.run()
    │
    ├─► Load PromptTemplate from DB (or use defaults)
    ├─► Extract text (PyPDF2 / python-docx)
    ├─► Call OpenAI GPT-4o
    └─► Parse JSON response
    │
    ▼
ProposedExtraction + ProposedFields created
    │
    ▼
[Human Review via Frontend or Admin]
    │
    ├─► ExtractionService.commit_extraction()
    │       └─► ExtractedFields created + Action logged
    │
    └─► ExtractionService.reject_extraction()
            └─► Status updated + Action logged
```

### Prompt Template Loading
```
ExtractionAgent._load_prompt_templates(doc_type)
    │
    ├─► Try: PromptTemplate for tenant + doc_type
    │         └─► Found? Use it
    │
    ├─► Fallback: PromptTemplate for tenant + None (default)
    │         └─► Found? Use it
    │
    └─► Fallback: Hardcoded DEFAULT_SYSTEM_PROMPT + DEFAULT_USER_PROMPT
```

### Middleware Chain
```
config/settings/base.py MIDDLEWARE = [
    ...
    "apps.common.middleware.TraceIDMiddleware",       # Adds request.trace_id
    "apps.features.middleware.FeatureFlagMiddleware", # Adds request.feature_flags
]
```

---

## Implementation Progress

### Session 1 ✅
- [x] Project scaffold
- [x] Django configuration
- [x] Docker setup
- [x] Documentation suite
- [x] Middleware stubs

### Session 2 ✅
- [x] All models with migrations
- [x] Service layer (Services, Selectors, Actions)
- [x] Mock extraction agent
- [x] Django Admin with bulk actions
- [x] Celery task with idempotency

### Session 3 ✅
- [x] API Serialisers (25 total)
- [x] API Views (9 total)
- [x] URL routing (3 apps)
- [x] OpenAI GPT-4o integration
- [x] PDF/DOCX text extraction
- [x] Docker testing verified
- [x] Bug fixes (logging, admin, middleware)

### Session 4 ✅
- [x] Vue.js frontend SPA (complete)
- [x] Document management UI (list, upload, delete, view)
- [x] Extraction viewing UI (fields, confidence scores)
- [x] Prompt template backend (model, views, serialisers)
- [x] Extraction settings UI (simplified for non-technical users)
- [x] URL routing fixes (order matters!)
- [x] Tenant ID fallback fixes
- [x] Serialiser fixes (detail vs list)

### Session 5 ✅
- [x] Production Docker infrastructure (docker-compose.prod.yml)
- [x] Nginx reverse proxy with SSL support
- [x] Operational scripts (deploy, backup, restore, ssl, health)
- [x] Production settings updates (conditional HTTPS)
- [x] Prompt template loading in ExtractionAgent
- [x] Prompts API defaults endpoint
- [x] Frontend progress indicator with polling
- [x] File size NaN fix
- [x] Comprehensive .gitignore and Makefile

### Session 6 (Planned)
- [ ] Hetzner VPS deployment
- [ ] SSL certificate setup
- [ ] Frontend production build
- [ ] Final testing and verification

---

## Environment Variables

### Development
| Variable | Required | Description |
|----------|----------|-------------|
| `DJANGO_SETTINGS_MODULE` | Yes | Settings module path |
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | Database user |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_HOST` | Yes | Database host |
| `REDIS_URL` | Yes | Redis connection URL |
| `OPENAI_API_KEY` | Yes | OpenAI API key for extraction |

### Production (additional)
| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Django secret key (generate with openssl) |
| `ALLOWED_HOSTS` | Yes | Comma-separated hostnames |
| `CSRF_TRUSTED_ORIGINS` | Yes | Full URLs for CSRF |
| `SECURE_SSL_REDIRECT` | Recommended | Enable after SSL setup |
| `SESSION_COOKIE_SECURE` | Recommended | Enable after SSL setup |
| `CSRF_COOKIE_SECURE` | Recommended | Enable after SSL setup |
| `SECURE_HSTS_SECONDS` | Optional | HSTS duration (31536000 = 1 year) |

---

## Makefile Commands

### Development
```bash
make dev              # Start development environment
make stop             # Stop all containers
make logs             # View container logs
make shell            # Django shell
make bash             # Container bash shell
make migrate          # Run migrations
make makemigrations   # Create migrations
make superuser        # Create admin user
make test             # Run tests
make lint             # Run linters
```

### Production
```bash
make prod             # Start production environment
make deploy           # Run deployment script
make backup           # Create backup
make health           # Run health check
make ssl              # Run SSL setup
```

### Maintenance
```bash
make build            # Rebuild containers
make clean            # Remove containers and volumes
make prune            # Docker system prune
make collectstatic    # Collect static files
```

### Frontend
```bash
make frontend-install # npm install
make frontend-dev     # npm run dev
make frontend-build   # npm run build
```

---

## Running the Application

### Development (Docker)
```bash
docker-compose up
# API: http://localhost:8000
# Admin: http://localhost:8000/admin/
```

### Frontend (Vite Dev Server)
```bash
cd frontend
npm install
npm run dev
# UI: http://localhost:5173
```

### Production
```bash
# Initial deployment
./scripts/deploy.sh --init

# SSL setup
./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com

# Updates
./scripts/deploy.sh
```

### Full Development Workflow
1. Start backend: `docker-compose up`
2. Start frontend: `cd frontend && npm run dev`
3. Log into Django Admin (creates session cookie)
4. Access frontend at http://localhost:5173
5. Upload documents, trigger extractions, view results

---

## Adding New Components

### New API Endpoint
```
1. Add serialiser in apps/<app>/serialisers.py
2. Add view in apps/<app>/views.py
3. Add URL pattern in apps/<app>/urls.py (BEFORE router!)
4. Document in docs/API_CONTRACTS.md
```

### New Service Method
```
1. Add method to apps/<app>/services.py
2. Create Action class if mutation
3. Add selector method if new query needed
4. Document in docs/SERVICE_LAYER.md
```

### New Frontend Page
```
1. Create page component in frontend/src/pages/
2. Add route in frontend/src/router/index.ts
3. Add navigation link in frontend/src/App.vue
4. Add API methods in frontend/src/api/client.ts
```

### New Field Type for Extraction
```
1. Add to FieldType choices in apps/extraction/models.py
2. Run makemigrations + migrate
3. Add keywords to FIELD_TYPE_KEYWORDS in agents.py
4. (Optional) Add to FIELD_EXAMPLES for doc-type guidance
```

### New Operational Script
```
1. Create script in scripts/
2. Add execute permission: chmod +x scripts/newscript.sh
3. Add Makefile target if frequently used
4. Document in docs/DEPLOYMENT.md
```