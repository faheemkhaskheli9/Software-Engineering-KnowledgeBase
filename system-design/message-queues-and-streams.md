---
title: Message queues and streams
category: system-design
tags: [queue, stream, kafka, rabbitmq, sqs, pub-sub, async, backpressure, dead-letter]
use_cases:
  - "decouple a slow job (email, video transcode) from the request path with a background worker"
  - "fan out one event to several independent consumers"
  - "choose between RabbitMQ, SQS and Kafka for a new workload"
  - "handle poison messages, retries and duplicates in consumers"
status: draft
last_verified: 2026-10-10
sources:
  - https://kafka.apache.org/documentation/
  - https://www.rabbitmq.com/docs
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/
  - "Martin Kleppmann, Designing Data-Intensive Applications, ch. 11 Stream Processing"
  - "Gregor Hohpe, Bobby Woolf, Enterprise Integration Patterns, 2003"
---

# Message queues and streams

## Summary
Messaging systems move data asynchronously between producers and consumers.
A **queue** hands each message to one consumer and deletes it once acknowledged
(work distribution). A **log/stream** (Kafka, Kinesis, Pulsar) appends messages
to a durable, replayable, partitioned log that many consumer groups read
independently. Pick by the access pattern: task distribution vs event history.

## Key concepts
- **Producer / broker / consumer**; **topic** (stream name) and **queue** (single-consumer buffer).
- **Delivery semantics**: at-most-once (may lose), at-least-once (may duplicate; the practical default), exactly-once (only within a closed system, e.g. Kafka transactions; end-to-end needs idempotent consumers, see [[idempotency-and-exactly-once]]).
- **Acknowledgement**: consumer acks after processing; unacked messages are redelivered after a visibility timeout (SQS) or on channel close (RabbitMQ).
- **Partitions** (Kafka): a topic is split into ordered logs; ordering is guaranteed only within a partition; the message key chooses the partition. Parallelism = number of partitions per consumer group.
- **Consumer group**: consumers sharing a group split partitions; different groups each get all messages (pub/sub).
- **Offset**: position of a consumer in a log; replay by rewinding it.
- **Retention**: queues delete on ack; logs keep by time/size, enabling replay and reprocessing.
- **Dead-letter queue (DLQ)**: destination for messages failing after N attempts, for inspection.
- **Backpressure**: slow consumers cause lag; bounded queues and lag alerts expose it.
- **Outbox pattern**: write the event to a DB table in the same transaction as the state change, then relay it, avoiding dual-write inconsistency.

## When to use / scenarios
- Slow or unreliable work off the request path: emails, image/video processing, report generation, webhooks delivery ([[webhooks]]).
- Smoothing bursts: queue absorbs spikes, workers drain at a steady pace.
- Fan-out of domain events to many services ([[event-driven-architecture]]).
- Event log as integration backbone, CDC, analytics ingestion, stream processing ([[batch-and-stream-processing]]).
- Not for: request/response needing an immediate answer (use a synchronous call, see [[choosing-communication-style]]); tiny systems where a DB table plus a worker is enough.

## How it works / example

```
            +-- queue model (work distribution) --------------------+
 producer ->| [m1][m2][m3][m4] |--> worker A (m1,m3)  worker B (m2,m4)|  each msg once
            +--------------------------------------------------------+

            +-- log model (Kafka-style) ------------------------------+
 producer ->| P0: m0 m3 m6 ... |  group "billing": consumer1 <- P0,P1  |
 (key=user) | P1: m1 m4 m7 ... |  group "search" : consumer2 <- P0,P1,P2 (own offsets)
            | P2: m2 m5 m8 ... |                                       |
            +---------------------------------------------------------+
```

Choosing a technology:

| Need | Pick |
|---|---|
| Simple managed task queue, no ops | SQS (standard or FIFO), Cloud Tasks, Azure Service Bus |
| Rich routing (topic/fanout/headers), per-message TTL, priorities | RabbitMQ |
| High-throughput ordered event log, replay, many consumers, stream processing | Kafka (or Redpanda, Kinesis, Pulsar) |
| Small scale, already have Redis | Redis Streams / a library (RQ, Celery, Sidekiq) |
| Tiny scale, already have Postgres | `SELECT ... FOR UPDATE SKIP LOCKED` job table |

Idempotent at-least-once consumer (runnable sketch with an in-memory queue):

```python
import queue, uuid

q: "queue.Queue[dict]" = queue.Queue()
processed: set[str] = set()     # production: DB unique constraint / Redis SETNX
MAX_ATTEMPTS = 3

def handle(msg):
    if msg["id"] in processed:          # duplicate delivery -> no-op
        return
    if msg["body"] == "poison":
        raise ValueError("cannot process")
    processed.add(msg["id"])

def worker(dead_letters: list):
    while not q.empty():
        msg = q.get()
        try:
            handle(msg)
        except Exception:
            msg["attempts"] = msg.get("attempts", 0) + 1
            (q.put(msg) if msg["attempts"] < MAX_ATTEMPTS else dead_letters.append(msg))
        # ack == finishing without re-enqueue

if __name__ == "__main__":
    for body in ("a", "a", "poison"):
        q.put({"id": str(uuid.uuid4()) if body != "a" else "same", "body": body})
    dlq: list = []
    worker(dlq)
    assert len(dlq) == 1 and "same" in processed
```

Retry pattern: retry with exponential backoff and jitter via delay queues or
retry topics, then DLQ. Do not retry forever in place; it blocks a partition.

## Trade-offs
- **Queue vs log**: queues are simple and delete data; logs add replay, multiple independent consumers and ordering per key at the cost of partition management.
- **Ordering vs parallelism**: global order means one consumer; per-key order with partitions is the practical compromise. Choose the key carefully (hot key = hot partition).
- **At-least-once + idempotency vs exactly-once**: the former is portable and cheap; the latter is narrow in scope.
- **Sync vs async**: async improves resilience and throughput but adds eventual consistency, harder debugging and operational surface.
- **Managed vs self-hosted**: Kafka self-hosting is operationally heavy; managed offerings trade control for time.
- **Push vs pull**: pull (Kafka, SQS) lets consumers control rate; push (RabbitMQ with prefetch) lowers latency but needs a prefetch limit for backpressure.

## Gotchas
- Dual writes: updating the DB and publishing to a broker separately loses events on crash. Use the transactional outbox or CDC.
- Poison messages blocking a partition or looping forever; always have max attempts and a DLQ with alerting.
- Visibility timeout shorter than processing time causes duplicate parallel processing; extend it or heartbeat.
- Rebalancing storms in consumer groups when consumers are slow (long poll intervals); tune session/poll timeouts.
- Consumer lag unnoticed; alert on lag and oldest-message age, not only queue depth.
- Large payloads in the broker; store blobs in [[blob-object-storage]] and pass a reference.
- Schema evolution breaking old consumers; use a schema registry or versioned envelopes and additive changes ([[api-versioning-and-evolution]]).
- Assuming FIFO and exactly-once from a "FIFO" queue; read its actual guarantees and throughput caps.

## Related
- [[event-driven-architecture]] - architectural style built on these brokers.
- [[idempotency-and-exactly-once]] - making duplicate-tolerant consumers.
- [[distributed-transactions-and-sagas]] - orchestrating multi-step workflows over messages.
- [[batch-and-stream-processing]] - consuming logs for analytics and derived data.
- [[design-notification-system]] - queue-driven fan-out case study.
- [[webhooks]] - outbound async delivery with retries.

## References
- Apache Kafka docs: https://kafka.apache.org/documentation/
- RabbitMQ docs: https://www.rabbitmq.com/docs
- Amazon SQS developer guide: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/
- Kleppmann, *Designing Data-Intensive Applications*, ch. 11.
- Hohpe and Woolf, *Enterprise Integration Patterns*.
