---
title: Migrating a monolith to services
category: scenarios
tags: [migration, strangler-fig, branch-by-abstraction, modular-monolith, microservices, data-migration, cdc, decision-guide]
use_cases:
  - "split a legacy monolith into services without a big-bang rewrite"
  - "decide which part of the monolith to extract first"
  - "move a module's data out of the shared database safely"
  - "shift traffic gradually from the old code path to a new service and roll back if needed"
  - "should we split the monolith at all, or modularise it first"
status: stable
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/bliki/StranglerFigApplication.html
  - https://martinfowler.com/bliki/BranchByAbstraction.html
  - https://martinfowler.com/articles/break-monolith-into-microservices.html
  - https://samnewman.io/books/monolith-to-microservices/
  - https://microservices.io/patterns/data/transactional-outbox.html
---

# Migrating a monolith to services

## Summary
Migrate incrementally, one capability at a time, and only for a stated reason (team contention, different scaling or isolation needs), never as a rewrite. The usual path is: modularise inside the monolith first, put a routing seam in front (strangler fig) or an interface inside (branch by abstraction), extract the capability with its data, shift traffic gradually with a fast rollback, then delete the old code. Data is the hard part: every extraction ends with the new service owning its tables and everyone else using its API or events.

## Key concepts
- **Reason first.** Write down the pain the split fixes and how you will know it worked (deploy frequency, lead time, incidents). If the pain is "messy code", modularise; do not distribute ([[monolith-vs-microservices]]).
- **Modular monolith as step zero.** Enforce module boundaries in-process; a boundary that cannot hold inside one process will not hold over a network.
- **Strangler fig.** A proxy or gateway in front of the monolith routes one capability's traffic to the new service; the old path shrinks until removed.
- **Branch by abstraction.** Inside the code, introduce an interface for the capability, switch callers to it, then swap the implementation (in-process to remote client) behind a flag.
- **Seams and boundaries.** Cut along bounded contexts ([[domain-driven-design]]), not technical layers.
- **Data ownership transfer.** Shared tables become the service's tables; other modules read via API, events, or a replicated read model. Dual writes need an outbox or CDC.
- **Parallel run / dark launch.** Call both old and new, serve the old result, compare outputs before switching.

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Unsure whether to split at all | Modular monolith, boundary tests, measure release friction | [[monolith-vs-microservices]], [[coupling-cohesion-and-design-principles]] |
| Choosing the first service | Edge capability with few inbound dependencies and a clear owner team (notifications, search, media processing) | [[domain-driven-design]] |
| HTTP-facing capability | Strangler fig: route by path at the gateway | [[api-gateway-and-service-mesh]], [[load-balancing]] |
| Capability called deep inside the code | Branch by abstraction + feature flag | [[refactoring-and-code-smells]], [[deployment-strategies]] |
| Capability's tables are joined by other modules | Replace joins with API calls or a local read model fed by events first | [[event-driven-architecture]], [[data-modeling-and-schema-design]] |
| Move data while both sides run | Expand/contract, CDC or outbox replication, then cut over writes | [[schema-migrations]], [[event-driven-architecture]] |
| Business transaction now spans services | Saga with compensations; keep the step that needs ACID inside one service | [[distributed-transactions-and-sagas]] |
| Need confidence the new service is correct | Parallel run comparing outputs, contract tests | [[integration-and-contract-testing]] |
| Shift traffic safely | Canary by percentage of users, instant rollback flag | [[deployment-strategies]], [[slis-slos-error-budgets]] |
| Calls across the new boundary fail or slow down | Timeouts, retries with jitter, circuit breakers | [[resilience-patterns]] |

Step order for each extracted capability:

```
0. Define success metric + owner team. Add tracing across the monolith.
1. Modularise: one module, public interface, owns its tables (enforced by tests).
2. Seam: gateway route (strangler) or interface + flag (branch by abstraction).
3. Build the service; replicate data to it (CDC/outbox), run in parallel, compare.
4. Shift reads, then writes, by percentage; watch SLOs; roll back by flag.
5. Service becomes the only writer; monolith reads via API/events.
6. Delete the old code path and the old tables. Repeat for the next capability.
```

When NOT to migrate: no observability or CI/CD per service yet, one team owns everything, or domain boundaries are still moving. Fix those first; a split made before them produces a distributed monolith.

## How it works / example
Gradual traffic shifting needs stable bucketing: the same user must hit the same side across requests, or they see data flip between versions. Runnable sketch of the router decision:

```python
import hashlib

def bucket(user_id: str, salt: str = "billing-v2") -> int:
    """Stable 0-99 bucket per user and per migration."""
    digest = hashlib.sha256(f"{salt}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100

def route(path: str, user_id: str, rollout_percent: int, kill_switch: bool) -> str:
    if not path.startswith("/billing/") or kill_switch:
        return "monolith"
    return "billing-service" if bucket(user_id) < rollout_percent else "monolith"

if __name__ == "__main__":
    users = [f"u{i}" for i in range(1000)]
    at_10 = {u for u in users if route("/billing/x", u, 10, False) == "billing-service"}
    at_50 = {u for u in users if route("/billing/x", u, 50, False) == "billing-service"}
    assert at_10 <= at_50                                  # raising the % never moves users back
    assert route("/billing/x", "u1", 100, True) == "monolith"   # rollback is one flag
    assert route("/orders/1", "u1", 100, False) == "monolith"
    print(len(at_10), len(at_50))
```

In production this logic lives in the gateway, a feature-flag service, or the monolith's own entry point; the flag values change without a deploy.

Data cutover for one table, while both sides run:

```
 a. monolith writes orders_billing; CDC/outbox streams changes -> billing service DB
 b. billing service serves reads for x% of users (compare with monolith results)
 c. switch writes: billing service is the writer; changes stream back to monolith
    for modules that still read the old table (temporary)
 d. remove readers of the old table, stop the back-stream, drop the table
```

## Trade-offs
- **Strangler at the edge vs branch by abstraction inside:** edge routing is clean for whole HTTP capabilities and easy to roll back; abstraction inside the code works for capabilities with no own endpoints but needs the monolith codebase to cooperate.
- **Extract easy edges first vs the most painful core first:** edges teach the team the pipeline, observability and deployment with low risk; the core is where the payoff is but has the most coupling. Most guidance starts at the edges.
- **Synchronous API vs replicated read model for data other modules need:** API calls are simpler and always fresh but add runtime coupling; a local read model fed by events decouples availability at the cost of eventual consistency.
- **Few coarse services vs many small ones:** coarse services keep transactions local and calls few; fine-grained services give more autonomy but more distributed transactions.

## Gotchas
- Rewriting instead of extracting: the rewrite chases a moving monolith and rarely catches up.
- Extracting code but leaving the data shared; the service is still coupled through the schema.
- Distributed monolith: services that must deploy together or call each other synchronously in long chains.
- Dual writes from application code without an outbox or CDC; one side silently diverges.
- No end-to-end tracing before the split, so the first cross-service incident cannot be debugged ([[observability-logs-metrics-traces]]).
- Random per-request percentage routing: a user alternates between old and new data.
- Never deleting the old path: two implementations live forever and drift.
- Network calls replacing in-process calls inside loops (N+1 over HTTP); batch the API.

## Related
- [[monolith-vs-microservices]] - whether to split, modular monolith, boundary tests.
- [[domain-driven-design]] - bounded contexts as extraction boundaries.
- [[distributed-transactions-and-sagas]] - consistency once data is split.
- [[deployment-strategies]] - canaries, flags and rollback for traffic shifting.
- [[schema-migrations]] - expand/contract while two versions run.
- [[choosing-communication-style]] - sync vs async across the new boundary.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- Martin Fowler, "StranglerFigApplication" and "BranchByAbstraction" (martinfowler.com/bliki).
- Zhamak Dehghani, "How to break a Monolith into Microservices", martinfowler.com.
- Sam Newman, *Monolith to Microservices*, O'Reilly, ch. 3 "Splitting the Monolith" (strangler fig, branch by abstraction, parallel run, CDC) and ch. 4 "Decomposing the Database".
- Chris Richardson, "Transactional outbox" pattern, microservices.io.
