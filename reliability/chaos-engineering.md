---
title: Chaos engineering and fault injection
category: reliability
tags: [chaos-engineering, fault-injection, game-day, steady-state, blast-radius, resilience-testing, chaos-monkey, aws-fis, chaos-mesh]
use_cases:
  - "check that our timeouts, retries and fallbacks actually work before a real outage tests them"
  - "plan a first game day for a team that has never broken anything on purpose"
  - "inject latency or errors into one dependency in staging and see whether the SLO holds"
  - "run a fault-injection experiment in production with a small blast radius and an abort switch"
  - "verify that losing one availability zone or one node does not take the service down"
status: draft
last_verified: 2026-10-24
sources:
  - https://principlesofchaos.org/
  - https://www.oreilly.com/library/view/chaos-engineering/9781492043850/
  - https://sre.google/sre-book/testing-reliability/
  - https://docs.aws.amazon.com/fis/latest/userguide/what-is.html
  - https://chaos-mesh.org/docs/
  - https://netflix.github.io/chaosmonkey/
---

# Chaos engineering and fault injection

## Summary
Chaos engineering is running controlled experiments that inject real-world
faults (killed instances, added latency, failing dependencies, lost zones)
into a system to check a hypothesis that its steady-state behavior will hold.
It finds the gap between how engineers believe the system handles failure and
how it actually does, before an outage finds it for them. It is an
experiment with a hypothesis, a limited blast radius and an abort condition,
not random breakage.

## Key concepts
- **Steady state**: a measurable output that shows the system is working for
  users, such as successful checkouts per minute, request success rate or
  p99 latency. Business or SLI metrics, not CPU usage
  (see [[slis-slos-error-budgets]]).
- **Hypothesis**: "steady state stays within X in both the control and the
  experimental group while fault F is injected". The Principles of Chaos
  Engineering frame an experiment as trying to disprove it.
- **Control vs experiment group**: compare the faulted slice with an
  unfaulted one over the same period so normal noise is not mistaken for
  impact.
- **Fault types**: resource (CPU, memory, disk full), network (latency,
  packet loss, partition, DNS failure), state (kill a process, a pod, a
  node, a zone), dependency (errors or slowness from a downstream service),
  time (clock skew).
- **Blast radius**: how many users, requests, hosts or regions the experiment
  can affect. Start small (one host, a percentage of requests, internal
  users) and widen only after the hypothesis holds.
- **Abort (stop) condition**: a pre-agreed metric threshold that ends the
  experiment and removes the fault automatically, for example the error rate
  of the experiment group exceeding the SLO burn threshold.
- **Game day**: a scheduled, facilitated session where a team runs failure
  scenarios on purpose and also rehearses detection, paging and runbooks.
- **Advanced principles** (principlesofchaos.org): vary real-world events,
  run experiments in production, automate them to run continuously, and
  minimize blast radius.

## When to use / scenarios
- You have resilience mechanisms (timeouts, retries, circuit breakers,
  failover, autoscaling) that have never been exercised; untested fallbacks
  usually fail when first needed ([[resilience-patterns]]).
- After an incident, to prove the fix: re-inject the fault that caused it.
- Before a launch or a migration (new region, new database, new mesh), to
  check failover and degradation paths.
- To validate alerts and runbooks: did the right alert fire, and did on-call
  know what to do ([[incident-response-and-postmortems]])?
- Continuously in CI or on a schedule once experiments are stable, so
  regressions in resilience are caught like functional ones.
- When NOT to: the system has no basic observability (you cannot see the
  steady state, so you learn nothing); known weaknesses are still unfixed
  (fix them first, an experiment will only confirm them); no way to stop the
  fault quickly. Start in staging with [[performance-and-load-testing]]
  style tooling instead.

## How it works / example
Experiment loop:

```
1. Define steady state (metric + normal range)
2. Hypothesis: steady state holds while fault F hits blast radius B
3. Set abort condition and owner; announce the window
4. Inject F into the experiment group only, keep a control group
5. Observe; abort automatically if the stop condition trips
6. Remove F, compare groups, record findings, fix, repeat wider
```

A self-contained simulation: a service calls a dependency through a timeout
and a cached fallback. The experiment injects 2 seconds of latency into 30
percent of dependency calls for the experiment group and checks the
hypothesis "success rate stays at or above 99 percent". The second run shows
how the same experiment disproves the hypothesis when the fallback is
missing, and the abort condition stops it early.

```python
import random

TIMEOUT_S = 0.5          # client-side timeout to the dependency
SLO_SUCCESS = 0.99       # steady-state hypothesis
ABORT_BELOW = 0.95       # stop condition, checked continuously

def call_dependency(rng, fault):
    """Return simulated latency in seconds; the fault adds latency to some calls."""
    latency = rng.uniform(0.01, 0.05)
    if fault and rng.random() < fault["rate"]:
        latency += fault["extra_latency_s"]
    return latency

def handle_request(rng, fault, has_fallback):
    latency = call_dependency(rng, fault)
    if latency <= TIMEOUT_S:
        return True                  # fresh answer
    return has_fallback              # timed out: serve cached value, or fail

def run(group_fault, has_fallback, requests=5000, seed=7):
    rng = random.Random(seed)
    ok = {"control": 0, "experiment": 0}
    seen = {"control": 0, "experiment": 0}
    for i in range(requests):
        group = "experiment" if i % 10 == 0 else "control"   # 10% blast radius
        fault = group_fault if group == "experiment" else None
        seen[group] += 1
        ok[group] += handle_request(rng, fault, has_fallback)
        if seen["experiment"] >= 50:
            rate = ok["experiment"] / seen["experiment"]
            if rate < ABORT_BELOW:
                return {"aborted_at": i, "experiment_success": rate}
    return {g: ok[g] / seen[g] for g in ok}

fault = {"rate": 0.30, "extra_latency_s": 2.0}

with_fallback = run(fault, has_fallback=True)
assert with_fallback["experiment"] >= SLO_SUCCESS, with_fallback
assert with_fallback["control"] >= SLO_SUCCESS
print("hypothesis holds with fallback:", with_fallback)

without_fallback = run(fault, has_fallback=False)
assert "aborted_at" in without_fallback       # stop condition fired
print("hypothesis disproved, experiment aborted:", without_fallback)
```

Tools that inject faults for real:
- **Chaos Monkey** (Netflix): randomly terminates instances in production
  during working hours so services must tolerate instance loss.
- **AWS Fault Injection Service (FIS)**: experiment templates with actions
  (stop instances, inject API errors, network disruption) and CloudWatch
  alarms as stop conditions.
- **Chaos Mesh** (CNCF): Kubernetes custom resources for pod kill, network
  delay and partition, I/O and time faults.
- In-process: a fault-injection wrapper or service-mesh fault rules (Envoy
  and Istio can delay or abort a percentage of requests,
  see [[api-gateway-and-service-mesh]]).

## Trade-offs
- **Staging vs production**: staging is safe but differs in traffic, data and
  configuration, so it misses real weaknesses; production gives real answers
  and needs small blast radius, abort conditions and organizational buy-in.
- **Game days vs continuous automation**: game days teach people and test
  process; automated experiments catch regressions but only for faults
  someone already thought of.
- **Narrow vs broad faults**: one dependency's latency is easy to reason
  about; zone or region loss tests more at once but makes the cause of any
  failure harder to isolate.
- **Platform tool vs in-code injection**: infrastructure tools need no code
  changes and test real failure; in-code hooks are precise and testable in
  unit tests but are not the real failure mode.

## Gotchas
- Running an experiment without a steady-state metric: "nothing obviously
  broke" is not a result.
- No abort switch or one that depends on the system being tested (the
  control plane is in the zone you just took down).
- Faults left behind: an injected latency rule or a stopped instance that
  nobody removed. Experiments need a guaranteed rollback step.
- Not telling on-call: the experiment pages people who then "fix" it, or a
  real incident is ignored as "probably the chaos test".
- Retries turning an injected 10 percent error rate into a retry storm that
  hurts the control group too; watch the control group as well.
- Only killing stateless pods. The interesting failures are in stateful
  pieces: database failover, cache loss, queue backlog, expired certificates,
  clock skew ([[failure-modes-and-fallacies]]).
- Treating a passed experiment as permanent; configuration and code drift,
  so rerun experiments regularly.

## Related
- [[resilience-patterns]] - the timeouts, retries, breakers and fallbacks experiments verify.
- [[failure-modes-and-fallacies]] - the catalogue of faults worth injecting.
- [[slis-slos-error-budgets]] - steady-state metrics and how much budget an experiment may spend.
- [[incident-response-and-postmortems]] - game days rehearse the incident process; postmortems suggest experiments.
- [[observability-logs-metrics-traces]] - you cannot run an experiment you cannot observe.
- [[backup-and-disaster-recovery]] - failover and restore drills are chaos experiments for DR plans.
- [[performance-and-load-testing]] - combine load with faults to test behavior near capacity.

## References
- Principles of Chaos Engineering: https://principlesofchaos.org/
- Casey Rosenthal and Nora Jones, *Chaos Engineering: System Resiliency in Practice*, O'Reilly, 2020: https://www.oreilly.com/library/view/chaos-engineering/9781492043850/
- Betsy Beyer et al., *Site Reliability Engineering*, ch. 17 "Testing for Reliability": https://sre.google/sre-book/testing-reliability/
- AWS Fault Injection Service user guide: https://docs.aws.amazon.com/fis/latest/userguide/what-is.html
- Chaos Mesh documentation: https://chaos-mesh.org/docs/
- Netflix Chaos Monkey: https://netflix.github.io/chaosmonkey/
