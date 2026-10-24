---
title: Distributed transactions and sagas
category: distributed-systems
tags: [saga, two-phase-commit, 2pc, outbox, compensation, orchestration, choreography, eventual-consistency]
use_cases:
  - "place an order that reserves inventory, charges a card and books shipping across three services"
  - "keep a database update and a published event consistent without losing either"
  - "roll back a multi-service workflow when the third step fails"
  - "decide whether to use 2PC, XA, or a saga for a cross-database business operation"
status: draft
last_verified: 2026-10-10
sources:
  - "Garcia-Molina and Salem, Sagas (SIGMOD 1987) https://dl.acm.org/doi/10.1145/38713.38742"
  - "Richardson, Microservices Patterns, ch. 4 (Managing transactions with sagas) https://microservices.io/patterns/data/saga.html"
  - "Richardson, Transactional outbox pattern https://microservices.io/patterns/data/transactional-outbox.html"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 7 and 9"
  - "Temporal documentation, workflows and sagas https://docs.temporal.io/"
---

# Distributed transactions and sagas

## Summary
When one business operation spans several databases or services, you cannot rely on a single ACID transaction. Two options: atomic commit protocols such as two-phase commit (strong, blocking, tightly coupled) or sagas (a sequence of local transactions with compensating actions, eventually consistent). Most microservice systems choose sagas plus the transactional outbox, and keep ACID inside each service.

## Key concepts
- **Two-phase commit (2PC)**: a coordinator asks all participants to *prepare* (vote yes, durably promising to commit), then tells everyone *commit* or *abort*. Atomic, but participants hold locks while in doubt and block if the coordinator dies. XA is the standard API.
- **Saga**: a workflow of local transactions T1..Tn, each with a compensating transaction C1..Cn-1 that semantically undoes it. If Tk fails, run C(k-1)..C1.
- **Orchestration**: a central orchestrator (state machine / workflow engine such as Temporal, AWS Step Functions, a hand-written process manager) calls each step and decides next or compensate. Explicit and debuggable.
- **Choreography**: services react to each other's events with no central brain. Loose coupling, but the flow is implicit and harder to follow as it grows.
- **Compensation is semantic, not rollback**: refund instead of "delete the charge"; the intermediate state was visible to others.
- **Pivot / retriable steps**: order steps as compensatable steps, then a pivot (point of no return), then retriable steps that must eventually succeed.
- **Transactional outbox**: write the business row and an "event to publish" row in the same local transaction; a relay publishes the outbox rows (polling or CDC). Fixes the dual-write problem.
- **Inbox / idempotent consumer**: dedupe incoming messages by ID so at-least-once delivery is safe ([[idempotency-and-exactly-once]]).
- **TCC (Try-Confirm-Cancel)**: reserve resources in Try, then Confirm or Cancel; saga variant with explicit reservations.

## When to use / scenarios
- Business flow across service or database boundaries where each service owns its data (checkout, booking, onboarding, order fulfilment): use a saga.
- "Update DB, then publish event" in one service: use the outbox, not a saga.
- 2PC/XA: a small number of trusted databases in one trust domain, short transactions, tolerance for coordinator-based blocking (some enterprise systems, distributed SQL databases implement it internally with consensus).
- Prefer avoiding the problem: model the aggregate so it fits in one service/database ([[domain-driven-design]]), or one shard ([[partitioning-and-sharding]]).
- When NOT to use sagas: when users cannot tolerate visible intermediate states (e.g. money visibly debited but order not yet placed) and no reservation model exists; or when strict isolation is needed across steps.

## How it works / example

Orchestrated order saga:

```
 Orchestrator
   1. Order.create(PENDING)           comp: Order.cancel
   2. Inventory.reserve               comp: Inventory.release
   3. Payment.charge   (pivot)        comp: Payment.refund
   4. Shipping.schedule (retriable)   no comp; retried until it succeeds
   5. Order.confirm
 failure at 3 -> run Inventory.release, Order.cancel (compensations in reverse order)
```

Minimal saga runner with persisted progress (in practice the log is a durable table or a workflow engine):

```python
class Saga:
    def __init__(self, steps):          # steps: [(action, compensation)]
        self.steps, self.done = steps, []
    def run(self, ctx):
        try:
            for action, comp in self.steps:
                action(ctx); self.done.append(comp)
        except Exception as e:
            for comp in reversed(self.done):
                comp(ctx)               # compensations must be idempotent and retried until success
            return f"aborted: {e}"
        return "ok"

log = []
def charge(ctx): raise RuntimeError("card declined")
saga = Saga([
    (lambda c: log.append("reserve"), lambda c: log.append("release")),
    (charge,                          lambda c: log.append("refund")),
])
assert saga.run({}) == "aborted: card declined"
assert log == ["reserve", "release"]     # charge never succeeded, so no refund; reservation undone
```

Transactional outbox (SQL sketch):

```sql
BEGIN;
  INSERT INTO orders (id, status) VALUES (:id, 'PENDING');
  INSERT INTO outbox (id, topic, payload) VALUES (:event_id, 'order.created', :json);
COMMIT;
-- relay: SELECT ... FROM outbox ORDER BY id; publish; mark sent (at-least-once)
-- or tail the WAL with CDC (Debezium)
```

Design checklist:
1. List the steps and, for each, its compensation and whether it is retriable.
2. Give every saga instance an ID and every step an idempotency key.
3. Persist saga state before and after each step; make the orchestrator resumable after crash.
4. Make compensations idempotent and never-failing in design; retry with backoff, alert after limits.
5. Add timeouts per step so stuck sagas get compensated.
6. Expose intermediate state explicitly (PENDING, RESERVED) to users and other services.

## Trade-offs
- **2PC vs saga**: 2PC gives atomicity and isolation but blocks, couples availability of all participants and is poorly supported across HTTP APIs and SaaS. Sagas scale and decouple but offer only eventual consistency and need compensation logic.
- **Orchestration vs choreography**: orchestration is easier to reason about, test and observe, with a central component; choreography has fewer moving parts for 2-3 steps but becomes a "distributed spaghetti" later.
- **Outbox via polling vs CDC**: polling is simple but adds latency and load; CDC is efficient but adds infrastructure.
- **Semantic locks / reservations** reduce anomalies from lack of isolation at the cost of modelling effort.

## Gotchas
- Dual writes (write DB then publish, or the reverse) lose or duplicate events on crash. Use the outbox.
- Compensation can fail too, and some actions cannot be undone (email sent, money wired). Place irreversible steps last or after the pivot.
- Lost isolation: other transactions see intermediate state, producing anomalies (dirty reads, lost updates). Mitigate with status fields, reservations, commutative updates, re-reading before acting.
- At-least-once messaging means every step can run twice; without idempotency a retry double-charges ([[idempotency-and-exactly-once]]).
- Orchestrator state must itself be durable and versioned; changing a running workflow's definition breaks in-flight instances (use workflow versioning features).
- Timeouts are ambiguous: a timed-out charge may have succeeded. Query or retry with the same key rather than assuming failure ([[failure-modes-and-fallacies]]).
- 2PC "heuristic" outcomes and in-doubt transactions can need manual resolution after crashes.

## Related
- [[idempotency-and-exactly-once]] - mandatory for retried saga steps and message consumers
- [[event-driven-architecture]] - choreographed sagas ride on events
- [[cqrs-and-event-sourcing]] - event-sourced aggregates pair naturally with sagas and outbox
- [[transactions-and-isolation-levels]] - what ACID inside one service gives you
- [[design-payment-system]] - worked example needing sagas, idempotency and reconciliation
- [[consensus-raft-paxos]] - how distributed SQL databases make cross-shard commit fault tolerant
- [[change-data-capture]] - publishing outbox rows from the database log
- [[durable-execution-and-workflow-engines]] - engines (Temporal, Step Functions) that run saga orchestrators durably with replay and timers

## References
- Garcia-Molina and Salem, Sagas (SIGMOD 1987).
- Richardson, Microservices Patterns (Manning 2018), saga and transactional outbox patterns.
- Kleppmann, Designing Data-Intensive Applications, ch. 7 and 9.
