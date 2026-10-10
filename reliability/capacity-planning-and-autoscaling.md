---
title: Capacity planning and autoscaling
category: reliability
tags: [capacity-planning, autoscaling, hpa, scaling, headroom, load-testing, saturation, cost]
use_cases:
  - decide how many instances a service needs for expected traffic plus headroom
  - configure autoscaling so a traffic spike does not cause an outage
  - prepare for a launch or sale event with 10x expected load
  - stop autoscaling from flapping or running up the cloud bill
  - choose between scaling up and scaling out for a database or API tier
status: draft
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/software-engineering-in-sre/
  - https://sre.google/workbook/managing-load/
  - https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
  - https://docs.aws.amazon.com/autoscaling/ec2/userguide/what-is-amazon-ec2-auto-scaling.html
  - https://keda.sh/docs/
  - Systems Performance, 2nd ed. (Brendan Gregg), Addison-Wesley
---

# Capacity planning and autoscaling

## Summary
Capacity planning is predicting how much compute, memory, storage and network a system needs to meet its SLOs at forecast demand plus headroom; autoscaling adjusts that capacity automatically as load changes. Use planning for the baseline, limits and long-lead items (databases, quotas, procurement), and autoscaling for the elastic stateless tier, always validated by load tests rather than guesses.

## Key concepts
- **Demand drivers**: requests per second, concurrent users, data growth, batch sizes. Translate business forecasts into these.
- **Per-unit capacity**: how much load one instance sustains while still meeting latency SLOs, found by load testing (see [[performance-and-load-testing]]). Capacity is where latency degrades, not where the CPU hits 100%.
- **Headroom / N+1 / N+2**: spare capacity so a failed instance, zone or deploy does not push survivors over the edge. Plan for losing a zone while serving peak.
- **Saturation**: the resource (CPU, memory, connections, disk IOPS, queue depth, thread pool) that hits its limit first. Find the bottleneck; scaling a non-bottleneck tier does nothing.
- **Little's Law**: concurrency = arrival rate x latency. Estimates required workers or connections.
- **Horizontal vs vertical scaling**: add instances (scale out) vs bigger instances (scale up). Out scales further and adds redundancy; up is simpler for stateful or single-writer systems.
- **Scaling signals**: CPU, memory, request rate per instance, queue depth/lag, custom latency or concurrency metrics. Pick a signal that leads load and correlates with capacity.
- **Reactive vs scheduled vs predictive scaling**: reactive follows metrics (always late by the scale-up lead time), scheduled handles known patterns (9am login surge), predictive uses forecasts.
- **Cooldown / stabilization**: delays that prevent oscillation (flapping).
- **Warm-up time**: instance start + app boot + cache warm-up + health check. Autoscaling only helps if this is shorter than the spike's ramp.

## When to use / scenarios
- Variable or spiky traffic on a stateless tier (web/API workers, consumers): autoscale.
- Predictable peaks (business hours, nightly batch): scheduled scaling plus a reactive safety net.
- Queue-driven workers: scale on queue depth or consumer lag rather than CPU (see [[message-queues-and-streams]]).
- Launches, sales, campaigns: pre-scale explicitly and load test; do not trust reactive scaling to catch a step change.
- Stateful tiers (databases, caches, Kafka brokers): plan capacity ahead; scaling is slow, risky and often needs re-partitioning (see [[partitioning-and-sharding]]).
- When NOT to autoscale: tiny steady workloads (fixed size is cheaper and simpler), or systems whose bottleneck is a fixed downstream (a database that cannot absorb more connections) where more app instances just amplify the overload.

## How it works / example

Back-of-envelope sizing (see [[back-of-envelope-estimation]]):

```python
import math

peak_rps          = 1200      # from forecast, measured in production or from analytics
per_instance_rps  = 150       # sustained at p99 under SLO, from a load test
target_util       = 0.6       # leave headroom for bursts and deploys
zones             = 3         # must survive losing one zone

needed = math.ceil(peak_rps / (per_instance_rps * target_util))        # steady-state instances
with_zone_loss = math.ceil(needed * zones / (zones - 1))               # survivors carry the load
print(needed, with_zone_loss)    # 14 -> 21 with these assumptions
```

Little's Law for pool sizing: at 1200 req/s and 80 ms average service time, concurrent in-flight requests are about 1200 x 0.08 = 96. Size worker threads, DB connection pools and limits from this, not from instinct.

Kubernetes HPA with sane behavior (fast up, slow down):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: orders-api}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: orders-api}
  minReplicas: 6                       # baseline covers N+1 and zone loss
  maxReplicas: 40                      # cost and downstream protection
  metrics:
    - type: Resource
      resource: {name: cpu, target: {type: Utilization, averageUtilization: 60}}
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies: [{type: Percent, value: 100, periodSeconds: 60}]
    scaleDown:
      stabilizationWindowSeconds: 300
      policies: [{type: Percent, value: 20, periodSeconds: 60}]
```

Related building blocks: Cluster Autoscaler/Karpenter add nodes when pods are unschedulable; KEDA scales on event sources (queue length, Kafka lag, cron); VPA right-sizes requests (avoid combining VPA and HPA on the same CPU/memory metric); cloud target-tracking policies (for example on average CPU or request count per target) work the same way for VM groups.

Planning routine:
1. Establish current peaks and growth trend from metrics (see [[observability-logs-metrics-traces]]).
2. Convert business forecasts (marketing event, new region) into load multipliers.
3. Load test to find per-instance capacity and the first bottleneck; fix it, repeat.
4. Size baseline for peak plus failure headroom; set autoscaler min/max around it.
5. Check quotas and lead times (cloud limits, IP ranges, database connection caps, third-party rate limits).
6. Review quarterly and before major events; record assumptions so surprises are visible.

## Trade-offs
- **Cost vs headroom**: more idle capacity buys safety; higher utilization saves money and shrinks failure tolerance. Pick per tier by how costly an outage is.
- **Aggressive vs conservative scale-down**: fast scale-down saves money but risks being undersized for the next burst and causes flapping; scale down slowly.
- **Reactive speed vs warm capacity**: shorter boot times (small images, lazy init) or warm pools reduce reliance on over-provisioning.
- **CPU vs custom metrics**: CPU is easy but a poor proxy for I/O-bound services; request concurrency or queue depth tracks real load better but needs instrumentation.
- **Spot/preemptible vs on-demand**: much cheaper but interruptible; fine for stateless, retry-tolerant work with an on-demand floor.
- **Scale up vs out for databases**: bigger primary is simplest until limits; read replicas help reads only; sharding is a major architectural step.

## Gotchas
- Scaling the web tier into a fixed-size database: connections and locks become the new bottleneck and the outage gets worse. Cap max replicas and use connection pooling.
- Autoscaler lag: by the time metrics cross the threshold and instances boot, the spike may have already caused errors. Keep a buffer or pre-scale.
- Scaling on average CPU hides hot instances; load balancing imbalance and uneven partitions matter (see [[load-balancing]]).
- Percentage targets in HPA are relative to requests; wrong or missing requests make scaling nonsense.
- Flapping from too-short windows, or from metrics that react to the scaling itself.
- Scale-in kills in-flight work. Drain connections and handle SIGTERM; for workers, finish or requeue jobs.
- Retry storms during overload make capacity needs jump; pair with load shedding and backoff (see [[resilience-patterns]]).
- Forgetting non-compute limits: file descriptors, ephemeral ports, NAT gateway throughput, API rate limits, IP address exhaustion, log ingestion limits.
- Assuming linear scaling; contention, locks and coordination give diminishing returns (Amdahl and Universal Scalability Law behavior).
- Cost blindness: unbounded max replicas plus a bug or attack can create a very large bill. Set budgets and alarms.

## Related
- [[performance-and-load-testing]] - how to measure per-instance capacity and find bottlenecks.
- [[back-of-envelope-estimation]] - quick sizing math for initial plans.
- [[kubernetes-basics]] - HPA, requests/limits and cluster autoscaling mechanics.
- [[load-balancing]] - even distribution is a prerequisite for scaling out.
- [[rate-limiting]] - protecting capacity from abusive or runaway clients.
- [[slis-slos-error-budgets]] - saturation-driven budget burn is the signal planning is missing.

## References
- Google SRE Workbook, "Managing Load": https://sre.google/workbook/managing-load/
- Kubernetes Horizontal Pod Autoscaling: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- AWS EC2 Auto Scaling: https://docs.aws.amazon.com/autoscaling/ec2/userguide/what-is-amazon-ec2-auto-scaling.html
- KEDA documentation: https://keda.sh/docs/
- Brendan Gregg, Systems Performance, 2nd ed. (Addison-Wesley).
