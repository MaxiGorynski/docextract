# Architecture

**System Design for DocExtract**

This document describes the high-level architecture, component responsibilities, and data flow through the system.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Layer Responsibilities](#layer-responsibilities)
4. [Data Flow](#data-flow)
5. [Agent / Function / Action Pattern](#agent--function--action-pattern)
6. [Security Model](#security-model)
7. [Observability](#observability)

---

## System Overview

DocExtract follows a modular monolith architecture with clear boundaries between domains. The system is designed for:

- **Auditability** — Every state change is logged with actor, timestamp, and pre/post state
- **Reversibility** — Committed changes can be rolled back
- **Safety** — AI outputs are proposals, not direct mutations
- **Operability** — Structured logging, metrics hooks, feature flags

### High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Layer                             │
│                   (Django Admin / API Consumers)                 │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Django Application                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Web Layer (Thin)                         │ │
│  │  • REST Views (DRF)                                        │ │
│  │  • Authentication / Permission checks                       │ │
│  │  • Request validation                                       │ │
│  │  • Trace ID injection (middleware)                         │ │
│  │  • Feature flag evaluation (middleware)                    │ │
│  └─────────────────────────┬──────────────────────────────────┘ │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                  Domain Layer (Rich)                        │ │
│  │  • Services — Business logic, orchestration                │ │
│  │  • Selectors — Read/query operations                       │ │
│  │  • Actions — Auditable state transitions                   │ │
│  │  • Agents — AI workflow orchestration                      │ │
│  │  • Functions — Discrete AI capabilities                    │ │
│  └─────────────────────────┬──────────────────────────────────┘ │
│                            ▼                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Data Layer                               │ │
│  │  • Django ORM Models                                       │ │
│  │  • Custom Managers (tenant-scoped queries)                 │ │
│  │  • Audit Log Models                                        │ │
│  └────────────────────────────────────────────────────────────┘ │
└───────────┬─────────────────────────────────┬───────────────────┘
            │                                 │
            ▼                                 ▼
    ┌───────────────┐                 ┌───────────────┐
    │  PostgreSQL   │                 │    Celery     │
    │  (Primary DB) │                 │   Workers     │
    └───────────────┘                 └───────┬───────┘
                                              │
                                              ▼
                                      ┌───────────────┐
                                      │     Redis     │
                                      │ (Broker/Cache)│
                                      └───────────────┘
```

---

## Component Architecture

### Django Apps

| App | Responsibility | Key Models |
|-----|---------------|------------|
| `documents` | Document upload, storage, lifecycle | `Document` |
| `extraction` | AI extraction pipeline, proposals | `ProposedExtraction`, `ProposedField`, `ExtractedField` |
| `actions` | Auditable state changes | `Action` |
| `features` | Feature flag management | `FeatureFlag`, `FlagEvaluation` |
| `common` | Shared utilities, base classes | `BaseModel`, `TenantMixin` |

### External Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| PostgreSQL | Primary data store | `DATABASE_URL` |
| Redis | Celery broker, optional caching | `REDIS_URL` |
| OpenAI API | AI extraction (optional) | `OPENAI_API_KEY` |

---

## Layer Responsibilities

### Web Layer (Views)

Views are intentionally thin. They handle:

1. **Authentication** — Verify user identity via session/token
2. **Authorisation** — Check permissions for the requested action
3. **Request validation** — Validate incoming data against schemas
4. **Service invocation** — Call appropriate Service/Action
5. **Response formatting** — Serialise result for client

Views do NOT contain:
- Business logic
- Database queries (beyond auth lookups)
- Direct model mutations
- AI/ML code

**Example View Pattern:**

```python
class DocumentExtractView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, document_id):
        # 1. Validate request
        serialiser = ExtractRequestSerializer(data=request.data)
        serialiser.is_valid(raise_exception=True)
        
        # 2. Check feature flag
        if not request.feature_flags.get('ai_extraction_enabled'):
            return Response(
                {'error': 'AI extraction is currently disabled'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # 3. Call service (all logic lives here)
        result = ExtractionService.trigger_extraction(
            document_id=document_id,
            actor=request.user,
            trace_id=request.trace_id,
        )
        
        # 4. Return response
        return Response(
            ExtractionResponseSerializer(result).data,
            status=status.HTTP_202_ACCEPTED
        )
```

### Domain Layer

#### Services

Services orchestrate business operations. They:
- Coordinate multiple Selectors and Actions
- Enforce business rules
- Manage transactions where needed
- Dispatch async tasks

Services are stateless — all state comes from parameters or database.

#### Selectors

Selectors encapsulate read operations. They:
- Build complex queries
- Handle filtering, ordering, pagination
- Return DTOs or model instances
- Never mutate state

#### Actions

Actions are auditable state transitions. They:
- Capture pre-state before mutation
- Perform the mutation
- Capture post-state after mutation
- Log the complete action record
- Provide rollback capability

#### Agents

Agents orchestrate AI workflows. They:
- Manage multi-step reasoning
- Call Functions (tools) as needed
- Produce proposals (not direct writes)
- Track token usage and costs

#### Functions

Functions are discrete AI capabilities. They:
- Perform specific tasks (extraction, validation, classification)
- Are deterministic where possible
- Return structured outputs
- Are independently testable

---

## Data Flow

### Document Upload Flow

```
Client                    View                     Service                   Database
  │                        │                         │                          │
  │  POST /documents/      │                         │                          │
  │  + file attachment     │                         │                          │
  │───────────────────────▶│                         │                          │
  │                        │                         │                          │
  │                        │  DocumentService.       │                          │
  │                        │  create_document()      │                          │
  │                        │────────────────────────▶│                          │
  │                        │                         │                          │
  │                        │                         │  INSERT Document         │
  │                        │                         │─────────────────────────▶│
  │                        │                         │                          │
  │                        │                         │  Store file to disk      │
  │                        │                         │─────────────────────────▶│
  │                        │                         │                          │
  │                        │◀────────────────────────│                          │
  │                        │  Document instance      │                          │
  │                        │                         │                          │
  │◀───────────────────────│                         │                          │
  │  201 Created           │                         │                          │
  │  + document_id         │                         │                          │
```

### Extraction Flow (Two-Phase)

```
Client          View            Service           Celery            Agent           Database
  │              │                 │                 │                │                │
  │ POST         │                 │                 │                │                │
  │ /extract/    │                 │                 │                │                │
  │─────────────▶│                 │                 │                │                │
  │              │                 │                 │                │                │
  │              │ trigger_        │                 │                │                │
  │              │ extraction()    │                 │                │                │
  │              │────────────────▶│                 │                │                │
  │              │                 │                 │                │                │
  │              │                 │ dispatch task   │                │                │
  │              │                 │ (idempotency    │                │                │
  │              │                 │  key check)     │                │                │
  │              │                 │────────────────▶│                │                │
  │              │                 │                 │                │                │
  │◀─────────────│◀────────────────│                 │                │                │
  │ 202 Accepted │                 │                 │                │                │
  │ + task_id    │                 │                 │                │                │
  │              │                 │                 │                │                │
  │              │                 │                 │ run_extraction │                │
  │              │                 │                 │───────────────▶│                │
  │              │                 │                 │                │                │
  │              │                 │                 │                │ Extract fields │
  │              │                 │                 │                │ (AI call)      │
  │              │                 │                 │                │                │
  │              │                 │                 │                │ Validate       │
  │              │                 │                 │                │ outputs        │
  │              │                 │                 │                │                │
  │              │                 │                 │                │ INSERT         │
  │              │                 │                 │                │ ProposedExtrac │
  │              │                 │                 │                │───────────────▶│
  │              │                 │                 │                │                │
  │              │                 │                 │◀───────────────│                │
  │              │                 │                 │                │                │
```

### Commit Flow (Action)

```
Client          View            Service           Action            Database
  │              │                 │                 │                  │
  │ POST         │                 │                 │                  │
  │ /commit/     │                 │                 │                  │
  │─────────────▶│                 │                 │                  │
  │              │                 │                 │                  │
  │              │ commit_         │                 │                  │
  │              │ extraction()    │                 │                  │
  │              │────────────────▶│                 │                  │
  │              │                 │                 │                  │
  │              │                 │ Action.commit() │                  │
  │              │                 │────────────────▶│                  │
  │              │                 │                 │                  │
  │              │                 │                 │ Capture pre_state│
  │              │                 │                 │─────────────────▶│
  │              │                 │                 │                  │
  │              │                 │                 │ INSERT           │
  │              │                 │                 │ ExtractedFields  │
  │              │                 │                 │─────────────────▶│
  │              │                 │                 │                  │
  │              │                 │                 │ UPDATE Proposal  │
  │              │                 │                 │ status=COMMITTED │
  │              │                 │                 │─────────────────▶│
  │              │                 │                 │                  │
  │              │                 │                 │ Capture post_    │
  │              │                 │                 │ state            │
  │              │                 │                 │─────────────────▶│
  │              │                 │                 │                  │
  │              │                 │                 │ INSERT Action    │
  │              │                 │                 │ record           │
  │              │                 │                 │─────────────────▶│
  │              │                 │                 │                  │
  │              │◀────────────────│◀────────────────│                  │
  │◀─────────────│                 │                 │                  │
  │ 200 OK       │                 │                 │                  │
  │ + action_id  │                 │                 │                  │
```

---

## Agent / Function / Action Pattern

This pattern separates concerns in AI workflows:

### Agent

The Agent is the orchestrator. It:
- Receives a task (e.g., "extract fields from this document")
- Decides which Functions to call
- Manages conversation/reasoning state
- Produces a **proposal** (never writes directly)

```python
class ExtractionAgent:
    """Orchestrates document field extraction."""
    
    def __init__(self, document: Document, context: AgentContext):
        self.document = document
        self.context = context
        self.functions = [
            TextExtractionFunction(),
            FieldValidationFunction(),
            ConfidenceScoreFunction(),
        ]
    
    def run(self) -> ProposedExtraction:
        # 1. Extract text from document
        text = self.functions[0].execute(self.document)
        
        # 2. Extract fields via AI (adapts to document type)
        raw_fields = self._call_llm(text)
        
        # 3. Validate extracted fields
        validated = self.functions[1].execute(raw_fields)
        
        # 4. Score confidence
        scored = self.functions[2].execute(validated)
        
        # 5. Return proposal (no writes)
        return ProposedExtraction(
            document=self.document,
            fields=scored,
            agent_run_id=self.context.run_id,
        )
```

### Function

Functions are tools the Agent can call. They:
- Have a single responsibility
- Are deterministic (given same input → same output, where possible)
- Return structured data
- Are independently testable

```python
class FieldValidationFunction:
    """Validates extracted fields against schema."""
    
    # Core fields expected for most document types
    COMMON_FIELDS = ['parties', 'effective_date', 'total_amount', 'reference_number']
    
    def execute(self, raw_fields: dict) -> ValidatedFields:
        errors = []
        validated = {}
        
        for field_name, field_value in raw_fields.items():
            validated[field_name] = self._validate_field(field_name, field_value)
        
        # Check for minimum viable extraction
        found_fields = set(raw_fields.keys())
        if not found_fields.intersection(self.COMMON_FIELDS):
            errors.append("No common fields identified")
        
        return ValidatedFields(
            fields=validated,
            errors=errors,
            is_valid=len(errors) == 0,
        )
```

### Action

Actions commit proposed changes to the database with full audit:

```python
class CommitExtractionAction:
    """Commits a proposed extraction to canonical storage."""
    
    def __init__(self, proposal: ProposedExtraction, actor: User, trace_id: str):
        self.proposal = proposal
        self.actor = actor
        self.trace_id = trace_id
    
    def commit(self) -> Action:
        # 1. Capture pre-state
        pre_state = self._capture_pre_state()
        
        # 2. Perform mutation
        with transaction.atomic():
            extracted_fields = self._create_extracted_fields()
            self.proposal.status = ProposalStatus.COMMITTED
            self.proposal.save()
        
        # 3. Capture post-state
        post_state = self._capture_post_state(extracted_fields)
        
        # 4. Log action
        action = Action.objects.create(
            action_type=ActionType.COMMIT_EXTRACTION,
            actor=self.actor,
            trace_id=self.trace_id,
            target_type='ProposedExtraction',
            target_id=self.proposal.id,
            pre_state=pre_state,
            post_state=post_state,
            is_reversible=True,
        )
        
        return action
    
    def rollback(self, action: Action) -> Action:
        # Restore pre-state from action record
        ...
```

---

## Security Model

### Authentication

- Session-based auth for Django Admin
- Token-based auth (DRF TokenAuthentication) for API
- JWT support optional for future integrations

### Authorisation

- Object-level permissions via `django-guardian` or custom checks
- Tenant isolation via `tenant_id` foreign key on all models
- All queries scoped to current tenant via custom managers

### Data Protection

- File uploads validated (type, size, content inspection)
- SQL injection prevented via ORM (no raw SQL with user input)
- XSS prevented via DRF serialisation (no raw HTML rendering)
- CSRF protection enabled for session-based requests

---

## Observability

### Structured Logging

Every log entry includes:
- `trace_id` — Unique ID for request chain
- `actor_id` — User or system identifier
- `tenant_id` — Tenant context
- `action_id` — If within an Action
- `agent_run_id` — If within an Agent execution

### Key Metrics (Hooks Prepared)

| Metric | Type | Description |
|--------|------|-------------|
| `extraction_triggered_total` | Counter | Extractions started |
| `extraction_completed_total` | Counter | Extractions finished (success/failure label) |
| `extraction_duration_seconds` | Histogram | Time to complete extraction |
| `action_committed_total` | Counter | Actions committed |
| `action_rolled_back_total` | Counter | Actions rolled back |
| `celery_task_duration_seconds` | Histogram | Task execution time |

### Feature Flags

Flags are logged when evaluated:
- Flag name
- Evaluated value
- User/tenant context
- Timestamp

This enables analysis of feature exposure and debugging.