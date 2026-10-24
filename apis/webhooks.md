---
title: Webhooks
category: apis
tags: [webhooks, callbacks, hmac, signatures, retries, idempotency, event-delivery, at-least-once]
use_cases:
  - "notify customers' servers when an order or payment changes state"
  - "receive and verify Stripe or GitHub style webhook events safely"
  - "retry failed webhook deliveries without flooding a broken endpoint"
  - "avoid processing the same webhook event twice"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.standardwebhooks.com/
  - https://docs.stripe.com/webhooks
  - https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
  - https://www.rfc-editor.org/rfc/rfc2104
---

# Webhooks

## Summary
A webhook is an HTTP callback: when something happens in system A, A sends an HTTP POST with an event payload to a URL registered by system B. It replaces polling with push notifications. Delivery is at-least-once over an unreliable network, so both sides must handle retries, duplicates, out-of-order events, and verify authenticity.

## Key concepts
- **Producer (sender)** stores subscriptions (URL, secret, event types), enqueues events, delivers with retries. **Consumer (receiver)** exposes an endpoint, verifies, acknowledges quickly, processes asynchronously.
- **Signature**: HMAC (RFC 2104) of the raw body (plus timestamp) with a per-endpoint secret, sent in a header; receiver recomputes and compares in constant time.
- **Replay protection**: include a timestamp in the signed content and reject old ones (for example older than 5 minutes).
- **Event id**: a unique id per event; receivers dedupe on it.
- **At-least-once delivery**: any 2xx is success; timeouts, 5xx and connection errors are retried; 4xx is typically permanent (410 may disable the endpoint).
- **Retry schedule**: exponential backoff with jitter over hours or days; then disable the endpoint and notify the owner.
- **Thin vs fat events**: thin events carry ids and the consumer fetches current state; fat events carry the full resource snapshot.
- **Ordering**: not guaranteed; include a version, sequence or timestamp so receivers can ignore stale events.
- Related spec: Standard Webhooks (headers `webhook-id`, `webhook-timestamp`, `webhook-signature`).

## When to use / scenarios
- Third parties need near-real-time notice of state changes: payments, shipments, repository pushes, form submissions.
- Long-running operations started through an API that complete later (see [[rest-api-design]], 202 Accepted pattern).
- Prefer polling for very low event volume or when the consumer cannot expose a public endpoint; prefer queues/streams for internal, high-throughput, ordered messaging (see [[message-queues-and-streams]]).
- Prefer SSE or WebSockets for live UI updates in a browser (see [[realtime-websockets-sse]]).
- Do NOT rely on webhooks as the only source of truth: provide a way to list or re-fetch events so consumers can reconcile missed ones.

## How it works / example
Flow:
```
event occurs -> producer writes event + delivery rows (same DB transaction, outbox)
             -> worker POSTs to each subscriber with signature
             -> 2xx: mark delivered | else: schedule retry (backoff + jitter) | give up: disable + alert
```

Sending a signed webhook (Python):
```python
import hmac, hashlib, json, time, uuid, requests

def send(url: str, secret: bytes, event_type: str, data: dict):
    msg_id = f"evt_{uuid.uuid4().hex}"
    ts = str(int(time.time()))
    body = json.dumps({"id": msg_id, "type": event_type, "created": ts, "data": data},
                      separators=(",", ":"))
    sig = hmac.new(secret, f"{msg_id}.{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return requests.post(url, data=body, timeout=10, headers={
        "Content-Type": "application/json",
        "Webhook-Id": msg_id, "Webhook-Timestamp": ts, "Webhook-Signature": f"v1,{sig}",
    })
```

Receiving: verify raw body, dedupe, enqueue, return 2xx fast (Python/FastAPI):
```python
import hmac, hashlib, time
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
SECRET = b"whsec_..."          # from a secrets manager, per endpoint
processed: set[str] = set()    # production: table with UNIQUE(event_id)

@app.post("/hooks/shop")
async def hook(request: Request):
    raw = await request.body()                     # verify the RAW bytes, not re-serialised JSON
    msg_id = request.headers["Webhook-Id"]
    ts = request.headers["Webhook-Timestamp"]
    if abs(time.time() - int(ts)) > 300:
        raise HTTPException(400, "timestamp too old")
    expected = hmac.new(SECRET, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    given = request.headers["Webhook-Signature"].removeprefix("v1,")
    if not hmac.compare_digest(expected, given):
        raise HTTPException(401, "bad signature")
    if msg_id in processed:
        return {"status": "duplicate"}              # still 2xx so the sender stops retrying
    processed.add(msg_id)
    # enqueue(raw) for a background worker; do the heavy work off the request path
    return {"status": "accepted"}
```

Backoff sketch for the sender: delays of roughly 1 min, 5 min, 30 min, 2 h, 8 h, 24 h with random jitter; stop after a documented window (for example 3 days) and surface failed deliveries in a dashboard with a manual "resend" button.

## Trade-offs
- **Push vs poll**: push is timely and cheap at low volume; polling is simpler for consumers and naturally rate-controlled.
- **Thin vs fat payloads**: thin avoids stale data and leaking sensitive fields, but forces a callback request; fat saves round trips but can arrive out of order and expands your contract.
- **Per-endpoint secret vs shared secret**: per-endpoint limits blast radius and allows rotation.
- **Strict retries vs endpoint protection**: aggressive retry floods struggling consumers; back off and disable.
- **Ordering guarantees**: per-resource ordering needs serialised delivery queues, at the cost of head-of-line blocking; usually send unordered with version fields.
- **Own it vs buy it**: services like Svix or Hookdeck handle delivery, retries and portals; building your own is straightforward but ongoing work.

## Gotchas
- Verifying a signature on parsed-then-re-serialised JSON fails; use the exact raw bytes.
- Using `==` instead of constant-time comparison leaks timing information.
- Doing slow work before responding causes timeouts, which cause retries, which cause duplicates.
- Returning 4xx/5xx for "already processed" events creates endless retry loops; return 2xx.
- SSRF: when users register arbitrary URLs, the sender can be pointed at internal addresses (cloud metadata IPs, localhost). Resolve and block private ranges, disallow redirects, enforce HTTPS and timeouts (see [[owasp-top-10]]).
- Secrets in URLs or logs: log event ids, not bodies containing PII; rotate secrets with an overlap period supporting two active secrets.
- Out-of-order delivery: "updated" arriving before "created" must not break the consumer.
- Missed events during consumer downtime: provide an events list API to backfill.
- Duplicate processing without idempotent handlers (see [[idempotency-and-exactly-once]]); dedupe with a unique constraint rather than an in-memory set.
- Enqueue webhook rows in the same transaction as the state change (outbox) so you never emit an event for a rolled-back change or lose one on a crash.

## Related
- [[idempotency-and-exactly-once]] - receivers must tolerate duplicates
- [[rest-api-design]] - webhooks complement request/response APIs for async results
- [[long-running-operations]] - the 202 + status-resource pattern webhooks often notify about
- [[message-queues-and-streams]] - internal equivalent with stronger ordering and consumer-pull semantics
- [[resilience-patterns]] - backoff, jitter, and circuit breaking for deliveries
- [[design-notification-system]] - delivery pipelines face the same retry and dedupe issues
- [[owasp-top-10]] - SSRF and signature verification pitfalls

## References
- Standard Webhooks specification: https://www.standardwebhooks.com/
- Stripe webhooks documentation: https://docs.stripe.com/webhooks
- GitHub webhook best practices: https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
- RFC 2104 HMAC: https://www.rfc-editor.org/rfc/rfc2104
