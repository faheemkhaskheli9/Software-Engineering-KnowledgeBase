---
title: Deployment strategies - rolling, blue-green, canary, feature flags
category: reliability
tags: [deployment, release, rolling-update, blue-green, canary, feature-flags, rollback, zero-downtime]
use_cases:
  - ship a new version without downtime and be able to roll back fast
  - release a risky change to 1 percent of users first
  - deploy a database schema change alongside application code safely
  - decouple deploying code from releasing a feature to users
  - choose between blue-green and canary for a customer-facing API
status: draft
last_verified: 2026-10-10
sources:
  - https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
  - https://martinfowler.com/bliki/BlueGreenDeployment.html
  - https://martinfowler.com/bliki/CanaryRelease.html
  - https://martinfowler.com/articles/feature-toggles.html
  - https://sre.google/workbook/canarying-releases/
  - Continuous Delivery (Humble, Farley), Addison-Wesley
---

# Deployment strategies - rolling, blue-green, canary, feature flags

## Summary
A deployment strategy defines how a new version replaces the old one and how you limit the damage if it is bad. The main options are recreate, rolling update, blue-green, canary and progressive delivery, and feature flags that separate deploy (code on servers) from release (users see it). The right choice balances rollback speed, infrastructure cost and how well you can detect problems.

## Key concepts
- **Deploy vs release**: deploy puts code in production; release exposes behavior to users. Feature flags make these independent.
- **Recreate**: stop old, start new. Simple, has downtime. Fine for internal tools and batch.
- **Rolling update**: replace instances gradually (max surge / max unavailable). Default in Kubernetes. Old and new versions run side by side, so they must be compatible.
- **Blue-green**: two full environments; switch traffic from blue (old) to green (new) at the router. Instant rollback by switching back; doubles infrastructure during the switch.
- **Canary**: send a small slice of traffic (1-5%) to the new version, compare error rate and latency against baseline, then ramp up or abort.
- **Progressive delivery**: automate canary analysis and ramp steps from metrics (Argo Rollouts, Flagger, cloud-native equivalents).
- **Shadow / dark launch**: mirror production traffic to the new version without returning its responses; validates behavior and load with no user risk.
- **Expand/contract (parallel change)**: make schema and API changes backward compatible in steps so every intermediate state works with both versions (see [[schema-migrations]]).
- **Rollback vs roll-forward**: rollback restores the previous artifact; roll-forward ships a fix. Rollback only works if data changes are compatible.

## When to use / scenarios
- Stateless web/API service with decent metrics: rolling by default, canary for risky or high-traffic changes.
- Need near-instant rollback and can afford duplicate capacity: blue-green.
- Large user base where a bad release is costly: canary with automated analysis tied to SLO signals (see [[slis-slos-error-budgets]]).
- Incomplete feature, long-lived branch, or A/B experiment: feature flag instead of a branch.
- Stateful or schema-dependent change: expand/contract migration plus a flag; never couple the schema change and code change in one atomic step.
- When NOT to use canary: no metrics or too little traffic to detect a regression statistically; use blue-green or staged rollout with manual verification.

## How it works / example

```
Rolling:      [v1 v1 v1 v1] -> [v2 v1 v1 v1] -> [v2 v2 v1 v1] -> [v2 v2 v2 v2]
Blue-green:   LB -> blue(v1)  ... deploy green(v2), smoke test ... LB -> green(v2); keep blue for rollback
Canary:       LB -> 95% v1 / 5% v2 -> analyze -> 25% -> 50% -> 100%   (abort => 0% v2)
```

Kubernetes rolling update with a readiness gate (zero downtime requires readiness probes and graceful shutdown):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: orders-api}
spec:
  replicas: 6
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  selector: {matchLabels: {app: orders-api}}
  template:
    metadata: {labels: {app: orders-api}}
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: app
          image: registry.example.com/orders-api:1.8.2
          readinessProbe:
            httpGet: {path: /readyz, port: 8080}
            periodSeconds: 5
          lifecycle:
            preStop:
              exec: {command: ["sleep", "5"]}   # let endpoints drain before SIGTERM handling
```

Roll back with `kubectl rollout undo deployment/orders-api`.

Percentage-based feature flag in Python (stable bucketing so a user keeps the same experience):

```python
import hashlib

def flag_enabled(flag: str, user_id: str, percent: int) -> bool:
    h = hashlib.sha256(f"{flag}:{user_id}".encode()).digest()
    bucket = int.from_bytes(h[:4], "big") % 100
    return bucket < percent

# Same user always lands in the same bucket, so their experience is stable.
enabled = sum(flag_enabled("new-checkout", f"user-{i}", percent=5) for i in range(10_000))
print(f"{enabled / 100:.1f}% of users see the new checkout")  # ~5%
assert flag_enabled("new-checkout", "user-42", 5) == flag_enabled("new-checkout", "user-42", 5)
```

Safe database change sequence (expand/contract):
1. Add the new column/table (nullable, no constraints that break old code).
2. Deploy code that writes both old and new, reads old.
3. Backfill; switch reads to new behind a flag.
4. Deploy code that stops using the old column.
5. Drop the old column in a later release.

Release checklist: automated tests and image scan pass (see [[ci-cd-pipelines]]), canary metrics healthy for a set bake time, dashboards and alerts watched by the person deploying, one-command rollback known and rehearsed.

## Trade-offs
- **Speed vs safety**: bigger ramp steps and shorter bake times ship faster but expose more users to a bad build.
- **Blue-green cost vs canary complexity**: blue-green needs double capacity and a clean switch; canary needs traffic splitting, good metrics and comparison logic.
- **Version skew**: rolling and canary run two versions concurrently; blue-green avoids skew at the instant of switch but sessions and in-flight work still straddle it.
- **Flags vs branches**: flags allow trunk-based development and instant kill switches but accumulate as dead code and combinatorial test states.
- **Automated vs manual promotion**: automation is consistent but needs trustworthy signals; manual gates catch odd cases but slow everything.
- **Per-region staging**: deploying one region at a time limits blast radius at the cost of a longer rollout.

## Gotchas
- Without a readiness probe, the platform sends traffic to pods that are not ready; rolling updates then cause errors.
- Shutdown without draining connections drops in-flight requests; handle SIGTERM, stop accepting new work, finish current, then exit.
- Rollback fails when the new version already migrated data in an incompatible way. Make migrations backward compatible first.
- Canary compared against the wrong baseline (global average rather than same-time stable instances) gives false signals; compare concurrently running populations.
- Sticky sessions and caches can pin users to one version or serve a mix of incompatible payloads.
- Feature flags left forever become permanent branches; give each an owner and a removal date, and delete after full rollout.
- Deploying on Friday afternoon with nobody watching is a process failure, not a strategy; deploy when people can respond.
- Config and secrets changes are deployments too; roll them with the same discipline.
- Mobile and client apps cannot be rolled back; keep server APIs compatible with old clients (see [[api-versioning-and-evolution]]).

## Related
- [[ci-cd-pipelines]] - the pipeline that builds, tests and triggers these rollouts.
- [[kubernetes-basics]] - rolling updates, probes and rollout commands live here.
- [[schema-migrations]] - expand/contract migrations that make rollbacks safe.
- [[slis-slos-error-budgets]] - canary analysis should use SLO-style signals.
- [[api-versioning-and-evolution]] - keeping old clients working during and after rollout.
- [[incident-response-and-postmortems]] - rollback is usually the first mitigation in an incident.

## References
- Kubernetes Deployments (rolling update, rollback): https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Martin Fowler, BlueGreenDeployment and CanaryRelease: https://martinfowler.com/bliki/BlueGreenDeployment.html and https://martinfowler.com/bliki/CanaryRelease.html
- Pete Hodgson, Feature Toggles: https://martinfowler.com/articles/feature-toggles.html
- Google SRE Workbook, "Canarying Releases": https://sre.google/workbook/canarying-releases/
- Humble and Farley, Continuous Delivery (Addison-Wesley).
