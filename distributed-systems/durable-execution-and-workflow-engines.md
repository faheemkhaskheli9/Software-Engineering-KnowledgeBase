---
title: Durable execution and workflow engines
category: distributed-systems
tags: [durable-execution, workflow-engine, orchestration, temporal, step-functions, durable-functions, event-history, replay, determinism, durable-timers, long-running-process]
use_cases:
  - "a multi-step business process (order, onboarding, refund) must survive worker crashes and deploys without losing its place"
  - "wait days for a human approval or a timeout without holding a thread or a cron job"
  - "replace a tangle of queues, status columns and retry cron jobs with one readable workflow"
  - "choose between a hand-written job table, a saga orchestrator and a workflow engine such as Temporal or Step Functions"
  - "deploy a new version of workflow code while old runs are still in flight"
status: draft
last_verified: 2026-10-24
sources:
  - https://docs.temporal.io/workflows
  - https://docs.temporal.io/activities
  - https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html
  - https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-code-constraints
  - "Hector Garcia-Molina and Kenneth Salem, Sagas, SIGMOD 1987"
---

# Durable execution and workflow engines

## Summary
Durable execution makes a multi-step function survive crashes: every step's
result is recorded in a durable history, and after a failure the function is
re-run from the top with recorded results replayed instead of re-executed, so
it continues exactly where it stopped. Workflow engines (Temporal, Cadence,
AWS Step Functions, Azure Durable Functions, Restate and similar) package this
with retries, durable timers that can wait for days, signals from outside and
visibility into every run. Use one when a business process spans many steps,
services and long waits, and the alternative is a hand-built web of queues,
status columns and cron jobs.

## Key concepts
- **Workflow vs activity (step)**: the workflow is orchestration code that
  decides what happens next; activities are the side-effecting calls (charge a
  card, send an email, call an API). The engine records each activity's result
  in the workflow's **event history**.
- **Replay**: to resume, the engine re-runs the workflow code from the start;
  when the code asks for an activity whose result is already in the history,
  it gets the recorded result instead of running it again. State lives in the
  history, not in a process.
- **Determinism**: because of replay, workflow code must make the same
  decisions every time it runs over the same history. No wall-clock reads,
  random numbers, direct I/O, threads or iteration over unordered data inside
  the workflow; use the engine's APIs for time, randomness, IDs and side
  effects. Azure Durable Functions and Temporal document this constraint
  explicitly.
- **Activities are at-least-once**: a worker can die after an activity's side
  effect but before its result is recorded, and the activity then runs again.
  Every activity must be idempotent, usually by passing an idempotency key
  derived from the workflow ID and step ([[idempotency-and-exactly-once]]).
- **Retry policies and timeouts per activity**: initial interval, backoff
  coefficient, maximum attempts and non-retryable error types are declared,
  not hand-coded. Timeouts distinguish "waiting to start" from "running too
  long" and "stopped heartbeating".
- **Durable timers**: `sleep(3 days)` is recorded as a timer event; no thread
  or process waits. The engine wakes the workflow when the timer fires.
- **Signals and queries**: external events (an approval, a cancellation) are
  delivered to a running workflow as history events; queries read its state.
- **Versioning**: changing workflow code while runs are in flight can make a
  replay take a different path from its history, which the engine detects as
  a non-determinism error. Engines provide patch or version markers, or you
  route new runs to new worker versions and let old ones drain.
- **History size**: every event is kept, so very long or looping workflows
  periodically restart themselves with fresh history (Temporal's
  Continue-As-New) instead of growing forever.
- **Code-first vs definition-first**: Temporal, Cadence, Durable Functions and
  Restate let you write workflows as ordinary code; Step Functions uses a JSON
  state-machine definition (Amazon States Language) with Standard workflows
  for long-running, exactly-once state transitions and Express workflows for
  short, high-rate, at-least-once runs.

## When to use / scenarios
- A process with several steps across services that must finish or be
  compensated: order fulfilment, account onboarding, refunds, KYC, data
  pipelines with external calls ([[distributed-transactions-and-sagas]]).
- Long waits inside a process: approval within 7 days, retry the payment in
  3 days, send a reminder if the user has not confirmed.
- Retry and timeout logic is scattered across consumers, a status column and
  a cron sweeper, and nobody can say where a given order is stuck.
- Infrastructure automation with many slow, failure-prone API calls
  (provisioning, migrations across many tenants).
- When NOT to use it: one-step background jobs (a queue with retries and a
  dead-letter queue is enough, [[background-jobs-and-queues]]); delayed or
  recurring single jobs ([[design-job-scheduler]]); high-rate stream
  processing ([[batch-and-stream-processing]]); a lifecycle that is just a few
  transitions on one row in your own database (a state machine with
  conditional updates, [[state-machines]]).

## How it works / example

```
workflow code            engine history (durable)          workers
-------------            ------------------------          -------
charge(order)   ───────> 1 activity charge  = ok  <─────── run charge
sleep(1 day)    ───────> 2 timer   wake_at  = T+1d         (no thread waits)
                    ...crash, deploy, a day passes...
replay from top:
charge(order)   <─────── 1 recorded: ok       (not re-run)
sleep(1 day)    <─────── 2 timer fired
ship(order)     ───────> 3 activity ship    = ok  <─────── run ship
```

A minimal durable-execution engine on SQLite: activities are recorded,
timers suspend the workflow instead of blocking, a crash mid-activity is
recovered by replay, the re-run activity is deduplicated by its idempotency
key, and changed workflow code is caught as non-determinism.

```python
import json
import sqlite3

class Suspended(Exception):
    """The workflow is waiting on a timer; a scheduler resumes it later."""

class NonDeterminismError(Exception):
    pass

class Engine:
    def __init__(self, db, clock):
        self.db, self.clock = db, clock
        db.execute("CREATE TABLE IF NOT EXISTS history (wf TEXT, seq INTEGER,"
                   " kind TEXT, name TEXT, result TEXT, PRIMARY KEY (wf, seq))")
        db.execute("CREATE TABLE IF NOT EXISTS runs (wf TEXT PRIMARY KEY,"
                   " status TEXT, result TEXT)")

    def run(self, wf_id, workflow, *args):
        row = self.db.execute("SELECT status, result FROM runs WHERE wf = ?",
                              (wf_id,)).fetchone()
        if row and row[0] == "completed":
            return "completed", json.loads(row[1])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO runs VALUES (?, 'running', NULL)",
                            (wf_id,))
        try:
            result = workflow(Context(self, wf_id), *args)
        except Suspended:
            return "suspended", None
        with self.db:
            self.db.execute("UPDATE runs SET status = 'completed', result = ?"
                            " WHERE wf = ?", (json.dumps(result), wf_id))
        return "completed", result

class Context:
    def __init__(self, engine, wf_id):
        self.engine, self.wf, self.seq = engine, wf_id, 0
        rows = engine.db.execute("SELECT seq, kind, name, result FROM history"
                                 " WHERE wf = ?", (wf_id,))
        self.history = {s: (k, n, r) for s, k, n, r in rows}

    def _next(self, kind, name):
        seq, self.seq = self.seq, self.seq + 1
        if seq in self.history:
            if self.history[seq][:2] != (kind, name):
                raise NonDeterminismError(
                    f"{self.wf} step {seq}: history has {self.history[seq][:2]},"
                    f" code asked for {(kind, name)}")
            return seq, json.loads(self.history[seq][2])
        return seq, None

    def _record(self, seq, kind, name, value):
        with self.engine.db:
            self.engine.db.execute("INSERT INTO history VALUES (?, ?, ?, ?, ?)",
                                   (self.wf, seq, kind, name, json.dumps(value)))

    def activity(self, fn, *args):
        seq, recorded = self._next("activity", fn.__name__)
        if seq in self.history:
            return recorded                      # replay: do not run again
        result = fn(*args, idempotency_key=f"{self.wf}:{seq}")
        self._record(seq, "activity", fn.__name__, result)
        return result

    def sleep(self, seconds):
        seq, wake_at = self._next("timer", "sleep")
        if seq not in self.history:
            wake_at = self.engine.clock() + seconds   # engine time, not the OS
            self._record(seq, "timer", "sleep", wake_at)
        if self.engine.clock() < wake_at:
            raise Suspended()

# --- fake external services: side effects we must not repeat ---------------
calls, shipped_keys = [], set()
crash_in_ship = {"on": False}

def charge(order, idempotency_key):
    calls.append("charge")
    return {"charge_id": "ch_" + order}

def ship(order, idempotency_key):
    calls.append("ship")
    shipped_keys.add(idempotency_key)        # the carrier dedups by key
    if crash_in_ship["on"]:
        crash_in_ship["on"] = False
        raise SystemExit("worker killed after the side effect, before recording")
    return {"tracking": "trk_" + order}

def email(order, idempotency_key):
    calls.append("email")
    return True

def fulfil_v1(ctx, order):
    payment = ctx.activity(charge, order)
    ctx.sleep(86_400)                        # wait a day for the shipping window
    parcel = ctx.activity(ship, order)
    ctx.activity(email, order)
    return {"order": order, **payment, **parcel}

now = {"t": 0}
engine = Engine(sqlite3.connect(":memory:"), clock=lambda: now["t"])

assert engine.run("order-1", fulfil_v1, "o1") == ("suspended", None)
now["t"] = 3_600                             # an hour later: still waiting
assert engine.run("order-1", fulfil_v1, "o1") == ("suspended", None)
assert calls == ["charge"]                   # replay did not charge again

now["t"] = 86_400
crash_in_ship["on"] = True
try:
    engine.run("order-1", fulfil_v1, "o1")
except SystemExit:
    pass                                     # worker died mid-activity

status, result = engine.run("order-1", fulfil_v1, "o1")   # another worker resumes
assert status == "completed" and result["tracking"] == "trk_o1"
assert calls == ["charge", "ship", "ship", "email"]       # ship ran twice...
assert shipped_keys == {"order-1:2"}                       # ...but one shipment

# Changing workflow code under an in-flight run breaks replay.
now["t"] = 0
assert engine.run("order-2", fulfil_v1, "o2")[0] == "suspended"

def fulfil_v2(ctx, order):
    ctx.activity(email, order)               # new first step inserted
    return fulfil_v1(ctx, order)

try:
    engine.run("order-2", fulfil_v2, "o2")
    raise AssertionError("expected non-determinism")
except NonDeterminismError as e:
    print("caught:", e)
print("history replayed, crash recovered, calls =", calls)
```

The same workflow in Temporal's Python SDK is ordinary async code; the engine
supplies replay, retries and timers (fragment, needs a Temporal server):

```python fragment
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn
class Fulfil:
    @workflow.run
    async def run(self, order: str) -> str:
        opts = dict(start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=5))
        await workflow.execute_activity("charge", order, **opts)
        await workflow.sleep(timedelta(days=1))      # durable timer
        return await workflow.execute_activity("ship", order, **opts)
```

## Trade-offs
- **Workflow engine vs hand-rolled state**: a job table plus a status column
  and a sweeper is transparent and transactional with your data, and enough
  for one or two steps. An engine pays off when steps, waits and retry rules
  multiply, at the cost of running (or buying) another critical system and
  learning its determinism rules.
- **Code-first vs JSON/visual definitions**: code workflows are testable,
  refactorable and expressive but hide the shape of the process in code;
  state-machine definitions (Step Functions, BPMN) are diagrammable and
  reviewable by non-engineers but get verbose for loops and branching.
- **Orchestration vs choreography**: an orchestrating workflow makes the
  process explicit and debuggable in one place but is a central dependency
  that knows every service; event choreography keeps services independent but
  makes "where is order 42?" hard to answer ([[event-driven-architecture]]).
- **Self-hosted vs managed**: self-hosting needs a database, the engine
  cluster and upgrades; managed services trade that for cost per action or
  state transition and provider lock-in on workflow definitions.
- **Granularity of activities**: many small activities give precise retries
  and visibility but grow history and latency; few large ones repeat more
  work after a failure.

## Gotchas
- `datetime.now()`, `random`, `uuid4()` or an HTTP call directly in workflow
  code: works in tests, then fails or forks on replay. Use the engine's time,
  random and side-effect APIs.
- Non-idempotent activities: the engine guarantees the workflow advances, not
  that each side effect happens once. Pass an idempotency key derived from
  workflow ID and step.
- Deploying changed workflow code without versioning: in-flight runs replay
  into the new code and fail with non-determinism errors, often days later
  when their timers fire.
- Large payloads in activity inputs and results: they are stored in history
  on every step. Store blobs elsewhere and pass references
  ([[blob-object-storage]]).
- Unbounded loops in one run (a subscription that "runs forever"): history
  grows until limits are hit. Continue as a new run periodically.
- Retrying non-retryable errors (validation failure, card declined) with the
  default policy: mark them non-retryable and handle them as business
  outcomes, often with compensation ([[distributed-transactions-and-sagas]]).
- Treating the engine as a queue for high-volume, single-step jobs: the
  per-step bookkeeping costs far more than a plain queue.
- Workflow IDs chosen at random: starting the same business process twice
  creates two runs. Use a business key (order ID) as the workflow ID so
  duplicate starts are rejected.

## Related
- [[distributed-transactions-and-sagas]] - compensation logic that workflow engines usually orchestrate.
- [[idempotency-and-exactly-once]] - activities run at least once, so their side effects must be idempotent.
- [[state-machines]] - a workflow is a durable state machine; use in-app machines for simple lifecycles.
- [[background-jobs-and-queues]] - the simpler choice for one-step background work.
- [[design-job-scheduler]] - delayed and recurring jobs without multi-step orchestration.
- [[long-running-operations]] - the API side: return 202 and a status resource backed by a workflow run.
- [[event-driven-architecture]] - choreography as the alternative to a central orchestrator.
- [[resilience-patterns]] - retries with backoff and timeouts, here declared per activity.

## References
- Temporal documentation, "Workflows" (event history, replay, determinism, Continue-As-New): https://docs.temporal.io/workflows
- Temporal documentation, "Activities" (retry policies, timeouts, idempotency): https://docs.temporal.io/activities
- AWS Step Functions Developer Guide, "What is Step Functions?" (Standard vs Express workflows): https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html
- Microsoft Learn, "Orchestrator function code constraints" (Durable Functions determinism rules): https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-code-constraints
- Hector Garcia-Molina and Kenneth Salem, "Sagas", SIGMOD 1987.
