---
title: Backpressure and load shedding
category: reliability
tags: [backpressure, load-shedding, overload, admission-control, bounded-queue, concurrency-limit, codel, adaptive-throttling, goodput, criticality]
use_cases:
  - "service falls over under a traffic spike instead of serving what it can"
  - "latency climbs to timeouts while CPU is pegged and every request fails"
  - "queue or consumer lag grows without bound when downstream is slow"
  - "decide what to reject first when demand exceeds capacity"
  - "set concurrency limits that adapt instead of hand-tuned thread pool sizes"
status: draft
last_verified: 2026-10-24
sources:
  - https://sre.google/sre-book/handling-overload/
  - https://sre.google/sre-book/addressing-cascading-failures/
  - https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/
  - https://queue.acm.org/detail.cfm?id=2839461
  - https://queue.acm.org/detail.cfm?id=2209336
  - https://github.com/Netflix/concurrency-limits
  - https://www.reactive-streams.org/
---

# Backpressure and load shedding

## Summary
Every system has a maximum rate at which it can do useful work. When demand
goes above it, an unprotected service keeps accepting requests, queues them,
and spends its capacity on work whose callers have already timed out, so
useful throughput (goodput) collapses to near zero. Backpressure pushes the
"slow down" signal back towards the producer (bounded queues, flow control,
429/503 with `Retry-After`); load shedding rejects excess work cheaply and
early, ideally the least important work first, so the rest still meets its
latency target.

## Key concepts
- **Throughput vs goodput**: throughput counts requests completed; goodput
  counts requests completed *in time to be useful*. Overload attacks goodput
  first.
- **Little's law**: items in the system = arrival rate x time in system. With
  a fixed concurrency limit, more arrivals can only mean longer waits, and
  waits beyond the client timeout are pure waste.
- **Bounded everything**: queues, thread pools, connection pools, in-flight
  requests per client. An unbounded queue turns an overload into a memory
  problem plus a latency problem.
- **Backpressure** (flow control): the consumer tells the producer how much
  it can take. Examples: TCP windows, HTTP/2 and gRPC stream flow control,
  Reactive Streams `request(n)`, pull-based consumers (Kafka, SQS), blocking
  `put()` on a bounded queue.
- **Load shedding** (admission control): when a limit is reached, reject new
  work immediately with a cheap error instead of accepting it and failing
  slowly. Rejecting costs far less than serving.
- **Deadline propagation**: pass the caller's deadline downstream (gRPC
  deadlines, a `timeout` header) and drop work whose deadline has passed
  before starting it.
- **Criticality / priority**: label requests (Google uses levels such as
  CRITICAL_PLUS, CRITICAL, SHEDDABLE_PLUS, SHEDDABLE) and shed the lowest
  first: prefetch, analytics and batch before checkout and login.
- **Queue-delay control** (CoDel idea): shed based on how long items have
  waited, not on queue length. Facebook's servers cap queue time at a short
  value when the queue has not been empty recently, and switch to adaptive
  LIFO under load so the freshest requests, whose callers are still waiting,
  are served first.
- **Adaptive concurrency limits**: instead of a hand-tuned pool size, adjust
  the in-flight limit from observed latency (AIMD or gradient algorithms, as
  in Netflix `concurrency-limits`).
- **Client-side adaptive throttling** (Google SRE): each client tracks
  `requests` and `accepts` over a window and rejects locally with probability
  `max(0, (requests - K * accepts) / (requests + 1))`, K typically 2, so a
  struggling backend is not hammered with requests it will reject anyway.

## When to use / scenarios
- Any service exposed to traffic you do not control (public APIs, mobile
  clients, retry storms from other services): put an in-flight limit and a
  fast reject path in front of expensive work.
- Queue consumers and stream processors: bounded buffers and pull-based
  consumption so a slow sink slows ingestion instead of exhausting memory
  ([[message-queues-and-streams]]).
- Mixed-importance traffic sharing one fleet: priority-aware shedding.
- Cascading failure risk: a slow dependency makes callers queue, which makes
  their callers queue; limits at every hop stop the spread
  ([[resilience-patterns]], [[failure-modes-and-fallacies]]).
- When NOT to rely on it alone: shedding protects you during a spike; it is
  not capacity. Sustained shedding means you need more capacity or less work
  ([[capacity-planning-and-autoscaling]]). Per-tenant fairness is a quota
  problem first ([[rate-limiting]]).

## How it works / example

```
producer --> [ admission: in-flight < limit? priority ok? ] --no--> 503 / 429 + Retry-After (cheap)
                     | yes
                     v
             [ bounded queue, max wait ] --waited too long / deadline passed--> drop before work
                     |
                     v
                 workers (fixed or adaptive concurrency)
```

A deterministic simulation of one worker receiving 1.5x its capacity. With an
unbounded FIFO queue the server stays busy but almost every response arrives
after the client timeout. A bounded queue (reject at the door) or
deadline-aware dropping keeps goodput close to capacity. The second part
shows an AIMD concurrency limit and Google's client-side throttling formula.

```python
from collections import deque

SERVICE = 1.0          # seconds of work per request
TIMEOUT = 10.0         # client gives up after this long
N = 4000
INTERVAL = SERVICE / 1.5   # arrivals at 1.5x capacity

def simulate(policy, max_queue=5):
    t_free = 0.0                      # when the single worker is next idle
    waiting = deque()                 # start times of accepted, not yet started requests
    good = late = rejected = dropped = 0
    for i in range(N):
        arrival = i * INTERVAL
        while waiting and waiting[0] <= arrival:
            waiting.popleft()
        if policy == "bounded" and len(waiting) >= max_queue:
            rejected += 1             # fast 503: costs (almost) nothing
            continue
        start = max(arrival, t_free)
        if policy == "deadline" and start + SERVICE - arrival > TIMEOUT:
            dropped += 1              # caller already gone: skip the work
            continue
        t_free = start + SERVICE
        waiting.append(start)
        if t_free - arrival <= TIMEOUT:
            good += 1
        else:
            late += 1                 # work done, nobody waiting for it
    return {"good": good, "late": late, "rejected": rejected, "dropped": dropped}

capacity = int(N * INTERVAL / SERVICE)        # requests the worker can finish
results = {p: simulate(p) for p in ("unbounded", "bounded", "deadline")}
for policy, r in results.items():
    print(f"{policy:9s} goodput={r['good'] / N:.0%} {r}")

assert results["unbounded"]["good"] < 0.01 * N          # goodput collapse
assert results["bounded"]["good"] >= 0.95 * capacity    # near capacity, all on time
assert results["deadline"]["good"] >= 0.95 * capacity
assert results["bounded"]["late"] == 0

class AIMDLimit:
    """In-flight limit: +1 per success under target latency, x0.9 on overload."""
    def __init__(self, initial=10, minimum=1, maximum=200, target_latency=0.1):
        self.limit, self.min, self.max, self.target = initial, minimum, maximum, target_latency
        self.inflight = 0

    def try_acquire(self):
        if self.inflight >= int(self.limit):
            return False              # shed
        self.inflight += 1
        return True

    def release(self, latency, overloaded=False):
        self.inflight -= 1
        if overloaded or latency > self.target:
            self.limit = max(self.min, self.limit * 0.9)
        else:
            self.limit = min(self.max, self.limit + 1 / self.limit)  # ~+1 per window

lim = AIMDLimit()
for latency in [0.05] * 200:          # healthy: limit grows slowly
    assert lim.try_acquire(); lim.release(latency)
grown = lim.limit
for latency in [0.5] * 20:            # latency spike: limit shrinks quickly
    assert lim.try_acquire(); lim.release(latency)
assert lim.limit < grown / 2, (grown, lim.limit)

def client_reject_probability(requests, accepts, k=2.0):
    """Google SRE client-side adaptive throttling."""
    return max(0.0, (requests - k * accepts) / (requests + 1))

assert client_reject_probability(1000, 1000) == 0.0    # healthy backend
assert client_reject_probability(1000, 100) > 0.79     # backend rejecting 90%
print(f"AIMD limit {grown:.1f} -> {lim.limit:.1f}; "
      f"reject p at 10% accepts = {client_reject_probability(1000, 100):.2f}")
```

## Trade-offs
- **Reject early vs queue a little**: a short queue absorbs bursts and keeps
  utilisation high; a long one only adds latency. Bound queues by time waited
  (a few multiples of normal latency), not by a large count.
- **Static vs adaptive limits**: static limits are predictable and easy to
  reason about but go stale as code, hardware and dependencies change;
  adaptive limits follow reality but can oscillate and need good latency
  signals.
- **Where to shed**: at the edge (load balancer, gateway) is cheapest and
  protects everything behind it but knows little about cost or priority; in
  the service it knows criticality and request cost; in the client it saves
  network and backend work but needs every client to cooperate.
- **FIFO vs LIFO under load**: FIFO is fair in calm periods; LIFO under
  overload serves requests whose callers are still waiting but starves old
  ones (acceptable, since they have usually timed out).
- **Fail fast vs degrade**: an error is cheapest; a degraded answer (cached,
  partial, lower quality) is friendlier but must itself be cheap or it is not
  shedding.

## Gotchas
- Shedding that is expensive: parsing the body, authenticating, or logging a
  full stack trace for every rejected request can cost as much as serving it.
- Retries multiply load exactly when the server is shedding. Use retry
  budgets, backoff with jitter and honour `Retry-After`
  ([[resilience-patterns]]).
- Health checks that fail under load pull instances out, which overloads the
  rest; keep readiness about the instance, not about being busy for a moment
  ([[health-checks-and-graceful-shutdown]]).
- Autoscaling on CPU while shedding keeps CPU low: rejected requests are
  cheap, so the scaler sees a calm fleet. Scale on offered load or shed rate
  too ([[capacity-planning-and-autoscaling]]).
- Timeouts not propagated: a downstream service keeps working for a request
  the edge abandoned seconds ago.
- Rejecting with 500: clients and load balancers treat it as a bug. Use 503
  (or 429 for per-client quota) with `Retry-After`.
- Thread-per-request servers with huge pools: the pool *is* the queue, and a
  large pool just moves the collapse into context switching and memory.
- Testing only at expected load. Load-test past saturation and check that
  goodput plateaus instead of falling ([[performance-and-load-testing]]).

## Related
- [[resilience-patterns]] - timeouts, retries with budgets, circuit breakers and bulkheads around these limits.
- [[rate-limiting]] - per-client quotas; shedding protects the server, quotas share it fairly.
- [[message-queues-and-streams]] - consumer lag, prefetch limits and pull-based backpressure.
- [[capacity-planning-and-autoscaling]] - adding capacity when shedding is sustained, not a one-off spike.
- [[failure-modes-and-fallacies]] - cascading failures and metastable states that overload starts.
- [[performance-and-load-testing]] - finding the saturation point and checking goodput beyond it.
- [[health-checks-and-graceful-shutdown]] - keeping overload from cascading through readiness probes.
- [[processes-threads-and-io-models]] - why thread pools and event loops saturate differently.

## References
- Google SRE Book, ch. 21 "Handling Overload" (criticality, client-side adaptive throttling): https://sre.google/sre-book/handling-overload/
- Google SRE Book, ch. 22 "Addressing Cascading Failures": https://sre.google/sre-book/addressing-cascading-failures/
- David Yanacek, "Using load shedding to avoid overload", Amazon Builders' Library: https://aws.amazon.com/builders-library/using-load-shedding-to-avoid-overload/
- Ben Maurer, "Fail at Scale", ACM Queue 13(8), 2015 (controlled delay, adaptive LIFO, concurrency control): https://queue.acm.org/detail.cfm?id=2839461
- Kathleen Nichols and Van Jacobson, "Controlling Queue Delay", ACM Queue 10(5), 2012 (CoDel): https://queue.acm.org/detail.cfm?id=2209336
- Netflix `concurrency-limits` library (AIMD, Vegas and gradient limiters): https://github.com/Netflix/concurrency-limits
- Reactive Streams specification (demand-based backpressure): https://www.reactive-streams.org/
