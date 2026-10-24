---
title: Failure modes and the fallacies of distributed computing
category: distributed-systems
tags: [fallacies, partial-failure, timeouts, network-partition, failure-detection, split-brain, byzantine, gray-failure]
use_cases:
  - "review a design for what happens when the network, a dependency or a node misbehaves"
  - "explain to the team why a timeout does not mean the request failed"
  - "choose timeouts and failure detectors that avoid both false alarms and long outages"
  - "write a failure-mode table for a design doc before building a multi-service feature"
status: draft
last_verified: 2026-10-10
sources:
  - "Deutsch and Gosling, The Eight Fallacies of Distributed Computing https://nighthacks.com/jag/res/Fallacies.html"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 8 (The Trouble with Distributed Systems)"
  - "Huang et al., Gray Failure: The Achilles' Heel of Cloud-Scale Systems (HotOS 2017) https://www.microsoft.com/en-us/research/publication/gray-failure-achilles-heel-cloud-scale-systems/"
  - "Bailis and Kingsbury, The Network is Reliable (ACM Queue 2014) https://queue.acm.org/detail.cfm?id=2655736"
  - "Hayashibara et al., The Phi Accrual Failure Detector (2004)"
---

# Failure modes and the fallacies of distributed computing

## Summary
A distributed system is one where a computer you did not know existed can make your own work fail. Unlike a single machine, parts fail independently and partially, and from the outside a crashed node, a slow node and a lost message look identical. Designs that assume a reliable, fast, secure network with one clock and one administrator fail in production; designing explicitly for partial failure is what separates robust systems from demos.

## Key concepts
- **Eight fallacies** (Deutsch, Gosling and others):
  1. The network is reliable.
  2. Latency is zero.
  3. Bandwidth is infinite.
  4. The network is secure.
  5. Topology does not change.
  6. There is one administrator.
  7. Transport cost is zero.
  8. The network is homogeneous.
- **Partial failure**: some components fail while others work, nondeterministically. Whole-system correctness must survive it.
- **Failure models** (weakest assumption last): crash-stop, crash-recovery, omission (messages dropped), timing (too slow or fast), Byzantine (arbitrary or malicious). Most systems assume crash-recovery plus omission; consensus protocols handle crash faults, BFT is for hostile settings.
- **Indistinguishability**: with timeouts you cannot tell dead from slow from partitioned. A failure detector only gives suspicion, never certainty.
- **Gray failure**: a component is degraded (slow disk, packet loss, saturated threads) so health checks pass while users suffer. Often worse than a clean crash.
- **Metastable and cascading failure**: retries, queue growth and cache stampedes keep a system overloaded after the trigger is gone.
- **Split brain**: two nodes both believe they are leader after a partition or pause; prevented by quorum and fencing ([[consensus-raft-paxos]]).
- **Blast radius / fault isolation**: bulkheads, cells and zones bound how much one failure takes down.

## When to use / scenarios
- During design review of any feature that crosses a process boundary: walk through "what if this call times out / returns twice / returns late / returns garbage".
- Choosing timeouts, retry policy, health checks, and failover thresholds.
- Post-incident analysis: classify the failure (crash, slow, partial, overload) and the missing defence.
- Before adding a synchronous dependency chain: the availability multiplies down (five 99.9% dependencies in series is about 99.5%).
- Not every internal call needs heroic handling; scale defences to the cost of failure. A batch report can fail and rerun; a payment cannot.

## How it works / example

What the caller sees when a call "fails":

```
 caller --request--> server
   (a) request lost            -> server never ran it
   (b) server crashed mid-way  -> partial side effects
   (c) server done, response lost -> effect happened, caller sees timeout
   (d) server slow (GC, queue) -> may complete after caller gave up
   The caller observes only: "no response in T".  Safe action: retry only if the operation is idempotent.
```

Failure-mode table to put in a design doc (fill per dependency):

| Dependency | Failure | Detection | Behaviour | Recovery |
|---|---|---|---|---|
| payments API | timeout | 3 s deadline | return PENDING, reconcile later | idempotent retry with same key |
| cache | down | connect error | read through to DB, shed load | circuit open, gradual re-warm |
| queue | duplicate delivery | message ID | dedupe | none needed |
| primary DB | leader failover | health + quorum | writes pause up to RTO | promote, replay, fence old |

A defensive call: deadline, bounded retries with jitter, and a breaker, in miniature:

```python
import random, time

def call_with_retry(fn, deadline_s=2.0, attempts=3, base=0.1, cap=1.0):
    start = time.monotonic()
    for i in range(attempts):
        remaining = deadline_s - (time.monotonic() - start)
        if remaining <= 0: break
        try:
            return fn(timeout=remaining)                      # always pass a timeout downstream
        except TimeoutError:
            sleep = min(cap, base * 2 ** i) * random.random() # exponential backoff with full jitter
            time.sleep(min(sleep, max(0, deadline_s - (time.monotonic() - start))))
    raise TimeoutError("exhausted deadline/attempts")

calls = []
def flaky(timeout):
    calls.append(1)
    if len(calls) < 3: raise TimeoutError
    return "ok"
assert call_with_retry(flaky) == "ok" and len(calls) == 3
```

Checklist of defences:
1. **Timeouts everywhere**, with an overall deadline propagated through the call chain; no default of "wait forever".
2. **Retries only for idempotent operations**, with backoff and jitter, and a retry budget so retries cannot multiply load ([[idempotency-and-exactly-once]]).
3. **Circuit breakers, bulkheads, load shedding, backpressure** ([[resilience-patterns]]).
4. **Health checks that test real work** (deep readiness), plus outlier detection on latency and error rate to catch gray failures.
5. **Failure detectors**: heartbeat with adaptive thresholds (phi accrual) rather than a fixed guess; accept false positives are costly (needless failover).
6. **Graceful degradation**: serve stale/cached/partial data instead of an error.
7. **Chaos and fault injection** (kill nodes, inject latency and packet loss) in staging and, mature teams, production; Jepsen-style tests for datastores.
8. **Observability** to see slowness, not just errors ([[observability-logs-metrics-traces]]).

## Trade-offs
- **Aggressive vs lenient timeouts**: short timeouts detect failures fast but trigger false failovers and retry storms; long ones hold resources and stretch outages. Base on measured p99/p999 latency.
- **Fail fast vs degrade gracefully**: failing fast protects the system; degrading protects the user. Decide per feature.
- **Redundancy vs complexity**: every replica, queue and failover path is itself a source of bugs; test the failure paths or they are fiction.
- **Synchronous vs asynchronous calls**: async decouples availability but adds eventual consistency and duplicate handling.

## Gotchas
- "The network is reliable": packet loss, partitions and delays happen in cloud networks regularly. Plan for them.
- Timeout means "unknown outcome", not "failed". Treating it as failure causes double charges and lost updates.
- Retries at several layers multiply (3 retries x 3 layers = 27 requests). Retry at one layer, or use budgets.
- Health check says OK but the node is slow or its dependency is down (gray failure); load balancers keep sending traffic.
- Clock assumptions: leases and "my timestamp is later" break under skew ([[time-clocks-and-ordering]]).
- Testing only the happy path and clean crashes; real failures are slow, partial and intermittent.
- Unbounded queues turn overload into latency collapse and memory exhaustion; bound them and reject early.
- Shared fate: "independent" replicas on the same rack, AZ, deploy pipeline or config push fail together.

## Related
- [[resilience-patterns]] - the concrete toolbox: timeouts, retries, breakers, bulkheads
- [[idempotency-and-exactly-once]] - makes retries after ambiguous failures safe
- [[cap-and-pacelc]] - what to give up when a partition occurs
- [[consensus-raft-paxos]] - agreement and leader election despite crashes
- [[networking-fundamentals]] - latency, packet loss and TCP behaviour behind fallacies 1-3
- [[incident-response-and-postmortems]] - learning from the failures that do happen
- [[chaos-engineering]] - injecting these failure modes on purpose, with a hypothesis and a small blast radius

## References
- Deutsch and Gosling, The Eight Fallacies of Distributed Computing.
- Kleppmann, Designing Data-Intensive Applications, ch. 8.
- Huang et al., Gray Failure (HotOS 2017); Bailis and Kingsbury, The Network is Reliable (ACM Queue 2014).
- Hayashibara et al., The Phi Accrual Failure Detector (2004).
