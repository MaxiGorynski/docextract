# Data Model

**Database Schema and Model Specifications for DocExtract**

This document defines all database models, their relationships, field specifications, and design rationale.

---

## Table of Contents

1. [Entity Relationship Diagram](#entity-relationship-diagram)
2. [Core Models](#core-models)
3. [Extraction Models](#extraction-models)
4. [Audit Models](#audit-models)
5. [Feature Flag Models](#feature-flag-models)
6. [Base Classes and Mixins](#base-classes-and-mixins)
7. [Indexes and Constraints](#indexes-and-constraints)
8. [Migration Strategy](#migration-strategy)

---

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CORE DOMAIN                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌─────────────────────┐                           │
│  │    Tenant    │────────<│      Document       │                           │
│  └──────────────┘    1:N  └──────────┬──────────┘                           │
│         │                            │                                       │
│         │                            │ 1:N                                   │
│         │                            ▼                                       │
│         │                 ┌─────────────────────┐        ┌───────────────┐  │
│         │                 │ ProposedExtraction  │───────>│ExtractedField │  │
│         │                 └──────────┬──────────┘   1:N  └───────────────┘  │
│         │                            │                           ▲          │
│         │                            │ 1:N                       │          │
│         │                            ▼                           │          │
│         │                 ┌─────────────────────┐                │          │
│         │                 │   ProposedField     │────────────────┘          │
│         │                 └─────────────────────┘    (on commit)            │
│         │                                                                    │
└─────────┼────────────────────────────────────────────────────────────────────┘
          │
┌─────────┼────────────────────────────────────────────────────────────────────┐
│         │                        AUDIT DOMAIN                                │
├─────────┼────────────────────────────────────────────────────────────────────┤
│         │                                                                    │
│         │    ┌──────────────┐                                               │
│         └───>│    Action    │                                               │
│              └──────────────┘                                               │
│                     │                                                        │
│                     │ (references any model via generic FK)                  │
│                     ▼                                                        │
│              ┌──────────────┐                                               │
│              │  AuditLog    │  (denormalized for queries)                   │
│              └──────────────┘                                               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                           FEATURE FLAGS                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌─────────────────────┐                           │
│  │ FeatureFlag  │────────<│  FlagEvaluation     │  (log of evaluations)     │
│  └──────────────┘    1:N  └─────────────────────┘                           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Models

### Tenant

Multi-tenancy support. All domain models reference a Tenant.

```python
class Tenant(models.Model):
    """
    Organisational tenant for multi-tenancy isolation.
    
    All domain data is scoped to a tenant. Queries should always
    filter by tenant_id to prevent data leakage.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    name = models.CharField(
        max_length=255,
        help_text="Display name for the tenant/organisation",
    )
    
    slug = models.SlugField(
        max_length=63,
        unique=True,
        help_text="URL-safe identifier, used in API paths",
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive tenants cannot access the system",
    )
    
    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tenant-specific configuration overrides",
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenants'
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]
```

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Unique identifier |
| `name` | VARCHAR(255) | NOT NULL | Display name |
| `slug` | VARCHAR(63) | UNIQUE, NOT NULL | URL-safe identifier |
| `is_active` | BOOLEAN | DEFAULT TRUE | Tenant access control |
| `settings` | JSONB | DEFAULT '{}' | Config overrides |
| `created_at` | TIMESTAMP | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL | Last modification |

---

### Document

Uploaded documents pending or completed extraction.

```python
class DocumentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    EXTRACTED = 'extracted', 'Extracted'
    FAILED = 'failed', 'Failed'


class Document(TenantMixin, TimestampMixin, models.Model):
    """
    An uploaded document for field extraction.
    
    Documents progress through statuses:
    PENDING → PROCESSING → EXTRACTED (or FAILED)
    
    File storage is handled via Django's FileField with
    configurable storage backend.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    # File storage
    file = models.FileField(
        upload_to='documents/%Y/%m/%d/',
        help_text="The uploaded document file",
    )
    
    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename from upload",
    )
    
    file_type = models.CharField(
        max_length=50,
        help_text="MIME type or extension (pdf, docx)",
    )
    
    file_size_bytes = models.PositiveIntegerField(
        help_text="File size in bytes",
    )
    
    file_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash for deduplication/integrity",
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
        db_index=True,
    )
    
    status_message = models.TextField(
        blank=True,
        help_text="Human-readable status details (e.g., error message)",
    )
    
    # Metadata
    title = models.CharField(
        max_length=500,
        blank=True,
        help_text="Document title (extracted or user-provided)",
    )
    
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional document metadata",
    )
    
    # Ownership
    uploaded_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_documents',
    )
    
    # Processing tracking
    extraction_started_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    extraction_completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    class Meta:
        db_table = 'documents'
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['file_hash']),
            models.Index(fields=['uploaded_by']),
        ]
        ordering = ['-created_at']
```

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Unique identifier |
| `tenant_id` | UUID | FK → Tenant | Tenant ownership |
| `file` | VARCHAR | NOT NULL | File storage path |
| `original_filename` | VARCHAR(255) | NOT NULL | Original name |
| `file_type` | VARCHAR(50) | NOT NULL | MIME type |
| `file_size_bytes` | INTEGER | NOT NULL, >= 0 | Size in bytes |
| `file_hash` | VARCHAR(64) | NOT NULL | SHA-256 hash |
| `status` | VARCHAR(20) | NOT NULL | Processing status |
| `status_message` | TEXT | | Status details |
| `title` | VARCHAR(500) | | Document title |
| `metadata` | JSONB | DEFAULT '{}' | Extra metadata |
| `uploaded_by_id` | INTEGER | FK → User, NULL | Uploader |
| `extraction_started_at` | TIMESTAMP | NULL | Processing start |
| `extraction_completed_at` | TIMESTAMP | NULL | Processing end |
| `created_at` | TIMESTAMP | NOT NULL | Upload time |
| `updated_at` | TIMESTAMP | NOT NULL | Last modification |

---

## Extraction Models

### ProposedExtraction

AI-generated extraction proposal awaiting review.

```python
class ProposalStatus(models.TextChoices):
    PENDING = 'pending', 'Pending Review'
    APPROVED = 'approved', 'Approved'
    COMMITTED = 'committed', 'Committed'
    REJECTED = 'rejected', 'Rejected'
    SUPERSEDED = 'superseded', 'Superseded'


class ProposedExtraction(TenantMixin, TimestampMixin, models.Model):
    """
    A proposed set of extracted fields from an AI agent.
    
    This is the "proposal" in the two-phase commit pattern.
    Fields are stored in related ProposedField records.
    
    Lifecycle:
    PENDING → APPROVED → COMMITTED (success path)
    PENDING → REJECTED (rejection path)
    PENDING → SUPERSEDED (if re-extraction requested)
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='proposed_extractions',
    )
    
    status = models.CharField(
        max_length=20,
        choices=ProposalStatus.choices,
        default=ProposalStatus.PENDING,
        db_index=True,
    )
    
    # AI execution context
    agent_run_id = models.UUIDField(
        help_text="Unique ID for the agent execution that produced this",
    )
    
    model_version = models.CharField(
        max_length=100,
        help_text="AI model identifier used for extraction",
    )
    
    prompt_hash = models.CharField(
        max_length=64,
        help_text="Hash of prompt template for reproducibility",
    )
    
    # Quality metrics
    overall_confidence = models.FloatField(
        help_text="Aggregate confidence score (0.0 - 1.0)",
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    
    token_usage = models.JSONField(
        default=dict,
        help_text="Token counts: input, output, total",
    )
    
    processing_duration_ms = models.PositiveIntegerField(
        help_text="Time taken to generate proposal in milliseconds",
    )
    
    # Review tracking
    reviewed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_extractions',
    )
    
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    review_notes = models.TextField(
        blank=True,
        help_text="Reviewer comments or rejection reason",
    )
    
    # Commit tracking
    committed_action = models.ForeignKey(
        'actions.Action',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='committed_extractions',
        help_text="The Action that committed this proposal",
    )
    
    class Meta:
        db_table = 'proposed_extractions'
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['document', 'status']),
            models.Index(fields=['agent_run_id']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']
```

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Unique identifier |
| `tenant_id` | UUID | FK → Tenant | Tenant ownership |
| `document_id` | UUID | FK → Document | Source document |
| `status` | VARCHAR(20) | NOT NULL | Proposal status |
| `agent_run_id` | UUID | NOT NULL | Agent execution ID |
| `model_version` | VARCHAR(100) | NOT NULL | AI model used |
| `prompt_hash` | VARCHAR(64) | NOT NULL | Prompt template hash |
| `overall_confidence` | FLOAT | 0.0-1.0 | Confidence score |
| `token_usage` | JSONB | DEFAULT '{}' | Token metrics |
| `processing_duration_ms` | INTEGER | >= 0 | Processing time |
| `reviewed_by_id` | INTEGER | FK → User, NULL | Reviewer |
| `reviewed_at` | TIMESTAMP | NULL | Review time |
| `review_notes` | TEXT | | Review comments |
| `committed_action_id` | UUID | FK → Action, NULL | Commit action |
| `created_at` | TIMESTAMP | NOT NULL | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL | Last modification |

---

### ProposedField

Individual field within a proposed extraction.

```python
class FieldType(models.TextChoices):
    # Common fields (cross-domain)
    PARTIES = 'parties', 'Parties/Entities'
    EFFECTIVE_DATE = 'effective_date', 'Effective Date'
    EXPIRY_DATE = 'expiry_date', 'Expiry/End Date'
    TOTAL_AMOUNT = 'total_amount', 'Total Amount'
    CURRENCY = 'currency', 'Currency'
    REFERENCE_NUMBER = 'reference_number', 'Reference Number'
    
    # Invoice fields
    VENDOR = 'vendor', 'Vendor Name'
    LINE_ITEMS = 'line_items', 'Line Items'
    TAX_AMOUNT = 'tax_amount', 'Tax Amount'
    DUE_DATE = 'due_date', 'Due Date'
    PAYMENT_TERMS = 'payment_terms', 'Payment Terms'
    
    # HR/Personnel fields
    EMPLOYEE_NAME = 'employee_name', 'Employee Name'
    JOB_TITLE = 'job_title', 'Job Title'
    SALARY = 'salary', 'Salary/Compensation'
    START_DATE = 'start_date', 'Start Date'
    
    # Contract fields
    GOVERNING_LAW = 'governing_law', 'Governing Law'
    JURISDICTION = 'jurisdiction', 'Jurisdiction'
    TERMINATION_CLAUSE = 'termination_clause', 'Termination Clause'
    
    # Insurance fields
    POLICY_NUMBER = 'policy_number', 'Policy Number'
    CLAIMANT = 'claimant', 'Claimant Name'
    CLAIM_AMOUNT = 'claim_amount', 'Claim Amount'
    
    # Flexible
    CUSTOM = 'custom', 'Custom Field'


class ProposedField(TimestampMixin, models.Model):
    """
    A single extracted field within a ProposedExtraction.
    
    Contains the AI-extracted value along with provenance
    information (where in the document it was found) and
    confidence scoring.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    extraction = models.ForeignKey(
        ProposedExtraction,
        on_delete=models.CASCADE,
        related_name='fields',
    )
    
    field_type = models.CharField(
        max_length=50,
        choices=FieldType.choices,
        db_index=True,
    )
    
    field_name = models.CharField(
        max_length=100,
        help_text="Display name (may differ for CUSTOM type)",
    )
    
    # Extracted value
    value = models.TextField(
        help_text="The extracted value as text",
    )
    
    normalised_value = models.JSONField(
        null=True,
        blank=True,
        help_text="Structured/normalized form (e.g., date as ISO, money as {amount, currency})",
    )
    
    # Provenance
    source_text = models.TextField(
        help_text="Original text snippet from document",
    )
    
    source_page = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Page number where field was found",
    )
    
    source_location = models.JSONField(
        null=True,
        blank=True,
        help_text="Bounding box or character offsets",
    )
    
    # Confidence
    confidence = models.FloatField(
        help_text="Confidence score for this field (0.0 - 1.0)",
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    
    confidence_reason = models.TextField(
        blank=True,
        help_text="Explanation for confidence score",
    )
    
    # Validation
    validation_status = models.CharField(
        max_length=20,
        default='pending',
        help_text="pending, valid, invalid, needs_review",
    )
    
    validation_errors = models.JSONField(
        default=list,
        help_text="List of validation errors if any",
    )
    
    class Meta:
        db_table = 'proposed_fields'
        indexes = [
            models.Index(fields=['extraction', 'field_type']),
            models.Index(fields=['confidence']),
        ]
        # Ensure unique field types per extraction (except CUSTOM)
        constraints = [
            models.UniqueConstraint(
                fields=['extraction', 'field_type'],
                condition=~models.Q(field_type='custom'),
                name='unique_field_type_per_extraction',
            ),
        ]
```

| Field               | Type | Constraints | Description |
|---------------------|------|-------------|-------------|
| `id`                | UUID | PK | Unique identifier |
| `extraction_id`     | UUID | FK → ProposedExtraction | Parent extraction |
| `field_type`        | VARCHAR(50) | NOT NULL | Field category |
| `field_name`        | VARCHAR(100) | NOT NULL | Display name |
| `value`             | TEXT | NOT NULL | Extracted value |
| `normalised_value`  | JSONB | NULL | Structured form |
| `source_text`       | TEXT | NOT NULL | Source snippet |
| `source_page`       | INTEGER | NULL, >= 0 | Page number |
| `source_location`   | JSONB | NULL | Position info |
| `confidence`        | FLOAT | 0.0-1.0 | Confidence score |
| `confidence_reason` | TEXT | | Score explanation |
| `validation_status` | VARCHAR(20) | DEFAULT 'pending' | Validation state |
| `validation_errors` | JSONB | DEFAULT '[]' | Error list |
| `created_at`        | TIMESTAMP | NOT NULL | Creation time |
| `updated_at`        | TIMESTAMP | NOT NULL | Last modification |

---

### ExtractedField

Canonical extracted field (committed from a proposal).

```python
class ExtractedField(TenantMixin, TimestampMixin, models.Model):
    """
    A committed, canonical extracted field.
    
    Created when a ProposedField is committed via an Action.
    This is the "source of truth" for extracted data.
    
    Maintains reference to original proposal for audit trail.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='extracted_fields',
    )
    
    # Source tracking
    source_proposal = models.ForeignKey(
        ProposedExtraction,
        on_delete=models.SET_NULL,
        null=True,
        related_name='committed_fields',
        help_text="The proposal this field was committed from",
    )
    
    source_proposed_field = models.ForeignKey(
        ProposedField,
        on_delete=models.SET_NULL,
        null=True,
        related_name='committed_as',
        help_text="The specific proposed field",
    )
    
    # Field data (copied from ProposedField at commit time)
    field_type = models.CharField(
        max_length=50,
        choices=FieldType.choices,
        db_index=True,
    )
    
    field_name = models.CharField(
        max_length=100,
    )
    
    value = models.TextField()
    
    normalised_value = models.JSONField(
        null=True,
        blank=True,
    )
    
    # Provenance (copied)
    source_text = models.TextField()
    source_page = models.PositiveIntegerField(null=True, blank=True)
    source_location = models.JSONField(null=True, blank=True)
    
    # Confidence at commit time
    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    
    # Commit tracking
    committed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='committed_fields',
    )
    
    committed_at = models.DateTimeField(
        auto_now_add=True,
    )
    
    committed_action = models.ForeignKey(
        'actions.Action',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_fields',
    )
    
    # Soft delete for rollback support
    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )
    
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    deactivated_by_action = models.ForeignKey(
        'actions.Action',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deactivated_fields',
    )
    
    class Meta:
        db_table = 'extracted_fields'
        indexes = [
            models.Index(fields=['tenant', 'document']),
            models.Index(fields=['document', 'field_type', 'is_active']),
            models.Index(fields=['committed_at']),
        ]
```

---

## Audit Models

### Action

Core audit record for all state changes.

```python
class ActionType(models.TextChoices):
    COMMIT_EXTRACTION = 'commit_extraction', 'Commit Extraction'
    ROLLBACK_EXTRACTION = 'rollback_extraction', 'Rollback Extraction'
    REJECT_EXTRACTION = 'reject_extraction', 'Reject Extraction'
    UPDATE_FIELD = 'update_field', 'Update Field'
    DELETE_FIELD = 'delete_field', 'Delete Field'
    DOCUMENT_UPLOAD = 'document_upload', 'Document Upload'
    DOCUMENT_DELETE = 'document_delete', 'Document Delete'


class ActionStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    ROLLED_BACK = 'rolled_back', 'Rolled Back'


class Action(TimestampMixin, models.Model):
    """
    Immutable audit record of a state change.
    
    Every mutation to domain state should create an Action record.
    Actions capture:
    - Who performed the action (actor)
    - What was changed (target)
    - The state before and after
    - Whether it can be reversed
    
    Actions are append-only; they are never updated or deleted.
    Rollback creates a NEW Action that reverses the original.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    # Classification
    action_type = models.CharField(
        max_length=50,
        choices=ActionType.choices,
        db_index=True,
    )
    
    status = models.CharField(
        max_length=20,
        choices=ActionStatus.choices,
        default=ActionStatus.COMPLETED,
    )
    
    # Actor
    actor_type = models.CharField(
        max_length=20,
        default='user',
        help_text="user, system, celery_task",
    )
    
    actor_id = models.CharField(
        max_length=100,
        help_text="User ID or system identifier",
    )
    
    actor_email = models.EmailField(
        blank=True,
        help_text="Denormalised for readability",
    )
    
    # Target (generic foreign key pattern)
    target_type = models.CharField(
        max_length=100,
        help_text="Model class name",
    )
    
    target_id = models.CharField(
        max_length=100,
        help_text="Primary key of target",
    )
    
    # Tenant context
    tenant_id = models.UUIDField(
        db_index=True,
        help_text="Tenant where action occurred",
    )
    
    # Tracing
    trace_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Request trace ID for correlation",
    )
    
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Prevents duplicate actions",
    )
    
    # State capture
    pre_state = models.JSONField(
        default=dict,
        help_text="State before mutation",
    )
    
    post_state = models.JSONField(
        default=dict,
        help_text="State after mutation",
    )
    
    # Reversibility
    is_reversible = models.BooleanField(
        default=True,
    )
    
    reversed_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reverses',
        help_text="Action that reversed this one",
    )
    
    reverses = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_by_set',
        help_text="Action that this one reverses",
    )
    
    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context (agent_run_id, etc.)",
    )
    
    error_message = models.TextField(
        blank=True,
        help_text="Error details if status is FAILED",
    )
    
    class Meta:
        db_table = 'actions'
        indexes = [
            models.Index(fields=['tenant_id', 'action_type']),
            models.Index(fields=['tenant_id', 'created_at']),
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['trace_id']),
            models.Index(fields=['actor_id']),
        ]
        ordering = ['-created_at']
```

| Field | Type | Constraints | Description        |
|-------|------|-------------|--------------------|
| `id` | UUID | PK | Unique identifier  |
| `action_type` | VARCHAR(50) | NOT NULL | Action category    |
| `status` | VARCHAR(20) | NOT NULL | Completion status  |
| `actor_type` | VARCHAR(20) | DEFAULT 'user' | Actor category     |
| `actor_id` | VARCHAR(100) | NOT NULL | Actor identifier   |
| `actor_email` | VARCHAR(254) | | Denormalised email |
| `target_type` | VARCHAR(100) | NOT NULL | Target model       |
| `target_id` | VARCHAR(100) | NOT NULL | Target PK          |
| `tenant_id` | UUID | NOT NULL | Tenant context     |
| `trace_id` | VARCHAR(100) | NOT NULL | Request trace      |
| `idempotency_key` | VARCHAR(100) | UNIQUE, NULL | Dedup key          |
| `pre_state` | JSONB | DEFAULT '{}' | Before state       |
| `post_state` | JSONB | DEFAULT '{}' | After state        |
| `is_reversible` | BOOLEAN | DEFAULT TRUE | Can rollback       |
| `reversed_by_id` | UUID | FK → self, NULL | Reversal action    |
| `reverses_id` | UUID | FK → self, NULL | Reversed action    |
| `metadata` | JSONB | DEFAULT '{}' | Extra context      |
| `error_message` | TEXT | | Error details      |
| `created_at` | TIMESTAMP | NOT NULL | Action time        |

---

## Feature Flag Models

### FeatureFlag

```python
class FeatureFlag(TimestampMixin, models.Model):
    """
    Feature flag for progressive rollout and kill switches.
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    
    key = models.CharField(
        max_length=100,
        unique=True,
        help_text="Flag identifier (e.g., 'ai_extraction_enabled')",
    )
    
    description = models.TextField(
        blank=True,
        help_text="What this flag controls",
    )
    
    # Global state
    is_enabled = models.BooleanField(
        default=False,
        help_text="Master switch",
    )
    
    # Rollout configuration
    rollout_percentage = models.PositiveIntegerField(
        default=100,
        validators=[MaxValueValidator(100)],
        help_text="Percentage of users who see this enabled (0-100)",
    )
    
    # Tenant overrides
    enabled_tenants = models.JSONField(
        default=list,
        help_text="List of tenant IDs where flag is always enabled",
    )
    
    disabled_tenants = models.JSONField(
        default=list,
        help_text="List of tenant IDs where flag is always disabled",
    )
    
    # Metadata
    owner = models.CharField(
        max_length=100,
        blank=True,
        help_text="Team or person responsible",
    )
    
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Auto-disable after this time",
    )
    
    class Meta:
        db_table = 'feature_flags'
        indexes = [
            models.Index(fields=['key']),
            models.Index(fields=['is_enabled']),
        ]
```

---

## Base Classes and Mixins

```python
class TimestampMixin(models.Model):
    """Adds created_at and updated_at fields."""
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True


class TenantMixin(models.Model):
    """Adds tenant foreign key with scoped manager."""
    
    tenant = models.ForeignKey(
        'common.Tenant',
        on_delete=models.CASCADE,
        related_name='%(class)ss',
    )
    
    class Meta:
        abstract = True
```

---

## Indexes and Constraints

### Primary Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| `documents` | `ix_documents_tenant_status` | (tenant_id, status) | Filter by tenant + status |
| `documents` | `ix_documents_file_hash` | (file_hash) | Deduplication lookup |
| `proposed_extractions` | `ix_proposals_document` | (document_id, status) | Find proposals for doc |
| `proposed_extractions` | `ix_proposals_agent_run` | (agent_run_id) | Trace agent executions |
| `extracted_fields` | `ix_fields_document_active` | (document_id, field_type, is_active) | Active fields query |
| `actions` | `ix_actions_trace` | (trace_id) | Request correlation |
| `actions` | `ix_actions_target` | (target_type, target_id) | Find actions for entity |

### Unique Constraints

| Table | Constraint | Columns | Condition |
|-------|------------|---------|-----------|
| `proposed_fields` | `unique_field_type_per_extraction` | (extraction_id, field_type) | field_type != 'custom' |
| `actions` | `unique_idempotency_key` | (idempotency_key) | idempotency_key IS NOT NULL |

---

## Migration Strategy

### Initial Migration Order

1. `common` — Tenant, base classes
2. `features` — FeatureFlag (no dependencies)
3. `actions` — Action (references Tenant by UUID, not FK)
4. `documents` — Document (depends on Tenant)
5. `extraction` — ProposedExtraction, ProposedField, ExtractedField

### Data Migration Patterns

For production deployments:
1. Deploy schema changes with nullable new columns
2. Backfill data in batches (Celery task)
3. Add NOT NULL constraints once backfill complete
4. Add indexes concurrently (`CREATE INDEX CONCURRENTLY`)