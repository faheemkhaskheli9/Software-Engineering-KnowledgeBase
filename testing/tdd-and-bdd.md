---
title: TDD and BDD
category: testing
tags: [tdd, bdd, red-green-refactor, gherkin, acceptance-testing, behave, pytest-bdd]
use_cases:
  - "adopt test-driven development on a new feature"
  - "turn product requirements into executable acceptance tests"
  - "write Gherkin scenarios that business stakeholders can review"
  - "refactor safely by writing tests first"
  - "decide whether our team needs BDD tooling at all"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.oreilly.com/library/view/test-driven-development/0321146530/
  - https://dannorth.net/introducing-bdd/
  - https://cucumber.io/docs/gherkin/reference/
  - https://behave.readthedocs.io/
  - https://martinfowler.com/bliki/TestDrivenDevelopment.html
---

# TDD and BDD

## Summary
Test-driven development (TDD) is a design and implementation loop: write a
failing test, make it pass with the simplest code, then refactor. Behaviour-
driven development (BDD) extends the idea to shared, example-based
specifications written in domain language that both business and engineers can
read, often as Given/When/Then scenarios. TDD is a developer technique; BDD is
a collaboration technique that may or may not use special tooling.

## Key concepts
- **Red-Green-Refactor (Kent Beck):** (1) Red: write a small failing test;
  (2) Green: do the least to pass; (3) Refactor: clean up with tests green.
  Cycles last minutes.
- **Three rules (Uncle Bob):** no production code without a failing test; no
  more test than needed to fail; no more production code than needed to pass.
- **Schools:** *Chicago/classicist* (state-based, real collaborators, inside-
  out) vs *London/mockist* (interaction-based, doubles, outside-in).
- **ATDD / outside-in:** start from a failing acceptance test at the system
  edge, then drive inner units with TDD (the "double loop").
- **BDD:** discover requirements through conversations ("three amigos":
  business, dev, QA), capture concrete examples, automate them as living
  documentation.
- **Gherkin:** `Feature`, `Scenario`, `Given` (context), `When` (action),
  `Then` (outcome), `And/But`; `Scenario Outline` with `Examples` tables.
- **Test list / baby steps:** keep a list of next tests; triangulate to
  generalise from several examples.

## When to use / scenarios
- Well-understood logic with clear inputs/outputs (pricing, parsers, rules):
  TDD works superbly.
- Bug fixes: write the failing regression test first, always.
- Refactoring or characterising legacy code: add tests first, then change.
- Cross-functional requirements with ambiguity or compliance wording: BDD
  conversations and Gherkin examples.
- Poor fit: exploratory spikes, UI layout, prototypes whose shape is unknown
  (spike first, then discard and TDD the real thing), and teams where nobody
  reads the Gherkin (then it is just a verbose, slow test layer).

## How it works / example

One red-green-refactor cycle in pytest, building a `slugify` function.

```python
# Step 1 RED: write the test, run it, watch it fail (ImportError/NameError)
# test_slug.py
from slug import slugify

def test_lowercases_and_hyphenates():
    assert slugify("Hello World") == "hello-world"

# Step 2 GREEN: simplest thing that passes
# slug.py
def slugify(s):
    return s.lower().replace(" ", "-")

# Step 3 RED again: next example forces generalisation
def test_strips_punctuation_and_collapses_spaces():
    assert slugify("  Hello,   World!  ") == "hello-world"

# Step 4 GREEN + REFACTOR
import re
def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
```

BDD scenario and step definitions with `pytest-bdd` (or behave, same idea):

```gherkin
# features/discount.feature
Feature: Loyalty discount
  Scenario Outline: Discount by tier
    Given a customer with <tier> status
    When they check out a basket of <total> euros
    Then they pay <paid> euros

    Examples:
      | tier   | total | paid |
      | gold   | 100   | 90   |
      | silver | 100   | 95   |
      | none   | 100   | 100  |
```

```python
from pytest_bdd import scenarios, given, when, then, parsers
scenarios("features/discount.feature")

@given(parsers.parse("a customer with {tier} status"), target_fixture="customer")
def customer(tier): return {"tier": tier}

@when(parsers.parse("they check out a basket of {total:d} euros"), target_fixture="charged")
def checkout(customer, total): return price(customer["tier"], total)

@then(parsers.parse("they pay {paid:d} euros"))
def assert_paid(charged, paid): assert charged == paid
```

Write scenarios declaratively ("Given a gold customer") not procedurally
("Given I click the login button...").

## Trade-offs
- **TDD design pressure vs speed on unknowns:** TDD yields testable, decoupled
  design and a regression net; it slows exploration. Spike, then rebuild with
  tests.
- **Mockist vs classicist:** mockist (outside-in) clarifies collaborator
  roles but couples tests to interactions; classicist resists refactoring
  better but can need larger setup.
- **BDD tooling vs plain tests:** Gherkin adds an indirection layer and
  maintenance; worthwhile only when non-engineers actually read and co-author
  scenarios. Otherwise well-named pytest tests deliver most of the value.
- **Acceptance test level:** through the UI (slow, brittle) vs through the
  service API (faster, stabler). Prefer the lowest level that expresses the
  behaviour.

## Gotchas
- Testing implementation details, so every refactor turns tests red.
- Skipping the refactor step, accumulating cruft that the tests merely
  protect.
- Writing the test after the code and calling it TDD; the red step proves the
  test can fail.
- Giant steps: if you cannot get green in minutes, back up and take a smaller
  step.
- Gherkin scenarios as UI scripts; dozens of near-duplicate scenarios;
  scenarios nobody owns.
- Coverage-driven TDD ("add tests until 90%") misses the design benefit.
- Mutation testing (mutmut, cosmic-ray) is the honest check that your
  tests would notice a bug.

## Related
- [[unit-testing-and-test-doubles]] - the building blocks of the TDD loop.
- [[testing-strategy-and-pyramid]] - where acceptance and unit tests fit.
- [[refactoring-and-code-smells]] - the third step of red-green-refactor.
- [[domain-driven-design]] - ubiquitous language feeds BDD scenarios.
- [[agile-scrum-kanban]] - acceptance criteria and definition of done.
- [[property-based-and-fuzz-testing]] - complements example-based tests.

## References
- Kent Beck, Test-Driven Development: By Example (2002).
- Dan North, "Introducing BDD", https://dannorth.net/introducing-bdd/
- Cucumber Gherkin reference; behave and pytest-bdd documentation.
- Freeman and Pryce, Growing Object-Oriented Software, Guided by Tests (2009).
