---
title: Monolith vs microservices
category: architecture
tags: [monolith, modular-monolith, microservices, service-boundaries, deployment, team-topology]
use_cases:
  - "we are a 5-person startup, should we build microservices from day one"
  - "our monolith deploys take hours and teams block each other, should we split it"
  - "decide where to draw service boundaries when extracting a service from a monolith"
  - "migrate a legacy monolith to microservices without a big-bang rewrite"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/bliki/MonolithFirst.html
  - https://martinfowler.com/articles/microservices.html
  - https://martinfowler.com/bliki/StranglerFigApplication.html
  - https://samnewman.io/books/building_microservices_2nd_edition/
  - https://www.oreilly.com/library/view/software-architecture-the/9781492086888/
---

# Monolith vs microservices

## Summary
A monolith is one deployable unit; microservices are many independently deployable services, each owning its data and one business capability. Microservices buy independent deployment and team autonomy at the price of distributed-systems complexity (network failure, eventual consistency, operational overhead). The default for a new product is a well-structured modular monolith; split out services only when a concrete organizational or scaling pain justifies it.

## Key concepts
- **Deployment unit vs module.** Modularity (clear boundaries in code) is separate from distribution (boundaries over a network). You can have the first without the second.
- **Modular monolith.** One process, one deploy, but strict module boundaries: each module has a public API, owns its tables, and other modules cannot reach into its internals.
- **Independent deployability** is the defining property of a microservice. If two services must be released together, you have a distributed monolith (the worst of both).
- **Database per service.** Shared databases couple services through the schema. Cross-service data needs APIs or events, not joins.
- **Bounded context** ([[domain-driven-design]]) is the best unit for a service boundary; technical layers (a "database service") are the wrong cut.
- **Conway's law.** Architecture mirrors communication structure; pick boundaries to match teams you actually have (or want).
- **Strangler fig.** Incremental migration: route traffic for one capability to a new service, retire the old code path, repeat.

## When to use / scenarios
Choose a (modular) monolith when:
- Team is smaller than roughly one or two pizza-teams, product-market fit is not found, domain boundaries are still moving.
- You do not yet have CI/CD, observability and on-call maturity for many services.
- Latency-sensitive paths do many cross-module calls per request.

Choose microservices when:
- Several teams block each other on one release train and merge conflicts / coordination dominate.
- Parts of the system have clearly different scaling, availability, or technology needs (e.g. a CPU-heavy image pipeline beside a CRUD API).
- Regulatory or blast-radius isolation is required (payments, PII).
- You already know the domain well enough that boundaries will survive.

Not microservices: when the motive is "it is modern", a resume line, or fixing a messy codebase. A messy monolith becomes a messy distributed system.

## How it works / example
```
Modular monolith                       Microservices
+----------------------------+        +-------+  HTTP/gRPC  +--------+
| orders | billing | catalog |        | orders|------------>|billing |
|  (public API per module)   |        +---+---+             +---+----+
|  one process, one DB       |            |db                    |db
|  schemas per module        |        +---v---+             +---v----+
+----------------------------+        |catalog|<-- events ->| ...    |
```

Enforcing module boundaries in a Python monolith (a test that fails the build when a module imports another module's internals):

```python
# tests/test_boundaries.py
import ast, pathlib

ALLOWED_PUBLIC = "api"          # modules may only import <other>.api
MODULES = {"orders", "billing", "catalog"}

def violations(root="src"):
    out = []
    for path in pathlib.Path(root).rglob("*.py"):
        owner = path.relative_to(root).parts[0]
        if owner not in MODULES:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] in MODULES and parts[0] != owner:
                    if len(parts) < 2 or parts[1] != ALLOWED_PUBLIC:
                        out.append(f"{path}: imports {node.module}")
    return out

def test_no_cross_module_internals():
    assert violations() == []
```

Extraction path (strangler): put the module behind its `api` interface in-process first; once callers only use the interface, swap the in-process implementation for an HTTP/gRPC client and move the module and its tables into a new service.

## Trade-offs
| Concern | Monolith | Microservices |
|---|---|---|
| Local dev / debugging | Easy, one process | Needs compose/k8s, distributed tracing |
| Deploy independence | None | High, if boundaries are right |
| Data consistency | ACID transactions | Sagas, eventual consistency |
| Refactoring across boundaries | IDE rename | Versioned API changes |
| Scaling | Scale whole app | Scale hot services only |
| Ops cost | One pipeline | Pipeline, monitoring, config per service |
| Fault isolation | One bug can take all down | Contained if resilience patterns exist |

Decision pushers: team count and release friction push toward services; domain uncertainty and small teams push toward the monolith. Middle path: a few coarse services (2-5) along strong boundaries rather than dozens of nano-services.

## Gotchas
- **Distributed monolith:** services share a DB or must deploy in lockstep; you pay all the costs, get none of the benefits.
- **Nano-services:** one entity per service leads to chatty calls and distributed transactions for every operation.
- **Wrong boundaries are expensive to fix.** Moving behavior between services is a cross-team migration; moving it between modules is a refactor. This is the core argument for monolith-first.
- **Synchronous call chains** multiply latency and failure probability; availability is the product of each hop. Use [[resilience-patterns]] and prefer async events where the business allows.
- **Shared libraries** that carry domain logic recreate coupling; share only stable, generic code.
- **No observability, no microservices.** Without [[observability-logs-metrics-traces]] you cannot debug a request crossing five services.
- **Testing** shifts toward [[integration-and-contract-testing]]; end-to-end suites across services become slow and flaky.
- Mixed data ownership during migration: dual writes without a transactional outbox lose or duplicate data.

## Related
- [[domain-driven-design]] - bounded contexts give principled service boundaries.
- [[layered-hexagonal-clean-architecture]] - internal structure of each module or service.
- [[distributed-transactions-and-sagas]] - how consistency works once data is split.
- [[api-gateway-and-service-mesh]] - edge and cross-cutting concerns for many services.
- [[choosing-communication-style]] - sync vs async between services.
- [[deployment-strategies]] - release mechanics that make independent deploys safe.
- [[migrating-monolith-to-services]] - strangler-fig steps once the decision to split is made.
- [[modular-monolith]] - module boundaries, data ownership and CI checks inside one deployable.

## References
- Martin Fowler, "MonolithFirst" and "Microservices" (martinfowler.com).
- Sam Newman, *Building Microservices*, 2nd ed., O'Reilly.
- Mark Richards and Neal Ford, *Fundamentals of Software Architecture*, O'Reilly.
- Martin Fowler, "StranglerFigApplication".
