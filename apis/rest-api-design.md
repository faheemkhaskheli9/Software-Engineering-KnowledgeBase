---
title: REST API design
category: apis
tags: [rest, http, api-design, openapi, status-codes, idempotency, hateoas, json]
use_cases:
  - "design a public JSON HTTP API for a SaaS product"
  - "choose correct HTTP methods, status codes and error format"
  - "make POST requests safe to retry without duplicate orders"
  - "document an API with OpenAPI and keep clients in sync"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc9110
  - https://www.rfc-editor.org/rfc/rfc9457
  - https://spec.openapis.org/oas/latest.html
  - "Roy Fielding, Architectural Styles and the Design of Network-based Software Architectures (2000), ch. 5"
  - https://cloud.google.com/apis/design
---

# REST API design

## Summary
REST-style HTTP APIs expose resources (nouns) at stable URLs and manipulate them with standard methods and status codes. Most "REST" APIs in practice are resource-oriented JSON over HTTP. Good design is mainly consistency: predictable URLs, correct semantics for methods and codes, a uniform error shape, safe retries, and a machine-readable contract.

## Key concepts
- **Resources and URLs**: plural nouns, hierarchy only where ownership is real: `/orders/123/items`. Verbs belong in methods, not paths.
- **Methods**: `GET` read (safe, idempotent), `POST` create/action, `PUT` replace (idempotent), `PATCH` partial update, `DELETE` remove (idempotent).
- **Safe and idempotent** (RFC 9110): safe means no side effects; idempotent means repeating has the same effect as once. Clients and proxies retry based on this.
- **Status codes**: 200 OK, 201 Created (+`Location`), 202 Accepted (async), 204 No Content, 400 malformed, 401 unauthenticated, 403 forbidden, 404 not found, 409 conflict, 412 precondition failed, 422 semantic validation, 429 rate limited, 5xx server fault.
- **Representations and content negotiation**: `Accept`, `Content-Type`; JSON by default.
- **Caching and concurrency**: `ETag` with `If-None-Match` (304) and `If-Match` (optimistic concurrency, 412).
- **Problem details**: RFC 9457 `application/problem+json` for errors.
- **HATEOAS**: hypermedia links in responses; rarely fully applied, but links for pagination and related resources are useful.
- **Contract**: OpenAPI document as source of truth for docs, validation and SDK generation.

## When to use / scenarios
- Public or partner APIs, browser/mobile backends, CRUD-heavy domains, anything benefiting from HTTP caching, tooling and universal client support.
- Prefer gRPC for internal low-latency service-to-service calls with strict schemas (see [[grpc-and-protobuf]]); GraphQL when many client types need flexible field selection (see [[graphql]]).
- Model non-CRUD actions as sub-resources or action endpoints: `POST /orders/123/cancel` or a `cancellation` resource; stay consistent.
- Long-running work: return `202 Accepted` with a status resource (`/jobs/9`) and optionally a webhook on completion (see [[webhooks]]).
- Do NOT leak database structure, nest more than two levels, or invent per-endpoint error formats.

## How it works / example
Resource design for orders:
```
GET    /v1/orders?status=open&limit=20      list (see pagination)
POST   /v1/orders                           create          -> 201 + Location: /v1/orders/123
GET    /v1/orders/123                       read            -> 200 + ETag
PATCH  /v1/orders/123                       partial update  (If-Match: "etag")
DELETE /v1/orders/123                       remove          -> 204
POST   /v1/orders/123/cancel                action          -> 200
```

Request and response:
```http
POST /v1/orders HTTP/1.1
Content-Type: application/json
Idempotency-Key: 7c9e6679-7425-40de-944b-e07fc1f90ae7

{"customer_id": 42, "items": [{"sku": "A1", "qty": 2}]}

HTTP/1.1 201 Created
Location: /v1/orders/123
Content-Type: application/json

{"id": 123, "status": "open", "total_cents": 1900, "created_at": "2026-10-10T09:30:00Z"}
```

Uniform error shape (RFC 9457):
```http
HTTP/1.1 422 Unprocessable Content
Content-Type: application/problem+json

{
  "type": "https://api.example.com/problems/validation",
  "title": "Validation failed",
  "status": 422,
  "detail": "qty must be positive",
  "errors": [{"field": "items[0].qty", "message": "must be > 0"}]
}
```

Idempotency for POST (Python/FastAPI sketch): store the key with the response; replay the stored response on a repeat.
```python
from fastapi import FastAPI, Header, HTTPException
app = FastAPI()
seen: dict[str, dict] = {}     # production: a table with UNIQUE(key) + TTL

@app.post("/v1/orders", status_code=201)
def create_order(body: dict, idempotency_key: str = Header(...)):
    if idempotency_key in seen:
        return seen[idempotency_key]
    order = {"id": len(seen) + 1, **body, "status": "open"}
    seen[idempotency_key] = order
    return order
```

Optimistic concurrency: client sends `If-Match: "v7"`; server returns `412 Precondition Failed` if the resource changed, preventing lost updates.

## Trade-offs
- **Strict REST vs pragmatic JSON-RPC-ish endpoints**: purity helps tooling and caching; action endpoints are clearer for business operations.
- **PUT vs PATCH**: PUT replaces the whole resource and is simple to reason about; PATCH saves bandwidth but needs a merge convention (JSON Merge Patch RFC 7396 or JSON Patch RFC 6902).
- **Embedding vs linking**: embedding related data reduces round trips; links keep payloads small. Offer `?expand=customer` for flexibility.
- **401 vs 404 on hidden resources**: returning 404 for resources a caller may not know exist avoids information leaks.
- **Coarse vs fine-grained endpoints**: chatty fine-grained APIs cost round trips; mega-endpoints get unwieldy.
- **Spec-first vs code-first OpenAPI**: spec-first gives agreement before implementation; code-first stays in sync automatically.

## Gotchas
- `200 OK` with `{"error": ...}` in the body breaks clients, monitoring and retries; use real status codes.
- Using `GET` for state changes allows crawlers, prefetchers and caches to trigger them.
- Returning different shapes for one resource in list vs detail makes SDKs painful; keep a consistent core shape.
- Floating-point money and ambiguous timestamps: use integer minor units and ISO 8601 UTC.
- Unbounded list endpoints take down the service; always paginate (see [[pagination-filtering-sorting]]).
- Breaking changes by renaming fields or changing types: plan versioning from day one (see [[api-versioning-and-evolution]]).
- Missing rate limits and request size limits (see [[rate-limiting]]); missing auth on every route, not just most.
- Exposing internal auto-increment IDs invites enumeration; authorise per object, not just per route (see [[owasp-top-10]]).
- Clients retry on timeouts: if POST is not idempotent, duplicates appear (see [[idempotency-and-exactly-once]]).

## Related
- [[api-versioning-and-evolution]] - how to change an API without breaking clients
- [[pagination-filtering-sorting]] - list endpoints conventions
- [[idempotency-and-exactly-once]] - safe retries for unsafe methods
- [[webhooks]] - async notifications complementing request/response
- [[grpc-and-protobuf]] - alternative for internal service calls
- [[rate-limiting]] - protecting the API under load and abuse

## References
- RFC 9110 HTTP Semantics: https://www.rfc-editor.org/rfc/rfc9110
- RFC 9457 Problem Details for HTTP APIs: https://www.rfc-editor.org/rfc/rfc9457
- OpenAPI Specification: https://spec.openapis.org/oas/latest.html
- Fielding, dissertation chapter 5 (REST).
- Google API Design Guide: https://cloud.google.com/apis/design
