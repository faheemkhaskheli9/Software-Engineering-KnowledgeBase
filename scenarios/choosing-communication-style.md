---
title: Choosing a communication style
category: scenarios
tags: [rest, grpc, graphql, messaging, events, webhooks, websockets, sync-vs-async, decision-guide]
use_cases:
  - "how should our services talk to each other: REST, gRPC, or a message queue"
  - "choose between synchronous calls and asynchronous events for a workflow"
  - "pick an API style for a public API versus an internal one"
  - "push live updates to browsers: polling, SSE, or WebSockets"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.enterpriseintegrationpatterns.com/
  - https://grpc.io/docs/what-is-grpc/introduction/
  - https://graphql.org/learn/
  - https://martinfowler.com/articles/microservices.html
  - https://www.oreilly.com/library/view/building-microservices-2nd/9781492034018/
---

# Choosing a communication style

## Summary
Decide along two axes: does the caller need the answer now (synchronous request/response) or can work happen later (asynchronous messaging and events), and who are the consumers (public, internal, browsers)? Use REST for public and general APIs, gRPC for internal low-latency typed calls and streaming, GraphQL when many client types need flexible reads, queues/events when decoupling, buffering or fan-out matter, and webhooks, SSE or WebSockets to push to external systems or browsers.

## Key concepts
- **Temporal coupling.** Sync calls need both sides up at the same time; async via a broker removes that.
- **Request/response vs publish/subscribe.** Command to one handler vs fact broadcast to many ([[event-driven-architecture]]).
- **Contract style.** Resource-oriented HTTP+JSON, schema-first binary RPC (Protobuf), client-shaped queries, or message schemas.
- **Availability math.** A request chain with n synchronous dependencies multiplies their availabilities (n services at 99.9% each give about 0.999^n), so the chain is less available than any single hop; async cuts the chain.
- **Delivery semantics.** Sync: retry may duplicate. Async: usually at-least-once, so consumers must be idempotent ([[idempotency-and-exactly-once]]).
- **Direction.** Client pull (polling), server push (SSE, WebSocket, webhook).

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Public API, third-party developers, cacheable resources | REST over HTTP/JSON | [[rest-api-design]], [[api-versioning-and-evolution]], [[pagination-filtering-sorting]] |
| Internal service-to-service, strict typed contracts, low overhead, streaming | gRPC + Protobuf | [[grpc-and-protobuf]] |
| Mobile/web clients each need different shapes, avoid over/under-fetching | GraphQL (BFF or gateway) | [[graphql]] |
| Do work later, smooth bursts, retry independently | Message queue + workers | [[message-queues-and-streams]] |
| One fact, many independent reactions | Pub/sub events | [[event-driven-architecture]] |
| Replayable history, stream processing | Log-based stream | [[message-queues-and-streams]], [[batch-and-stream-processing]] |
| Notify customers' servers of changes | Webhooks | [[webhooks]] |
| Live updates one-way (feeds, notifications) | Server-Sent Events | [[realtime-websockets-sse]] |
| Bidirectional low-latency (chat, collaboration, games) | WebSockets | [[realtime-websockets-sse]], [[design-chat-system]] |
| Multi-step business transaction across services | Saga (orchestrated or choreographed) | [[distributed-transactions-and-sagas]] |
| Simple low-volume updates, no infra | Polling / long polling | [[realtime-websockets-sse]] |
| Edge concerns: auth, routing, throttling | API gateway / mesh in front | [[api-gateway-and-service-mesh]], [[rate-limiting]] |

Decision flow:

```
Caller needs the result to continue?
  yes -> sync:  public/3rd-party? -> REST   internal+typed/streaming? -> gRPC
                varied client shapes? -> GraphQL at the edge
  no  -> async: one consumer, task semantics -> queue (command)
                many consumers, facts        -> pub/sub (event)
                external party               -> webhook
Server must push to a browser? -> one-way SSE, two-way WebSocket
```

Rule of thumb for a workflow: keep the user-facing step synchronous and short, make everything the user need not wait for asynchronous.

## How it works / example
The same "place order" flow in two styles.

```
Synchronous chain (fragile, simple)
 client -> orders -> payments -> inventory -> email    (4 hops, any failure fails the request)

Hybrid (usual answer)
 client -> orders --sync--> payments       (needs the answer)
              | OrderPlaced event
              +--> inventory, email, analytics   (async, independent, retryable)
```

A runnable sketch contrasting an in-process sync call with an async hand-off through a queue, with a retry-safe consumer:

```python
import queue, threading

events: "queue.Queue[dict]" = queue.Queue()
done: set[str] = set()                       # idempotency record (a DB table in real life)
sent = []

def place_order(order_id: str) -> str:
    # synchronous part: validate + take payment would go here
    events.put({"id": f"evt-{order_id}", "type": "OrderPlaced", "order": order_id})
    return "accepted"                        # caller does not wait for email

def email_worker() -> None:
    while True:
        evt = events.get()
        if evt is None:
            break
        if evt["id"] in done:                # duplicate delivery is harmless
            continue
        sent.append(evt["order"])
        done.add(evt["id"])

if __name__ == "__main__":
    t = threading.Thread(target=email_worker); t.start()
    place_order("o1")
    events.put({"id": "evt-o1", "type": "OrderPlaced", "order": "o1"})   # simulated redelivery
    events.put(None); t.join()
    assert sent == ["o1"]; print("ok")
```

For sync calls add timeouts, retries with jitter and circuit breakers ([[resilience-patterns]]); give every command an idempotency key.

## Trade-offs
| Axis | Sync (REST/gRPC) | Async (queue/events) |
|---|---|---|
| Latency to result | Immediate | Eventual |
| Coupling | Runtime (availability, latency) | Contract (message schema) |
| Debuggability | Simple stack traces/trace IDs | Needs correlation and tracing |
| Backpressure | Caller sees errors/timeouts | Queue absorbs, grows lag |
| Consistency | Easier to reason about | Eventual, needs sagas/outbox |

- **REST vs gRPC:** REST wins on ubiquity, caching, browser support, debuggability; gRPC on strong typing, codegen, streaming, efficiency. Many systems use gRPC inside and REST at the edge.
- **GraphQL vs REST:** GraphQL moves complexity to the server (N+1, authorization per field, query cost limits) in exchange for client flexibility.
- **Queue vs log:** queues delete after consumption and suit task distribution; logs retain for replay and multiple independent consumers.
- **WebSocket vs SSE:** SSE is simpler (HTTP, auto-reconnect) for server-to-client; WebSocket needed for client-to-server streaming; both need sticky or stateful connection handling at scale.

## Gotchas
- **Distributed monolith by sync chains:** deep call graphs, shared deadlines, cascading failures.
- **Using a queue for request/response** (reply queues) reinvents RPC badly; use it when the caller truly does not wait.
- **Events that are really commands** (`SendEmail` published as an event) hide who is responsible.
- **Chatty fine-grained RPC** across a network; batch or coarsen APIs.
- **GraphQL exposed publicly without depth/cost limits** invites denial of service.
- **Webhook receivers** must verify signatures, dedupe and respond fast ([[webhooks]], [[owasp-top-10]]).
- **No timeouts:** default infinite timeouts turn slowness into outages.
- **Schema evolution neglected** for any style: Protobuf field numbers, event versions, REST deprecation ([[api-versioning-and-evolution]]).
- Choosing a protocol for fashion; match it to the requirement row above.

## Related
- [[rest-api-design]] - default public API style.
- [[grpc-and-protobuf]] - internal typed RPC.
- [[event-driven-architecture]] - async fan-out and outbox.
- [[realtime-websockets-sse]] - push to browsers.
- [[monolith-vs-microservices]] - determines how much inter-service communication exists at all.
- [[scenario-chooser]] - broader problem router.

## References
- Gregor Hohpe and Bobby Woolf, *Enterprise Integration Patterns*, ch. 2 "Integration Styles", ch. 4 "Messaging Channels" (point-to-point vs publish-subscribe) and ch. 5 "Message Construction" (command vs event messages).
- gRPC documentation (grpc.io); GraphQL documentation (graphql.org).
- Sam Newman, *Building Microservices*, 2nd ed., ch. 4 "Microservice Communication Styles".
- Martin Fowler, "Microservices" article on smart endpoints and dumb pipes.
