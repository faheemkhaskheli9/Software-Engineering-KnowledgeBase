---
title: SOLID principles
category: design
tags: [solid, oop, srp, ocp, lsp, isp, dip, dependency-injection, design-principles]
use_cases:
  - "refactor a 2000-line class that handles validation, persistence and email in one place"
  - "add a new payment provider without editing the checkout code"
  - "make business logic testable without a database or network"
  - "review a PR where a subclass breaks callers that expect the base type"
  - "decide when to introduce an interface and when it is over-engineering"
status: draft
last_verified: 2026-10-10
sources:
  - "Agile Software Development, Principles, Patterns, and Practices, Robert C. Martin"
  - "Clean Architecture, Robert C. Martin"
  - "A Behavioral Notion of Subtyping, Liskov and Wing, 1994"
  - "Object-Oriented Software Construction, Bertrand Meyer"
---

# SOLID principles

## Summary
Five heuristics for organizing classes and modules so that change stays local: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion. They are guides for managing coupling and change, not laws; applied dogmatically they produce interface-per-class bloat. Use them when a concrete pain (hard to test, shotgun edits, fragile inheritance) appears.

## Key concepts
- **S - Single Responsibility:** a module should have one reason to change (one actor/stakeholder whose requirements drive it). Not "does one thing" in the micro sense.
- **O - Open/Closed:** extend behavior by adding code, not by editing tested code. Achieved via polymorphism, strategies, plugins.
- **L - Liskov Substitution:** a subtype must be usable wherever its base is, without callers noticing. Do not strengthen preconditions, weaken postconditions or throw surprising errors.
- **I - Interface Segregation:** clients should not depend on methods they do not use. Prefer small, role-specific interfaces (in Python, `Protocol`s).
- **D - Dependency Inversion:** high-level policy depends on abstractions, not on low-level details; details depend on the abstraction. Wire dependencies from outside (dependency injection).

## When to use / scenarios
- A class changes for unrelated reasons (tax rule change and email template change both edit `Order`): split by responsibility (SRP).
- A growing `if provider == "stripe" ... elif ...` chain edited every release: introduce a small interface and one class per provider (OCP). Wait until the second or third variant before abstracting.
- Inheritance hierarchy where `Square(Rectangle)` surprises callers: LSP violation, prefer composition.
- Unit tests need a live database to test pricing rules: invert the dependency so domain code takes a repository interface (DIP); see [[layered-hexagonal-clean-architecture]].
- NOT every class needs an interface. A single implementation with no test or deployment reason for a seam is noise (YAGNI). SOLID is mostly about OOP; in functional or data-oriented code the same goals are met with functions and plain data.

## How it works / example

Dependency inversion + open/closed in one small example:

```python
from typing import Protocol

class PaymentGateway(Protocol):          # abstraction owned by the domain
    def charge(self, amount_cents: int, token: str) -> str: ...

class StripeGateway:
    def charge(self, amount_cents, token):
        return f"stripe-{token}-{amount_cents}"     # real SDK call here

class FakeGateway:
    def charge(self, amount_cents, token):
        return "fake-ok"

class Checkout:                          # high-level policy
    def __init__(self, gateway: PaymentGateway):
        self.gateway = gateway           # injected, not constructed inside
    def pay(self, cart_total_cents, token):
        if cart_total_cents <= 0:
            raise ValueError("empty cart")
        return self.gateway.charge(cart_total_cents, token)

assert Checkout(FakeGateway()).pay(500, "tok") == "fake-ok"   # no network in tests
# Adding PayPal = new class, Checkout unchanged (open/closed)
```

SRP split:

```
Before:  OrderService: validate + price + save to DB + send email + render PDF
After:   OrderValidator   OrderPricer   OrderRepository   Notifier   InvoiceRenderer
         OrderService orchestrates (thin), each other piece changes for one reason
```

LSP violation and fix:

```python
class Bird:
    def fly(self): ...
class Penguin(Bird):
    def fly(self): raise NotImplementedError   # callers of Bird.fly() now break
# Fix: split capabilities
class Bird: ...
class FlyingBird(Bird):
    def fly(self): ...
```

ISP with protocols: a function that only reads should take `Reader`, not the full `Repository` with save/delete.

```
 high-level policy  --depends on-->  [Abstraction]  <--implements--  low-level detail
        (domain)                      (owned by domain)                (DB, HTTP, SDK)
```

## Trade-offs
- **Flexibility vs indirection:** each abstraction adds a file, a name and a hop when reading. Add the seam where variation or test isolation is real.
- **Many small classes vs cohesion:** over-applied SRP scatters one workflow across a dozen classes; keep things that change together together (see [[coupling-cohesion-and-design-principles]]).
- **Inheritance vs composition:** LSP is hard to honor in deep hierarchies; composition and small protocols avoid the problem.
- **DI containers vs manual wiring:** manual constructor injection is enough for most Python projects; a container pays off only in large graphs.
- **OCP in practice:** you cannot predict every axis of change. Prefer making the code easy to change (clear, tested) over pre-building extension points.

## Gotchas
- Interface-per-class (`IUserService` with a single `UserService`) is cargo-cult DIP.
- "Single responsibility" read as "one method per class" produces anemic, unreadable code.
- Mocks hiding LSP violations: test every implementation against the same contract tests.
- Abstractions defined by the low-level side (leaking SDK types into the domain interface) defeat inversion; define the interface in domain terms.
- Constructing dependencies inside constructors (`self.db = Database()`) silently hard-wires them and kills testability.
- Subclass overriding a method to do nothing or raise is a smell for LSP and ISP together.
- Extension-point reflection or plugin systems built "just in case" tend to rot unused.

## Related
- [[coupling-cohesion-and-design-principles]] - the broader principles SOLID instantiates (DRY, KISS, YAGNI, Law of Demeter)
- [[design-patterns-gof]] - strategy, factory and adapter are the usual vehicles for OCP and DIP
- [[layered-hexagonal-clean-architecture]] - DIP applied at architecture scale
- [[unit-testing-and-test-doubles]] - the payoff: substitutable dependencies
- [[refactoring-and-code-smells]] - how to get from a god class to SRP safely
- [[dependency-injection]] - the mechanism that supplies implementations behind DIP

## References
- Martin, "Agile Software Development: Principles, Patterns, and Practices"
- Martin, "Clean Architecture"
- Liskov and Wing, "A Behavioral Notion of Subtyping" (1994)
- Meyer, "Object-Oriented Software Construction" (open/closed)
