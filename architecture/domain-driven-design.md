---
title: Domain-driven design
category: architecture
tags: [ddd, bounded-context, aggregate, ubiquitous-language, domain-model, context-mapping]
use_cases:
  - "model a complex business domain (insurance, logistics, billing) so code matches how experts talk"
  - "find service boundaries before splitting a monolith"
  - "decide what belongs in one transaction and what can be eventually consistent"
  - "different teams use the word customer to mean different things and the shared model keeps breaking"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.domainlanguage.com/ddd/
  - https://www.oreilly.com/library/view/domain-driven-design-tackling/0321125215/
  - https://www.oreilly.com/library/view/implementing-domain-driven-design/9780133039900/
  - https://martinfowler.com/bliki/BoundedContext.html
  - https://martinfowler.com/bliki/DDD_Aggregate.html
---

# Domain-driven design

## Summary
DDD is an approach to software for complicated domains: build a shared language with domain experts, split the problem into bounded contexts, and model the core with entities, value objects and aggregates that enforce business invariants. Strategic DDD (contexts, language, context maps) is the high-value part and informs team and service boundaries; tactical DDD (aggregates, repositories) is a toolbox applied only where logic is rich.

## Key concepts
- **Ubiquitous language.** One vocabulary used by developers and experts in conversation, docs, and code identifiers. If code says `Account` but the business says `Policy Holder`, fix the code.
- **Bounded context.** A boundary inside which a model and its language are consistent. "Customer" in Sales (lead, pipeline) differs from "Customer" in Billing (payment method, invoices). Do not build one universal model.
- **Subdomains.** Core (competitive advantage; invest, build in-house), supporting (needed, custom but simple), generic (auth, email; buy or use off-the-shelf).
- **Context map.** Relationships between contexts: shared kernel, customer-supplier, conformist, anticorruption layer (ACL), open-host service, published language.
- **Entity** has identity and lifecycle; **value object** is immutable and compared by value (Money, DateRange).
- **Aggregate.** A cluster of objects treated as one consistency boundary with a single root. Invariants inside an aggregate are enforced in one transaction; outside, eventually.
- **Domain event.** A fact that happened (`OrderPlaced`), used to react across aggregates and contexts ([[event-driven-architecture]]).
- **Repository.** Collection-like access to aggregates; **domain service** holds logic that fits no single entity.

## When to use / scenarios
- Business rules are the hard part: many invariants, special cases, workflows, regulation.
- Multiple teams or departments with conflicting vocabularies.
- You need principled boundaries for [[monolith-vs-microservices]] decisions.
- Experts are available to collaborate (event storming, domain storytelling).

When NOT: CRUD apps, reporting dashboards, data pipelines, glue integration. There, full tactical DDD adds ceremony without payoff. Apply it only to the core subdomain and keep generic parts boring.

## How it works / example
Strategic: discover contexts by event storming (orange sticky notes for domain events along a timeline, then group by language shifts).

```
 +-------------+  OrderPlaced   +-------------+   InvoicePaid   +-----------+
 |   Sales     |--------------->|  Billing    |---------------->| Shipping  |
 | Customer=   |   (published   | Customer=   |                 | Recipient |
 |  lead/buyer |    language)   |  payer      |                 |           |
 +-------------+                +------+------+                 +-----------+
                                       | ACL
                                +------v------+
                                | Legacy ERP  |
                                +-------------+
```

Tactical: an aggregate protecting an invariant ("order total never exceeds credit limit; lines only added while draft").

```python
from dataclasses import dataclass, field
from decimal import Decimal

@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str
    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("currency mismatch")
        return Money(self.amount + other.amount, self.currency)

@dataclass
class Order:                      # aggregate root
    id: str
    credit_limit: Money
    status: str = "draft"
    lines: list = field(default_factory=list)   # (sku, Money) inside the aggregate
    events: list = field(default_factory=list)

    def total(self) -> Money:
        total = Money(Decimal(0), self.credit_limit.currency)
        for _, price in self.lines:
            total = total + price
        return total

    def add_line(self, sku: str, price: Money) -> None:
        if self.status != "draft":
            raise ValueError("order not editable")
        if (self.total() + price).amount > self.credit_limit.amount:
            raise ValueError("credit limit exceeded")   # invariant
        self.lines.append((sku, price))

    def place(self) -> None:
        if not self.lines:
            raise ValueError("empty order")
        self.status = "placed"
        self.events.append(("OrderPlaced", self.id))     # published after commit

if __name__ == "__main__":
    o = Order("o1", Money(Decimal(100), "USD"))
    o.add_line("A", Money(Decimal(60), "USD"))
    try:
        o.add_line("B", Money(Decimal(50), "USD"))
    except ValueError as e:
        print("rejected:", e)
    o.place(); print(o.events)
```

Aggregate design rules of thumb: keep aggregates small; reference other aggregates by ID, not object; one aggregate modified per transaction; use domain events and [[distributed-transactions-and-sagas]] across aggregates.

## Trade-offs
- **Depth of modelling vs cost.** Rich domain models need domain experts' time and developer skill; payoff only appears in complex domains.
- **Large aggregates** give strong consistency but cause contention and heavy loading; **small aggregates** scale but force eventual consistency between them.
- **Shared kernel vs separate models:** sharing reduces duplication but couples teams; separate models with translation (ACL) cost mapping code but isolate change.
- **Context per service:** aligning a bounded context with a deployable unit is common, but a context can be a module inside a monolith.

## Gotchas
- **Anemic domain model:** entities with only getters/setters and all logic in "services" ([[refactoring-and-code-smells]]).
- **Treating DDD as only patterns** (entities, repositories) and skipping language and context work; this misses the main value.
- **One giant model** for the whole company; contexts exist precisely to avoid this.
- **Aggregates mirroring database tables** or object graphs instead of invariants.
- **Cross-aggregate transactions** sneaking back in because it is "easier"; they lock you out of future partitioning.
- **Event naming in CRUD terms** (`OrderUpdated`) loses intent; name events after business facts.
- The ubiquitous language drifts if not curated; keep a glossary per context next to the code.

## Related
- [[monolith-vs-microservices]] - bounded contexts guide where to cut services.
- [[layered-hexagonal-clean-architecture]] - the code structure that keeps the domain pure.
- [[event-driven-architecture]] - domain events flow between contexts.
- [[cqrs-and-event-sourcing]] - frequently paired with aggregates.
- [[data-modeling-and-schema-design]] - persisting aggregates in relational or document stores.
- [[coupling-cohesion-and-design-principles]] - boundaries as cohesion and coupling choices.

## References
- Eric Evans, *Domain-Driven Design: Tackling Complexity in the Heart of Software*, 2003.
- Vaughn Vernon, *Implementing Domain-Driven Design*, 2013.
- Alberto Brandolini, *Introducing EventStorming*.
- Martin Fowler, "BoundedContext" and "DDD_Aggregate" (martinfowler.com).
