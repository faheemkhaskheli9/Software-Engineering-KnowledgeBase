---
title: Idempotency and exactly-once processing
category: distributed-systems
tags: [idempotency, idempotency-key, exactly-once, at-least-once, deduplication, retries, outbox, kafka]
use_cases:
  - "stop a retried payment request from charging the customer twice"
  - "make a message consumer safe when the broker redelivers messages"
  - "design a POST endpoint that clients can safely retry after a timeout"
  - "explain whether Kafka exactly-once means our side effects happen once"
status: stable
last_verified: 2026-10-10
sources:
  - "Stripe API docs, Idempotent requests https://docs.stripe.com/api/idempotent_requests"
  - "IETF draft, The Idempotency-Key HTTP Header Field https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/"
  - "RFC 9110, HTTP Semantics, section 9.2.2 Idempotent Methods https://www.rfc-editor.org/rfc/rfc9110#name-idempotent-methods"
  - "Kafka documentation, Message delivery semantics https://kafka.apache.org/documentation/#semantics"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 11 and 12"
---

# Idempotency and exactly-once processing

## Summary
Networks lose requests and responses, so clients and brokers retry, and the same operation arrives more than once. An operation is idempotent when applying it many times has the same effect as applying it once. "Exactly-once delivery" is not achievable over an unreliable network; what you build is at-least-once delivery plus idempotent processing, which gives exactly-once *effects*.

## Key concepts
- **Delivery semantics**: at-most-once (no retry, may lose), at-least-once (retry, may duplicate), exactly-once (the effect happens once; achieved by dedup or atomic commit).
- **Idempotent by nature**: `PUT /users/7 {state}`, `DELETE`, "set balance = 10", upserts, `INSERT ... ON CONFLICT DO NOTHING`. Not idempotent: `POST /charges`, "increment counter", "append item".
- **Idempotency key**: a client-generated unique ID (UUID) sent with a non-idempotent request. The server stores key -> result and returns the stored result on repeats instead of re-executing.
- **Deduplication window**: how long keys are remembered (hours to days). Beyond it, a replay would be treated as new.
- **Inbox/processed-message table**: consumer records message IDs it handled, in the same transaction as the side effect.
- **Natural keys and conditional writes**: version checks (`WHERE version = n`), unique constraints and compare-and-set make duplicates harmless.
- **Exactly-once in Kafka**: idempotent producer (sequence numbers per partition) and transactions make read-process-write *within Kafka* atomic. Effects outside Kafka (HTTP calls, emails, a database) still need idempotency.
- **Outbox + idempotent consumer**: the standard end-to-end recipe ([[distributed-transactions-and-sagas]]).

## When to use / scenarios
- Any operation with money, inventory, emails/SMS, provisioning, or external side effects where a retry may follow a timeout.
- Public APIs where clients retry POST: accept an `Idempotency-Key` header.
- Queue/stream consumers (SQS, RabbitMQ, Kafka, Pub/Sub), webhooks receivers ([[webhooks]]), cron/job runners that may run twice, saga steps.
- Mobile/offline clients that resend queued actions.
- When NOT necessary: pure reads, naturally idempotent writes, or best-effort telemetry where duplicates are harmless.

## How it works / example

Request flow with an idempotency key:

```
 client: POST /payments  Idempotency-Key: 7f3c...   (timeout, no response seen)
 client: POST /payments  Idempotency-Key: 7f3c...   (retry, same key and same body)
 server: 1. INSERT key (status=IN_PROGRESS) -- unique constraint decides the winner
         2. winner executes; stores response; status=DONE
         3. loser / retry: key exists -> if DONE return stored response; if IN_PROGRESS return 409 or wait
         4. same key but different body -> reject (422), it is a client bug
```

Runnable sketch (swap the dict for a table with a UNIQUE key on Postgres/Redis `SET NX`):

```python
import hashlib, json, threading

class IdempotentService:
    def __init__(self):
        self.store, self.lock = {}, threading.Lock()   # ponytail: in-memory; use a UNIQUE-keyed table in prod
        self.charges = 0
    def charge(self, key: str, body: dict):
        fp = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.lock:
            rec = self.store.get(key)
            if rec:
                if rec["fp"] != fp: raise ValueError("key reused with different request")
                return rec["response"]                  # replay: same answer, no second charge
            self.charges += 1                           # the side effect, exactly once per key
            resp = {"charge_id": self.charges, "amount": body["amount"]}
            self.store[key] = {"fp": fp, "response": resp}
            return resp

svc = IdempotentService()
a = svc.charge("k1", {"amount": 500})
b = svc.charge("k1", {"amount": 500})      # client retry
assert a == b and svc.charges == 1
```

Consumer-side dedup in SQL, atomic with the effect:

```sql
BEGIN;
  INSERT INTO processed_messages (message_id) VALUES (:id);   -- PK; duplicate -> unique violation -> skip
  UPDATE accounts SET balance = balance + :amt WHERE id = :acct;
COMMIT;
```

Rules of thumb:
1. The key must be created by the caller before the first attempt and reused for every retry of that logical operation.
2. Check-then-act is a race; let a unique constraint or atomic `SET NX` arbitrate.
3. Store the response, not just "seen", so retries get the original outcome (including errors that are deterministic).
4. Pass the key downstream to third parties that support it (e.g. payment providers) or derive their key from yours.
5. Retries need backoff with jitter ([[resilience-patterns]]).

## Trade-offs
- **Storage and TTL**: remembering keys costs space; short windows risk late-duplicate effects. Choose from your clients' maximum retry horizon.
- **Where to dedupe**: at the API edge (simple, protects everything behind it) vs at each consumer (needed anyway for broker redelivery).
- **Stored response vs "already processed"**: full replay is friendlier to clients but needs larger records.
- **Conditional/version-based writes vs key tables**: conditional writes need no extra storage but only fit state-overwrite operations.
- **Broker "exactly-once" features** reduce duplicate handling in stream pipelines but couple you to the platform and stop at its boundary.

## Gotchas
- A timeout is not a failure: the first attempt may still be running or have succeeded. Concurrent retries need the IN_PROGRESS state handled (lock, wait, or 409).
- Keys generated server-side per attempt, or regenerated per retry, defeat the whole mechanism.
- Dedup check and side effect in different transactions leaves a crash window: charged but key not recorded, or the opposite. Co-locate them or order them so a crash is safe to retry.
- Same key with a different payload should be rejected, not silently replayed.
- Message IDs must be stable across redeliveries; broker-assigned delivery tags often change. Use a business ID or producer-assigned ID.
- At-least-once plus non-idempotent increments (`counter += 1`) overcounts. Use events with IDs and count distinct, or CRDT counters.
- HTTP method idempotency (PUT/DELETE) is a contract; verify your handler actually honours it, e.g. DELETE returning 404 on repeat is fine, but a PUT that appends is not.

## Related
- [[distributed-transactions-and-sagas]] - retried steps and the outbox/inbox pattern
- [[message-queues-and-streams]] - delivery guarantees and redelivery behaviour of brokers
- [[webhooks]] - receivers must dedupe repeated deliveries
- [[resilience-patterns]] - retries, backoff and jitter that create the duplicates
- [[rest-api-design]] - Idempotency-Key header and safe/idempotent HTTP methods
- [[design-payment-system]] - the canonical case for idempotency keys
- [[design-job-scheduler]] - at-least-once job runs made safe by idempotent jobs
- [[design-ticket-booking]] - idempotent holds and checkout under retries
- [[distributed-locks-and-leader-election]] - when to lock instead, and fencing tokens for the stale-holder case

## References
- Stripe API documentation on idempotent requests; IETF HTTPAPI Idempotency-Key draft.
- RFC 9110 section 9.2.2 (idempotent methods).
- Kafka documentation, message delivery semantics and transactions.
- Kleppmann, Designing Data-Intensive Applications, ch. 11-12 (end-to-end argument, exactly-once).
