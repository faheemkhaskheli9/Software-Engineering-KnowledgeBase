---
title: Testing strategy and the test pyramid
category: testing
tags: [testing, test-pyramid, e2e, flaky-tests, coverage, ci, test-strategy]
use_cases:
  - "decide how many unit, integration and end-to-end tests our service needs"
  - "fix a slow and flaky CI test suite"
  - "set a sensible coverage policy for the team"
  - "plan a test strategy for a new microservice"
  - "choose what to test manually versus automate"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/articles/practical-test-pyramid.html
  - https://martinfowler.com/bliki/TestPyramid.html
  - https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html
  - https://abseil.io/resources/swe-book/html/ch11.html
  - https://martinfowler.com/articles/microservice-testing/
---

# Testing strategy and the test pyramid

## Summary
A testing strategy decides which kinds of tests you write, in what
proportions, and what each is responsible for, so that the suite gives fast,
trustworthy feedback at a sustainable maintenance cost. The classic test
pyramid says: many fast, isolated unit tests; fewer integration tests; very
few slow end-to-end (E2E) tests.

## Key concepts
- **Pyramid:** unit (milliseconds, no I/O) at the base; integration/service
  tests (real DB, queue, HTTP boundary) in the middle; E2E/UI at the top.
  Cost, runtime, flakiness and diagnosis difficulty grow up the pyramid;
  confidence in real wiring also grows.
- **Alternative shapes:** the *trophy* (Kent C. Dodds) emphasises integration
  tests for frontends; the *honeycomb* (Spotify) for microservices favours
  integration tests over unit tests of thin glue. Pick by where bugs actually
  live; the principle is "test at the lowest level that can catch the bug".
- **Google's size taxonomy:** small (single process, no I/O), medium (single
  machine, localhost), large (multi-machine). Sizes constrain what a test may
  do, which keeps small tests fast and deterministic.
- **Test types by purpose:** functional, regression, contract, performance,
  security, accessibility, exploratory (manual, human-driven).
- **Coverage:** a lagging signal of untested code, not evidence of good tests.
  Mutation testing measures whether tests catch changes.
- **Flaky test:** passes and fails without code change. Treat as a bug.

## When to use / scenarios
- Business logic, parsing, pricing, state machines: heavy unit coverage.
- Persistence queries, migrations, framework wiring, serialization: integration
  tests against the real thing (Testcontainers), not mocks.
- Service boundaries between teams: contract tests.
- Critical user journeys (signup, checkout): a handful of E2E smoke tests,
  run on deploy; not every permutation.
- Legacy code with no tests: start with characterization tests at the
  highest seam that is practical, then refactor under them.
- Anti-pattern: the *ice-cream cone* (mostly manual and E2E tests, few unit
  tests): slow, flaky, expensive.

## How it works / example

A budget view of a typical web service:

```
          /\            E2E: 5-20 journeys, run on every deploy (minutes)
         /  \           Integration/contract: per component, real DB (seconds)
        /----\          Unit: thousands, pure logic (sub-second total)
       /______\
```

Mark and select tiers so CI can run them separately (pytest markers):

```python
# conftest.py
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs real DB/services")
    config.addinivalue_line("markers", "e2e: full-stack, slow")

# test_pricing.py
import pytest

def apply_discount(total: float, pct: float) -> float:
    if not 0 <= pct <= 100:
        raise ValueError("pct out of range")
    return round(total * (1 - pct / 100), 2)

def test_discount_basic():
    assert apply_discount(200.0, 10) == 180.0

def test_discount_rejects_bad_pct():
    with pytest.raises(ValueError):
        apply_discount(100.0, 120)

@pytest.mark.integration
def test_order_persisted(db_session):   # fixture provides a real Postgres
    ...
```

CI layout: `pytest -m "not integration and not e2e"` on every push (fast
gate); integration on every PR; E2E post-merge or pre-deploy. Quarantine
flaky tests automatically (retry once, record, open a ticket) rather than
letting the team learn to ignore red builds.

Test design rules of thumb:
- Arrange-Act-Assert; one reason to fail per test.
- Test behaviour through public interfaces, not private implementation.
- Deterministic: inject clocks, seeds, IDs; no sleeping on real time.
- Independent: any order, in parallel, no shared mutable state.

## Trade-offs
- **Coverage target:** a floor (for example 70-80% on new code) prevents rot;
  chasing 100% encourages assertion-free tests and brittle mocks.
- **Mock-heavy units vs integration-heavy:** mocks are fast but verify
  assumptions; real dependencies find real bugs but cost seconds. Mix by risk.
- **E2E breadth:** more E2E means more confidence in wiring and more flake and
  maintenance; keep the set small and owned.
- **Testing in production** (canaries, feature flags, synthetic checks,
  observability) complements pre-prod tests, especially for distributed
  behaviour you cannot reproduce locally.
- **Manual exploratory testing** finds what scripts do not imagine; automate
  regressions, keep humans for exploration.

## Gotchas
- Duplicated coverage: the same rule tested at unit, integration and E2E
  levels triples change cost.
- Tests coupled to implementation break on every refactor, teaching
  engineers to distrust or delete them.
- Shared test environments and shared data produce order-dependent failures.
- `sleep()`-based waits; use explicit conditions/polling with timeouts.
- Ignoring test code quality; it needs the same review and refactoring.
- A green suite after mocking everything proves little. Verify each mocked
  boundary is covered by an integration or contract test somewhere.
- Test data realism: toy data hides encoding, null, size and timezone bugs.

## Related
- [[unit-testing-and-test-doubles]] - the base of the pyramid in detail.
- [[integration-and-contract-testing]] - the middle tier and service boundaries.
- [[tdd-and-bdd]] - test-first workflows that shape the suite.
- [[property-based-and-fuzz-testing]] - generated inputs for unit-level rigor.
- [[performance-and-load-testing]] - non-functional tier of the strategy.
- [[ci-cd-pipelines]] - staging the tiers into fast and slow gates.
- [[flaky-tests]] - detecting, quarantining and fixing nondeterministic tests.
- [[mutation-testing]] - measuring whether tests catch injected bugs, beyond coverage.
- [[test-data-management]] - builders, factories and isolation for test state.
- [[snapshot-and-golden-testing]] - output-level regression tests and their review discipline.
- [[accessibility-basics]] - automated plus manual accessibility checks in the test mix.
- See also (AI KB): [LLM evaluation](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/llm-evaluation.md) - testing non-deterministic LLM output with eval sets instead of exact asserts.

## References
- Martin Fowler, "The Practical Test Pyramid", https://martinfowler.com/articles/practical-test-pyramid.html
- Winters, Manshreck, Wright, Software Engineering at Google, ch. 11-14 (Testing).
- Google Testing Blog, "Just Say No to More End-to-End Tests".
- Toby Clemson, "Testing Strategies in a Microservice Architecture" (martinfowler.com, 2014).
