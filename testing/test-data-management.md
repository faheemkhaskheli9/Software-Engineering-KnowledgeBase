---
title: Test data management
category: testing
tags: [test-data, fixtures, test-data-builder, object-mother, factories, factory-boy, seed-data, anonymization, database-tests]
use_cases:
  - "stop tests breaking every time a new required field is added to a model"
  - "set up realistic database state for integration tests without a shared mutable test DB"
  - "use production-like data in staging without leaking personal data"
  - "make tests independent so they can run in parallel and in any order"
  - "choose between fixtures files, factories and builders for test setup"
status: draft
last_verified: 2026-10-10
sources:
  - "xUnit Test Patterns, Gerard Meszaros (Fresh Fixture, Shared Fixture, Test Data patterns) - http://xunitpatterns.com/"
  - "Growing Object-Oriented Software, Guided by Tests, Freeman and Pryce (Test Data Builders)"
  - "ObjectMother, Martin Fowler bliki - https://martinfowler.com/bliki/ObjectMother.html"
  - "factory_boy docs - https://factoryboy.readthedocs.io/"
  - "pytest fixtures docs - https://docs.pytest.org/en/stable/how-to/fixtures.html"
  - "UK ICO guidance on anonymisation and pseudonymisation - https://ico.org.uk/"
---

# Test data management

## Summary
Test data management is how tests get the inputs and stored state they need: building objects, seeding databases, and isolating each test's data from every other test's. The durable approach is for each test to create the minimal data it needs through builders or factories with sensible defaults, mention only the fields that matter to its assertion, and clean up through transactions or throwaway databases. Shared, hand-maintained fixture databases and copies of production data are the usual sources of brittle, order-dependent and privacy-risky tests.

## Key concepts
- **Fresh fixture vs shared fixture (Meszaros):** a fresh fixture is built per test (isolated, slower); a shared fixture is reused (fast, risks interference).
- **Object Mother:** a class of named factory methods returning canned objects (`customers.with_overdue_invoice()`). Readable, but grows a method per variation.
- **Test Data Builder (Freeman and Pryce):** a builder with defaults for every field and `with_x()` methods to override only what the test cares about.
- **Factories (factory_boy, FactoryBot):** library-backed builders that also persist to the DB and generate sequences and related objects.
- **Static fixtures:** JSON/YAML/SQL files loaded before tests. Simple for reference data (countries, currencies); brittle for business entities.
- **Seed data:** the minimal reference data an environment needs to run (roles, plans, feature flags), versioned with migrations ([[schema-migrations]]).
- **Isolation strategies:** wrap each test in a transaction and roll back; truncate tables between tests; a fresh database or schema per test worker; ephemeral containers ([[integration-and-contract-testing]]).
- **Synthetic vs production-derived data:** synthetic (generated, Faker) avoids privacy risk; production-derived (masked, subsetted) captures real distributions and edge cases but must be anonymized.
- **Anonymization vs pseudonymization:** anonymized data can no longer identify a person; pseudonymized data replaces identifiers but can be re-linked with extra information and is generally still personal data under GDPR-style regimes.
- **Deterministic generation:** seeded random generators so a failing case can be reproduced.

## When to use / scenarios

| Need | Approach |
|---|---|
| Domain objects in unit tests | builder or plain constructor with defaults |
| Rows in a real DB for integration tests | factories + per-test transaction rollback |
| Reference data every environment needs | versioned seed data / migrations |
| Load or performance tests | generated data at realistic volume and distribution ([[performance-and-load-testing]]) |
| Reproducing a production bug | minimal synthetic case extracted from the report; never a raw prod dump on a laptop |
| Staging with realistic data | subsetted, masked copy with a documented anonymization step |

- NOT a large shared "test database" that every test reads and writes: tests start depending on each other and on data someone edited by hand.
- NOT production personal data in test or dev environments without anonymization and a legal basis ([[secrets-management]] covers credentials; the same care applies to PII).

## How it works / example

Test Data Builder: defaults for everything, override only what the test is about.

```python
from dataclasses import dataclass, field, replace
from datetime import date
from itertools import count

_ids = count(1)

@dataclass(frozen=True)
class Customer:
    id: int
    email: str
    country: str
    vip: bool
    signup: date

def a_customer(**overrides):
    n = next(_ids)
    base = Customer(id=n, email=f"user{n}@example.test", country="DE",
                    vip=False, signup=date(2026, 1, 1))
    return replace(base, **overrides)        # unknown field names raise TypeError

def discount(c: Customer) -> int:
    return 10 if c.vip else 0

# The test names only the field that matters; adding a new field later does not touch it
assert discount(a_customer(vip=True)) == 10
assert discount(a_customer()) == 0
assert a_customer().email != a_customer().email   # unique by default
```

Per-test transaction rollback with SQLite (the same pattern as a pytest fixture around each test):

```python
import sqlite3

db = sqlite3.connect(":memory:", isolation_level=None)   # autocommit; we manage transactions
db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)")
db.execute("INSERT INTO orders (total) VALUES (100)")      # seed data shared by all tests

def run_isolated(test):
    db.execute("BEGIN")
    try:
        test(db)
    finally:
        db.execute("ROLLBACK")                              # nothing a test writes leaks out

def test_adds_order(conn):
    conn.execute("INSERT INTO orders (total) VALUES (50)")
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2

def test_sees_only_seed(conn):
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1

run_isolated(test_adds_order)
run_isolated(test_sees_only_seed)                           # passes in any order
print("isolated")
```

Deterministic masking for a staging copy (keyed hash keeps joins working; the key stays out of the dataset):

```python
import hashlib
import hmac

KEY = b"rotate-me-and-keep-me-out-of-the-repo"   # placeholder; load from a secret store

def mask_email(email: str) -> str:
    digest = hmac.new(KEY, email.lower().encode(), hashlib.sha256).hexdigest()[:12]
    return f"user-{digest}@example.test"

assert mask_email("Ana@Corp.com") == mask_email("ana@corp.com")   # same person, same token
print(mask_email("ana@corp.com"))
```

Keyed hashing is pseudonymization, not anonymization: anyone with the key, or with enough other columns, may re-identify people. Check the rules that apply to you before treating a masked copy as non-personal data.

## Trade-offs
- **Builders/factories vs static fixture files:** builders keep data next to the test and survive schema growth; fixture files are easy to load and share but every test silently depends on their full contents.
- **Fresh vs shared fixtures:** fresh data per test is isolated and parallel-safe; shared data is faster to set up. A common compromise: shared read-only seed data, fresh per-test writes.
- **Transaction rollback vs truncation vs new DB:** rollback is fastest but cannot test code that commits or uses multiple connections; truncation works across connections but is slower; a database per worker is the most isolated and costs setup time.
- **Synthetic vs production-derived:** synthetic is safe and controllable but misses real-world oddities; production-derived finds them but needs masking, subsetting, access control and a retention policy.
- **Random vs fixed values:** random data can find unexpected bugs ([[property-based-and-fuzz-testing]]); fixed data makes failures reproducible. Seed the generator and print the seed.

## Gotchas
- Tests asserting on data they did not create (`assert count == 42` against a shared DB) break when anyone adds a row.
- Hard-coded IDs collide when tests run in parallel; let the database or a sequence assign them.
- Factories that create deep object graphs by default (customer -> 10 orders -> 50 items) make tests slow; default to the minimum.
- Time-dependent data (`signup = today`) makes tests pass or fail by date; inject a fixed clock.
- Code under test that opens its own connection does not see data inside the test's uncommitted transaction.
- Masking only obvious columns (email, name) leaves PII in free-text fields, JSON blobs, logs and attachments.
- Unique constraints on generated values (emails, usernames) fail under reruns unless values include a sequence.
- Seed data drifting from migrations: environments diverge; generate seeds from the same migration pipeline.

## Related
- [[testing-strategy-and-pyramid]] - which tiers need real data and how much
- [[unit-testing-and-test-doubles]] - fixtures, fakes and in-memory repositories
- [[integration-and-contract-testing]] - containers and ephemeral databases for realistic tests
- [[flaky-tests]] - shared data and order dependence as causes of flakiness
- [[schema-migrations]] - versioned seed data and schema changes
- [[snapshot-and-golden-testing]] - stable inputs make outputs reproducible
- [[threat-modeling]] - deciding how much production data may leave production

## References
- Meszaros, "xUnit Test Patterns" (Fresh Fixture, Shared Fixture, Transaction Rollback Teardown)
- Freeman and Pryce, "Growing Object-Oriented Software, Guided by Tests" (Test Data Builders)
- Fowler, "ObjectMother" (bliki)
- factory_boy and pytest fixtures documentation
- UK ICO guidance on anonymisation and pseudonymisation
