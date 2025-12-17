"""
==============================================================================
FILE: models.py
LOCATION: /docextract/apps/extraction/models.py
==============================================================================

PURPOSE:
    Defines models for the AI extraction pipeline implementing a two-phase
    commit pattern. AI agents propose extractions, humans review, and
    approved proposals are committed to canonical storage.

MODELS:
    - ProposalStatus: Enumeration of proposal lifecycle states
    - FieldType: Enumeration of extractable field types
    - ProposedExtraction: AI-generated extraction proposal awaiting review
    - ProposedField: Individual field within a proposed extraction
    - ExtractedField: Canonical committed field (source of truth)

USAGE:
    from apps.extraction.models import (
        ProposedExtraction, ProposedField, ExtractedField,
        ProposalStatus, FieldType
    )

    # Create proposal from AI agent
    proposal = ProposedExtraction.objects.create(
        tenant=document.tenant,
        document=document,
        agent_run_id=uuid.uuid4(),
        model_version='gpt-4-turbo',
        prompt_hash=computed_hash,
        overall_confidence=0.92,
        processing_duration_ms=1500,
    )

    # Add proposed fields
    ProposedField.objects.create(
        extraction=proposal,
        field_type=FieldType.VENDOR,
        field_name='Vendor Name',
        value='Acme Corp',
        source_text='Invoice from Acme Corp',
        confidence=0.95,
    )

LIFECYCLE:
    ProposedExtraction: PENDING → APPROVED → COMMITTED (success)
                        PENDING → REJECTED (rejection)
                        PENDING → SUPERSEDED (re-extraction)

DESIGN DECISIONS:
    - Two-phase commit: proposals never directly modify canonical data
    - Soft delete on ExtractedField (is_active) enables rollback
    - Field provenance (source_text, source_page) for transparency
    - Normalised values stored alongside raw text for structured access
    - Unique constraint on (extraction, field_type) except for CUSTOM fields

PERFORMANCE NOTES:
    - Index on (document, status) for proposal lookups
    - Index on confidence for quality filtering
    - Consider prefetch_related('fields') when loading proposals
    - Partial unique index excludes CUSTOM fields from uniqueness

TESTING:
    - Test proposal lifecycle transitions
    - Test commit creates correct ExtractedFields
    - Test unique constraint allows multiple CUSTOM fields
    - Test rollback deactivates ExtractedFields correctly

==============================================================================
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from .prompt_models import PromptTemplate  # noqa: F401

from apps.common.models import TenantMixin, TimestampMixin


class ProposalStatus(models.TextChoices):
    """
    Enumeration of proposal lifecycle states.

    Status transitions:
    - PENDING: Awaiting human review
    - APPROVED: Reviewed and approved (ready for commit)
    - COMMITTED: Committed to canonical storage via Action
    - REJECTED: Rejected by reviewer
    - SUPERSEDED: Replaced by a newer extraction
    """

    PENDING = "pending", "Pending Review"
    APPROVED = "approved", "Approved"
    COMMITTED = "committed", "Committed"
    REJECTED = "rejected", "Rejected"
    SUPERSEDED = "superseded", "Superseded"


class FieldType(models.TextChoices):
    """
    Enumeration of extractable field types.

    Organised by domain for clarity. The CUSTOM type allows for
    ad-hoc fields not covered by predefined types.
    """

    # Common fields (cross-domain)
    PARTIES = "parties", "Parties/Entities"
    EFFECTIVE_DATE = "effective_date", "Effective Date"
    EXPIRY_DATE = "expiry_date", "Expiry/End Date"
    TOTAL_AMOUNT = "total_amount", "Total Amount"
    CURRENCY = "currency", "Currency"
    REFERENCE_NUMBER = "reference_number", "Reference Number"

    # Invoice fields
    VENDOR = "vendor", "Vendor Name"
    LINE_ITEMS = "line_items", "Line Items"
    TAX_AMOUNT = "tax_amount", "Tax Amount"
    DUE_DATE = "due_date", "Due Date"
    PAYMENT_TERMS = "payment_terms", "Payment Terms"

    # HR/Personnel fields
    EMPLOYEE_NAME = "employee_name", "Employee Name"
    JOB_TITLE = "job_title", "Job Title"
    SALARY = "salary", "Salary/Compensation"
    START_DATE = "start_date", "Start Date"

    # Contract fields
    GOVERNING_LAW = "governing_law", "Governing Law"
    JURISDICTION = "jurisdiction", "Jurisdiction"
    TERMINATION_CLAUSE = "termination_clause", "Termination Clause"

    # Insurance fields
    POLICY_NUMBER = "policy_number", "Policy Number"
    CLAIMANT = "claimant", "Claimant Name"
    CLAIM_AMOUNT = "claim_amount", "Claim Amount"

    # Flexible
    CUSTOM = "custom", "Custom Field"


class ProposedExtraction(TenantMixin, TimestampMixin, models.Model):
    """
    A proposed set of extracted fields from an AI agent.

    This is the "proposal" in the two-phase commit pattern. Fields are
    stored in related ProposedField records. Proposals must be reviewed
    and explicitly committed before data becomes canonical.

    Attributes:
        document: The source document for this extraction
        status: Current lifecycle state (pending, approved, committed, etc.)
        agent_run_id: Unique ID for the agent execution that produced this
        model_version: AI model identifier used for extraction
        prompt_hash: Hash of prompt template for reproducibility
        overall_confidence: Aggregate confidence score (0.0 - 1.0)
        token_usage: Token counts (input, output, total) as JSONB
        processing_duration_ms: Time taken to generate proposal
        reviewed_by: User who reviewed the proposal
        reviewed_at: Timestamp of review
        review_notes: Reviewer comments or rejection reason
        committed_action: Reference to the Action that committed this proposal
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="proposed_extractions",
        help_text="The source document for this extraction",
    )

    status = models.CharField(
        max_length=20,
        choices=ProposalStatus.choices,
        default=ProposalStatus.PENDING,
        db_index=True,
        help_text="Current lifecycle state",
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
        blank=True,
        help_text="Token counts: {input, output, total}",
    )

    processing_duration_ms = models.PositiveIntegerField(
        help_text="Time taken to generate proposal in milliseconds",
    )

    # Review tracking
    reviewed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_extractions",
        help_text="User who reviewed the proposal",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of review",
    )

    review_notes = models.TextField(
        blank=True,
        help_text="Reviewer comments or rejection reason",
    )

    # Commit tracking
    committed_action = models.ForeignKey(
        "actions.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committed_extractions",
        help_text="The Action that committed this proposal",
    )

    class Meta:
        db_table = "proposed_extractions"
        indexes = [
            models.Index(
                fields=["tenant", "status"],
                name="ix_proposals_tenant_status",
            ),
            models.Index(
                fields=["document", "status"],
                name="ix_proposals_document_status",
            ),
            models.Index(
                fields=["agent_run_id"],
                name="ix_proposals_agent_run_id",
            ),
            models.Index(
                fields=["created_at"],
                name="ix_proposals_created_at",
            ),
        ]
        ordering = ["-created_at"]
        verbose_name = "Proposed Extraction"
        verbose_name_plural = "Proposed Extractions"

    def __str__(self) -> str:
        return f"Extraction for {self.document} ({self.status})"

    @property
    def is_committable(self) -> bool:
        """Check if proposal can be committed."""
        return self.status in (ProposalStatus.PENDING, ProposalStatus.APPROVED)

    @property
    def is_rejectable(self) -> bool:
        """Check if proposal can be rejected."""
        return self.status == ProposalStatus.PENDING

    @property
    def field_count(self) -> int:
        """Return the number of proposed fields."""
        return self.fields.count()


class ProposedField(TimestampMixin, models.Model):
    """
    A single extracted field within a ProposedExtraction.

    Contains the AI-extracted value along with provenance information
    (where in the document it was found) and confidence scoring.

    Attributes:
        extraction: Parent ProposedExtraction
        field_type: Category of the field (vendor, date, amount, etc.)
        field_name: Display name (may differ for CUSTOM type)
        value: The extracted value as text
        normalised_value: Structured form (e.g., date as ISO, money as object)
        source_text: Original text snippet from document
        source_page: Page number where field was found
        source_location: Bounding box or character offsets as JSONB
        confidence: Confidence score for this field (0.0 - 1.0)
        confidence_reason: Explanation for confidence score
        validation_status: Validation state (pending, valid, invalid)
        validation_errors: List of validation errors as JSONB
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    extraction = models.ForeignKey(
        ProposedExtraction,
        on_delete=models.CASCADE,
        related_name="fields",
        help_text="Parent extraction proposal",
    )

    field_type = models.CharField(
        max_length=50,
        choices=FieldType.choices,
        db_index=True,
        help_text="Category of the field",
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
        help_text="Structured form (e.g., date as ISO, money as {amount, currency})",
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
        default="pending",
        help_text="Validation state: pending, valid, invalid, needs_review",
    )

    validation_errors = models.JSONField(
        default=list,
        blank=True,
        help_text="List of validation errors if any",
    )

    class Meta:
        db_table = "proposed_fields"
        indexes = [
            models.Index(
                fields=["extraction", "field_type"],
                name="ix_proposed_fields_ext_type",
            ),
            models.Index(
                fields=["confidence"],
                name="ix_proposed_fields_confidence",
            ),
        ]
        constraints = [
            # Ensure unique field types per extraction (except CUSTOM)
            models.UniqueConstraint(
                fields=["extraction", "field_type"],
                condition=~models.Q(field_type="custom"),
                name="unique_field_type_per_extraction",
            ),
        ]
        verbose_name = "Proposed Field"
        verbose_name_plural = "Proposed Fields"

    def __str__(self) -> str:
        return f"{self.field_name}: {self.value[:50]}..."


class ExtractedField(TenantMixin, TimestampMixin, models.Model):
    """
    A committed, canonical extracted field.

    Created when a ProposedField is committed via an Action. This is the
    "source of truth" for extracted data. Maintains reference to the
    original proposal for audit trail.

    Soft delete (is_active=False) enables rollback without data loss.

    Attributes:
        document: The source document
        source_proposal: The proposal this field was committed from
        source_proposed_field: The specific proposed field
        field_type: Category of the field
        field_name: Display name
        value: The committed value as text
        normalised_value: Structured form
        source_text: Original text snippet (copied from proposal)
        source_page: Page number (copied from proposal)
        source_location: Position info (copied from proposal)
        confidence: Confidence at commit time
        committed_by: User who committed the field
        committed_at: Timestamp of commit
        committed_action: Reference to the commit Action
        is_active: Soft delete flag (False when rolled back)
        deactivated_at: Timestamp when deactivated
        deactivated_by_action: Reference to the rollback Action
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.CASCADE,
        related_name="extracted_fields",
        help_text="The source document",
    )

    # Source tracking
    source_proposal = models.ForeignKey(
        ProposedExtraction,
        on_delete=models.SET_NULL,
        null=True,
        related_name="committed_fields",
        help_text="The proposal this field was committed from",
    )

    source_proposed_field = models.ForeignKey(
        ProposedField,
        on_delete=models.SET_NULL,
        null=True,
        related_name="committed_as",
        help_text="The specific proposed field",
    )

    # Field data (copied from ProposedField at commit time)
    field_type = models.CharField(
        max_length=50,
        choices=FieldType.choices,
        db_index=True,
        help_text="Category of the field",
    )

    field_name = models.CharField(
        max_length=100,
        help_text="Display name",
    )

    value = models.TextField(
        help_text="The committed value as text",
    )

    normalised_value = models.JSONField(
        null=True,
        blank=True,
        help_text="Structured form",
    )

    # Provenance (copied from ProposedField)
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

    # Confidence at commit time
    confidence = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Confidence score at time of commit",
    )

    # Commit tracking
    committed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="committed_fields",
        help_text="User who committed the field",
    )

    committed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of commit",
    )

    committed_action = models.ForeignKey(
        "actions.Action",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_fields",
        help_text="Reference to the commit Action",
    )

    # Soft delete for rollback support
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False when rolled back (soft delete)",
    )

    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when deactivated by rollback",
    )

    deactivated_by_action = models.ForeignKey(
        "actions.Action",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deactivated_fields",
        help_text="Reference to the rollback Action",
    )

    class Meta:
        db_table = "extracted_fields"
        indexes = [
            models.Index(
                fields=["tenant", "document"],
                name="ix_extracted_tenant_document",
            ),
            models.Index(
                fields=["document", "field_type", "is_active"],
                name="ix_extracted_doc_type_active",
            ),
            models.Index(
                fields=["committed_at"],
                name="ix_extracted_committed_at",
            ),
        ]
        verbose_name = "Extracted Field"
        verbose_name_plural = "Extracted Fields"

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.field_name}: {self.value[:50]}... ({status})"