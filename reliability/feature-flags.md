---
title: Feature flags
category: reliability
tags: [feature-flags, feature-toggles, kill-switch, percentage-rollout, experiments, openfeature, trunk-based-development]
use_cases:
  - "merge unfinished features to main without exposing them to users"
  - "roll a new checkout out to 10 percent of users and keep each user's experience stable"
  - "add a kill switch to turn off an expensive feature during an incident without a deploy"
  - "clean up hundreds of stale feature flags in a codebase"
  - "switch feature flag vendors without rewriting every call site"
status: draft
last_verified: 2026-10-11
sources:
  - https://martinfowler.com/articles/feature-toggles.html
  - https://openfeature.dev/specification/
  - https://openfeature.dev/docs/reference/intro
  - https://martinfowler.com/bliki/CanaryRelease.html
---

# Feature flags

## Summary
A feature flag (feature toggle) is a runtime decision point that switches code
paths without redeploying, which separates deploying code from releasing
behavior. Flags enable trunk-based development, gradual rollouts, kill
switches, experiments and per-customer entitlements. Each flag is also a branch
in production code with a carrying cost, so flags need an owner, a type and a
removal plan.

## Key concepts
- **Toggle categories** (Pete Hodgson, "Feature Toggles"):
  - *Release toggles*: hide incomplete or untested work; transitory, usually
    removed within a week or two; static per release.
  - *Experiment toggles*: A/B and multivariate tests; per-request decisions by
    cohort; live long enough for statistically significant results.
  - *Ops toggles*: operational control such as kill switches and degrading
    expensive features; must be flippable quickly at runtime; mostly short
    lived, a few long-lived kill switches.
  - *Permissioning toggles*: premium, beta or internal-only features per user;
    can live for years; very dynamic.
- **Toggle point / toggle router**: the `if` in the code is the toggle point;
  the logic that decides (config, targeting rules, percentages) belongs in one
  router or "feature decisions" object, so call sites ask a named question.
- **Evaluation context**: the attributes a decision uses (user id, tenant,
  country, app version).
- **Deterministic percentage rollout**: hash `flag key + user id` into a bucket
  0-99 and enable when `bucket < percent`. The same user always gets the same
  answer, raising the percentage only adds users, and different flags use
  independent buckets.
- **Kill switch**: an ops toggle that disables a feature or dependency in
  seconds; a standard incident mitigation.
- **Flag debt**: stale flags left in code after full rollout. Hodgson lists
  removal tasks in the backlog, expiration dates, "time bombs" (tests that
  fail past the expiry date) and a cap on live flags.
- **OpenFeature**: a vendor-neutral flag evaluation API and SDK specification,
  a CNCF incubating project. Application code calls the evaluation API; a
  *provider* resolves values from a particular flag system; *hooks* add
  logging, metrics or validation around evaluation.

## When to use / scenarios
- Trunk-based development with work that spans several merges: release
  toggle, default off.
- Risky change with good metrics: percentage rollout, ramped while watching
  error rate and latency (the flag-based form of a canary, see
  [[deployment-strategies]]).
- Expensive or fragile dependency (recommendations, search suggestions, a
  third-party API): ops kill switch that falls back to a cheaper path.
- Product experiment: experiment toggle feeding an analysis pipeline.
- Plan-based features: permissioning toggles, though a long-lived entitlement
  often belongs in the authorization model instead (see
  [[authorization-models]]).
- When NOT to use: a change that is easier to ship whole and roll back;
  database schema changes (use expand/contract in [[schema-migrations]], with a
  flag only for the read/write switch); security controls that must never be
  disabled.

## How it works / example

```
call site -> decide("new-checkout", ctx) -> router
                                        |- kill switch on?      -> False
                                        |- explicit allow list? -> True
                                        |- percentage bucket    -> bucket < pct
                                        '- default              -> False
```

Deterministic bucketing with the properties a rollout depends on:

```python
import hashlib

def bucket(flag: str, user_id: str) -> int:
    """Stable 0-99 bucket per (flag, user); independent across flags."""
    digest = hashlib.sha256(f"{flag}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100

def is_enabled(flag: str, user_id: str, percent: int, killed: bool = False) -> bool:
    if killed:
        return False
    return bucket(flag, user_id) < percent

users = [f"user-{i}" for i in range(20_000)]

# Stable: the same user gets the same answer on every evaluation and server.
assert all(is_enabled("new-checkout", u, 30) == is_enabled("new-checkout", u, 30) for u in users[:500])

# Roughly proportional to the percentage.
on = sum(is_enabled("new-checkout", u, 30) for u in users) / len(users)
assert 0.28 < on < 0.32, on

# Monotonic: raising 10 -> 30 -> 60 percent only adds users, never flips anyone off.
at10 = {u for u in users if is_enabled("new-checkout", u, 10)}
at30 = {u for u in users if is_enabled("new-checkout", u, 30)}
at60 = {u for u in users if is_enabled("new-checkout", u, 60)}
assert at10 <= at30 <= at60

# Independent per flag: the same 10% does not get every experiment.
other = {u for u in users if is_enabled("new-search", u, 10)}
assert len(at10 & other) < len(at10) / 2

# Kill switch wins over the rollout.
assert not any(is_enabled("new-checkout", u, 100, killed=True) for u in users[:100])
print(f"{on:.1%} enabled at 30%")
```

With OpenFeature the call site stays the same whichever vendor or in-house
service is the provider (`pip install openfeature-sdk`):

```python fragment
from openfeature import api
from openfeature.evaluation_context import EvaluationContext

client = api.get_client()          # provider registered once at start-up
ctx = EvaluationContext(targeting_key=user.id, attributes={"plan": user.plan})
if client.get_boolean_value("new-checkout", False, ctx):   # False = safe default
    render_new_checkout()
else:
    render_old_checkout()
```

Lifecycle that keeps debt down: create the flag with an owner, type and
expiry; ramp; reach 100 percent; delete the flag and the dead branch in code;
then delete it from the flag service.

## Trade-offs
- **Flags vs branches**: flags keep everyone on trunk and make rollback
  instant, at the cost of more code paths in production and in tests.
- **Static config vs dynamic service**: flags in a config file are simple,
  reviewable and need a deploy to change; a flag service changes behavior in
  seconds but is a runtime dependency and a powerful, auditable control plane.
- **Server-side vs client-side evaluation**: evaluating in the client (browser,
  mobile) is fast and offline-friendly, but the client sees the rules and
  context; keep sensitive targeting server-side.
- **Build vs buy**: an in-house router is a few dozen lines until you need
  targeting UI, audit logs, experiments and SDKs for many languages. OpenFeature
  reduces lock-in either way.
- **Testing combinations**: Hodgson recommends testing the expected production
  configuration with the new toggles on, plus the fallback with them off,
  rather than every combination.

## Gotchas
- Default value when the flag service is down: the SDK returns your default,
  so the default must be the safe, old behavior.
- Using `random()` per request instead of hashing a stable key flips users
  between versions on every page load.
- Hashing only the user id (not flag + user) puts the same users first into
  every rollout.
- Bucketing on an id that changes (anonymous session, then logged in) moves
  users across the boundary; choose the targeting key deliberately.
- Flags evaluated deep inside loops can call the flag service thousands of
  times per request; evaluate once and pass the decision down.
- A flag flip is a production change: it needs an audit trail and should show
  up in the "what changed" list during incidents (see
  [[incident-response-and-postmortems]]).
- Reusing an old flag name for new behavior turns on code paths someone forgot
  were still wired to it.
- Permission checks implemented as flags drift from the real authorization
  model and get flipped by people without security review.

## Related
- [[deployment-strategies]] - flags separate deploy from release; canary and rollout context.
- [[ci-cd-pipelines]] - trunk-based CI relies on release toggles for unfinished work.
- [[git-workflows-and-branching]] - flags are the alternative to long-lived branches.
- [[incident-response-and-postmortems]] - kill switches as a first mitigation.
- [[schema-migrations]] - expand/contract with a flag for the read switch.
- [[authorization-models]] - where long-lived entitlements belong.
- [[technical-debt-management]] - stale flags are debt with a known removal path.

## References
- Pete Hodgson, "Feature Toggles (aka Feature Flags)", martinfowler.com: https://martinfowler.com/articles/feature-toggles.html
- OpenFeature specification: https://openfeature.dev/specification/
- OpenFeature documentation, introduction: https://openfeature.dev/docs/reference/intro
- Danilo Sato, "CanaryRelease", martinfowler.com: https://martinfowler.com/bliki/CanaryRelease.html
