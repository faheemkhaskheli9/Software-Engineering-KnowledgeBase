---
title: SLIs, SLOs and error budgets
category: reliability
tags: [sre, slo, sli, sla, error-budget, burn-rate, availability, alerting]
use_cases:
  - define a reliability target for a new service and decide how reliable it needs to be
  - decide whether to ship a risky feature or freeze releases to fix reliability
  - replace noisy threshold alerts with alerts based on user impact
  - write an SLA for customers without promising more than the system can deliver
  - argue with product about how many nines we actually need
status: stable
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/service-level-objectives/
  - https://sre.google/workbook/implementing-slos/
  - https://sre.google/workbook/alerting-on-slos/
  - https://sre.google/sre-book/embracing-risk/
  - Site Reliability Engineering (Beyer et al.), O'Reilly
---

# SLIs, SLOs and error budgets

## Summary
An SLI is a measured indicator of service health from the user's perspective (for example the fraction of requests that succeed fast enough). An SLO is the target for that SLI over a window (99.9% over 30 days). The error budget is 100% minus the SLO: the amount of unreliability you are allowed to spend, which turns reliability versus feature velocity into a measurable, shared decision.

## Key concepts
- **SLI**: a ratio of good events to valid events, expressed as a percentage. Good SLIs sit close to user experience: request success, latency under a threshold, freshness, correctness, durability.
- **SLO**: an internal target for an SLI over a rolling window (28 or 30 days is common). It is a goal, not a promise.
- **SLA**: a contractual commitment with consequences (credits, penalties). Set it looser than the SLO so you notice trouble before breaching the contract.
- **Error budget**: `1 - SLO`. At 99.9% over 30 days that is about 43 minutes of full downtime equivalent, or the same share of failed requests.
- **Burn rate**: how fast the budget is consumed relative to plan. Burn rate 1 uses exactly the whole budget by the window end; 14.4 uses 2% of a 30-day budget in one hour.
- **Multi-window multi-burn-rate alerts**: page when both a short and a long window show fast burn; ticket on slow burn. Gives fast detection without flapping.
- **Error budget policy**: a written agreement on what happens when the budget is spent (freeze feature releases, prioritize reliability work) and who can override.
- **Nines are expensive**: each extra nine costs roughly an order of magnitude more effort, and your service cannot exceed the reliability of its hard dependencies.

## When to use / scenarios
- Any user-facing or revenue-affecting service with an owner who can act on the signal.
- Teams stuck in "reliability vs features" arguments: the budget gives a neutral rule.
- Replacing alerts on CPU, queue depth and pod restarts with alerts on user impact (see [[observability-logs-metrics-traces]]).
- Setting expectations with dependent teams: publish SLOs per service so callers can design retries and fallbacks (see [[resilience-patterns]]).
- When NOT to: prototypes with no users, or batch jobs where a simpler "finished by 06:00" check is enough. Do not set an SLO nobody will act on.

## How it works / example

Choosing SLIs by service type:

| Service type | Typical SLIs |
|---|---|
| Request/response API | availability (non-5xx / total), latency (fraction under threshold) |
| Data pipeline | freshness (age of newest data), correctness, throughput |
| Storage | durability, availability, latency of reads/writes |

Example definition (write it down, versioned next to the code):

```yaml
service: checkout-api
slis:
  availability:
    good:  http_requests_total{route="/checkout", status!~"5.."}
    valid: http_requests_total{route="/checkout"}      # exclude health checks, 4xx caused by client
  latency:
    good:  http_request_duration_seconds_bucket{route="/checkout", le="0.3"}
    valid: http_request_duration_seconds_count{route="/checkout"}
slos:
  - sli: availability
    target: 99.9
    window: 30d
  - sli: latency
    target: 95        # 95% of requests under 300 ms
    window: 30d
```

Budget arithmetic in Python:

```python
def allowed_downtime_minutes(slo_pct: float, window_days: int = 30) -> float:
    return (1 - slo_pct / 100) * window_days * 24 * 60

def burn_rate(bad_ratio_observed: float, slo_pct: float) -> float:
    return bad_ratio_observed / (1 - slo_pct / 100)

assert round(allowed_downtime_minutes(99.9)) == 43      # 43.2 min per 30 days
assert round(burn_rate(0.0144, 99.9), 1) == 14.4        # 1.44% errors => 14.4x burn
```

Burn-rate alerting recipe (from the SRE Workbook): page when burn rate over 1h and 5m are both above 14.4; page at 6 over 6h and 30m; ticket at 1 over 3d and 6h. The short window makes the alert reset quickly after recovery.

Error budget policy sketch:
1. Budget remaining above 0: normal releases.
2. Budget exhausted: freeze non-critical releases; engineering time goes to reliability until the window recovers.
3. A single incident consuming more than 20% of budget requires a postmortem with action items (see [[incident-response-and-postmortems]]).

## Trade-offs
- **Tighter SLO vs velocity and cost**: higher targets need redundancy, slower rollouts and more on-call load. Choose the loosest target users will not notice.
- **Rolling vs calendar window**: rolling is smoother and avoids end-of-month cliffs; calendar matches contracts and reporting.
- **Per-request vs time-based availability**: request-based SLIs handle uneven traffic well; time-based ("minutes up") is easier to explain but misleads at low traffic.
- **Few SLOs vs many**: two or three per service that people remember beat twenty nobody reads.
- **Measure at the load balancer vs client**: LB is easy and reliable, client-side is closer to truth but harder to collect and noisier.

## Gotchas
- Measuring from inside the service misses total outages (a dead service emits no errors). Measure at an edge, a load balancer or a synthetic prober.
- Counting 4xx caused by bad client input as failures punishes you for user mistakes; counting everything as success hides real faults. Define "valid" and "good" explicitly.
- Dependencies cap you: a 99.99% target on top of a 99.9% database is fiction without caching or degradation paths.
- 100% is the wrong target; it forbids all change and cannot be measured honestly.
- An SLO with no consequence (no budget policy) is decoration. Get product and engineering to sign the policy before you need it.
- Averaging latency instead of using a threshold or percentile SLI hides the slow tail.
- Do not reuse the SLA as the SLO; you want warning headroom.
- Low-traffic services have noisy ratios; a single failure at 3am can burn a large share. Use longer windows or synthetic traffic.

## Related
- [[observability-logs-metrics-traces]] - the telemetry SLIs are computed from.
- [[incident-response-and-postmortems]] - budget burn triggers incident process and review.
- [[deployment-strategies]] - canaries and rollbacks protect the budget.
- [[resilience-patterns]] - the techniques that keep a service inside its SLO when dependencies degrade.
- [[capacity-planning-and-autoscaling]] - saturation is a common cause of budget burn.
- [[browser-rendering-and-core-web-vitals]] - Core Web Vitals at p75 as front-end SLIs.

## References
- Google SRE Book, ch. 4 "Service Level Objectives": https://sre.google/sre-book/service-level-objectives/
- Google SRE Workbook, "Implementing SLOs" and "Alerting on SLOs": https://sre.google/workbook/implementing-slos/ and https://sre.google/workbook/alerting-on-slos/
- Google SRE Book, ch. 3 "Embracing Risk": https://sre.google/sre-book/embracing-risk/
