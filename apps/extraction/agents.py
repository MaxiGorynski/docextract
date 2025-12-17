"""
==============================================================================
FILE: agents.py
LOCATION: /docextract/apps/extraction/agents.py
==============================================================================

PURPOSE:
    Defines the ExtractionAgent for orchestrating AI-powered document field
    extraction using OpenAI's GPT models. Implements free-form extraction
    that discovers all meaningful fields in a document without predefined
    restrictions.

CLASSES:
    - AgentContext: Context for agent execution
    - AgentResult: Result of agent execution
    - ExtractionAgent: Orchestrates the extraction workflow

USAGE:
    from apps.extraction.agents import ExtractionAgent, AgentContext

    context = AgentContext(
        tenant_id=tenant.id,
        document_id=document.id,
        trace_id=request.trace_id,
        run_id=uuid.uuid4(),
    )

    agent = ExtractionAgent(context)
    result = agent.run()

PROMPT TEMPLATE LOADING:
    The agent loads prompts from the PromptTemplate model:
    1. First tries document-type-specific template (e.g., "invoice")
    2. Falls back to default template (document_type=None)
    3. Falls back to hardcoded DEFAULT_SYSTEM_PROMPT / DEFAULT_USER_PROMPT

    User prompt templates support these placeholders:
    - {doc_type}: Detected document type
    - {field_examples}: Document-type-specific extraction guidance
    - {filename}: Original filename
    - {text_content}: Extracted document text
    - {additional_notes}: User-provided notes from template

EXTRACTION APPROACH:
    Free-form extraction asks the AI to identify and extract ALL meaningful
    structured data from the document. Each extracted field is then mapped
    to a predefined FieldType where possible, or assigned FieldType.CUSTOM
    for novel field types.

ENVIRONMENT:
    OPENAI_API_KEY: Required for AI extraction

CHANGELOG:
    v4 (2025-12-17): PromptTemplate database loading with fallbacks
    v3 (2025-12-17): Free-form extraction, dynamic field type mapping
    v2 (2025-12-16): OpenAI GPT-4o integration, document type detection
    v1 (2025-12-15): Initial mock implementation

==============================================================================
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from django.conf import settings

from apps.documents.models import Document
from apps.extraction.models import (
    FieldType,
    ProposalStatus,
    ProposedExtraction,
    ProposedField,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Default Prompts (used when no PromptTemplate exists in database)
# =============================================================================

DEFAULT_SYSTEM_PROMPT = """You are a thorough document extraction AI. Your task is to extract EVERY piece of structured data from documents - not just the obvious fields, but ALL identifiable information.

CRITICAL: You must be exhaustive. Do not stop at 2-5 fields. Most documents contain 15-50+ extractable fields. Extract them ALL.

{field_examples}

For EACH field you extract, provide:
- field_type: A descriptive snake_case identifier (e.g., "employee_name", "company_phone", "skill_python")
- field_name: A human-readable label (e.g., "Employee Name", "Company Phone", "Skill: Python")
- value: The extracted value as a string
- normalised_value: Structured form where applicable (ISO dates as "YYYY-MM-DD", amounts as numbers)
- confidence: Your confidence score (0.0 to 1.0)
- confidence_reason: Brief explanation (1 sentence)
- source_text: The exact text snippet from the document (keep brief, under 100 chars)
- source_page: Page number where found (use 1 if single page or unknown)

IMPORTANT RULES:
1. Extract EVERY distinct piece of information as a separate field
2. For lists (skills, experiences, line items), extract EACH item as a separate field
3. Use specific field_type names: "skill_python" not just "skill", "work_experience_1_company" not just "company"
4. Only extract what is clearly present - do not invent values
5. If uncertain about a value, still extract it with lower confidence
6. Aim for completeness - missing fields is worse than having too many

{additional_notes}

Return valid JSON only."""

DEFAULT_USER_PROMPT = """Extract ALL structured data from this {doc_type} document.

Document filename: {filename}

Document content:
{text_content}

Return a JSON object:
{{
    "document_type": "{doc_type}",
    "document_summary": "One-line summary",
    "field_count_estimate": <your estimate of how many fields this document contains>,
    "fields": [
        {{
            "field_type": "snake_case_type",
            "field_name": "Human Readable Name",
            "value": "extracted value",
            "normalised_value": null,
            "confidence": 0.95,
            "confidence_reason": "Found explicitly in header",
            "source_text": "exact text snippet",
            "source_page": 1
        }}
    ]
}}

REMEMBER: Extract ALL fields. A {doc_type} document typically has 15-40+ fields. Do not stop early."""


@dataclass
class AgentContext:
    """
    Context for agent execution.

    Attributes:
        tenant_id: UUID of the tenant
        document_id: UUID of the document to extract
        trace_id: Request correlation ID
        run_id: Unique ID for this agent execution
        field_types: Optional list of specific field types to extract
                     (if provided, only these types are returned)
    """

    tenant_id: UUID
    document_id: UUID
    trace_id: str
    run_id: UUID
    field_types: list[str] | None = None


@dataclass
class AgentResult:
    """
    Result of agent execution.

    Attributes:
        success: Whether extraction completed successfully
        proposal: The created ProposedExtraction (on success)
        error: Error message (on failure)
        token_usage: Dict of token counts (input, output, total)
        duration_ms: Processing time in milliseconds
    """

    success: bool
    proposal: ProposedExtraction | None = None
    error: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class LoadedPrompts:
    """
    Container for loaded prompt templates.

    Attributes:
        system_prompt: The system message for the AI
        user_prompt_template: The user message template with placeholders
        template_id: UUID of the PromptTemplate used (None if using defaults)
        template_name: Name of the template (or "default")
        additional_notes: Extra instructions from the template
    """

    system_prompt: str
    user_prompt_template: str
    template_id: UUID | None = None
    template_name: str = "default"
    additional_notes: str = ""


class ExtractionAgent:
    """
    Orchestrates document field extraction using OpenAI.

    The agent:
    1. Loads the document
    2. Extracts text content from PDF/DOCX
    3. Detects document type for context
    4. Loads prompt template from database (or uses defaults)
    5. Sends to OpenAI for free-form field extraction
    6. Maps AI responses to FieldType enum (or CUSTOM)
    7. Creates ProposedExtraction with ProposedFields
    """

    MODEL_VERSION = "gpt-4o-2024-08-06"
    PROMPT_VERSION = "v4-templates"
    MAX_TEXT_LENGTH = 50000  # Characters to send to API
    MAX_OUTPUT_TOKENS = 8000  # High limit for comprehensive extraction

    # Mapping from keywords/patterns to FieldType for reverse-matching
    # Each FieldType has associated keywords that might appear in AI responses
    FIELD_TYPE_KEYWORDS: dict[str, list[str]] = {
        FieldType.VENDOR: [
            "vendor", "supplier", "seller", "provider", "merchant",
            "company name", "business name", "from company",
        ],
        FieldType.TOTAL_AMOUNT: [
            "total amount", "total", "grand total", "amount due",
            "total payable", "net total", "gross total", "sum",
        ],
        FieldType.EFFECTIVE_DATE: [
            "effective date", "commencement date", "start date agreement",
            "agreement date", "contract date", "execution date",
        ],
        FieldType.REFERENCE_NUMBER: [
            "reference", "ref", "invoice number", "invoice no", "document id",
            "document number", "order number", "order no", "po number",
            "purchase order", "case number", "file number", "id number",
        ],
        FieldType.PARTIES: [
            "parties", "party", "between", "contracting parties",
            "first party", "second party", "signatories",
        ],
        FieldType.DUE_DATE: [
            "due date", "payment due", "payable by", "deadline",
            "due by", "pay by",
        ],
        FieldType.CURRENCY: [
            "currency", "currency code",
        ],
        FieldType.EMPLOYEE_NAME: [
            "employee name", "employee", "candidate name", "candidate",
            "applicant name", "applicant", "worker name", "staff name",
            "name of employee", "full name",
        ],
        FieldType.JOB_TITLE: [
            "job title", "position", "role", "designation", "title",
            "job position", "employment position", "job role",
        ],
        FieldType.SALARY: [
            "salary", "compensation", "remuneration", "wage", "pay",
            "annual salary", "base salary", "gross salary", "package",
        ],
        FieldType.START_DATE: [
            "start date", "joining date", "commencement", "employment start",
            "begin date", "starting date", "hire date",
        ],
        FieldType.POLICY_NUMBER: [
            "policy number", "policy no", "policy id", "insurance number",
            "cover number", "scheme number",
        ],
        FieldType.CLAIMANT: [
            "claimant", "claimant name", "insured", "insured name",
            "policyholder", "beneficiary",
        ],
        FieldType.CLAIM_AMOUNT: [
            "claim amount", "claimed amount", "claim value", "amount claimed",
            "loss amount", "damage amount",
        ],
        FieldType.EXPIRY_DATE: [
            "expiry date", "expiration date", "end date", "termination date",
            "valid until", "expires on", "valid through", "maturity date",
        ],
        FieldType.GOVERNING_LAW: [
            "governing law", "jurisdiction", "applicable law", "legal jurisdiction",
            "laws of", "governed by",
        ],
        FieldType.LINE_ITEMS: [
            "line items", "items", "products", "services", "description of goods",
        ],
        FieldType.TAX_AMOUNT: [
            "tax amount", "tax", "vat", "gst", "sales tax", "tax total",
        ],
        FieldType.PAYMENT_TERMS: [
            "payment terms", "terms of payment", "payment conditions",
            "net 30", "net 60", "payment schedule",
        ],
        FieldType.JURISDICTION: [
            "jurisdiction", "court", "venue", "forum",
        ],
        FieldType.TERMINATION_CLAUSE: [
            "termination", "termination clause", "notice period",
            "termination terms", "exit clause",
        ],
    }

    # Document-type-specific field extraction guidance
    FIELD_EXAMPLES: dict[str, str] = {
        "hr": """For CVs/resumes, extract ALL of these (where present):
- Full name, email, phone number, address, LinkedIn URL, portfolio URL
- Current job title, target job title
- Each work experience entry: company name, job title, start date, end date, location, description/achievements
- Each education entry: institution name, degree, field of study, graduation date, grades/honours
- Each skill (technical skills, soft skills, languages, tools)
- Each certification: name, issuing organisation, date, expiry
- Professional summary/objective
- References if listed
- Any other structured information

A typical CV should yield 20-50+ fields.""",

        "invoice": """For invoices, extract ALL of these (where present):
- Vendor/seller name, address, phone, email, website, tax ID
- Buyer/customer name, address, contact details
- Invoice number, invoice date, due date, payment terms
- Each line item: description, quantity, unit price, total
- Subtotal, tax rate, tax amount, discount, total amount
- Currency, payment methods, bank details
- Purchase order number, delivery address, shipping terms
- Any notes or terms

A typical invoice should yield 15-40+ fields.""",

        "contract": """For contracts, extract ALL of these (where present):
- All party names, addresses, roles (e.g., "First Party", "Contractor")
- Contract title, reference number, effective date, expiry date
- Contract value/amount, payment terms, payment schedule
- Key obligations for each party
- Termination conditions, notice periods
- Governing law, jurisdiction, dispute resolution
- Signatures, signatory names, dates signed
- Witness details if present
- Key clauses: confidentiality, non-compete, indemnity
- Any schedules or annexes referenced

A typical contract should yield 20-40+ fields.""",

        "insurance": """For insurance documents, extract ALL of these (where present):
- Policy number, policy type, effective date, expiry date
- Insured name, address, contact details
- Insurer name, agent details
- Coverage types, coverage limits, deductibles
- Premium amount, payment frequency, payment method
- Beneficiary names and details
- Claim number, claim date, claim amount (if claim document)
- Property/asset details if relevant
- Exclusions, conditions, endorsements

A typical insurance document should yield 15-35+ fields.""",

        "generic": """Extract ALL structured information including:
- All names (people, companies, organisations)
- All dates (with context: effective, due, start, end, etc.)
- All monetary amounts (with context: total, fee, salary, etc.)
- All reference numbers and IDs
- All contact information (addresses, phones, emails, URLs)
- All titles, roles, positions
- Any quantities, measurements, percentages
- Any status indicators or categories
- Any other identifiable structured data

Be thorough - most documents contain 15-30+ extractable fields.""",
    }

    def __init__(self, context: AgentContext) -> None:
        """Initialise the extraction agent."""
        self.context = context
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._openai_client = None
        self._loaded_prompts: LoadedPrompts | None = None

    @property
    def openai_client(self):
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            try:
                from openai import OpenAI

                api_key = getattr(settings, "OPENAI_API_KEY", None) or os.getenv(
                    "OPENAI_API_KEY"
                )
                if not api_key:
                    raise ValueError("OPENAI_API_KEY not configured")
                self._openai_client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )
        return self._openai_client

    def run(self) -> AgentResult:
        """Execute the extraction workflow."""
        start_time = time.time()

        self.logger.info(
            f"Starting extraction for document {self.context.document_id}",
            extra={
                "trace_id": self.context.trace_id,
                "run_id": str(self.context.run_id),
                "document_id": str(self.context.document_id),
            },
        )

        try:
            # Load document
            document = self._load_document()
            if not document:
                return AgentResult(
                    success=False,
                    error=f"Document not found: {self.context.document_id}",
                    duration_ms=self._calculate_duration(start_time),
                )

            # Extract text from document
            text_content = self._extract_text(document)
            if not text_content:
                return AgentResult(
                    success=False,
                    error="Could not extract text from document",
                    duration_ms=self._calculate_duration(start_time),
                )

            # Detect document type (used for context in prompt)
            doc_type = self._detect_document_type(document, text_content)

            # Load prompt templates from database (or use defaults)
            self._loaded_prompts = self._load_prompt_templates(doc_type)

            self.logger.info(
                f"Using prompt template: {self._loaded_prompts.template_name}",
                extra={
                    "template_id": str(self._loaded_prompts.template_id) if self._loaded_prompts.template_id else None,
                    "template_name": self._loaded_prompts.template_name,
                    "document_id": str(self.context.document_id),
                    "doc_type": doc_type,
                },
            )

            # Call OpenAI for free-form extraction
            extraction_result = self._call_openai(document, text_content, doc_type)

            if not extraction_result["success"]:
                return AgentResult(
                    success=False,
                    error=extraction_result.get("error", "Extraction failed"),
                    duration_ms=self._calculate_duration(start_time),
                )

            raw_fields = extraction_result["fields"]
            token_usage = extraction_result.get("token_usage", {})

            # Map AI field types to FieldType enum
            mapped_fields = self._map_fields_to_types(raw_fields)

            # Filter by requested field types if specified
            if self.context.field_types:
                mapped_fields = [
                    f for f in mapped_fields
                    if f["field_type"] in self.context.field_types
                ]

            # Calculate overall confidence
            overall_confidence = self._calculate_overall_confidence(mapped_fields)

            # Generate prompt hash (now includes template info)
            prompt_hash = self._generate_prompt_hash(document, doc_type)

            # Calculate duration
            duration_ms = self._calculate_duration(start_time)

            # Create ProposedExtraction
            proposal = ProposedExtraction.objects.create(
                tenant_id=self.context.tenant_id,
                document=document,
                status=ProposalStatus.PENDING,
                agent_run_id=self.context.run_id,
                model_version=self.MODEL_VERSION,
                prompt_hash=prompt_hash,
                overall_confidence=overall_confidence,
                token_usage=token_usage,
                processing_duration_ms=duration_ms,
            )

            # Create ProposedFields
            for field_data in mapped_fields:
                ProposedField.objects.create(
                    extraction=proposal,
                    field_type=field_data["field_type"],
                    field_name=field_data["field_name"],
                    value=field_data["value"],
                    normalised_value=field_data.get("normalised_value"),
                    source_text=field_data.get("source_text", ""),
                    source_page=field_data.get("source_page", 1),
                    source_location=field_data.get("source_location"),
                    confidence=field_data["confidence"],
                    confidence_reason=field_data.get("confidence_reason", ""),
                    validation_status="pending",
                )

            self.logger.info(
                f"Extraction completed for document {self.context.document_id}",
                extra={
                    "trace_id": self.context.trace_id,
                    "run_id": str(self.context.run_id),
                    "proposal_id": str(proposal.id),
                    "field_count": len(mapped_fields),
                    "overall_confidence": overall_confidence,
                    "duration_ms": duration_ms,
                    "template_used": self._loaded_prompts.template_name if self._loaded_prompts else "default",
                },
            )

            return AgentResult(
                success=True,
                proposal=proposal,
                token_usage=token_usage,
                duration_ms=duration_ms,
            )

        except Exception as e:
            self.logger.exception(
                f"Extraction failed for document {self.context.document_id}",
                extra={
                    "trace_id": self.context.trace_id,
                    "run_id": str(self.context.run_id),
                    "error": str(e),
                },
            )
            return AgentResult(
                success=False,
                error=str(e),
                duration_ms=self._calculate_duration(start_time),
            )

    def _load_document(self) -> Document | None:
        """Load the document from database."""
        return Document.objects.filter(
            id=self.context.document_id,
            tenant_id=self.context.tenant_id,
        ).first()

    def _extract_text(self, document: Document) -> str:
        """Extract text content from PDF or DOCX."""
        if not document.file:
            return ""

        file_path = document.file.path
        file_type = document.file_type.lower()

        try:
            if "pdf" in file_type:
                return self._extract_pdf_text(file_path)
            elif "word" in file_type or "docx" in file_type:
                return self._extract_docx_text(file_path)
            else:
                self.logger.warning(
                    f"Unsupported file type for text extraction: {file_type}"
                )
                return ""
        except Exception as e:
            self.logger.error(f"Text extraction failed: {e}")
            return ""

    def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF file."""
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)
            text_parts = []

            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text() or ""
                if page_text:
                    text_parts.append(f"[Page {page_num}]\n{page_text}")

            return "\n\n".join(text_parts)
        except ImportError:
            self.logger.error("PyPDF2 not installed. Run: pip install PyPDF2")
            return ""

    def _extract_docx_text(self, file_path: str) -> str:
        """Extract text from DOCX file."""
        try:
            from docx import Document as DocxDocument

            doc = DocxDocument(file_path)
            text_parts = []

            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)

            return "\n\n".join(text_parts)
        except ImportError:
            self.logger.error("python-docx not installed. Run: pip install python-docx")
            return ""

    def _detect_document_type(self, document: Document, text_content: str) -> str:
        """Detect document type from filename, metadata, and content."""
        combined = (
            f"{document.original_filename} {document.title or ''} "
            f"{text_content[:1000]}"
        ).lower()

        if any(kw in combined for kw in ["invoice", "bill", "receipt", "payment due"]):
            return "invoice"
        elif any(
            kw in combined
            for kw in ["contract", "agreement", "hereby agree", "terms and conditions"]
        ):
            return "contract"
        elif any(
            kw in combined
            for kw in [
                "cv",
                "resume",
                "curriculum vitae",
                "employment",
                "offer letter",
                "salary",
            ]
        ):
            return "hr"
        elif any(
            kw in combined for kw in ["claim", "policy", "insurance", "premium"]
        ):
            return "insurance"
        else:
            return "generic"

    def _load_prompt_templates(self, doc_type: str) -> LoadedPrompts:
        """
        Load prompt templates from database or use defaults.

        Attempts to load in order:
        1. Document-type-specific template for this tenant
        2. Default template (document_type=None) for this tenant
        3. Hardcoded defaults (DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT)

        Args:
            doc_type: Detected document type (hr, invoice, contract, etc.)

        Returns:
            LoadedPrompts with system and user prompts ready to use
        """
        try:
            from apps.extraction.prompt_models import PromptTemplate

            # Try to get active template from database
            template = PromptTemplate.get_active_template(
                tenant_id=self.context.tenant_id,
                document_type=doc_type,
            )

            if template:
                self.logger.debug(
                    f"Loaded prompt template from database: {template.name}",
                    extra={
                        "template_id": str(template.id),
                        "template_name": template.name,
                        "document_type": template.document_type,
                    },
                )

                return LoadedPrompts(
                    system_prompt=template.system_prompt,
                    user_prompt_template=template.user_prompt_template,
                    template_id=template.id,
                    template_name=template.name,
                    additional_notes=template.description or "",
                )

        except Exception as e:
            self.logger.warning(
                f"Failed to load prompt template from database: {e}. Using defaults.",
                extra={"error": str(e)},
            )

        # Fall back to hardcoded defaults
        self.logger.debug("Using default hardcoded prompts")
        return LoadedPrompts(
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            user_prompt_template=DEFAULT_USER_PROMPT,
            template_id=None,
            template_name="default (hardcoded)",
            additional_notes="",
        )

    def _get_field_examples_for_doc_type(self, doc_type: str) -> str:
        """
        Get document-type-specific field examples to guide extraction.

        Args:
            doc_type: Detected document type

        Returns:
            String with example fields for the prompt
        """
        return self.FIELD_EXAMPLES.get(doc_type, self.FIELD_EXAMPLES["generic"])

    def _call_openai(
        self, document: Document, text_content: str, doc_type: str
    ) -> dict[str, Any]:
        """
        Call OpenAI API for free-form field extraction.

        Uses prompts loaded from PromptTemplate (or defaults).
        Supports placeholders in prompts:
        - {doc_type}: Detected document type
        - {field_examples}: Document-type-specific guidance
        - {filename}: Original filename
        - {text_content}: Extracted document text
        - {additional_notes}: Notes from template description
        """
        # Truncate text if too long
        truncated_text = text_content[: self.MAX_TEXT_LENGTH]
        if len(text_content) > self.MAX_TEXT_LENGTH:
            truncated_text += "\n\n[Document truncated...]"

        # Get document-type-specific examples
        field_examples = self._get_field_examples_for_doc_type(doc_type)

        # Prepare placeholder values
        placeholders = {
            "doc_type": doc_type,
            "field_examples": field_examples,
            "filename": document.original_filename,
            "text_content": truncated_text,
            "additional_notes": self._loaded_prompts.additional_notes if self._loaded_prompts else "",
        }

        # Build prompts from templates (with safe placeholder substitution)
        system_prompt = self._substitute_placeholders(
            self._loaded_prompts.system_prompt if self._loaded_prompts else DEFAULT_SYSTEM_PROMPT,
            placeholders,
        )

        user_prompt = self._substitute_placeholders(
            self._loaded_prompts.user_prompt_template if self._loaded_prompts else DEFAULT_USER_PROMPT,
            placeholders,
        )

        try:
            response = self.openai_client.chat.completions.create(
                model=self.MODEL_VERSION,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=self.MAX_OUTPUT_TOKENS,
            )

            # Parse response
            content = response.choices[0].message.content

            # Extract token usage
            token_usage = {
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
                "total": response.usage.total_tokens,
            }

            # Attempt to parse JSON, with repair for truncated responses
            result = self._parse_json_response(content, token_usage)

            if result is None:
                return {"success": False, "error": "Failed to parse JSON response"}

            fields = result.get("fields", [])

            # Debug logging - critical for diagnosing extraction issues
            self.logger.info(
                f"OpenAI extraction result for document {self.context.document_id}",
                extra={
                    "document_id": str(self.context.document_id),
                    "field_count": len(fields),
                    "field_count_estimate": result.get("field_count_estimate", "N/A"),
                    "document_summary": result.get("document_summary", "N/A"),
                    "token_usage": token_usage,
                    "template_used": self._loaded_prompts.template_name if self._loaded_prompts else "default",
                    "field_types_returned": [f.get("field_type") for f in fields[:10]],
                },
            )

            # Warn if field count is suspiciously low
            if len(fields) < 10:
                self.logger.warning(
                    f"Low field count ({len(fields)}) for document {self.context.document_id}. "
                    f"Expected 15-40+ fields. Raw response length: {len(content)} chars",
                    extra={
                        "document_id": str(self.context.document_id),
                        "field_count": len(fields),
                        "response_preview": content[:500] if len(content) > 500 else content,
                    },
                )

            return {
                "success": True,
                "fields": fields,
                "document_summary": result.get("document_summary", ""),
                "token_usage": token_usage,
            }

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse OpenAI response: {e}")
            return {"success": False, "error": f"Invalid JSON response: {e}"}
        except Exception as e:
            self.logger.error(f"OpenAI API error: {e}")
            return {"success": False, "error": str(e)}

    def _substitute_placeholders(
        self, template: str, placeholders: dict[str, str]
    ) -> str:
        """
        Safely substitute placeholders in a template string.

        Uses a safe approach that doesn't raise KeyError for missing
        placeholders - they are left as-is.

        Args:
            template: Template string with {placeholder} markers
            placeholders: Dict of placeholder name -> value

        Returns:
            Template with placeholders substituted
        """
        result = template
        for key, value in placeholders.items():
            # Use simple string replacement to avoid format string issues
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, str(value))
        return result

    def _parse_json_response(
        self, content: str, token_usage: dict[str, int]
    ) -> dict[str, Any] | None:
        """
        Parse JSON response with repair logic for truncated responses.

        OpenAI's response_format=json_object should guarantee valid JSON,
        but responses can be truncated if they hit max_tokens. This method
        attempts to repair common truncation issues.

        Args:
            content: Raw response content from OpenAI
            token_usage: Token usage dict for logging

        Returns:
            Parsed JSON dict, or None if parsing fails
        """
        # First, try direct parsing
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.warning(
                f"Initial JSON parse failed at position {e.pos}, attempting repair",
                extra={
                    "error": str(e),
                    "content_length": len(content),
                    "token_usage": token_usage,
                },
            )

        # Log the raw content for debugging
        self.logger.debug(
            f"Raw OpenAI response (first 1000 chars): {content[:1000]}",
        )
        self.logger.debug(
            f"Raw OpenAI response (last 500 chars): {content[-500:]}",
        )

        # Attempt repair strategies
        repaired_content = self._attempt_json_repair(content)

        if repaired_content:
            try:
                result = json.loads(repaired_content)
                self.logger.info(
                    f"JSON repair successful, extracted {len(result.get('fields', []))} fields"
                )
                return result
            except json.JSONDecodeError as e:
                self.logger.error(
                    f"JSON repair failed: {e}",
                    extra={"repaired_content_tail": repaired_content[-200:]},
                )

        # Log failure details for manual inspection
        self.logger.error(
            f"Could not parse or repair JSON response. "
            f"Content length: {len(content)}, Output tokens: {token_usage.get('output', 'N/A')}",
            extra={
                "content_tail": content[-500:] if len(content) > 500 else content,
            },
        )

        return None

    def _attempt_json_repair(self, content: str) -> str | None:
        """
        Attempt to repair truncated or malformed JSON.

        Common issues:
        1. Truncated mid-object (missing closing braces/brackets)
        2. Trailing comma before closing bracket
        3. Incomplete string at the end

        Args:
            content: Malformed JSON string

        Returns:
            Repaired JSON string, or None if repair not possible
        """
        # Strategy 1: Find the last complete field and close the JSON
        # Look for the last complete field object ending with }
        last_complete_field = content.rfind('},')
        if last_complete_field == -1:
            last_complete_field = content.rfind('}')

        if last_complete_field > 0:
            # Truncate to last complete field
            truncated = content[:last_complete_field + 1]

            # Count open braces/brackets to determine what needs closing
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')

            # Close the fields array and root object
            if open_brackets > 0 and open_braces > 0:
                # We're inside the fields array
                repaired = truncated + ']' + '}' * open_braces
            elif open_braces > 0:
                repaired = truncated + '}' * open_braces
            else:
                repaired = truncated

            # Clean up trailing commas before closing brackets/braces
            repaired = re.sub(r',\s*}', '}', repaired)
            repaired = re.sub(r',\s*]', ']', repaired)

            return repaired

        return None

    def _map_fields_to_types(
        self, raw_fields: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Map AI-returned field types to FieldType enum values.

        Attempts to match each field to a predefined FieldType based on
        the field_type and field_name. Falls back to FieldType.CUSTOM
        for unrecognised field types.

        Args:
            raw_fields: List of field dicts from OpenAI response

        Returns:
            List of field dicts with field_type mapped to FieldType enum values
        """
        mapped_fields = []
        seen_types: set[str] = set()

        for field_data in raw_fields:
            ai_field_type = field_data.get("field_type", "")
            ai_field_name = field_data.get("field_name", "")

            # Attempt to map to a predefined FieldType
            matched_type = self._match_field_type(ai_field_type, ai_field_name)

            # Handle uniqueness constraint (non-CUSTOM types must be unique)
            if matched_type != FieldType.CUSTOM:
                if matched_type in seen_types:
                    # Already have this type, demote to CUSTOM
                    matched_type = FieldType.CUSTOM
                else:
                    seen_types.add(matched_type)

            # Build mapped field data
            mapped_field = {
                "field_type": matched_type,
                "field_name": ai_field_name or self._humanise_field_type(ai_field_type),
                "value": field_data.get("value", ""),
                "normalised_value": field_data.get("normalised_value"),
                "source_text": field_data.get("source_text", ""),
                "source_page": field_data.get("source_page", 1),
                "source_location": field_data.get("source_location"),
                "confidence": self._validate_confidence(
                    field_data.get("confidence", 0.5)
                ),
                "confidence_reason": field_data.get("confidence_reason", ""),
            }

            mapped_fields.append(mapped_field)

        return mapped_fields

    def _match_field_type(self, ai_field_type: str, ai_field_name: str) -> str:
        """
        Match an AI-returned field type to a predefined FieldType.

        Uses keyword matching against FIELD_TYPE_KEYWORDS to find the
        best match. Returns FieldType.CUSTOM if no match found.

        Args:
            ai_field_type: The snake_case field type from AI
            ai_field_name: The human-readable field name from AI

        Returns:
            Matching FieldType value or FieldType.CUSTOM
        """
        # Normalise inputs for matching
        search_text = f"{ai_field_type} {ai_field_name}".lower()
        search_text = re.sub(r"[_\-]", " ", search_text)

        # Check for direct FieldType match first
        valid_field_types = {choice[0] for choice in FieldType.choices}
        if ai_field_type in valid_field_types:
            return ai_field_type

        # Search through keyword mappings
        best_match = None
        best_score = 0

        for field_type, keywords in self.FIELD_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in search_text:
                    # Score by keyword length (longer = more specific = better)
                    score = len(keyword)
                    if score > best_score:
                        best_score = score
                        best_match = field_type

        return best_match if best_match else FieldType.CUSTOM

    def _humanise_field_type(self, snake_case: str) -> str:
        """
        Convert snake_case to Human Readable Title Case.

        Args:
            snake_case: A snake_case string like "employee_name"

        Returns:
            Title case string like "Employee Name"
        """
        if not snake_case:
            return "Unknown Field"
        return snake_case.replace("_", " ").replace("-", " ").title()

    def _validate_confidence(self, confidence: Any) -> float:
        """
        Validate and clamp confidence score to valid range.

        Args:
            confidence: Raw confidence value from AI

        Returns:
            Float clamped to [0.0, 1.0]
        """
        try:
            conf = float(confidence)
            return max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            return 0.5

    def _calculate_overall_confidence(self, fields: list[dict[str, Any]]) -> float:
        """Calculate overall confidence as weighted average."""
        if not fields:
            return 0.0
        confidences = [f.get("confidence", 0.5) for f in fields]
        return round(sum(confidences) / len(confidences), 2)

    def _generate_prompt_hash(self, document: Document, doc_type: str) -> str:
        """
        Generate hash of the prompt configuration for reproducibility.

        Includes template ID if using database template, or 'default' marker.
        """
        template_marker = (
            str(self._loaded_prompts.template_id)
            if self._loaded_prompts and self._loaded_prompts.template_id
            else "default"
        )

        prompt_template = (
            f"{self.PROMPT_VERSION}:{self.MODEL_VERSION}:{doc_type}:"
            f"{document.file_type}:{template_marker}"
        )
        return hashlib.sha256(prompt_template.encode()).hexdigest()[:64]

    def _calculate_duration(self, start_time: float) -> int:
        """Calculate duration in milliseconds."""
        return int((time.time() - start_time) * 1000)