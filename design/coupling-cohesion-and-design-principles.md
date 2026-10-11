---
title: Coupling, cohesion and core design principles
category: design
tags: [coupling, cohesion, dry, kiss, yagni, law-of-demeter, composition, abstraction, modularity]
use_cases:
  - "decide whether to merge two near-duplicate functions or leave them separate"
  - "split a codebase into modules so a change in one does not ripple into five others"
  - "review a design for hidden dependencies between components"
  - "argue against a speculative abstraction that no requirement asks for"
  - "choose between inheritance and composition for sharing behavior"
status: draft
last_verified: 2026-10-11
sources:
  - https://wstomv.win.tue.nl/edu/2ip30/references/criteria_for_modularization.pdf
  - https://doi.org/10.1147/sj.132.0115
  - https://www.ccs.neu.edu/home/lieber/LoD.html
  - "A Philosophy of Software Design, John Ousterhout, chapters 4-5"
  - "The Pragmatic Programmer, 20th anniversary ed., Hunt and Thomas, topics 9 and 28"
  - "Structured Design, Yourdon and Constantine, chapters 6-7"
  - "Design Patterns, Gamma et al., chapter 1, section 1.6 (composition over inheritance)"
---

# Coupling, cohesion and core design principles

## Summary
Good design makes change cheap. Two measurements capture most of it: coupling (how much modules depend on each other's internals) and cohesion (how closely a module's parts belong together). The named principles (DRY, KISS, YAGNI, Law of Demeter, composition over inheritance, information hiding) are rules of thumb for lowering coupling and raising cohesion without over-building.

## Key concepts
- **Coupling:** degree of dependency between modules. Worst to best: content (reaching into internals), common/global state, control (passing flags that steer behavior), stamp/data (sharing whole structures), message (narrow calls). Aim for the narrow end.
- **Cohesion:** how related a module's responsibilities are. Low: grab-bag `utils`. High: everything in the module serves one purpose.
- **Information hiding (Parnas):** a module hides a design decision likely to change behind a stable interface. This is the real reason for modules.
- **Deep modules (Ousterhout):** simple interface, powerful implementation. Shallow modules (thin wrappers) add interface cost for little benefit.
- **DRY:** every piece of *knowledge* has one authoritative representation. It is about duplicated knowledge, not duplicated characters.
- **KISS:** the simplest design that works. Complexity is the enemy.
- **YAGNI:** do not build for hypothetical future requirements.
- **Law of Demeter:** talk to immediate collaborators, not their internals (`a.b.c.d()` chains = tight coupling).
- **Composition over inheritance:** assemble behavior from small parts instead of deep class trees.
- **Separation of concerns:** keep distinct concerns (UI, rules, persistence) in distinct places.
- **Principle of least surprise:** names and behavior match what a reader expects.
- **Tell, don't ask:** tell objects what to do rather than extracting their state and deciding for them.

## When to use / scenarios
- Every change to X forces edits in A, B and C: coupling is too high; find the shared decision and hide it behind one module.
- A module needs "and" in its description (`UserAuthAndEmailAndReports`): low cohesion; split.
- Two code blocks look alike: ask whether they represent the same *knowledge* (merge) or merely similar shape today that will diverge (keep apart). Rule of three: tolerate duplication until the third occurrence reveals the true abstraction.
- Tempted to add a config option or plugin point with no current user: YAGNI; add when the second use arrives.
- Choosing a boundary between services or packages: see [[monolith-vs-microservices]] and [[domain-driven-design]]; the same coupling/cohesion logic applies at larger scale.
- NOT a reason to chase zero coupling. A system whose parts do not interact does nothing; the goal is explicit, narrow, stable dependencies.

## How it works / example

Tight coupling (feature envy, Demeter violation):

```python
# Caller digs through internals; any change to Order/Customer/Address breaks it
def shipping_label(order):
    return order.customer.address.city.upper() + order.customer.address.zip
```

Loosened by hiding the decision and telling the object:

```python
class Order:
    def __init__(self, customer, items):
        self._customer, self._items = customer, items
    def shipping_label(self):                     # knowledge lives with the data
        return self._customer.mailing_label()

class Customer:
    def __init__(self, city, zip_code):
        self._city, self._zip = city, zip_code
    def mailing_label(self):
        return f"{self._city.upper()} {self._zip}"

print(Order(Customer("Lahore", "54000"), []).shipping_label())
```

Control coupling (flag argument) replaced by narrow functions or polymorphism:

```python
# before: def export(data, fmt): if fmt == "csv": ... elif fmt == "json": ...
def export_csv(data): ...
def export_json(data): ...
EXPORTERS = {"csv": export_csv, "json": export_json}   # open to extension, callers pass no flags
```

Composition over inheritance:

```python
class Logger:
    def log(self, msg): print(msg)

class RetryPolicy:
    def __init__(self, attempts): self.attempts = attempts

class ApiClient:                          # has-a, not is-a
    def __init__(self, logger, retry):
        self.logger, self.retry = logger, retry
```

Dependency direction picture:

```
   BAD: everyone reaches into everyone          GOOD: depend on narrow interfaces
   [UI] <-> [Orders] <-> [DB]                   [UI] -> [Orders API]
     \__________/___________/                          [Orders] -> [Repository interface]
                                                       [DB adapter] implements it
```

Heuristic checklist for a review: Can I change this module's internals without touching callers? Can I describe its purpose in one sentence without "and"? Does it import more than a handful of other modules? Are there cyclic imports?

## Trade-offs
- **DRY vs coupling:** merging near-duplicates creates a shared dependency; if the two users evolve differently you gain flags and conditionals. Duplication is cheaper than the wrong abstraction.
- **Abstraction vs simplicity:** each layer hides detail and adds indirection. Deep, few abstractions beat many shallow ones.
- **Cohesion vs size:** a cohesive module can still be large; split only along real seams, not to hit a line count.
- **YAGNI vs foresight:** do not build features early, but do keep decisions reversible (isolate third-party libraries behind your own thin interface, versioned APIs).
- **Inheritance vs composition:** inheritance is concise for true "is-a" with stable base classes (frameworks); composition is flexible and easier to test.
- **Loose coupling vs performance/locality:** hot paths sometimes justify tighter coupling; document it.

## Gotchas
- DRY applied to coincidental similarity: two validators that look the same but belong to different business rules.
- A `utils`/`helpers`/`common` module that everything imports is a coupling magnet and a cohesion failure.
- Global/singleton state is invisible coupling; pass dependencies explicitly.
- Cyclic dependencies between packages mean they are really one module in disguise.
- Boolean flag parameters often hide two functions in one.
- Shared database tables between services couple them as tightly as shared code.
- Over-applying Demeter produces forwarding-method bloat; apply it to behavior, not to plain data records.
- Speculative generality ("we might need pluggable X") is the most common source of unused complexity.

## Related
- [[solid-principles]] - concrete OOP guidance built on these ideas
- [[design-patterns-gof]] - recurring structures that reduce coupling (strategy, adapter, observer)
- [[refactoring-and-code-smells]] - detecting and fixing high coupling and low cohesion in existing code
- [[clean-code-and-naming]] - readability as the human side of the same goal
- [[layered-hexagonal-clean-architecture]] - coupling control at system scale
- [[monolith-vs-microservices]] - module boundaries become service boundaries
- [[library-api-design]] - information hiding applied to a package's public surface

## References
- Parnas, "On the Criteria To Be Used in Decomposing Systems into Modules", CACM 15(12), 1972: https://wstomv.win.tue.nl/edu/2ip30/references/criteria_for_modularization.pdf
- Stevens, Myers and Constantine, "Structured design", IBM Systems Journal 13(2), 1974 (origin of coupling and cohesion): https://doi.org/10.1147/sj.132.0115
- Lieberherr, "Law of Demeter" (Northeastern University): https://www.ccs.neu.edu/home/lieber/LoD.html
- Ousterhout, "A Philosophy of Software Design", chapters 4 "Modules Should Be Deep" and 5 "Information Hiding (and Leakage)".
- Hunt and Thomas, "The Pragmatic Programmer", 20th anniversary ed. (2019), topic 9 "DRY - The Evils of Duplication" and topic 28 "Decoupling".
- Yourdon and Constantine, "Structured Design" (1979), chapters 6 (coupling) and 7 (cohesion).
- Gamma et al., "Design Patterns" (1994), chapter 1, section 1.6 (favor object composition over class inheritance).
