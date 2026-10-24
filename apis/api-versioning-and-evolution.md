---
title: API versioning and evolution
category: apis
tags: [versioning, backward-compatibility, deprecation, breaking-changes, semver, sunset, expand-contract]
use_cases:
  - "change a response field without breaking existing mobile app versions"
  - "decide between URL, header or date-based API versioning"
  - "deprecate and retire an old API version with notice to clients"
  - "detect breaking changes automatically in CI"
status: stable
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc8594
  - https://datatracker.ietf.org/doc/rfc9745/
  - https://cloud.google.com/apis/design/compatibility
  - https://stripe.com/blog/api-versioning
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 4"
---

# API versioning and evolution

## Summary
Once clients you do not control depend on your API, every change is a compatibility question. The best strategy is to evolve additively so versions are rarely needed, and to have an explicit, boring process (versioning scheme, deprecation signals, sunset dates, automated checks) for the changes that must break.

## Key concepts
- **Backward compatible (non-breaking)**: new optional request fields, new response fields, new endpoints, new optional query params, new enum values *if clients are told to tolerate unknown values*.
- **Breaking**: removing or renaming fields, changing types or meaning, making an optional field required, tightening validation, changing error codes, changing default behaviour or pagination order.
- **Robustness principle for clients**: ignore unknown fields (tolerant reader); for servers: accept only what you define, but do not break old requests.
- **Versioning schemes**: URL path (`/v2/orders`), header/media type (`Accept: application/vnd.example.v2+json`), date-pinned versions (`Stripe-Version: 2024-06-20`), query param, or no versions with strict additive evolution (GraphQL, protobuf).
- **Deprecation signals**: `Deprecation` header (RFC 9745), `Sunset` header (RFC 8594), `Link` to migration docs, changelog, emails.
- **Expand/contract** applies to APIs: add new alongside old, migrate clients, remove old (same idea as [[schema-migrations]]).
- **Contract testing and diffing**: tools compare OpenAPI or proto schemas to flag breaking changes.

## When to use / scenarios
- Public or partner APIs and mobile apps (old app versions live for years): version explicitly and support more than one at a time.
- Internal APIs deployed together: prefer coordinated additive changes and contract tests over formal versions (see [[integration-and-contract-testing]]).
- Renaming a field: add the new name, return both, deprecate the old, remove in the next major version.
- Behaviour change (e.g. pagination order, rounding): treat as breaking even when the schema is identical; gate behind a new version or opt-in flag.
- Do NOT create `v2` for every small change; a major version is a maintenance commitment (two code paths, two docs, two test suites).
- Do NOT version by "just changing it, clients will update".

## How it works / example
Strategy comparison:
```
URL path       /v2/orders                      visible, cacheable, easy to route and test; version applies to whole API
Header/media   Accept: ...vnd.example.v2+json  clean URLs; harder to try in a browser, easy to forget
Date-pinned    Example-Version: 2026-10-10     fine-grained; account pinned at first use, changelog per date (Stripe style)
Additive only  no version; fields only added   cheapest when you control clients or use GraphQL/protobuf
```

Additive change with a deprecation, expressed in the response:
```http
GET /v1/customers/42 HTTP/1.1

HTTP/1.1 200 OK
Deprecation: @1760000000
Sunset: Wed, 31 Dec 2026 23:59:59 GMT
Link: <https://docs.example.com/migrate-customer-name>; rel="deprecation"

{"id": 42, "name": "Ada Lovelace",          // deprecated: use display_name
 "display_name": "Ada Lovelace"}
```

Server-side compatibility layer (Python): keep one internal model, translate at the edge per version.
```python
def to_v1(order):  # old shape
    return {"id": order.id, "total": order.total_cents / 100}

def to_v2(order):  # new shape
    return {"id": order.id, "total": {"amount": order.total_cents, "currency": order.currency}}

SERIALIZERS = {"v1": to_v1, "v2": to_v2}

def render(order, version):
    return SERIALIZERS[version](order)
```
Keeping a single domain model and thin per-version adapters avoids forked business logic. Date-pinned versioning extends this: each dated change is a small transformation applied in sequence to bring the latest response down to the client's pinned version.

CI guard: run an OpenAPI diff tool (for example `oasdiff breaking old.yaml new.yaml`) or `buf breaking` for protobuf and fail the build on unapproved breaking changes (see [[ci-cd-pipelines]]).

Retirement process: announce, add Deprecation/Sunset headers, log which clients still call the old version (by API key/user agent), contact them directly, brown-out (short scheduled failures) near the date, then remove.

## Trade-offs
- **URL versions vs header versions**: URLs are discoverable and simple; headers keep resource identity stable. Most teams choose URL path for public REST APIs.
- **Few big majors vs many small dated versions**: majors are easier to explain; dated versions give smoother migration but need infrastructure.
- **Supporting old versions vs forcing upgrades**: long support protects customers but multiplies cost; define a written support window.
- **Strict validation vs leniency**: strict input validation catches bugs early but makes later tightening a breaking change; start lenient where safe and document it.
- **Unknown enum values**: adding enum members is breaking for clients with exhaustive switches unless the contract says clients must handle unknown values.

## Gotchas
- Changing error formats, status codes, rate-limit headers or field ordering is breaking for someone, even if undocumented. Hyrum's law: any observable behaviour will be depended on.
- Making an optional input field required, or adding a required field to a webhook payload schema, breaks existing integrations (see [[webhooks]]).
- Numeric type widening (int to string IDs) breaks typed clients; start with opaque string IDs.
- Shipping a new version without a data migration path leaves customers stranded between versions; versions share one database, so schema changes still follow expand/contract.
- Mobile clients cannot be force-updated quickly; keep old versions alive until measured traffic is near zero.
- Silent behaviour changes under the same version (e.g. fixing a bug someone depended on) still need a notice.
- Deprecation headers are ignored unless someone reads them; track usage per client and reach out.
- Do not couple your API versions to your internal service versions or database schema.

## Related
- [[rest-api-design]] - baseline conventions that make evolution easier
- [[grpc-and-protobuf]] - field numbers and reserved fields as built-in evolution rules
- [[graphql]] - additive schema with `@deprecated` instead of versions
- [[schema-migrations]] - the same expand/contract pattern for databases
- [[integration-and-contract-testing]] - automated detection of broken consumers
- [[library-api-design]] - semantic versioning and deprecation for in-process library APIs
- [[schema-evolution-and-serialization]] - compatibility rules for event and file schemas, with schema registries

## References
- RFC 8594 The Sunset HTTP Header Field: https://www.rfc-editor.org/rfc/rfc8594
- RFC 9745 The Deprecation HTTP Response Header Field: https://datatracker.ietf.org/doc/rfc9745/
- Google API compatibility guidance: https://cloud.google.com/apis/design/compatibility
- Stripe on API versioning: https://stripe.com/blog/api-versioning
- Kleppmann, Designing Data-Intensive Applications, chapter 4 (encoding and evolution).
