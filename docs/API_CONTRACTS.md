# API Contracts

**REST API Specifications for DocExtract**

This document defines all API endpoints, request/response schemas, error handling, and authentication requirements.

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Common Patterns](#common-patterns)
4. [Documents API](#documents-api)
5. [Extractions API](#extractions-api)
6. [Actions API](#actions-api)
7. [Feature Flags API](#feature-flags-api)
8. [Error Handling](#error-handling)
9. [Rate Limiting](#rate-limiting)

---

## Overview

### Base URL

```
Production: https://api.docextract.example.com/api/v1/
Development: http://localhost:8000/api/v1/
```

### Content Type

All requests and responses use JSON:

```
Content-Type: application/json
Accept: application/json
```

### API Versioning

Version is included in the URL path (`/api/v1/`). Breaking changes will increment the version number.

---

## Authentication

### Token Authentication

All API endpoints require authentication via token header:

```http
Authorisation: Token <your-api-token>
```

Tokens are obtained via Django Admin or the token endpoint (if enabled).

### Session Authentication

For browser-based access (Django Admin), session cookies are used. CSRF protection is enforced for non-safe methods.

### Request Context

Every authenticated request includes:
- `request.user` — Authenticated user
- `request.tenant` — User's tenant (via middleware)
- `request.trace_id` — Unique request identifier (via middleware)
- `request.feature_flags` — Evaluated feature flags (via middleware)

---

## Common Patterns

### Pagination

List endpoints return paginated responses:

```json
{
    "count": 100,
    "next": "https://api.example.com/api/v1/documents/?page=2",
    "previous": null,
    "results": [...]
}
```

Query parameters:
- `page` — Page number (default: 1)
- `page_size` — Items per page (default: 20, max: 100)

### Filtering

List endpoints support filtering via query parameters:

```
GET /api/v1/documents/?status=pending&created_after=2024-01-01
```

### Ordering

List endpoints support ordering:

```
GET /api/v1/documents/?ordering=-created_at
GET /api/v1/documents/?ordering=title
```

### Standard Response Envelope

Success responses return data directly or with metadata:

```json
{
    "id": "uuid",
    "...": "..."
}
```

Error responses use standard format (see [Error Handling](#error-handling)).

---

## Documents API

### List Documents

```http
GET /api/v1/documents/
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: pending, processing, extracted, failed |
| `created_after` | datetime | Filter by creation date |
| `created_before` | datetime | Filter by creation date |
| `ordering` | string | Sort field: created_at, title, status |
| `search` | string | Search in title and filename |

**Response: 200 OK**

```json
{
    "count": 42,
    "next": "http://localhost:8000/api/v1/documents/?page=2",
    "previous": null,
    "results": [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "original_filename": "invoice-2024-001.pdf",
            "file_type": "application/pdf",
            "file_size_bytes": 245678,
            "status": "extracted",
            "status_message": "",
            "title": "Invoice #INV-2024-001 - Acme Corp",
            "uploaded_by": {
                "id": 1,
                "email": "user@example.com"
            },
            "extraction_count": 1,
            "active_field_count": 8,
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T10:35:00Z"
        }
    ]
}
```

---

### Create Document (Upload)

```http
POST /api/v1/documents/
Content-Type: multipart/form-data
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | Document file (PDF, DOCX) |
| `title` | string | No | Document title (auto-extracted if omitted) |
| `metadata` | object | No | Additional metadata |
| `auto_extract` | boolean | No | Trigger extraction immediately (default: false) |

**Response: 201 Created**

```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "original_filename": "invoice-2024-001.pdf",
    "file_type": "application/pdf",
    "file_size_bytes": 245678,
    "file_hash": "sha256:a1b2c3d4...",
    "status": "pending",
    "status_message": "",
    "title": "invoice-2024-001.pdf",
    "metadata": {},
    "uploaded_by": {
        "id": 1,
        "email": "user@example.com"
    },
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "links": {
        "self": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/",
        "extract": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/extract/",
        "extractions": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/extractions/"
    }
}
```

**Errors:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `invalid_file_type` | File type not supported |
| 400 | `file_too_large` | File exceeds size limit |
| 400 | `duplicate_file` | File with same hash already exists |

---

### Retrieve Document

```http
GET /api/v1/documents/{id}/
```

**Response: 200 OK**

```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "original_filename": "invoice-2024-001.pdf",
    "file_type": "application/pdf",
    "file_size_bytes": 245678,
    "file_hash": "sha256:a1b2c3d4...",
    "status": "extracted",
    "status_message": "",
    "title": "Invoice #INV-2024-001 - Acme Corp",
    "metadata": {},
    "uploaded_by": {
        "id": 1,
        "email": "user@example.com"
    },
    "extraction_started_at": "2024-01-15T10:31:00Z",
    "extraction_completed_at": "2024-01-15T10:32:30Z",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:32:30Z",
    "latest_extraction": {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "status": "committed",
        "overall_confidence": 0.92,
        "field_count": 8
    },
    "extracted_fields": [
        {
            "id": "770e8400-e29b-41d4-a716-446655440002",
            "field_type": "vendor",
            "field_name": "Vendor Name",
            "value": "Acme Corporation",
            "confidence": 0.95,
            "is_active": true
        }
    ],
    "links": {
        "self": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/",
        "download": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/download/",
        "extract": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/extract/",
        "extractions": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/extractions/"
    }
}
```

---

### Trigger Extraction

```http
POST /api/v1/documents/{id}/extract/
```

Initiates async AI extraction. Requires `ai_extraction_enabled` feature flag.

**Request Body:**

```json
{
    "force": false,
    "field_types": ["parties", "effective_date", "governing_law"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `force` | boolean | No | Re-extract even if extraction exists (default: false) |
| `field_types` | array | No | Specific fields to extract (default: all) |

**Response: 202 Accepted**

```json
{
    "task_id": "abc123-def456",
    "document_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "message": "Extraction task queued",
    "estimated_duration_seconds": 30,
    "links": {
        "document": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/",
        "status": "/api/v1/tasks/abc123-def456/"
    }
}
```

**Errors:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `extraction_in_progress` | Document already being processed |
| 400 | `extraction_exists` | Extraction exists (use force=true) |
| 404 | `document_not_found` | Document does not exist |
| 503 | `feature_disabled` | AI extraction is disabled |

---

### Download Document

```http
GET /api/v1/documents/{id}/download/
```

**Response: 200 OK**

Returns the file with appropriate Content-Type and Content-Disposition headers.

```http
Content-Type: application/pdf
Content-Disposition: attachment; filename="invoice-2024-001.pdf"
```

---

## Extractions API

### List Extractions for Document

```http
GET /api/v1/documents/{document_id}/extractions/
```

**Response: 200 OK**

```json
{
    "count": 2,
    "results": [
        {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "committed",
            "overall_confidence": 0.92,
            "model_version": "gpt-4-turbo-2024-01-01",
            "processing_duration_ms": 4523,
            "field_count": 8,
            "reviewed_by": {
                "id": 1,
                "email": "user@example.com"
            },
            "reviewed_at": "2024-01-15T10:35:00Z",
            "created_at": "2024-01-15T10:32:30Z"
        },
        {
            "id": "660e8400-e29b-41d4-a716-446655440002",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "superseded",
            "overall_confidence": 0.78,
            "model_version": "gpt-4-turbo-2024-01-01",
            "processing_duration_ms": 3891,
            "field_count": 6,
            "reviewed_by": null,
            "reviewed_at": null,
            "created_at": "2024-01-15T10:31:00Z"
        }
    ]
}
```

---

### Retrieve Extraction

```http
GET /api/v1/extractions/{id}/
```

**Response: 200 OK**

```json
{
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "document": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "Invoice #INV-2024-001 - Acme Corp"
    },
    "status": "pending",
    "overall_confidence": 0.92,
    "model_version": "gpt-4-turbo-2024-01-01",
    "agent_run_id": "880e8400-e29b-41d4-a716-446655440003",
    "processing_duration_ms": 4523,
    "token_usage": {
        "input": 3420,
        "output": 892,
        "total": 4312
    },
    "fields": [
        {
            "id": "990e8400-e29b-41d4-a716-446655440004",
            "field_type": "vendor",
            "field_name": "Vendor Name",
            "value": "Acme Corporation",
            "normalised_value": {
                "name": "Acme Corporation",
                "tax_id": "12-3456789"
            },
            "source_text": "From: Acme Corporation, 123 Business St...",
            "source_page": 1,
            "confidence": 0.95,
            "confidence_reason": "Clear vendor header identification",
            "validation_status": "valid"
        },
        {
            "id": "990e8400-e29b-41d4-a716-446655440005",
            "field_type": "total_amount",
            "field_name": "Total Amount",
            "value": "$4,250.00",
            "normalised_value": {
                "amount": 4250.00,
                "currency": "USD"
            },
            "source_text": "Total Due: $4,250.00",
            "source_page": 1,
            "confidence": 0.98,
            "confidence_reason": "Explicit total field with currency symbol",
            "validation_status": "valid"
        }
    ],
    "review_notes": "",
    "reviewed_by": null,
    "reviewed_at": null,
    "committed_action": null,
    "created_at": "2024-01-15T10:32:30Z",
    "links": {
        "self": "/api/v1/extractions/660e8400-e29b-41d4-a716-446655440001/",
        "document": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/",
        "commit": "/api/v1/extractions/660e8400-e29b-41d4-a716-446655440001/commit/",
        "reject": "/api/v1/extractions/660e8400-e29b-41d4-a716-446655440001/reject/"
    }
}
```

---

### Commit Extraction

```http
POST /api/v1/extractions/{id}/commit/
```

Commits proposed extraction to canonical storage via Action.

**Request Body:**

```json
{
    "review_notes": "Verified against original document",
    "field_overrides": {
        "990e8400-e29b-41d4-a716-446655440005": {
            "value": "January 15, 2024",
            "normalised_value": {
                "iso_date": "2024-01-15"
            }
        }
    }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `review_notes` | string | No | Reviewer comments |
| `field_overrides` | object | No | Corrections to proposed values |

**Response: 200 OK**

```json
{
    "extraction_id": "660e8400-e29b-41d4-a716-446655440001",
    "action": {
        "id": "aa0e8400-e29b-41d4-a716-446655440006",
        "action_type": "commit_extraction",
        "status": "completed",
        "is_reversible": true,
        "created_at": "2024-01-15T10:35:00Z"
    },
    "committed_fields": 8,
    "message": "Extraction committed successfully",
    "links": {
        "extraction": "/api/v1/extractions/660e8400-e29b-41d4-a716-446655440001/",
        "action": "/api/v1/actions/aa0e8400-e29b-41d4-a716-446655440006/",
        "document": "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/"
    }
}
```

**Errors:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `already_committed` | Extraction already committed |
| 400 | `already_rejected` | Extraction was rejected |
| 400 | `validation_failed` | Field overrides invalid |
| 409 | `concurrent_modification` | Document modified by another request |

---

### Reject Extraction

```http
POST /api/v1/extractions/{id}/reject/
```

**Request Body:**

```json
{
    "reason": "Incorrect party identification",
    "request_re_extraction": true
}
```

**Response: 200 OK**

```json
{
    "extraction_id": "660e8400-e29b-41d4-a716-446655440001",
    "status": "rejected",
    "action": {
        "id": "aa0e8400-e29b-41d4-a716-446655440007",
        "action_type": "reject_extraction",
        "status": "completed"
    },
    "re_extraction_triggered": true,
    "new_task_id": "def456-ghi789"
}
```

---

## Actions API

### List Actions

```http
GET /api/v1/actions/
```

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `action_type` | string | Filter by type |
| `target_type` | string | Filter by target model |
| `target_id` | string | Filter by target ID |
| `actor_id` | string | Filter by actor |
| `trace_id` | string | Filter by trace ID |
| `created_after` | datetime | Filter by date |

**Response: 200 OK**

```json
{
    "count": 156,
    "results": [
        {
            "id": "aa0e8400-e29b-41d4-a716-446655440006",
            "action_type": "commit_extraction",
            "status": "completed",
            "actor": {
                "type": "user",
                "id": "1",
                "email": "user@example.com"
            },
            "target": {
                "type": "ProposedExtraction",
                "id": "660e8400-e29b-41d4-a716-446655440001"
            },
            "is_reversible": true,
            "reversed_by": null,
            "trace_id": "req-abc123",
            "created_at": "2024-01-15T10:35:00Z"
        }
    ]
}
```

---

### Retrieve Action

```http
GET /api/v1/actions/{id}/
```

**Response: 200 OK**

```json
{
    "id": "aa0e8400-e29b-41d4-a716-446655440006",
    "action_type": "commit_extraction",
    "status": "completed",
    "actor": {
        "type": "user",
        "id": "1",
        "email": "user@example.com"
    },
    "target": {
        "type": "ProposedExtraction",
        "id": "660e8400-e29b-41d4-a716-446655440001"
    },
    "trace_id": "req-abc123",
    "idempotency_key": "commit-660e8400-e29b-41d4-a716-446655440001",
    "pre_state": {
        "proposal_status": "pending",
        "existing_fields": []
    },
    "post_state": {
        "proposal_status": "committed",
        "created_field_ids": [
            "770e8400-e29b-41d4-a716-446655440002",
            "770e8400-e29b-41d4-a716-446655440003"
        ]
    },
    "is_reversible": true,
    "reversed_by": null,
    "reverses": null,
    "metadata": {
        "agent_run_id": "880e8400-e29b-41d4-a716-446655440003",
        "field_count": 8
    },
    "created_at": "2024-01-15T10:35:00Z",
    "links": {
        "self": "/api/v1/actions/aa0e8400-e29b-41d4-a716-446655440006/",
        "rollback": "/api/v1/actions/aa0e8400-e29b-41d4-a716-446655440006/rollback/"
    }
}
```

---

### Rollback Action

```http
POST /api/v1/actions/{id}/rollback/
```

Reverses a previously committed action.

**Request Body:**

```json
{
    "reason": "Incorrect data committed, need to re-extract"
}
```

**Response: 200 OK**

```json
{
    "original_action_id": "aa0e8400-e29b-41d4-a716-446655440006",
    "rollback_action": {
        "id": "bb0e8400-e29b-41d4-a716-446655440008",
        "action_type": "rollback_extraction",
        "status": "completed",
        "reverses": "aa0e8400-e29b-41d4-a716-446655440006"
    },
    "restored_state": {
        "proposal_status": "pending",
        "deactivated_field_count": 8
    },
    "message": "Action rolled back successfully"
}
```

**Errors:**

| Status | Error Code | Description |
|--------|------------|-------------|
| 400 | `not_reversible` | Action cannot be rolled back |
| 400 | `already_reversed` | Action was already rolled back |
| 409 | `dependent_actions` | Later actions depend on this one |

---

## Feature Flags API

### List Feature Flags

```http
GET /api/v1/features/
```

Admin only. Returns all flags with current state.

**Response: 200 OK**

```json
{
    "results": [
        {
            "key": "ai_extraction_enabled",
            "description": "Enable AI-powered field extraction",
            "is_enabled": true,
            "rollout_percentage": 100,
            "enabled_tenants": [],
            "disabled_tenants": [],
            "owner": "ml-team"
        }
    ]
}
```

---

### Evaluate Flags for Current Context

```http
GET /api/v1/features/evaluate/
```

Returns evaluated flags for current user/tenant.

**Response: 200 OK**

```json
{
    "flags": {
        "ai_extraction_enabled": true,
        "new_ui_enabled": false,
        "beta_features": true
    },
    "context": {
        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
        "user_id": 1
    }
}
```

---

## Error Handling

### Error Response Format

All errors follow a consistent format:

```json
{
    "error": {
        "code": "validation_error",
        "message": "Invalid request data",
        "details": {
            "field": ["This field is required."]
        },
        "trace_id": "req-abc123"
    }
}
```

### HTTP Status Codes

| Code | Meaning               | Usage |
|------|-----------------------|-------|
| 200 | OK                    | Successful GET, PUT, PATCH |
| 201 | Created               | Successful POST creating resource |
| 202 | Accepted              | Async task queued |
| 204 | No Content            | Successful DELETE |
| 400 | Bad Request           | Validation error, invalid input |
| 401 | Unauthorised          | Missing or invalid auth |
| 403 | Forbidden             | Insufficient permissions |
| 404 | Not Found             | Resource doesn't exist |
| 409 | Conflict              | Concurrent modification, duplicate |
| 422 | Unprocessable Entity  | Semantic error (valid JSON, invalid meaning) |
| 429 | Too Many Requests     | Rate limited |
| 500 | Internal Server Error | Unexpected server error |
| 503 | Service Unavailable   | Feature disabled, maintenance |

### Common Error Codes

| Code | Description |
|------|-------------|
| `validation_error` | Request data failed validation |
| `authentication_required` | No valid auth credentials |
| `permission_denied` | User lacks required permission |
| `not_found` | Resource does not exist |
| `conflict` | Resource state conflict |
| `feature_disabled` | Feature flag is off |
| `rate_limited` | Too many requests |
| `internal_error` | Unexpected server error |

---

## Rate Limiting

### Limits

| Endpoint Type | Limit | Window |
|---------------|-------|--------|
| Standard endpoints | 100 requests | 1 minute |
| Upload endpoints | 10 requests | 1 minute |
| Extraction trigger | 5 requests | 1 minute |

### Response Headers

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705312800
```

### Rate Limit Exceeded Response

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30

{
    "error": {
        "code": "rate_limited",
        "message": "Rate limit exceeded. Try again in 30 seconds.",
        "retry_after": 30
    }
}
```