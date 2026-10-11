---
title: Design a distributed job scheduler
category: case-studies
tags: [job-scheduler, cron, task-queue, leases, at-least-once, skip-locked, fencing-token, workflow, case-study]
use_cases:
  - "design a distributed cron that runs scheduled jobs exactly when due, once, across many machines"
  - "run delayed and recurring background jobs (emails, reports, billing runs) with retries"
  - "make sure a job is not run twice when a worker dies or a scheduler fails over"
  - "build a task queue on Postgres with leases and SKIP LOCKED instead of adding a broker"
  - "practice the job scheduler system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/distributed-periodic-scheduling/
  - https://queue.acm.org/detail.cfm?id=2745840
  - https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
  - https://www.postgresql.org/docs/current/sql-select.html
  - https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
  - https://docs.temporal.io/
---

# Design a distributed job scheduler

## Summary
A job scheduler stores job definitions (one-off at a time, delayed, or
recurring on a cron schedule), triggers each run when it is due, hands it to a
worker, retries failures and records the outcome. The hard parts are making
"exactly once" true enough (at-least-once execution plus idempotent jobs and
leases), surviving scheduler and worker crashes without losing or duplicating
runs, and keeping the "find due jobs" query cheap at millions of jobs.

## Key concepts
- **Job definition vs job run**: the definition holds schedule and payload; each firing creates a run row with its own state machine (`scheduled -> running -> succeeded | failed | retrying | dead`).
- **Lease (visibility timeout)**: a worker claims a run for a bounded time and must heartbeat; an expired lease means the run is handed to someone else.
- **At-least-once + idempotency**: a worker can crash after doing the work but before recording success, so the job may run again. Jobs must be idempotent or take an idempotency key ([[idempotency-and-exactly-once]]).
- **Fencing token**: a monotonically increasing number per claim so a zombie worker whose lease expired cannot overwrite the newer attempt's result (Kleppmann's distributed-locking post).
- **Leader election** for the trigger loop, so only one scheduler fires a given schedule ([[consensus-raft-paxos]]).
- **Misfire policy**: what to do with runs missed during downtime (run once now, run all, skip). Kubernetes CronJob exposes this as `startingDeadlineSeconds` and `concurrencyPolicy`.

## When to use / scenarios
- Periodic reports, billing runs, data exports, cleanup and retention sweeps.
- Delayed actions: "send reminder 24 h after signup", "cancel unpaid order after 15 min".
- Fan-out of many small async tasks with retries.
- Not for multi-step business processes with compensation and long waits: use a workflow engine (Temporal, Step Functions) or a saga ([[distributed-transactions-and-sagas]]).
- Not needed for a few jobs on one box: system cron or a single-process scheduler with a DB lock is enough. Say so.

## How it works / example

### 1. Requirements
Functional:
- Create/update/delete jobs: one-off at time T, delay, or cron expression with timezone.
- Execute on workers with per-job timeout, retry policy (max attempts, backoff) and concurrency policy (allow, forbid overlap).
- Query run history and status; manual trigger and cancel.

Non-functional:
- A due job starts within a few seconds of its time (seconds-level precision, not milliseconds).
- No lost runs once a job is accepted; duplicates possible but rare and harmless when jobs are idempotent.
- Scheduler and workers scale horizontally; no single box whose death stops all jobs.
- Isolation: one tenant's flood of jobs must not starve others.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 10 M job definitions, average 10 runs/day each -> 100 M runs/day -> about 1,200 runs/s average.
- Schedules cluster on round times (every hour at :00, midnight UTC): assume peaks of 20-50x average in the first seconds of the hour. This spike, not the average, sizes the system.
- Run row about 500 bytes -> 50 GB/day of history; keep 30 days hot (1.5 TB), archive the rest.

### 3. API
```
POST   /jobs        { name, schedule: "0 * * * *" | run_at | delay_s, tz, payload,
                      timeout_s, max_attempts, backoff, concurrency: "forbid"|"allow",
                      idempotency_key? }                     -> 201 { job_id }
GET    /jobs/{id}/runs?status=&cursor=                      -> paged run history
POST   /jobs/{id}:trigger                                   -> 202 { run_id }
DELETE /jobs/{id}                                           -> 204
worker API (internal): claim(n, lease_s) -> runs; heartbeat(run_id, token); complete(run_id, token, result)
```

### 4. Data model
```
jobs(job_id PK, tenant_id, schedule, tz, payload, policy..., next_fire_at, version)
runs(run_id PK, job_id, scheduled_for, state, attempt, lease_owner, lease_until,
     fence, result, error, created_at)
     UNIQUE (job_id, scheduled_for)           -- one run per firing, makes triggering idempotent
     INDEX (state, scheduled_for)             -- the due-work query
```
`UNIQUE(job_id, scheduled_for)` is the key trick: two schedulers that both try
to create the same firing get a constraint violation instead of a duplicate run.

### 5. High-level architecture
```
 API --> jobs DB (Postgres, partitioned by tenant/hash)
            ^   |
 trigger loop (leader-elected per partition): every second,
   SELECT jobs WHERE next_fire_at <= now  -> INSERT run (ON CONFLICT DO NOTHING),
   advance next_fire_at
            |
            v
 runs table (or a queue: Kafka/SQS) <-- workers claim with lease, heartbeat, complete
            |                                   |
     reaper: expired leases -> back to pending   +--> outcomes, metrics, dead-letter
```
For delays beyond the queue's native limit, keep the run in the DB and enqueue
only when due ([[message-queues-and-streams]]).

### 6. Deep dive A: claiming work safely
On Postgres, workers claim with `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n`,
so concurrent workers skip rows another transaction already holds instead of
blocking on them. The example below uses SQLite (no `SKIP LOCKED`), so it
claims with a conditional `UPDATE` instead; the lease and fence logic is the
same.

```python
import sqlite3

db = sqlite3.connect(":memory:")
db.execute("""CREATE TABLE runs(id INTEGER PRIMARY KEY, due REAL, state TEXT,
              owner TEXT, lease_until REAL, fence INTEGER DEFAULT 0, result TEXT)""")
db.executemany("INSERT INTO runs(due, state) VALUES (?, 'pending')", [(0,), (5,), (100,)])

def claim(worker, now, lease_s=30):
    """Claim one due run; an expired lease counts as claimable. Returns (id, fence) or None."""
    with db:
        row = db.execute("""SELECT id FROM runs WHERE due <= ? AND
                 (state='pending' OR (state='running' AND lease_until < ?))
                 ORDER BY due LIMIT 1""", (now, now)).fetchone()
        if not row:
            return None
        cur = db.execute("""UPDATE runs SET state='running', owner=?, lease_until=?, fence=fence+1
                 WHERE id=? AND (state='pending' OR (state='running' AND lease_until < ?))""",
                 (worker, now + lease_s, row[0], now))
        if cur.rowcount == 0:      # someone else won the race
            return None
        return row[0], db.execute("SELECT fence FROM runs WHERE id=?", row).fetchone()[0]

def complete(run_id, fence, result):
    with db:                       # only the current lease holder may finish the run
        cur = db.execute("UPDATE runs SET state='done', result=? WHERE id=? AND fence=? AND state='running'",
                         (result, run_id, fence))
        return cur.rowcount == 1

a = claim("w1", now=10)                    # w1 gets run 1
b = claim("w2", now=10)                    # w2 gets run 2, run 3 not yet due
assert a[0] == 1 and b[0] == 2 and claim("w3", now=10) is None
c = claim("w3", now=50)                    # w1's lease (until 40) expired: run 1 re-claimed
assert c == (1, 2)
assert not complete(1, a[1], "stale")      # zombie w1 is fenced off
assert complete(1, c[1], "ok")
```

### 7. Deep dive B: the trigger loop and time
- Partition jobs by hash; each partition has one leader (lease in etcd/ZooKeeper or a DB advisory lock) that scans `next_fire_at <= now` using the index. Failover is a new leader picking up the same partition; the unique constraint absorbs double-firing during the overlap.
- Compute `next_fire_at` from the cron expression in the job's timezone. DST transitions create skipped and repeated local times; decide and document behaviour (Google's SRE chapter discusses why distributed cron must be explicit about skipped and doubled runs).
- **Thundering herd at :00**: pre-materialise runs a few minutes ahead, add per-job jitter where the user allows it, and cap per-tenant concurrency.
- Use the DB or leader's clock, not each worker's, for due checks ([[time-clocks-and-ordering]]).

### 8. Deep dive C: retries, timeouts and dead letters
- Retry with exponential backoff and jitter by writing a new `scheduled_for` for the next attempt; after `max_attempts` move the run to `dead` and alert ([[resilience-patterns]]).
- Timeout: lease length >= job timeout; long jobs heartbeat to extend the lease.
- `concurrency=forbid`: before starting, check no other run of the job is `running`; with leases this is a soft guarantee, so jobs that must never overlap also take a fenced lock on the resource they modify.
- Results and logs go to object storage for big outputs; the run row keeps a pointer ([[blob-object-storage]]).

### 9. Scaling and failure handling
- **Scheduler crash**: leader lease expires, another node takes over; missed firings follow the misfire policy.
- **Worker crash**: lease expires, reaper or the next claim picks the run up; fencing stops the zombie.
- **DB as bottleneck**: partition `runs` by time and archive old partitions; move hot dispatch to a broker if claim QPS outgrows the DB, keeping the DB as the source of truth.
- **Fairness**: per-tenant queues or weighted claiming so one tenant's million jobs do not block others.
- **Monitoring**: schedule lag (start time minus scheduled time) p99, runs pending, retry and dead-letter rates, lease expiries.

## Trade-offs
- DB-backed queue (one system, transactional with your data, `SKIP LOCKED`) vs a broker (higher throughput, another system to run). Start with the DB at moderate scale.
- Exactly-once is not available end to end; choose at-least-once with idempotent jobs over at-most-once (which silently drops work) for almost everything.
- Short leases recover faster from crashes but cause more spurious re-runs of slow jobs; heartbeats resolve most of it.
- Precise firing time vs smoothing the :00 spike with jitter.

## Gotchas
- Two schedulers both firing the same cron because the leader lock is not fenced or the run has no unique key.
- Non-idempotent jobs (send email, charge card) running twice after a worker crash.
- Storing cron times in server local time; DST makes jobs run twice or never.
- Backlog after an outage: "run all missed" replays thousands of stale runs at once.
- Retrying a job forever because of a permanent error (bad payload): classify errors and dead-letter.
- Long-running jobs without heartbeats get re-claimed while still running.

## Related
- [[message-queues-and-streams]] - brokers, visibility timeouts and dead-letter queues
- [[idempotency-and-exactly-once]] - why at-least-once plus idempotent jobs is the target
- [[consensus-raft-paxos]] - leader election for the trigger loop
- [[distributed-transactions-and-sagas]] - when jobs turn into multi-step workflows
- [[time-clocks-and-ordering]] - clocks, timezones and fencing
- [[system-design-interview-framework]] - the procedure this case follows
- [[distributed-locks-and-leader-election]] - leases, fencing tokens and leader election for the trigger loop

## References
- Google SRE book, "Distributed Periodic Scheduling with Cron": https://sre.google/sre-book/distributed-periodic-scheduling/
- Stepan Davidovic and Kavita Guliani, "Reliable Cron across the Planet", ACM Queue 2015: https://queue.acm.org/detail.cfm?id=2745840
- Kubernetes CronJob (concurrencyPolicy, startingDeadlineSeconds): https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
- PostgreSQL SELECT, locking clause and SKIP LOCKED: https://www.postgresql.org/docs/current/sql-select.html
- Martin Kleppmann, "How to do distributed locking" (fencing tokens): https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
- Temporal documentation (durable workflows): https://docs.temporal.io/
