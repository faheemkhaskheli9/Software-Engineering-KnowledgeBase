---
title: Layered, hexagonal and clean architecture
category: architecture
tags: [layered-architecture, hexagonal, ports-and-adapters, clean-architecture, dependency-inversion, onion]
use_cases:
  - "keep business logic independent of the web framework and database so we can test it without them"
  - "structure a new backend service so we can swap the database or message broker later"
  - "our controllers contain business rules and tests need a running database"
  - "explain how to organize packages in a Python or Java service"
status: draft
last_verified: 2026-10-10
sources:
  - https://alistair.cockburn.us/hexagonal-architecture/
  - https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
  - https://www.oreilly.com/library/view/clean-architecture-a/9780134494272/
  - https://www.cosmicpython.com/
  - https://martinfowler.com/bliki/PresentationDomainDataLayering.html
---

# Layered, hexagonal and clean architecture

## Summary
These are three related ways to organize code inside one service. Classic layering stacks presentation, business and data layers with dependencies pointing down. Hexagonal (ports and adapters), onion and clean architecture invert that: the domain sits at the centre, defines interfaces (ports), and infrastructure (web, DB, queues) plugs in as adapters that depend on the domain. The payoff is a domain you can test fast and an infrastructure you can replace.

## Key concepts
- **Dependency rule.** Source-code dependencies point inward, toward the domain. The domain never imports the framework, ORM, or HTTP library.
- **Port.** An interface owned by the application/domain, describing what it needs (`OrderRepository`, `PaymentGateway`) or offers (use cases).
- **Adapter.** Implementation of a port for a concrete technology (`SqlAlchemyOrderRepository`, `StripeGateway`, a FastAPI route calling a use case).
- **Driving (primary) vs driven (secondary) adapters.** Driving adapters call the app (HTTP, CLI, queue consumer); driven adapters are called by it (DB, email, external API).
- **Use case / application service.** Orchestrates one user intent: load aggregates via ports, call domain logic, persist, publish.
- **Domain model.** Entities and value objects holding business rules, with no I/O ([[domain-driven-design]]).
- **Composition root.** The one place (main/bootstrap) where concrete adapters are wired to ports.

## When to use / scenarios
- Business rules are non-trivial (pricing, eligibility, workflows) and you want unit tests that run in milliseconds.
- You expect to change infrastructure (DB engine, broker, payment provider) or support several entry points (REST, CLI, events) for the same logic.
- Long-lived system, several developers.

When NOT:
- Thin CRUD over a table with no real rules: a plain layered or even "framework-native" structure is enough. Ports for everything is ceremony.
- Throwaway scripts and prototypes.
- Do not add a repository interface "just in case" when there will only ever be one implementation and tests can use a real test DB cheaply. Introduce ports where the isolation earns its keep (external services, slow I/O).

## How it works / example
```
 driving adapters                    driven adapters
 (HTTP, CLI, consumer)               (SQL, Stripe, SMTP)
        |                                   ^
        v                                   |
   +----------+     +----------------+  implements
   | use case |---->|  domain model  |      |
   +----+-----+     +----------------+  +---+------+
        |  depends on ports (interfaces)|  adapter |
        +------------------------------>+----------+
   dependencies point INWARD; adapters implement ports
```

Minimal Python example:

```python
from dataclasses import dataclass
from typing import Protocol

# ---- domain (no imports from frameworks) ----
@dataclass
class Order:
    id: str
    total_cents: int
    paid: bool = False

    def pay(self, amount_cents: int) -> None:
        if amount_cents != self.total_cents:
            raise ValueError("amount mismatch")
        if self.paid:
            raise ValueError("already paid")
        self.paid = True

# ---- ports (owned by the application) ----
class OrderRepository(Protocol):
    def get(self, order_id: str) -> Order: ...
    def save(self, order: Order) -> None: ...

class PaymentGateway(Protocol):
    def charge(self, order_id: str, amount_cents: int) -> None: ...

# ---- use case ----
class PayOrder:
    def __init__(self, repo: OrderRepository, gateway: PaymentGateway):
        self.repo, self.gateway = repo, gateway

    def __call__(self, order_id: str, amount_cents: int) -> None:
        order = self.repo.get(order_id)
        order.pay(amount_cents)              # rules in the domain
        self.gateway.charge(order_id, amount_cents)
        self.repo.save(order)

# ---- adapters: in-memory for tests; SQL/Stripe in production ----
class InMemoryRepo:
    def __init__(self): self.rows = {}
    def get(self, order_id): return self.rows[order_id]
    def save(self, order): self.rows[order.id] = order

class FakeGateway:
    def __init__(self): self.charges = []
    def charge(self, order_id, amount_cents): self.charges.append((order_id, amount_cents))

def test_pay_order():
    repo, gw = InMemoryRepo(), FakeGateway()
    repo.save(Order("o1", 500))
    PayOrder(repo, gw)("o1", 500)
    assert repo.get("o1").paid and gw.charges == [("o1", 500)]

if __name__ == "__main__":
    test_pay_order(); print("ok")
```

Suggested layout:
```
src/shop/
  domain/        # entities, value objects, domain services, domain events
  application/   # use cases, port interfaces
  adapters/      # http/, persistence/, payments/, messaging/
  bootstrap.py   # composition root
```

## Trade-offs
- **Layered** is familiar and fast to start; risk is business logic leaking into controllers and the DB schema driving the model, with every layer coupled to the one below.
- **Hexagonal/clean** costs extra indirection (interfaces, mappers between domain objects and ORM rows) in exchange for testability and replaceable infrastructure.
- **Domain model vs ORM entities:** using ORM classes as domain objects is pragmatic and removes mapping code, but couples rules to the persistence framework. Separate models fit complex domains; shared models fit simple ones.
- **Number of layers:** more concentric rings add names, not value. Three (domain, application, adapters) is usually enough.
- **Vertical slices** (feature folders, each with its own mini-layers) scale better than horizontal layers across a big codebase; combine with the dependency rule inside each slice.

## Gotchas
- **Leaky ports:** a `Repository` returning ORM query objects or exposing `session` defeats the purpose. Return domain objects.
- **Anemic domain:** if all logic is in use cases and entities are bags of getters, the architecture is layering with extra steps. Put invariants on the entities.
- **Interface per class:** mechanical `IFoo`/`FooImpl` pairs are noise; ports express needs of the domain, not a mirror of implementations.
- **Mapping explosion:** DTO to domain to ORM to DTO. Map at boundaries only where models genuinely differ.
- **Circular imports** are the first symptom of a violated dependency rule; enforce it with an import-linter or architecture test (see [[monolith-vs-microservices]] for a sample).
- **Transactions** are an application concern; a unit-of-work port keeps them out of the domain.
- Exceptions: map infrastructure errors to domain/application errors at the adapter ([[error-handling-strategies]]).

## Related
- [[domain-driven-design]] - supplies the model that sits at the centre.
- [[solid-principles]] - dependency inversion is the mechanism behind ports.
- [[unit-testing-and-test-doubles]] - fakes for ports make use-case tests fast.
- [[coupling-cohesion-and-design-principles]] - the underlying forces this structure manages.
- [[cqrs-and-event-sourcing]] - often layered on top of a hexagonal core.
- [[monolith-vs-microservices]] - a modular monolith applies these rules per module.

## References
- Alistair Cockburn, "Hexagonal architecture".
- Robert C. Martin, *Clean Architecture*, and "The Clean Architecture" blog post.
- Harry Percival and Bob Gregory, *Architecture Patterns with Python* (cosmicpython.com).
- Jeffrey Palermo, "The Onion Architecture".
