---
title: CQRS and event sourcing
category: architecture
tags: [cqrs, event-sourcing, read-model, projections, snapshots, audit-log]
use_cases:
  - "scale reads and writes independently because the read model needs different shape than the write model"
  - "keep a full audit history of every change to an account or order and replay it"
  - "build denormalized read views fed from a write model"
  - "decide whether event sourcing is worth it for our domain"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/bliki/CQRS.html
  - https://martinfowler.com/eaaDev/EventSourcing.html
  - https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs
  - https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing
  - https://www.oreilly.com/library/view/implementing-domain-driven-design/9780133039900/
---

# CQRS and event sourcing

## Summary
CQRS (Command Query Responsibility Segregation) separates the model that handles writes (commands) from the model(s) that serve reads (queries), so each can be shaped and scaled for its job. Event sourcing stores state as an append-only sequence of events instead of the current row; current state is derived by replaying them. They are independent patterns that combine well, but both add real complexity and should be adopted narrowly.

## Key concepts
- **Command**: intent to change state, may be rejected (`PlaceOrder`). **Query**: read-only, no side effects.
- **Simple CQRS**: same database, separate code paths and models for read and write. Cheap and often enough.
- **Full CQRS**: separate read store(s) (search index, document DB, denormalized tables) updated from the write side, usually asynchronously, giving eventual consistency.
- **Event store**: append-only log per aggregate (stream), with a version for optimistic concurrency.
- **Rehydration**: load events of a stream, fold them into current state: `state = fold(apply, initial, events)`.
- **Projection**: a consumer that folds events into a read model; can be rebuilt from scratch by replaying.
- **Snapshot**: periodic saved state so replay need not start at event zero.
- **Upcasting**: transform old event versions into the current schema on read.
- **Compensating event**: you never edit history; you append a correcting event (`PaymentRefunded`).

## When to use / scenarios
CQRS fits when:
- Read and write workloads differ sharply in shape or volume (many list/search views over a small write model).
- Complex domain where commands carry validation logic but queries want flat, joined data.
- Multiple read representations of the same data (UI list, search, analytics).

Event sourcing fits when:
- The history itself is a requirement: audit, finance, compliance, "what did this look like on March 3".
- Temporal queries, undo, replay to fix bugs or build new projections later.
- Naturally event-shaped domains (ledgers, order lifecycle, inventory movements).

When NOT:
- CRUD with trivial rules. A single model and ORM is cheaper ([[orm-and-n-plus-one]]).
- You cannot tolerate eventual consistency on reads and cannot hide it in UX.
- Team has no experience; this is among the easiest patterns to get wrong. Prefer an audit-log table (append change records beside normal state) when you only need history, not replay.
- GDPR-style deletion is a hard requirement and you have not planned crypto-shredding or data separation.

## How it works / example
```
 command --> [ handler ] --validate--> append events --> [ event store ]
                                                            |  publish
                                                            v
                                             [ projector ] --> read DB / search
 query  ---------------------------------------------------> read model
```

Minimal event-sourced account with projection:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Deposited:  amount: int
@dataclass(frozen=True)
class Withdrawn:  amount: int

class Account:
    def __init__(self):
        self.balance, self.version = 0, 0
    def apply(self, e) -> None:                 # pure state transition, never rejects
        if isinstance(e, Deposited): self.balance += e.amount
        elif isinstance(e, Withdrawn): self.balance -= e.amount
        self.version += 1
    # command handlers decide, then return NEW events
    def withdraw(self, amount: int):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        return [Withdrawn(amount)]

class EventStore:
    def __init__(self): self.streams = {}
    def load(self, sid): return list(self.streams.get(sid, []))
    def append(self, sid, events, expected_version: int):
        stream = self.streams.setdefault(sid, [])
        if len(stream) != expected_version:     # optimistic concurrency
            raise RuntimeError("concurrent modification")
        stream.extend(events)

def rehydrate(store, sid) -> Account:
    acc = Account()
    for e in store.load(sid): acc.apply(e)
    return acc

def balances_projection(store) -> dict:         # read model, rebuildable at any time
    return {sid: rehydrate(store, sid).balance for sid in store.streams}

if __name__ == "__main__":
    store = EventStore()
    store.append("a1", [Deposited(100)], expected_version=0)
    acc = rehydrate(store, "a1")
    store.append("a1", acc.withdraw(30), expected_version=acc.version)
    print(balances_projection(store))           # {'a1': 70}
```

Operational notes: keep command-side reads on the event store (strong consistency inside an aggregate); serve queries from projections; track each projector's last processed position so it can resume and be rebuilt.

## Trade-offs
- **Consistency vs scale:** async projections scale reads but a user may not see their own write immediately. Mitigate with returning the result in the command response, version-aware reads, or optimistic UI.
- **History vs complexity:** you gain audit and replay, you lose simple ad-hoc SQL on current state and take on event versioning forever.
- **Rebuild power vs cost:** replaying millions of events is slow; plan snapshots and parallel projectors.
- **Event store choices:** a relational table with `(stream_id, version)` unique key is a fine start; dedicated stores or Kafka-like logs help at scale but Kafka alone is a weak fit for per-aggregate optimistic concurrency.
- **Granularity:** fine events (`ItemAdded`) preserve intent; coarse snapshots-as-events lose it.

## Gotchas
- **Events are forever.** A badly named or modeled event persists; schema changes need upcasters and discipline ([[api-versioning-and-evolution]]).
- **Do not put commands behind event handlers' side effects:** replaying a projection must not resend emails or charge cards. Separate pure projections from reactions.
- **Eventual consistency leaks into UX** and into validation that spans aggregates; see [[distributed-transactions-and-sagas]].
- **Projection bugs** are fixed by rebuild, which needs spare capacity and a swap strategy (build new, cut over).
- **Using event sourcing as integration bus:** internal domain events differ from published integration events; map between them ([[event-driven-architecture]]).
- **Deleting personal data** from an immutable log: design for it up front.
- **CQRS everywhere:** applying it to every module multiplies code. Use it per bounded context where it pays.

## Related
- [[event-driven-architecture]] - broker, outbox and delivery issues shared by projections.
- [[domain-driven-design]] - aggregates define the stream boundaries.
- [[consistency-models]] - what read-after-write guarantees you actually give.
- [[idempotency-and-exactly-once]] - projectors must tolerate replays.
- [[data-modeling-and-schema-design]] - shaping read models.
- [[message-queues-and-streams]] - log-based infrastructure for projections.
- [[audit-logs-and-temporal-data]] - lighter options when you need history and audit, not a full event-sourced model.

## References
- Martin Fowler, "CQRS" and "Event Sourcing".
- Microsoft Azure Architecture Center, CQRS and Event Sourcing patterns.
- Greg Young, "CQRS Documents" and talks on event sourcing.
- Vaughn Vernon, *Implementing Domain-Driven Design*, chapters on events.
