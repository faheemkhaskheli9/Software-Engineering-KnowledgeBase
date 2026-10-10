---
title: Refactoring and code smells
category: design
tags: [refactoring, code-smells, legacy-code, characterization-tests, strangler, technical-debt]
use_cases:
  - "clean up a 1500-line function safely without changing behavior"
  - "decide whether to refactor now, later, or rewrite a legacy module"
  - "spot why every feature request touches the same five files"
  - "add tests to untested legacy code before changing it"
  - "review a PR for duplicated logic, long parameter lists and feature envy"
status: draft
last_verified: 2026-10-10
sources:
  - "Refactoring: Improving the Design of Existing Code, 2nd ed., Martin Fowler"
  - "Working Effectively with Legacy Code, Michael Feathers"
  - "https://refactoring.guru/refactoring/smells"
  - "https://martinfowler.com/bliki/StranglerFigApplication.html"
---

# Refactoring and code smells

## Summary
Refactoring is changing the internal structure of code without changing its observable behavior, in small steps, each verified by tests. Code smells are surface symptoms (long method, duplicated code, feature envy) that hint at deeper design trouble. Together they give a disciplined loop: notice smell, ensure a safety net, apply a named refactoring, run tests, commit.

## Key concepts
- **Behavior preservation:** if behavior changes it is a feature or a fix, not a refactoring. Keep the two kinds of commits separate.
- **Safety net first:** tests (or at minimum characterization tests that pin current behavior) must exist before restructuring.
- **Small steps:** many tiny reversible transformations beat one big rewrite. Green tests between each step.
- **Code smell:** a heuristic indicator, not a defect. Judgment decides.
- Common smells:
  - Long Method / Large Class (god object)
  - Duplicated Code
  - Long Parameter List, Data Clumps (same group of args travel together)
  - Feature Envy (method uses another class's data more than its own)
  - Shotgun Surgery (one change touches many places) and Divergent Change (one class changes for many reasons)
  - Primitive Obsession (strings/ints for domain concepts)
  - Switch/if-chains on type; Speculative Generality; Dead Code; Comments that explain bad code
  - Message chains (`a.b().c().d()`), Middle Man
- Core refactorings: Extract Function, Inline Function, Rename, Extract Class, Move Function, Introduce Parameter Object, Replace Conditional with Polymorphism, Replace Magic Number with Constant, Replace Temp with Query, Decompose Conditional.
- **Rule of three:** duplicate once, tolerate twice, refactor on the third.
- **Boy scout rule:** leave code a little cleaner than you found it.

## When to use / scenarios
- Before adding a feature to messy code: "make the change easy, then make the easy change" (Kent Beck).
- When a bug fix needs understanding a confusing function: refactor to understand, then fix.
- During code review ([[code-review]]) when a smell recurs.
- Legacy code with no tests: write characterization tests that record actual outputs, then refactor under them. For module-scale replacement use the Strangler Fig: route traffic gradually to the new implementation; see [[technical-debt-management]].
- NOT when: no tests and no time to add them, the code is about to be deleted, or deadline pressure makes a half-done refactor riskier than leaving it. Never mix a refactor into an urgent hotfix.
- Full rewrites are almost always costlier than incremental refactoring; justify them explicitly (see [[architecture-decision-records]]).

## How it works / example

The loop:

```
smell noticed -> tests green? (write characterization tests if not)
  -> one small refactoring -> run tests -> commit -> repeat
```

Before: long function, primitive obsession, magic numbers.

```python
def process(order):
    total = 0
    for item in order["items"]:
        total += item["price"] * item["qty"]
    if order["customer"]["type"] == "vip":
        total = total * 0.9
    elif order["customer"]["type"] == "staff":
        total = total * 0.8
    if total > 1000:
        total += 0
    else:
        total += 25
    return total
```

After: Extract Function, named constants, Replace Conditional with lookup.

```python
DISCOUNT = {"vip": 0.10, "staff": 0.20}
FREE_SHIPPING_OVER = 1000
SHIPPING_FEE = 25

def subtotal(items):
    return sum(i["price"] * i["qty"] for i in items)

def discounted(total, customer_type):
    return total * (1 - DISCOUNT.get(customer_type, 0))

def shipping(total):
    return 0 if total > FREE_SHIPPING_OVER else SHIPPING_FEE

def process(order):
    total = discounted(subtotal(order["items"]), order["customer"]["type"])
    return total + shipping(total)
```

Characterization test to pin behavior before touching legacy code:

```python
def test_process_characterization():
    order = {"items": [{"price": 100, "qty": 2}], "customer": {"type": "vip"}}
    assert process(order) == 205.0     # observed value from the existing code, not a spec
```

Replace a type-switch with polymorphism (when variants carry behavior):

```python
class Vip:   rate = 0.10
class Staff: rate = 0.20
class Regular: rate = 0.0
# each type can later own more behavior without touching a central if-chain
```

Introduce Parameter Object for data clumps:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DateRange:
    start: str
    end: str
# report(start, end, ...) becomes report(range_, ...)
```

Tools: IDE rename/extract (automated refactorings are safer than manual), linters (ruff, pylint complexity checks), coverage reports to find untested areas, `git blame`/churn analysis to find hot spots worth cleaning.

## Trade-offs
- **Refactor now vs later:** cleaning along the way is cheap and keeps debt low; large cleanups need scheduled time and explicit buy-in.
- **Refactor vs rewrite:** refactoring preserves hard-won edge-case behavior; rewriting resets risk to zero knowledge. Prefer the strangler approach when replacement is needed.
- **Test coverage cost vs safety:** characterization tests are brittle by nature (they pin accidents too) but are the pragmatic bridge for legacy code.
- **DRY vs clarity:** removing duplication can couple unrelated concerns ([[coupling-cohesion-and-design-principles]]).
- **Local vs systemic smells:** a long method is a quick fix; shotgun surgery usually signals a misplaced boundary and needs design work.
- **Churn vs value:** refactor code that changes often; leave stable ugly code alone.

## Gotchas
- Refactoring without tests: "it looks the same" is not verification.
- Mixing refactoring and behavior change in one commit makes review and bisect painful.
- Renaming public APIs breaks external callers; deprecate first.
- Extracting functions that share mutable state creates parameter explosions; extract a class instead.
- Over-eager abstraction during refactor (introducing hierarchies "while we're here").
- Metrics worship: cyclomatic complexity thresholds flag candidates, they do not prove a problem.
- Long-lived refactoring branches conflict with the whole team's work; land small steps behind green CI.
- Dynamic features (reflection, string-based dispatch, monkeypatching) defeat automated refactoring tools; grep and test thoroughly.

## Related
- [[clean-code-and-naming]] - naming and function-shape rules that most refactorings aim at
- [[solid-principles]] - target structure when splitting a god class
- [[design-patterns-gof]] - patterns are common destinations of refactoring
- [[unit-testing-and-test-doubles]] - the safety net
- [[technical-debt-management]] - deciding what to refactor and when
- [[code-review]] - where smells are usually caught
- [[functional-core-imperative-shell]] - a target shape when extracting logic from I/O-heavy code

## References
- Fowler, "Refactoring", 2nd ed. (2018)
- Feathers, "Working Effectively with Legacy Code"
- Refactoring.Guru smells catalog: https://refactoring.guru/refactoring/smells
- Fowler, Strangler Fig Application: https://martinfowler.com/bliki/StranglerFigApplication.html
