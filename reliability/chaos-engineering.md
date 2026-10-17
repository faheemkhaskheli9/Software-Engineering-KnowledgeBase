---
title: Chaos engineering and fault injection
category: reliability
tags: [chaos-engineering, fault-injection, game-day, resilience-testing, blast-radius, steady-state, toxiproxy, aws-fis, chaos-mesh, litmus]
use_cases:
  - "prove our timeouts, retries and fallbacks actually work before a real outage"
  - "run a first game day for a team that has never done chaos experiments"
  - "check that losing one availability zone or a cache cluster does not take the site down"
  - "add latency and error injection to integration tests for a service's dependencies"
  - "decide whether it is safe to run fault injection in production"
status: draft
last_verified: 2026-10-17
sources:
  - https://principlesofchaos.org/
  - https://netflix.github.io/chaosmonkey/
  - https://docs.aws.amazon.com/fis/latest/userguide/what-is.html
  - https://learn.microsoft.com/en-us/azure/chaos-studio/chaos-studio-overview
  - https://chaos-mesh.org/docs/
  - https://litmuschaos.io/
  - https://github.com/Shopify/toxiproxy
  - "Casey Rosenthal and Nora Jones, Chaos Engineering: System Resiliency in Practice (O'Reilly, 2020)"
---

# Chaos engineering and fault injection

## Summary
Chaos engineering is running controlled experiments that inject real-world failures (killed instances, added latency, dropped packets, a failing dependency, a lost zone) into a system to check that it keeps its steady-state behaviour. It turns resilience claims ("the circuit breaker will open", "we survive losing a node") into tested facts, and finds the weaknesses before an incident does. Each experiment has a hypothesis, a measured steady state, a limited blast radius and an abort condition.

## Key concepts
- **Principles** (principlesofchaos.org): build a hypothesis around steady-state behaviour; vary real-world events; run experiments in production; automate experiments to run continuously; minimise blast radius.
- **Steady state**: a measurable output that shows the system works for users, such as successful checkouts per minute or the SLI from [[slis-slos-error-budgets]], not CPU or other internal signals.
- **Hypothesis**: "with 300 ms added to the recommendations service, checkout success stays above 99.5 percent and p99 latency below 1 s".
- **Control and experiment groups**: compare the steady-state metric for traffic with and without the fault at the same time, so normal variation is not mistaken for impact.
- **Blast radius**: the share of users, hosts or regions exposed. Start with one host or a small percentage of requests and widen only after the hypothesis holds.
- **Abort (stop) condition**: a guardrail metric that ends the experiment and removes the fault automatically when breached.
- **Fault types**: resource (CPU, memory, disk full), state (kill process or instance, reboot, clock skew), network (latency, loss, partition, DNS failure), dependency (errors or slow responses from a downstream API), and larger events such as losing a zone.
- **Game day**: a scheduled, facilitated exercise where a team injects a failure and practises detection, diagnosis and recovery; it also tests runbooks, alerts and on-call ([[incident-response-and-postmortems]]).

## When to use / scenarios
- You rely on timeouts, retries, circuit breakers, fallbacks or failover ([[resilience-patterns]]) and have never seen them fire.
- After a postmortem: turn the incident into a repeatable experiment so the fix stays fixed.
- Before a launch or a peak event: confirm that losing a replica, cache node or zone degrades gracefully.
- In CI: fault injection around dependencies in integration tests (Toxiproxy-style latency and resets) catches missing timeouts early ([[integration-and-contract-testing]]).
- When NOT to use (yet):
  - No observability: if you cannot see the steady state you cannot judge the experiment ([[observability-logs-metrics-traces]]).
  - Known single points of failure: fix them first; an experiment only confirms what you know.
  - No way to stop the fault quickly, or no agreement from the teams that own the affected systems.

## How it works / example

Experiment loop:

```
define steady state -> hypothesis -> choose fault + blast radius + abort condition
      -> run (control vs experiment) -> abort on guardrail breach
      -> compare -> fix weaknesses -> automate and widen
```

The simulation below wraps a dependency with a fault injector (added latency and errors for a fraction of calls) and runs the same experiment against two versions of a caller: one without a timeout or fallback and one with both. Time is simulated, so the run is fast and deterministic. The experiment rejects the hypothesis for the first version, which is the point: it found a weakness before production traffic did.

```python
import random
import statistics

class Timeout(Exception): ...
class DependencyError(Exception): ...

def recommendations(user_id: int) -> tuple[list[str], float]:
    """Healthy dependency: (result, simulated latency in ms)."""
    return [f"item-{user_id % 7}"], 40.0

def inject(dep, rng, rate, extra_ms=0.0, error=False):
    """Fault injector: for `rate` of calls add latency, or fail."""
    def wrapped(user_id):
        result, ms = dep(user_id)
        if rng.random() < rate:
            if error:
                raise DependencyError("injected failure")
            ms += extra_ms
        return result, ms
    return wrapped

def checkout_naive(dep, user_id):
    recs, ms = dep(user_id)                   # no timeout, no fallback
    return True, ms + 50

def checkout_resilient(dep, user_id, timeout_ms=200):
    try:
        recs, ms = dep(user_id)
        if ms > timeout_ms:
            raise Timeout()                   # the client gives up at the deadline
    except (Timeout, DependencyError):
        recs, ms = [], timeout_ms             # fallback: checkout without recommendations
    return True, min(ms, timeout_ms) + 50

def run(checkout, dep, n, slo_ms):
    """Steady state: share of checkouts that succeed within the latency SLO, and p99."""
    ok, lat = 0, []
    for uid in range(n):
        try:
            success, ms = checkout(dep, uid)
        except DependencyError:
            success, ms = False, 0.0
        lat.append(ms)
        ok += success and ms <= slo_ms
    return ok / n, statistics.quantiles(lat, n=100)[98]

def experiment(checkout, fault, n=5_000, slo_ms=1_000, target=0.995, abort_below=0.95):
    control = run(checkout, recommendations, n, slo_ms)
    treated = run(checkout, fault, n, slo_ms)
    aborted = treated[0] < abort_below        # guardrail: in production this stops the fault
    holds = treated[0] >= target and not aborted
    return control, treated, holds, aborted

rng = random.Random(7)
slow = inject(recommendations, rng, rate=0.05, extra_ms=2_000)   # blast radius: 5% of calls
failing = inject(recommendations, rng, rate=0.05, error=True)

for name, checkout in [("naive", checkout_naive), ("resilient", checkout_resilient)]:
    for fault_name, fault in [("latency", slow), ("errors", failing)]:
        (c_ok, c_p99), (t_ok, t_p99), holds, aborted = experiment(checkout, fault)
        print(f"{name:9} {fault_name:7} control={c_ok:.3f} p99={c_p99:.0f}ms "
              f"experiment={t_ok:.3f} p99={t_p99:.0f}ms hypothesis={'holds' if holds else 'rejected'}")
        if name == "naive":
            assert not holds                  # the weakness the experiment exists to find
        else:
            assert holds and t_p99 <= 250
```

A first production experiment, written down before it runs:

```
Hypothesis:   checkout success >= 99.5% and p99 < 1 s while recommendations has +300 ms latency
Fault:        +300 ms on calls from checkout to recommendations (fault-injection tool or mesh fault rule)
Blast radius: 1% of checkout requests in one region, 15 minutes, business hours, owners on call
Abort:        checkout success < 99% for 2 minutes, or any page fires -> remove fault automatically
Result:       hypothesis held / rejected; action items with owners
```

Tooling (check each project's docs for current features): AWS Fault Injection Service and Azure Chaos Studio for managed experiments on cloud resources; Chaos Mesh and LitmusChaos (CNCF projects) for Kubernetes; Netflix's Chaos Monkey for random instance termination; Toxiproxy for network faults between a service and its dependencies in tests; service-mesh fault injection (delays and aborts per route, [[api-gateway-and-service-mesh]]).

## Trade-offs
- **Production vs staging**: production is the only place with real traffic, data and configuration, which is why the principles call for it; staging is safer but misses the emergent behaviour you are looking for. Most teams start in staging or in CI and move to production with a small blast radius.
- **Random vs targeted faults**: random termination (Chaos Monkey) keeps teams honest about statelessness; targeted experiments from a hypothesis teach more per run.
- **Automated vs game day**: continuous automated experiments catch regressions; game days also exercise people, alerts and runbooks.
- **Blast radius vs signal**: a tiny exposure is safe but may be too small to move the metric; widen in steps.
- **Cost**: experiments use engineering time and some error budget; spend it on the dependencies and failure modes that past incidents and [[threat-modeling]]-style reviews point to.

## Gotchas
- Measuring host metrics instead of user-facing steady state: CPU looks fine while checkouts fail.
- No automatic abort: a fault that cannot be removed in seconds is an incident, not an experiment.
- Fault injected but traffic did not reach it (wrong route, cached responses): verify the fault is active, for example from traces.
- Retries amplify injected errors into load on the dependency; watch the dependency during the run ([[resilience-patterns]]).
- Surprising other teams: announce experiments, share the schedule, and record them in the change log that incident responders check.
- Running during a real incident or a peak, or while the error budget is already spent ([[slis-slos-error-budgets]]).
- Treating a passed experiment as permanent: code and configuration change, so rerun it automatically.
- Clock-skew and disk-full faults can corrupt data on stateful systems; test those on replicas or copies first ([[backup-and-disaster-recovery]]).

## Related
- [[resilience-patterns]] - the timeouts, retries, circuit breakers and fallbacks these experiments verify.
- [[failure-modes-and-fallacies]] - the catalogue of failures worth injecting.
- [[slis-slos-error-budgets]] - steady-state metrics and the budget experiments spend.
- [[incident-response-and-postmortems]] - game days rehearse the incident process; postmortems feed new experiments.
- [[observability-logs-metrics-traces]] - you need it to see the steady state and the fault.
- [[performance-and-load-testing]] - load plus faults shows behaviour under stress.
- [[backup-and-disaster-recovery]] - restore and failover drills are experiments too.
- [[kubernetes-basics]] - pod and node failures are the most common first experiments.

## References
- Principles of Chaos Engineering: https://principlesofchaos.org/
- Casey Rosenthal and Nora Jones, *Chaos Engineering: System Resiliency in Practice*, O'Reilly, 2020.
- Netflix Chaos Monkey: https://netflix.github.io/chaosmonkey/
- AWS Fault Injection Service user guide: https://docs.aws.amazon.com/fis/latest/userguide/what-is.html
- Azure Chaos Studio overview: https://learn.microsoft.com/en-us/azure/chaos-studio/chaos-studio-overview
- Chaos Mesh documentation: https://chaos-mesh.org/docs/
- LitmusChaos: https://litmuschaos.io/
- Toxiproxy: https://github.com/Shopify/toxiproxy
