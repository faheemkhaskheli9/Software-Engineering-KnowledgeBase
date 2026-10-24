---
title: Design a payment system
category: case-studies
tags: [payments, psp, ledger, double-entry, idempotency, reconciliation, stripe, case-study]
use_cases:
  - "design the backend that processes card payments for an e-commerce checkout"
  - "make payment requests safe to retry so customers are never charged twice"
  - "build an internal ledger with double-entry bookkeeping for wallets or marketplaces"
  - "reconcile our records against the payment provider's settlement files"
  - "handle payment-provider timeouts and webhooks that arrive late or out of order"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 2 (Alex Xu and Sahn Lam), ch. 'Payment System'"
  - https://stripe.com/blog/idempotency
  - https://docs.stripe.com/payments/payment-intents
  - https://www.pcisecuritystandards.org/
  - https://martinfowler.com/eaaDev/AccountingTransaction.html
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
---

# Design a payment system

## Summary
A payment system moves money on behalf of a merchant or platform: it takes a
customer's payment instrument, authorises and captures funds through a payment
service provider (PSP) or acquirer, records everything in an auditable ledger,
and reconciles with external statements. Unlike most designs, correctness
beats latency: no double charges, no lost money, a full audit trail, and clean
recovery from partial failures.

## Key concepts
- **Actors:** customer, merchant/platform, payment service provider (Stripe/Adyen-like), card networks, issuing and acquiring banks.
- **Pay-in vs pay-out:** collect from customers (pay-in) and disburse to sellers/drivers (pay-out).
- **Authorise then capture:** authorisation reserves funds; capture settles them (often at shipment). Refunds and chargebacks reverse flows.
- **Idempotency keys** make retried requests safe ([[idempotency-and-exactly-once]]).
- **Double-entry ledger:** every movement is two entries (debit and credit) that sum to zero; append-only, never update or delete.
- **Payment state machine:** created -> requires_action -> processing -> succeeded | failed | cancelled; refunds separate.
- **Reconciliation:** compare internal ledger to the PSP's settlement reports to catch mismatches.
- **PCI DSS scope:** never touch raw card numbers if you can avoid it; use hosted fields/tokenisation so card data goes straight to the PSP.
- **Eventual consistency with external systems:** PSP responses and webhooks are asynchronous.

## When to use / scenarios
Design applies to e-commerce checkout, subscription billing, marketplaces (split payments), wallets, ride/delivery
payments ([[design-ride-sharing]]). For most products integrate a PSP and focus on your order/payment state and ledger;
building direct acquirer integrations or a card vault is a regulated, specialist effort. Skip your own ledger for
trivial single-merchant stores where the PSP dashboard suffices.

## How it works / example

### 1. Requirements
Functional: create payment for an order; authorise/capture; support multiple methods (card, wallet, bank transfer);
refunds and partial refunds; webhooks from PSP; payouts to sellers; payment history, receipts; reconciliation reports.

Non-functional: **exactly-once effect** on money; strong consistency for the ledger; high availability on checkout; full
auditability; security and compliance (PCI DSS, strong customer authentication such as 3-D Secure, encryption,
fraud screening); tolerance of PSP outages; traceability of every state change.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 1 M payments/day -> about 12/s average, maybe 100/s at peak (sale events). Throughput is modest; the difficulty is correctness, not scale.
- Ledger: each payment creates a handful of entries (say 4-6) -> 5 M rows/day, roughly 1.8 B/year; at 200 B per row about 360 GB/year. Easily handled by a partitioned relational DB.
- PSP latency of 1-3 s per call is typical for card auth (assumption), so use timeouts and async completion flows.

### 3. API
```
POST /v1/payments                 Idempotency-Key: <uuid>
  { order_id, amount: 4999, currency: "USD", payment_method_token, capture: false }
  -> 201 { payment_id, status: "processing" | "requires_action" | "succeeded" }
GET  /v1/payments/{id}
POST /v1/payments/{id}/capture    { amount }
POST /v1/payments/{id}/refund     { amount, reason }   Idempotency-Key
POST /webhooks/psp                (signed by PSP; we verify and process)
```
Amounts are integers in minor units (cents), never floats. Currency stored beside every amount. See
[[rest-api-design]] and [[webhooks]].

### 4. Data model
```
payment(id, order_id, merchant_id, amount, currency, status, psp_ref, idempotency_key UNIQUE(merchant_id,key),
        version, created_at, updated_at)
payment_event(payment_id, seq, type, payload, ts)            -- append-only history
ledger_account(id, owner, type[asset|liability|revenue|fees], currency)
ledger_entry(id, txn_id, account_id, direction[debit|credit], amount, currency, created_at)  -- append-only
ledger_txn(id, payment_id, kind, created_at)                 -- entries in one txn must balance
idempotency_record(key, request_hash, response, status, expires_at)
reconciliation_item(psp_ref, psp_amount, our_amount, status)
```
Use a relational DB with serialisable or carefully chosen isolation for ledger writes ([[transactions-and-isolation-levels]],
[[sql-vs-nosql]]). Constraint: sum of debits equals sum of credits per `txn_id`, checked in code and asserted by a periodic audit job.
Never mutate ledger rows; correct with a reversing transaction.

### 5. High-level architecture
```
 browser/mobile --card data directly--> PSP hosted fields/SDK  (we only see a token)   [reduces PCI scope]
 client --> API gateway --> Payment service --> Payment DB (state + ledger, ACID)
                                  |  \--> PSP adapter(s) (auth/capture/refund) with timeouts + circuit breaker
                                  |
                       Outbox table --> Kafka "payment-events" --> Order service, Notification, Analytics, Fraud
 PSP --webhook--> Webhook receiver (verify signature, dedupe, enqueue) --> Payment service
 Daily: PSP settlement file --> Reconciliation job --> mismatches queue --> ops tooling
 Risk/fraud service (score before authorising)   Payout service (batch, ledger-backed)
```
See [[api-gateway-and-service-mesh]], [[message-queues-and-streams]], [[distributed-transactions-and-sagas]].

### 6. Deep dive A: idempotency and exactly-once effect
Networks fail after the PSP charged but before we recorded the result; clients retry. Defence in layers:
1. **Client idempotency key** (UUID per user intent). Server stores `(merchant, key) -> request hash, response`. On replay with the
   same key and same body return the stored response; with a different body return a 422/409.
2. **PSP idempotency key** derived from our payment ID so a retried PSP call cannot create a second charge (Stripe documents this pattern).
3. **Write intent first**: persist the payment as `processing` with its PSP idempotency key *before* calling the PSP. If we crash mid-call,
   a recovery job asks the PSP for the status by key/reference and completes the record, rather than blindly retrying.
4. **Unique constraint** on the idempotency key makes concurrent duplicates race to a single winner.

```python
def create_payment(req, key, db, psp):
    with db.tx():
        rec = db.get_idempotency(req.merchant, key)
        if rec: return rec.response if rec.request_hash == hash(req) else Conflict()
        pay = db.insert_payment(req, status="processing", psp_key=f"pay-{uuid4()}")
        db.insert_idempotency(req.merchant, key, hash(req), pending=True)
    try:
        r = psp.authorize(pay.amount, pay.currency, req.token, idempotency_key=pay.psp_key, timeout=10)
    except Timeout:
        return Accepted(pay.id)            # status unknown: resolved by webhook / poller, never re-charge
    with db.tx():
        db.update_payment(pay.id, status=r.status, psp_ref=r.id, expected_version=pay.version)
        db.post_ledger(pay, r)             # balanced entries
        db.outbox("payment.updated", pay.id)
    return Created(pay.id, r.status)
```
Treat timeouts as "unknown", never as "failed". Resolve unknowns by querying the PSP or waiting for the webhook.

### 7. Deep dive B: ledger and consistency
Double-entry example for a 49.99 USD card sale with a 1.75 fee (illustrative numbers):
```
Authorisation succeeded + captured:
  DEBIT  psp_receivable (asset)        49.99
  CREDIT merchant_payable (liability)  48.24
  CREDIT fee_revenue                    1.75
Payout to merchant later:
  DEBIT  merchant_payable              48.24
  CREDIT bank_cash (asset)             48.24
Refund: reverse entries as a new transaction, never edit old ones.
```
Atomicity: payment status update, ledger entries and the outbox event commit in **one local DB transaction** (transactional outbox),
and a relay publishes the event afterwards; this avoids the dual-write problem without distributed transactions. Cross-service
steps (reserve inventory, charge, ship) use sagas with compensations: refund/void on failure
([[distributed-transactions-and-sagas]]). Balances are derived (sum of entries) or kept as a checked cache; shard by account when
write hot spots on platform accounts appear (batch posting for high-volume accounts).

### 8. Deep dive C: webhooks, reconciliation and failure recovery
- **Webhooks** deliver asynchronous results (3DS completion, delayed bank transfers, disputes). Verify the signature, record the raw event with the PSP event ID
  (dedupe on it), respond 2xx fast, process async; handle out-of-order events by comparing state versions/timestamps rather than trusting arrival order
  ([[webhooks]], [[time-clocks-and-ordering]]).
- **Reconciliation:** a nightly job matches PSP settlement/report lines to `payment`/`ledger` by `psp_ref`; classify: matched, missing on our side, missing at PSP,
  amount mismatch. Alert, route to ops tooling, resolve via adjusting ledger transactions. This is the final safety net for all other bugs.
- **Poller for stuck payments:** payments in `processing` older than N minutes are re-queried at the PSP.
- **Fraud and risk:** score synchronously before auth (velocity, device, geography), step-up with 3-D Secure; keep rules outside the critical path with a fast fail-open/closed policy decided by risk appetite.
- **Multi-PSP routing:** route by cost/success rate and fail over on PSP outage; keep payment methods tokenised per PSP (portability needs token migration).

### 9. Scaling and failure handling
- Shard payments and ledger by merchant or account ID ([[partitioning-and-sharding]]); keep a txn's entries on one shard so it commits locally.
- Replicate the DB synchronously across zones for zero-loss failover ([[replication]], [[cap-and-pacelc]]: prefer consistency; during partitions fail payments rather than risk wrong balances).
- Circuit breakers, timeouts and bulkheads around PSP calls ([[resilience-patterns]]); queue non-urgent follow-ups.
- Security: tokenisation, TLS everywhere ([[cryptography-and-tls]]), secrets in vault ([[secrets-management]]), least privilege, audit logs, no card data in logs.
- Observability: auth success rate per PSP/BIN, stuck-payment count, reconciliation mismatch rate, webhook lag ([[observability-logs-metrics-traces]]).
- Retention and compliance: immutable audit trail, data residency, right-to-erasure vs financial record-keeping (keep financial records, minimise PII).

## Trade-offs
- Single PSP is simple; multiple PSPs add resilience and cost optimisation but duplicate integration, reconciliation and token handling.
- Sync response vs async completion: sync is simpler for the client but couples checkout latency to the PSP; async plus webhooks is robust but needs a pending-state UX.
- Authorise+capture separately gives control (ship before charge) but expires; immediate capture is simpler.
- Building a ledger gives control, audit and marketplace features; relying only on the PSP is cheaper for simple needs.
- Strict serialisable isolation is safest for balances but reduces throughput on hot accounts; use per-account partitioning and optimistic versioning.

## Gotchas
- Using floating point for money; store integer minor units plus currency (watch zero- and three-decimal currencies).
- Treating a timeout as failure and retrying with a new idempotency key: double charge.
- Updating or deleting ledger rows to "fix" things instead of appending a reversal.
- Dual writes (DB then message broker) without an outbox: lost or phantom events.
- Trusting webhook arrival order or accepting unsigned webhooks.
- Logging full PAN, CVV or tokens; CVV must never be stored at all under PCI DSS.
- Skipping reconciliation; silent drift accumulates.
- Refund exceeding captured amount through concurrent requests; guard with a conditional update on remaining refundable amount.
- Time zones in settlement cut-offs.

## Related
- [[idempotency-and-exactly-once]] - the core technique for safe retries
- [[distributed-transactions-and-sagas]] - orchestrating charge, inventory and shipping with compensations
- [[transactions-and-isolation-levels]] - ledger correctness inside the database
- [[webhooks]] - receiving and verifying asynchronous PSP events
- [[consistency-models]] - why the ledger demands strong consistency
- [[cryptography-and-tls]] - protecting card and token data
- [[design-ride-sharing]] - a payment consumer with pre-authorisation and payouts
- [[design-ticket-booking]] - a payment consumer where a seat hold must outlive checkout
- [[floating-point-and-money]] - exact amounts, rounding modes and allocation the ledger depends on

## References
- Alex Xu and Sahn Lam, *System Design Interview Vol. 2* (payment system chapter)
- Stripe, "Designing robust and predictable APIs with idempotency": https://stripe.com/blog/idempotency
- Stripe PaymentIntents docs: https://docs.stripe.com/payments/payment-intents
- Martin Fowler, "Accounting Transaction": https://martinfowler.com/eaaDev/AccountingTransaction.html
- PCI Security Standards Council: https://www.pcisecuritystandards.org/
