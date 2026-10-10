---
title: Dependency injection
category: design
tags: [dependency-injection, inversion-of-control, composition-root, constructor-injection, service-locator, di-container, testability]
use_cases:
  - "make a service class testable without patching imports"
  - "swap a real payment, email or storage client for a fake in tests and local dev"
  - "decide whether a project needs a DI container or plain constructor wiring"
  - "untangle a codebase where every class creates its own database connection"
  - "wire different implementations per environment (dev, staging, prod)"
status: draft
last_verified: 2026-10-10
sources:
  - "Inversion of Control Containers and the Dependency Injection pattern, Martin Fowler, 2004 - https://martinfowler.com/articles/injection.html"
  - "Dependency Injection Principles, Practices, and Patterns, Steven van Deursen and Mark Seemann"
  - "Growing Object-Oriented Software, Guided by Tests, Steve Freeman and Nat Pryce"
  - "Clean Architecture, Robert C. Martin"
---

# Dependency injection

## Summary
Dependency injection (DI) means a component receives its collaborators from outside instead of constructing or looking them up itself. All the wiring happens in one place near the program's entry point (the composition root), so the rest of the code depends only on what it is handed. In most Python code plain constructor and function arguments are all the DI you need; containers and frameworks earn their keep only in large object graphs.

## Key concepts
- **Dependency:** anything a component needs to do its job and that you may want to vary: database, HTTP client, clock, random source, config, logger.
- **Inversion of control:** the component no longer controls how its dependencies are created; the caller does. DI is one form of IoC (Fowler, 2004).
- **Constructor injection:** dependencies are constructor parameters. The default choice: the object is complete once built and its needs are visible in its signature.
- **Parameter (method) injection:** pass the dependency to the one function that needs it. Good for functions and for per-call values such as the current time.
- **Setter/property injection:** assign after construction. Allows optional dependencies but leaves a window where the object is half-built.
- **Composition root:** the single place (usually `main`, an app factory, or framework startup) where concrete implementations are chosen and the object graph is built.
- **DI container:** a library that builds the graph from registrations or type hints and manages lifetimes (singleton, per-request, transient).
- **Service locator:** components ask a global registry for dependencies. It hides dependencies inside method bodies and is usually considered an anti-pattern next to DI (Seemann).
- **Lifetimes:** singleton (one per process, e.g. a connection pool), scoped (one per request or unit of work, e.g. a DB session), transient (new each time).
- **Relation to DIP:** dependency *inversion* is about which side owns the abstraction ([[solid-principles]]); dependency *injection* is the mechanism that supplies the implementation.

## When to use / scenarios
- A class calls `requests`, a database or `datetime.now()` directly and is hard to test: inject the client or a clock.
- Different environments need different implementations (S3 in prod, local disk in dev): choose them in the composition root from config.
- Cross-cutting decorators (retry, caching, metrics) wrapping a client: build the wrapped object at the root and inject it ([[design-patterns-gof]] decorator).
- Framework-provided DI (FastAPI `Depends`, Spring, ASP.NET Core) is already there: use it for request-scoped objects instead of a second mechanism.
- NOT needed for pure functions, value objects, or a dependency that will never vary and does no I/O (a stdlib helper). Injecting everything adds parameters with no payoff.
- NOT a reason to add an interface per class: in Python, duck typing or a `Protocol` lets any object with the right methods be injected.

## How it works / example

Hard-wired vs injected:

```python
import time

class HardWiredReport:
    def build(self):
        now = time.time()                       # hidden dependency on the real clock
        return f"report at {int(now)}"

class Report:
    def __init__(self, clock=time.time):        # injected; real clock by default
        self.clock = clock
    def build(self):
        return f"report at {int(self.clock())}"

assert Report(clock=lambda: 1_000).build() == "report at 1000"   # deterministic
```

A composition root with constructor injection and no container:

```python
from typing import Protocol

class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

class MemoryStorage:
    def __init__(self): self.items = {}
    def put(self, key, data): self.items[key] = data

class DiskStorage:
    def __init__(self, root): self.root = root
    def put(self, key, data):
        raise NotImplementedError("writes to disk in the real app")

class Uploader:
    def __init__(self, storage: Storage, max_bytes: int):
        self.storage, self.max_bytes = storage, max_bytes
    def upload(self, key, data):
        if len(data) > self.max_bytes:
            raise ValueError("too large")
        self.storage.put(key, data)

def build_app(env: str) -> Uploader:           # composition root: the only place that picks concretes
    storage = MemoryStorage() if env == "test" else DiskStorage("/var/data")
    return Uploader(storage, max_bytes=1024)

app = build_app("test")
app.upload("a.txt", b"hi")
assert app.storage.items == {"a.txt": b"hi"}
```

Service locator, for contrast (dependencies are invisible from the signature):

```
class Uploader:
    def upload(self, key, data):
        Registry.get("storage").put(key, data)   # what does Uploader need? read every method to find out
```

## Trade-offs
- **Manual wiring vs container:** manual wiring is explicit, debuggable and fine up to a few dozen components; a container reduces boilerplate and manages lifetimes in large graphs at the cost of magic, slower startup and runtime wiring errors.
- **Constructor vs parameter injection:** constructor injection suits long-lived collaborators; parameter injection keeps functions pure-ish and suits per-call values.
- **Defaults vs required parameters:** a default real implementation (`clock=time.time`) keeps call sites short but can hide I/O; required parameters make every dependency explicit.
- **DI vs monkeypatching:** `unittest.mock.patch` tests code that was not designed for injection, but couples tests to import paths ([[unit-testing-and-test-doubles]]); DI makes the seam part of the design.
- **Many small dependencies vs a facade:** a constructor with eight parameters is a smell that the class does too much ([[refactoring-and-code-smells]]), not a reason for a container.

## Gotchas
- Constructing dependencies inside `__init__` (`self.db = Database()`) is the most common way DI is lost.
- Global singletons and module-level clients are hidden dependencies; tests then leak state into each other.
- Captive dependency: a singleton holding a request-scoped object (a DB session) keeps it alive across requests. Match lifetimes.
- Resolving from the container deep inside business code turns DI into a service locator.
- Circular dependencies show up at wiring time; they usually mean two classes should be merged or a third extracted.
- Injecting configuration as one big dict hides which settings a class uses; pass the specific values.
- Container-driven code can make "where does this object come from?" hard to answer; keep the composition root readable.

## Related
- [[solid-principles]] - dependency inversion, the principle DI implements
- [[unit-testing-and-test-doubles]] - the main payoff: injecting fakes, stubs and spies
- [[layered-hexagonal-clean-architecture]] - ports and adapters wired at the composition root
- [[functional-core-imperative-shell]] - an alternative that pushes dependencies to the edge entirely
- [[design-patterns-gof]] - factory, strategy and decorator used inside the wiring
- [[twelve-factor-app]] - config from the environment feeds the composition root

## References
- Fowler, "Inversion of Control Containers and the Dependency Injection pattern" (2004)
- van Deursen and Seemann, "Dependency Injection Principles, Practices, and Patterns" (composition root, service locator, captive dependency)
- Freeman and Pryce, "Growing Object-Oriented Software, Guided by Tests"
- Martin, "Clean Architecture"
