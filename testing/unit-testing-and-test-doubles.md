---
title: Unit testing and test doubles
category: testing
tags: [unit-testing, pytest, mock, stub, fake, spy, dependency-injection, fixtures]
use_cases:
  - "write pytest unit tests for code that calls an external API"
  - "replace a database or clock in tests without making them brittle"
  - "decide between a mock, a stub and a fake"
  - "make a legacy function testable by injecting its dependencies"
  - "parametrize tests to cover many input cases concisely"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/articles/mocksArentStubs.html
  - https://docs.pytest.org/en/stable/
  - https://docs.python.org/3/library/unittest.mock.html
  - http://xunitpatterns.com/Test%20Double.html
  - https://abseil.io/resources/swe-book/html/ch13.html
---

# Unit testing and test doubles

## Summary
A unit test exercises a small piece of behaviour in isolation, fast and
deterministically, and fails for exactly one reason. Test doubles (dummies,
stubs, spies, mocks, fakes) replace slow or nondeterministic collaborators
such as the network, database, clock and randomness. The skill is replacing
the right boundaries, and asserting on outcomes rather than on implementation.

## Key concepts
Gerard Meszaros' taxonomy (xUnit Patterns), as popularised by Fowler:
- **Dummy:** passed to fill a parameter, never used.
- **Stub:** returns canned answers; drives the code under test down a path.
- **Spy:** a stub that also records how it was called.
- **Mock:** pre-programmed with expectations about calls; fails if they are
  not met (verifies behaviour/interaction).
- **Fake:** a working lightweight implementation (in-memory repository, SQLite
  instead of Postgres, fake clock).
- **State vs interaction testing:** state tests assert on results/state;
  interaction tests assert calls were made. Prefer state; use interaction only
  for side effects with no observable state (sending an email).
- **Seams and dependency injection:** pass collaborators in (constructor or
  parameter) so tests can substitute them. Don't mock what you don't own;
  wrap third-party clients in your own thin adapter and double the adapter.
- **FIRST:** Fast, Isolated, Repeatable, Self-validating, Timely.

## When to use / scenarios
- Pure logic: no doubles needed; just call and assert.
- Code with I/O: inject a port (interface), pass a fake in tests.
- Time-dependent code: inject a clock callable.
- Verifying a side effect happened (notification sent, metric emitted): spy
  or mock.
- Avoid doubles for value objects, simple pure collaborators, and the thing
  under test itself. Over-mocking couples tests to implementation.

## How it works / example

Code designed with a seam:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

class EmailSender(Protocol):
    def send(self, to: str, subject: str) -> None: ...

class UserRepo(Protocol):
    def find_by_email(self, email: str) -> "User | None": ...
    def add(self, user: "User") -> None: ...

@dataclass
class User:
    email: str
    created_at: datetime

class Signup:
    def __init__(self, repo: UserRepo, mailer: EmailSender,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.repo, self.mailer, self.now = repo, mailer, now

    def register(self, email: str) -> User:
        if self.repo.find_by_email(email):
            raise ValueError("already registered")
        user = User(email, self.now())
        self.repo.add(user)
        self.mailer.send(email, "Welcome")
        return user
```

Tests using a fake (state), a spy (interaction) and a fixed clock:

```python
import pytest
from datetime import datetime, timezone

class FakeRepo:                                   # fake: real behaviour, in memory
    def __init__(self): self.users = {}
    def find_by_email(self, e): return self.users.get(e)
    def add(self, u): self.users[u.email] = u

class SpyMailer:                                  # spy: records calls
    def __init__(self): self.sent = []
    def send(self, to, subject): self.sent.append((to, subject))

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)

@pytest.fixture
def svc():
    repo, mailer = FakeRepo(), SpyMailer()
    return Signup(repo, mailer, now=lambda: FIXED), repo, mailer

def test_register_persists_and_welcomes(svc):
    s, repo, mailer = svc
    user = s.register("a@b.com")
    assert repo.find_by_email("a@b.com") == user       # state
    assert user.created_at == FIXED                    # deterministic time
    assert mailer.sent == [("a@b.com", "Welcome")]     # side effect

def test_duplicate_rejected(svc):
    s, _, mailer = svc
    s.register("a@b.com")
    with pytest.raises(ValueError):
        s.register("a@b.com")
    assert len(mailer.sent) == 1                       # no second email

@pytest.mark.parametrize("email", ["", "no-at", "x@"])
def test_invalid_emails_documented_behaviour(email):
    ...
```

When `unittest.mock` is the right tool: stubbing a function you cannot inject.

```python
from unittest.mock import patch, Mock

def test_fetch_rate_handles_timeout():
    with patch("myapp.rates.requests.get", side_effect=TimeoutError):
        assert get_rate("EUR") is None        # graceful fallback

def test_notifier_called_once():
    notifier = Mock()
    process(order_id=1, notifier=notifier)
    notifier.assert_called_once_with(order_id=1)
```

Patch where the name is *looked up* (the importing module), not where it is
defined. Use `Mock(spec=Real)` or `create_autospec` so signatures stay honest.

## Trade-offs
- **Fakes vs mocks:** fakes survive refactors and are reusable but need
  maintenance and their own tests; mocks are quick but encode call sequences.
  Google's guidance favours real implementations, then fakes, then mocks.
- **Granularity:** testing at "unit = class" vs "unit = behaviour via a small
  cluster of classes". The latter resists refactoring better.
- **Parametrized vs separate tests:** parametrize for data variations; separate
  tests when failure messages and intent differ.
- **Test readability vs DRY:** some duplication in tests is fine; each test
  should read as a standalone specification.

## Gotchas
- Mocking the thing under test, or asserting only that mocks were called,
  yields tests that pass while the real code is broken.
- A fake that diverges from the real dependency (ordering, constraints,
  errors) gives false confidence; back it with a contract test run against
  both.
- Patching the wrong import path: the patch silently has no effect.
- Shared module-level state and fixtures with wide scope create order
  dependence; run in random order (pytest-randomly) in CI to detect it.
- Floating-point equality: use `pytest.approx`.
- Asserting on log text or exact error strings makes tests brittle.
- Time: `datetime.now()` or `sleep` inside code under test; inject instead.

## Related
- [[testing-strategy-and-pyramid]] - where unit tests sit in the overall suite.
- [[integration-and-contract-testing]] - verify the doubles match reality.
- [[tdd-and-bdd]] - writing these tests first to drive design.
- [[solid-principles]] - dependency inversion is what creates testable seams.
- [[property-based-and-fuzz-testing]] - generated inputs instead of hand-picked.
- [[layered-hexagonal-clean-architecture]] - ports and adapters make doubles natural.

## References
- Martin Fowler, "Mocks Aren't Stubs".
- Meszaros, xUnit Test Patterns (2007), Test Double.
- pytest and unittest.mock documentation.
- Software Engineering at Google, ch. 13 "Test Doubles".
