---
title: Background jobs and queues - choosing an approach
category: scenarios
tags: [background-jobs, task-queue, workers, celery, sqs, rabbitmq, kafka, cron, outbox, retries, decision-guide]
use_cases:
  - "move slow work (emails, PDFs, image processing) out of the web request"
  - "do we need a message broker or is a database job table enough"
  - "run scheduled jobs reliably on more than one server"
  - "retry failed jobs without running them twice"
  - "choose between Celery/RQ, SQS, RabbitMQ and Kafka for background work"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.postgresql.org/docs/current/sql-select.html
  - https://docs.celeryq.dev/en/stable/
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/
  - https://microservices.io/patterns/data/transactional-outbox.html
  - "Gregor Hohpe, Bobby Woolf, Enterprise Integration Patterns, 2003, ch. 4 'Messaging Channels' (Guaranteed Delivery, Dead Letter Channel) and ch. 10 'Messaging Endpoints' (Competing Consumers)"
  - "Martin Kleppmann, Designing Data-Intensive Applications (1st ed.), ch. 11 'Stream Processing'"
---

# Background jobs and queues - choosing an approach

## Summary
Anything the user does not need to wait for should leave the request path: accept the request, record the work durably, return, and let a worker do it. Start with the simplest durable queue you already operate (a job table in your database, or your framework's queue library on Redis), move to a managed queue or broker when volume, routing or isolation demands it, and use a log such as Kafka only when you need replay or many independent consumers. Whatever you pick, delivery is at-least-once, so every job must be idempotent and have a retry limit and a dead-letter destination.

## Key concepts
- **Job vs event.** A job is a command for one handler ("render invoice 42"); an event is a fact many consumers may react to ([[event-driven-architecture]]). Jobs fit queues; events fit pub/sub or logs.
- **Durability.** In-memory or fire-and-forget threads lose work on restart. A job must be persisted before the request returns.
- **Enqueue atomically with the state change.** Write the job (or an outbox row) in the same DB transaction as the business change, or a crash between the two loses or orphans it.
- **Leases / visibility timeouts.** A worker claims a job for a period; if it dies the job becomes visible again. Processing longer than the lease causes duplicates.
- **At-least-once + idempotency.** Retries and redeliveries happen; make the handler safe to repeat ([[idempotency-and-exactly-once]]).
- **Retry policy.** Exponential backoff with jitter, a maximum attempt count, then a dead-letter queue with alerting.
- **Scheduling.** Cron on one box is a single point of failure; on many boxes it runs N times. Use a scheduler that enqueues jobs with a uniqueness key, or a lock.

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Low volume, one app, already on Postgres | Job table claimed with `SELECT ... FOR UPDATE SKIP LOCKED` | [[message-queues-and-streams]], [[transactions-and-isolation-levels]] |
| Python/Ruby app, moderate volume, Redis available | Framework queue library (Celery, RQ, Sidekiq) | [[message-queues-and-streams]] |
| Cloud-native, want no broker to run | Managed queue (SQS, Cloud Tasks, Service Bus) | [[message-queues-and-streams]], [[serverless-architecture]] |
| Complex routing, priorities, per-message TTL | RabbitMQ | [[message-queues-and-streams]] |
| One event, many consumers, replay, stream processing | Log (Kafka-like) | [[message-queues-and-streams]], [[batch-and-stream-processing]] |
| Multi-step workflow with compensation, long waits | Saga orchestrator or a durable workflow engine | [[distributed-transactions-and-sagas]] |
| Outgoing calls to customers' URLs | Webhook delivery queue with per-endpoint retries | [[webhooks]] |
| Large inputs (videos, files) | Store the blob, enqueue a reference | [[blob-object-storage]], [[choosing-file-and-media-storage]] |
| Recurring jobs on several servers | Scheduler that enqueues with a dedupe key, or leader-elected scheduler | [[consensus-raft-paxos]], [[idempotency-and-exactly-once]] |
| Bursty load that must not hit the DB at once | Queue as a buffer, fixed worker concurrency | [[capacity-planning-and-autoscaling]], [[rate-limiting]] |

Decision flow:

```
Must the user wait for the result? yes -> keep it synchronous (make it faster)
No:
  Need replay or many independent consumers?        -> log (Kafka-like)
  Need routing/priorities/broker features?          -> RabbitMQ or managed equivalent
  Low volume, data already in Postgres?             -> DB job table (SKIP LOCKED)
  Otherwise                                         -> framework queue on Redis or a managed queue
Always: enqueue in the same transaction (or via outbox), idempotent handler,
        backoff + max attempts + DLQ, alert on queue age
```

When NOT to add a broker: a few jobs per minute in an app that already has a database; the job table is easier to observe, back up and query. When NOT to use the DB table: high job rates that contend with OLTP traffic, or many consumers needing fan-out.

## How it works / example
A durable job table with lease-based claiming and capped retries. Runnable with stdlib `sqlite3` (needs SQLite 3.35+ for `RETURNING`); in Postgres the claim subquery adds `FOR UPDATE SKIP LOCKED` so concurrent workers skip rows another worker holds.

```python
import sqlite3, time

db = sqlite3.connect(":memory:", isolation_level=None)
db.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY, kind TEXT, payload TEXT,
              status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
              run_after REAL DEFAULT 0, dedupe_key TEXT UNIQUE)""")
MAX_ATTEMPTS, LEASE = 3, 30.0

def enqueue(kind, payload, dedupe_key=None):
    # in the app: same transaction as the business write
    db.execute("INSERT OR IGNORE INTO jobs(kind, payload, dedupe_key) VALUES (?,?,?)",
               (kind, payload, dedupe_key))

def claim(now):
    # Postgres: ... WHERE id = (SELECT id ... ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
    return db.execute("""UPDATE jobs SET status='running', attempts=attempts+1, run_after=?
        WHERE id = (SELECT id FROM jobs WHERE status IN ('queued','running')
                    AND run_after <= ? AND attempts < ? ORDER BY id LIMIT 1)
        RETURNING id, kind, payload, attempts""", (now + LEASE, now, MAX_ATTEMPTS)).fetchone()

def finish(job_id, ok, attempts, now):
    if ok:
        db.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
    elif attempts >= MAX_ATTEMPTS:
        db.execute("UPDATE jobs SET status='dead' WHERE id=?", (job_id,))     # DLQ: alert here
    else:
        db.execute("UPDATE jobs SET status='queued', run_after=? WHERE id=?",
                   (now + 2 ** attempts, job_id))                             # backoff

if __name__ == "__main__":
    enqueue("email", "welcome:42", dedupe_key="welcome:42")
    enqueue("email", "welcome:42", dedupe_key="welcome:42")   # duplicate request ignored
    enqueue("pdf", "poison")
    now = time.time()
    for _ in range(10):
        job = claim(now)
        if job is None:
            now += 10; continue                                # wait out backoff
        job_id, kind, payload, attempts = job
        finish(job_id, payload != "poison", attempts, now)
    rows = dict(db.execute("SELECT payload, status FROM jobs"))
    assert rows == {"welcome:42": "done", "poison": "dead"}, rows
    print("ok")
```

A `running` row whose lease (`run_after`) has passed is claimable again, which is how a crashed worker's job gets retried; the handler must therefore be idempotent. A job that crashed on its last allowed attempt stays `running` with an expired lease; a periodic sweep marks those `dead`.

For the outbox variant (business row + outbox row in one transaction, a relay publishes to the broker) see [[event-driven-architecture]] and [[distributed-transactions-and-sagas]].

AI-specific angle: long-running LLM work (bulk summarisation, embedding backfills) is a background job too; provider batch APIs can replace your own worker fleet for offline workloads, see the AI Knowledge Base on [prompt caching and cost](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/prompt-caching-and-cost.md).

## Trade-offs
| Axis | DB job table | Queue library on Redis | Managed queue | Log (Kafka-like) |
|---|---|---|---|---|
| New infrastructure | None | Redis | Cloud service | Broker cluster or managed service |
| Enqueue atomic with business write | Yes (same DB) | Needs outbox | Needs outbox | Needs outbox |
| Fan-out / replay | No | Limited | Via topics/pub-sub | Yes |
| Observability | SQL queries | Library dashboards | Provider metrics | Consumer lag tooling |
| Load on primary DB | Yes | No | No | No |

- **Worker concurrency vs downstream limits:** more workers drain faster but can overload the DB or a rate-limited API; cap concurrency per job type.
- **Ordering vs throughput:** strict order needs one consumer per key; most jobs should not depend on order.
- **Separate queues per job type:** isolation stops slow reports from starving password-reset emails, at the cost of more queues to watch.

## Gotchas
- Enqueuing after commit in a separate call: a crash in between loses the job; enqueuing before commit runs jobs for rolled-back data.
- Handlers that are not idempotent: retries send two emails or charge twice.
- Lease or visibility timeout shorter than the job's run time gives parallel duplicate execution; heartbeat or extend it.
- No max attempts: a poison job retries forever and hides real failures.
- Alerting on queue depth only; alert on age of the oldest job, which is what users feel.
- Passing whole objects as payload: data goes stale between enqueue and run. Pass ids and reload.
- Cron jobs copied onto every server run N times.
- Large payloads in the broker; store the blob and pass a key.
- Jobs bypassing authorization because "it is internal"; check tenant and permissions when the job acts for a user ([[authorization-models]]).

## Related
- [[message-queues-and-streams]] - queue vs log, technology table, DLQ.
- [[idempotency-and-exactly-once]] - making retries safe.
- [[event-driven-architecture]] - events, outbox, fan-out.
- [[distributed-transactions-and-sagas]] - multi-step workflows.
- [[choosing-communication-style]] - when async beats a synchronous call.
- [[design-notification-system]] - queue-driven fan-out case study.
- [[design-job-scheduler]] - delayed and cron jobs at scale, case study.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- PostgreSQL documentation, `SELECT ... FOR UPDATE SKIP LOCKED` (The Locking Clause).
- Celery documentation, https://docs.celeryq.dev/en/stable/
- Amazon SQS Developer Guide (visibility timeout, dead-letter queues).
- Chris Richardson, "Transactional outbox" pattern, microservices.io.
- Hohpe and Woolf, *Enterprise Integration Patterns*, ch. 4 "Messaging Channels" and ch. 10 "Messaging Endpoints".
- Kleppmann, *Designing Data-Intensive Applications* (1st ed.), ch. 11 "Stream Processing".
