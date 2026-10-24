---
title: Cloud cost optimization (FinOps)
category: reliability
tags: [finops, cloud-cost, cost-optimization, rightsizing, spot-instances, savings-plans, reserved-instances, unit-economics, tagging, egress, storage-tiering]
use_cases:
  - "the cloud bill grew faster than traffic and nobody knows which team or feature drives it"
  - "decide how much compute to cover with reserved capacity or savings plans"
  - "cut cost of idle, oversized or forgotten resources without hurting reliability"
  - "run batch or CI workloads on spot or preemptible instances safely"
  - "estimate the cost per request, per customer or per tenant of a new design"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.finops.org/framework/
  - https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html
  - https://cloud.google.com/architecture/framework/cost-optimization
  - https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/
  - https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-interruptions.html
  - https://docs.aws.amazon.com/savingsplans/latest/userguide/what-is-savings-plans.html
  - https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html
---

# Cloud cost optimization (FinOps)

## Summary
Cloud cost is an engineering property like latency: every architecture choice
sets it, and it drifts upward unless someone measures it. FinOps is the
practice of making spend visible per team, service and customer (allocation),
comparing it to business output (unit economics), and then reducing waste
(idle and oversized resources), paying less per unit (commitments, spot,
cheaper tiers) and changing architecture where the big costs are (data
transfer, storage growth, chatty designs). Do it continuously, with engineers
who own the services making the trade-offs against reliability and speed.

## Key concepts
- **FinOps lifecycle** (FinOps Foundation): *inform* (visibility and
  allocation), *optimize* (rates and usage), *operate* (continuous governance),
  repeated in iterations rather than a one-off cleanup.
- **Allocation**: tags or labels (team, service, environment, tenant) applied
  by infrastructure as code and enforced by policy, plus rules for shared
  costs (clusters, networking, support) so every unit of spend has an owner.
- **Unit economics**: cost per request, per active user, per order, per GB
  processed. A rising bill with a falling unit cost is growth; a rising unit
  cost is a regression.
- **Usage optimization**: delete idle resources (unattached volumes, old
  snapshots, unused IPs, idle load balancers, forgotten test environments),
  rightsize from observed utilization, schedule non-production off-hours,
  autoscale to demand.
- **Rate optimization**: commitment discounts (reserved instances, savings
  plans, committed-use discounts) for the steady baseline; spot/preemptible
  capacity for interruptible work; on-demand for the variable top.
- **Spot / preemptible instances**: spare capacity at a discount that the
  provider can reclaim; AWS gives a two-minute interruption notice. Only for
  stateless, checkpointed or retryable work.
- **Data transfer**: inbound traffic is usually free while egress to the
  internet, between regions and often between availability zones is charged;
  it hides in chatty microservices, cross-AZ replication and NAT gateways.
- **Storage lifecycle**: move cold objects to cheaper tiers and expire them
  with lifecycle rules; set log and metric retention deliberately.
- **Cost as a non-functional requirement**: estimate cost in design reviews,
  show it on dashboards next to SLOs, alert on anomalies.

## When to use / scenarios
- The bill is large or growing faster than usage, or finance asks "which
  feature costs this" and nobody can answer: start with allocation and unit
  cost, not with discounts.
- Stable baseline load running on on-demand pricing: commitments for the part
  that is reliably used.
- Batch jobs, CI runners, rendering, ML training with checkpoints: spot.
- Multi-tenant SaaS pricing decisions: cost per tenant from allocation tags or
  usage metering ([[choosing-a-multi-tenancy-model]]).
- When NOT to prioritize it: tiny bills where engineering time costs more than
  the savings, or before product-market fit; still tag from day one, because
  retrofitting allocation is expensive.

## How it works / example
Three calculations that drive most decisions: how much baseline to commit,
whether a commitment pays off, and how to rightsize from utilization.

```python
import math

def commitment_breakeven(discount: float) -> float:
    """Minimum utilization of committed capacity for it to beat on-demand.
    Committed cost = (1 - discount) * on_demand, paid whether used or not."""
    return 1 - discount

def commit_level(hourly_usage: list[float], discount: float) -> float:
    """Choose the commitment (units/hour) that minimizes total cost.
    Each hour: pay the commitment, plus on-demand for usage above it."""
    candidates = sorted(set(hourly_usage)) + [0.0]
    def cost(c: float) -> float:
        return sum((1 - discount) * c + max(0.0, u - c) for u in hourly_usage)
    return min(candidates, key=cost)

def rightsize(p95_cpu: float, vcpus: int, target: float = 0.6) -> int:
    """Smallest power-of-two vCPU count keeping p95 utilization under target."""
    needed = p95_cpu * vcpus / target
    size = 1
    while size < needed:
        size *= 2
    return size

def unit_cost(monthly_cost: float, monthly_units: int) -> float:
    return monthly_cost / monthly_units

# A daily curve: 4 quiet hours at 10 units, 16 busy at 30, 4 peak at 50.
day = [10.0] * 4 + [30.0] * 16 + [50.0] * 4
assert math.isclose(commitment_breakeven(0.3), 0.7)
best = commit_level(day, discount=0.3)
assert best == 30.0          # units 10-30 run 20 of 24 h (above 70%); 30-50 only 4 h
on_demand = sum(day)
committed = sum((1 - 0.3) * best + max(0.0, u - best) for u in day)
assert committed < on_demand
print(f"commit {best}/h saves {1 - committed / on_demand:.0%} vs on-demand")

assert rightsize(p95_cpu=0.20, vcpus=16) == 8    # oversized: halve it
assert rightsize(p95_cpu=0.75, vcpus=4) == 8     # hot: grow it
assert math.isclose(unit_cost(12_000.0, 3_000_000), 0.004)  # per request
```

Typical order of work, cheapest and safest first:

| Step | Examples | Risk |
|---|---|---|
| See it | tags, per-team dashboards, budgets, anomaly alerts | none |
| Delete waste | idle volumes, snapshots, test stacks, old images | low, with owner sign-off |
| Schedule and autoscale | stop dev at night, scale to demand | low |
| Rightsize | smaller instances, lower requests/limits in k8s | medium: watch SLOs |
| Change rates | commitments for baseline, spot for batch | financial lock-in, interruption |
| Change architecture | cut cross-AZ chatter, cache, tier storage, compress | engineering effort |

## Trade-offs
- **Commitment depth vs flexibility**: committing more saves more per unit
  but locks spend for one or three years; architecture changes (new instance
  families, serverless, a region move) can strand it. Commit only to the
  floor you are confident in; flexible plan types cost a smaller discount.
- **Rightsizing vs headroom**: smaller instances cut cost but leave less
  buffer for spikes and failover; size against SLOs and N+1 capacity, not
  average utilization ([[capacity-planning-and-autoscaling]]).
- **Spot savings vs interruption**: big discounts for work that tolerates
  being killed; diversify instance types and zones, checkpoint, and keep an
  on-demand fallback for deadlines.
- **Managed services vs self-hosting**: a managed database or queue usually
  costs more per unit of compute than running it yourself, and much less in
  engineer time and incidents.
- **Multi-AZ and multi-region vs data transfer**: redundancy multiplies
  compute and adds replication traffic; that is the price of availability, so
  decide it from the availability target, not by default.

## Gotchas
- Untagged resources and shared clusters make allocation impossible; enforce
  tags at creation time in IaC and policy, not by later cleanup.
- Looking at the total bill instead of unit cost: a successful launch looks
  like a cost problem.
- NAT gateway processing and cross-AZ traffic often appear as large lines
  nobody designed for; check data transfer before rightsizing compute.
- Deleting "unused" resources without checking owners deletes someone's
  disaster-recovery snapshot ([[backup-and-disaster-recovery]]).
- Logs and metrics with default or unlimited retention grow without bound;
  high-cardinality metric labels multiply series count and cost.
- Kubernetes requests far above real usage waste whole nodes even when pods
  look idle; the scheduler reserves what pods request.
- Serverless is cheap at low, spiky volume and can be expensive at high,
  steady volume; recompute when traffic shape changes ([[serverless-architecture]]).
- Savings that degrade an SLO are not savings; track cost and reliability on
  the same dashboard.

## Related
- [[capacity-planning-and-autoscaling]] - how much capacity is needed, which cost work then prices.
- [[serverless-architecture]] - pay-per-use pricing and when it stops being cheap.
- [[blob-object-storage]] - storage classes and lifecycle rules for cold data.
- [[kubernetes-basics]] - requests, limits and cluster autoscaling that set node count.
- [[infrastructure-as-code]] - where tags and cost policies are enforced.
- [[multi-region-architecture]] - the compute and transfer cost of redundancy.
- [[observability-logs-metrics-traces]] - retention and cardinality as cost drivers.
- [[back-of-envelope-estimation]] - quick sizing to estimate cost in design reviews.

## References
- FinOps Foundation, "FinOps Framework" (finops.org).
- AWS Well-Architected Framework, "Cost Optimization Pillar".
- Google Cloud Architecture Framework, "Cost optimization".
- Microsoft Azure Well-Architected Framework, "Cost Optimization".
- AWS documentation: "Spot Instance interruptions", "What are Savings Plans?", "Managing the lifecycle of objects" (Amazon S3).
- J.R. Storment and Mike Fuller, *Cloud FinOps* (2nd ed., O'Reilly, 2023).
