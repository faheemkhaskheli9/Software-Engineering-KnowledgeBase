---
title: Modular monolith
category: architecture
tags: [modular-monolith, modules, boundaries, packwerk, import-linter, bounded-context, monolith, dependency-rules]
use_cases:
  - "structure a new product as one deployable without it turning into a big ball of mud"
  - "stop teams reaching into each other's tables and internals inside our monolith"
  - "enforce module boundaries in CI so a later split into services stays possible"
  - "decide whether to extract a module into a service or keep it in-process"
status: draft
last_verified: 2026-10-24
sources:
  - https://martinfowler.com/bliki/MonolithFirst.html
  - https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity
  - https://github.com/Shopify/packwerk
  - https://import-linter.readthedocs.io/
  - https://www.kamilgrzybek.com/blog/posts/modular-monolith-primer
  - "Sam Newman, Monolith to Microservices (O'Reilly, 2019), ch. 1"
---

# Modular monolith

## Summary
A modular monolith is one deployable application split into modules that each
own one business capability, its data and a small public interface; other
modules may use only that interface. It keeps the simple operations of a
monolith (one build, one deploy, in-process calls, local transactions) while
getting most of the maintainability that teams seek from microservices. The
boundaries are enforced by tooling in CI, not by good intentions, so a module
can later be extracted into a service if a real need appears.

## Key concepts
- **Module = bounded context**: draw modules around business capabilities (billing, catalog, shipping), not technical layers (controllers, models). See [[domain-driven-design]].
- **Public API per module**: a facade, service interface or published events. Everything else (models, repositories, helpers) is private to the module.
- **Data ownership**: each module owns its tables or schema. Other modules never join or write to them; they call the owning module's API or keep a read copy from its events.
- **Dependency direction**: modules form a directed acyclic graph. Cycles mean the boundary is wrong; break them by merging modules, moving code, or inverting the dependency with an event or interface.
- **Enforced boundaries**: static checks fail the build on a forbidden import or a cycle. Shopify's `packwerk` (Ruby) and `import-linter` (Python) are examples; ArchUnit does the same for Java.
- **In-process communication**: direct calls through the public API are fine and fast; in-process events decouple modules that only need to react.

## When to use / scenarios
- Default for a new product or a team under roughly a few dozen engineers, where independent deployment is not yet a bottleneck ([[monolith-vs-microservices]]).
- An existing monolith where changes ripple everywhere: modularise in place first, before or instead of splitting ([[migrating-monolith-to-services]]).
- When a later split is plausible but uncertain: a module with a clean API and its own data is the cheapest thing to extract.
- Not enough on its own when parts need different scaling profiles, runtimes, release cadences or fault isolation (a crash or memory leak still takes down the whole process); extract that module into a service.

## How it works / example
Layout: each module exposes `api.py`; everything else is private.

```
app/
  billing/   api.py  models.py  repository.py
  catalog/   api.py  models.py
  shipping/  api.py  ...
```

A minimal boundary check, the idea behind import-linter and packwerk: a
module may import another module only through its `api`, and the module graph
must have no cycles.

```python
import ast

SOURCES = {  # module/file -> source; in CI, walk the package instead
    "billing/service.py": "from catalog.api import price_of\nfrom billing.repository import save\n",
    "shipping/service.py": "from billing.models import Invoice\n",  # reaches into internals
    "catalog/api.py": "from shipping.api import quote\n",
    "shipping/api.py": "from catalog.api import price_of\n",  # cycle catalog <-> shipping
}

def imports(path, code):
    me = path.split("/")[0]
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] != me and parts[0] in {p.split("/")[0] for p in SOURCES}:
                yield me, parts[0], parts[1] if len(parts) > 1 else ""

def check(sources):
    errors, graph = [], {}
    for path, code in sources.items():
        for src, dst, sub in imports(path, code):
            graph.setdefault(src, set()).add(dst)
            if sub != "api":
                errors.append(f"{path}: imports {dst}.{sub}; use {dst}.api")
    def visit(node, stack):
        for nxt in graph.get(node, ()):
            if nxt in stack:
                errors.append("cycle: " + " -> ".join(stack[stack.index(nxt):] + [nxt]))
            elif len(stack) < len(graph) + 1:
                visit(nxt, stack + [nxt])
    for start in sorted(graph):
        visit(start, [start])
    return sorted(set(errors))

problems = check(SOURCES)
for p in problems:
    print(p)
assert "shipping/service.py: imports billing.models; use billing.api" in problems
assert any(p.startswith("cycle: catalog -> shipping -> catalog") for p in problems)
```

With import-linter the same rules are configuration (`independence`,
`layers` and `forbidden` contracts) run as `lint-imports` in CI.

## Trade-offs
- **Shared database vs schema per module**: one database with per-module schemas keeps local transactions and simple ops; strict ownership makes extraction easy but cross-module queries need an API or read model.
- **Synchronous calls vs in-process events**: calls are simple and consistent; events reduce coupling and prepare for a split but add ordering and failure handling ([[event-driven-architecture]]).
- **Granularity**: few large modules are easy to keep acyclic; many small ones give finer ownership but more interfaces to maintain.
- **Modular monolith vs microservices**: in-process calls and one deploy versus independent deploys, scaling and fault isolation at the cost of network and data consistency problems.

## Gotchas
- Boundaries that are not checked in CI erode within months; one convenient import becomes the norm.
- Cross-module joins and foreign keys quietly couple data; they are the hardest part to undo when extracting a service.
- A "shared" or "common" module that grows business logic becomes a hidden coupling hub; keep it to genuinely generic utilities.
- Modules by layer (all controllers, all models) are not modules; a feature change still touches every one.
- Long builds and test runs still slow everyone; invest in incremental builds and per-module test selection.

## Related
- [[monolith-vs-microservices]] - when one deployable is enough and when to split.
- [[domain-driven-design]] - bounded contexts give module boundaries.
- [[layered-hexagonal-clean-architecture]] - internal structure inside each module.
- [[migrating-monolith-to-services]] - extracting a module once a split is justified.
- [[coupling-cohesion-and-design-principles]] - the coupling rules the boundary checks enforce.
- [[event-driven-architecture]] - in-process events between modules.

## References
- Martin Fowler, "MonolithFirst": https://martinfowler.com/bliki/MonolithFirst.html
- Shopify Engineering, "Deconstructing the Monolith": https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity
- packwerk: https://github.com/Shopify/packwerk
- import-linter documentation: https://import-linter.readthedocs.io/
- Kamil Grzybek, "Modular Monolith: A Primer": https://www.kamilgrzybek.com/blog/posts/modular-monolith-primer
- Sam Newman, *Monolith to Microservices*, O'Reilly, 2019, ch. 1.
