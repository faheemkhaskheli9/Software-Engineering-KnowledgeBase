---
title: Event-driven architecture
category: architecture
tags: [events, pub-sub, choreography, orchestration, outbox, async, eventual-consistency]
use_cases:
  - "decouple order placement from email, inventory and analytics so adding a consumer needs no change to the producer"
  - "react to changes in one service from several others without synchronous calls"
  - "publish database changes reliably to a message broker without losing or duplicating them"
  - "decide between choreography and orchestration for a multi-step workflow"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/articles/201701-event-driven.html
  - https://microservices.io/patterns/data/transactional-outbox.html
  - https://www.enterpriseintegrationpatterns.com/
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://www.oreilly.com/library/view/building-event-driven-microservices/9781492057888/
---

# Event-driven architecture

## Summary
In an event-driven architecture, components communicate by publishing events (facts about something that happened) to a broker, and interested components react asynchronously. Producers do not know their consumers, so you can add behavior without modifying the source. The price is eventual consistency, harder tracing, and a new class of failure: duplicate, lost, and out-of-order messages.

## Key concepts
- **Event vs command vs query.** Event: past-tense fact, many consumers (`OrderPlaced`). Command: request for one handler to do something (`ChargeCard`). Query: read request. Mixing them up produces hidden coupling.
- **Event notification** (thin: id only, consumers call back), **event-carried state transfer** (fat: consumers keep a local copy, no callback), **event sourcing** (events are the source of truth; see [[cqrs-and-event-sourcing]]).
- **Choreography.** Each service reacts to events and emits its own; no central coordinator. **Orchestration.** A coordinator (saga orchestrator, workflow engine) tells participants what to do. See [[distributed-transactions-and-sagas]].
- **Delivery semantics.** Brokers typically give at-least-once; consumers must be idempotent ([[idempotency-and-exactly-once]]).
- **Ordering.** Usually guaranteed only within a partition/key; choose the partition key per entity.
- **Transactional outbox.** Write the event to an outbox table in the same DB transaction as the state change; a relay publishes it. Solves the dual-write problem.
- **Schema evolution.** Events are a public contract; version them and prefer additive changes ([[api-versioning-and-evolution]]).

## When to use / scenarios
- One action triggers several independent side effects (notifications, search indexing, analytics, cache invalidation).
- Producers and consumers scale or fail independently; you need buffering for bursts ([[message-queues-and-streams]]).
- Integrating bounded contexts ([[domain-driven-design]]) without temporal coupling.
- Audit/streaming use cases where a durable log of facts is valuable.

When NOT:
- You need an immediate answer to the caller (validate this card now): use a synchronous call.
- Simple app with one database: a function call or in-process event bus is enough.
- Strict cross-entity consistency in a single step: use a local transaction.

## How it works / example
```
 Service A (orders)                         Broker                  Consumers
 +------------------+   1 tx: row + outbox   +---------+  OrderPlaced  +-> email
 | business tx      |---------------------->|  topic  |-------------->+-> inventory
 | outbox table     |   2 relay publishes    | orders  |               +-> analytics
 +------------------+------(poll/CDC)------->+---------+
```

Transactional outbox with an idempotent consumer (SQLite for a runnable demo):

```python
import json, sqlite3, uuid

db = sqlite3.connect(":memory:")
db.executescript("""
create table orders(id text primary key, total int);
create table outbox(id text primary key, topic text, payload text, sent int default 0);
create table processed(event_id text primary key);   -- consumer dedup
""")

def place_order(order_id: str, total: int) -> None:
    with db:                                           # ONE transaction
        db.execute("insert into orders values (?,?)", (order_id, total))
        evt = {"type": "OrderPlaced", "order_id": order_id, "total": total}
        db.execute("insert into outbox(id,topic,payload) values (?,?,?)",
                   (str(uuid.uuid4()), "orders", json.dumps(evt)))

def relay(publish) -> None:                            # run in a loop / CDC in prod
    rows = db.execute("select id, topic, payload from outbox where sent=0").fetchall()
    for event_id, topic, payload in rows:
        publish(topic, event_id, payload)              # may be retried => duplicates
        with db:
            db.execute("update outbox set sent=1 where id=?", (event_id,))

def consume(event_id: str, payload: str, handler) -> None:
    try:
        with db:                                       # dedup + effect atomically
            db.execute("insert into processed values (?)", (event_id,))
            handler(json.loads(payload))
    except sqlite3.IntegrityError:
        pass                                           # already processed

if __name__ == "__main__":
    seen = []
    place_order("o1", 500)
    relay(lambda t, i, p: (consume(i, p, seen.append), consume(i, p, seen.append)))  # duplicate delivery
    print(seen)    # handled exactly once despite two deliveries
```

Choreography vs orchestration quick guide: two or three steps with simple compensation, choreography; long workflows with branching, timeouts and visibility needs, orchestration (a state machine or workflow engine).

## Trade-offs
| Choice | Gains | Costs |
|---|---|---|
| Async events | Decoupling, resilience, buffering | Eventual consistency, harder debugging |
| Fat events | Consumers independent of producer | Larger payloads, schema coupling, stale copies |
| Thin events | Small, always-fresh data on callback | Callback load and runtime coupling |
| Choreography | No single point, easy to add steps | Business flow is implicit and scattered |
| Orchestration | Flow visible in one place | Coordinator becomes a coupling hot spot |
| Outbox + relay | No lost events | Extra table, relay operation, slight latency |

## Gotchas
- **Dual write:** saving to the DB and publishing to the broker as two steps will eventually lose or invent events. Use the outbox or CDC.
- **Duplicates and reordering** are normal. Idempotent consumers and version/sequence checks are mandatory.
- **Poison messages** block a partition; use retry with backoff and a dead-letter queue.
- **Hidden coupling:** consumers depending on exact payload fields turns events into a distributed API with no versioning discipline.
- **Event storms and cycles:** service A reacts to B which reacts to A. Draw the event flow.
- **Tracing:** propagate correlation IDs in headers ([[observability-logs-metrics-traces]]).
- **Read-your-writes:** a user may not see their change right after the write; design UI around it (optimistic UI, return the new state in the response).
- Treating the broker as a database: retention, compaction and replay limits differ from a store of record.

## Related
- [[change-data-capture]] - publishing the outbox (or row changes) from the database log.
- [[message-queues-and-streams]] - the broker technologies underneath.
- [[cqrs-and-event-sourcing]] - events as state and read-model projection.
- [[distributed-transactions-and-sagas]] - coordinating multi-service workflows.
- [[idempotency-and-exactly-once]] - making at-least-once safe.
- [[choosing-communication-style]] - sync vs async decision guide.
- [[webhooks]] - events pushed to external parties over HTTP.

## References
- Martin Fowler, "What do you mean by Event-Driven?" (martinfowler.com).
- Chris Richardson, "Transactional outbox" (microservices.io).
- Gregor Hohpe and Bobby Woolf, *Enterprise Integration Patterns*.
- Martin Kleppmann, *Designing Data-Intensive Applications*, ch. 11.
- Adam Bellemare, *Building Event-Driven Microservices*.
