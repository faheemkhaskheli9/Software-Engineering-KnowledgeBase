---
title: Integration and contract testing
category: testing
tags: [integration-testing, contract-testing, pact, testcontainers, consumer-driven, api-testing]
use_cases:
  - "test our repository layer against a real Postgres in CI"
  - "stop breaking the mobile app or another team's service when we change our API"
  - "verify our service against a third-party API without calling it live"
  - "set up consumer-driven contract tests between microservices"
  - "make integration tests fast and isolated"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/bliki/IntegrationTest.html
  - https://martinfowler.com/articles/consumerDrivenContracts.html
  - https://docs.pact.io/
  - https://testcontainers.com/
  - https://martinfowler.com/articles/microservices-testing/
---

# Integration and contract testing

## Summary
Integration tests check that your code works with real collaborators:
database, message broker, filesystem, HTTP framework. Contract tests check
that two independently deployed components (consumer and provider) agree on
the interface, without spinning up both in one environment. Together they
cover the wiring that unit tests with doubles cannot prove.

## Key concepts
- **Narrow integration test:** exercises your code plus one real dependency
  (for example repository + Postgres). Fast enough for every PR.
- **Broad integration / system test:** several real services together. Slow,
  fragile; keep few.
- **Component test:** one service run for real with its outbound dependencies
  stubbed at the network edge (WireMock, `responses`, `pytest-httpserver`).
- **Contract test:** consumer records the requests it makes and responses it
  needs (a *pact*); the provider replays them against its real code in its own
  pipeline. Break either side and the build fails before deploy.
- **Consumer-driven contracts (CDC):** the contract expresses only what
  consumers actually use, so providers learn which fields are safe to change.
- **Schema-based alternatives:** OpenAPI/JSON Schema/protobuf compatibility
  checks (breaking-change detectors like `buf breaking`, oasdiff) for public
  APIs with unknown consumers.
- **Testcontainers:** start real databases/brokers in throwaway Docker
  containers from test code.

## When to use / scenarios
- ORM mappings, SQL, migrations, transactions, indexes, constraints: real DB.
- Message consumers/producers: real broker (or emulator) with a round trip.
- Internal microservices owned by different teams: CDC with Pact; run the
  `can-i-deploy` gate.
- Third-party APIs: record/replay (VCR.py) plus a periodic live smoke test,
  or a sandbox environment. Contract-test against *your adapter*, not the
  vendor.
- Public API with many unknown consumers: schema compatibility and
  versioning policy instead of per-consumer pacts.
- Don't use an in-memory SQLite stand-in to validate Postgres-specific SQL.

## How it works / example

Real Postgres per test session with Testcontainers
(`pip install testcontainers[postgres] psycopg[binary] pytest`):

```python
import pytest, psycopg
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer("postgres:16") as pg:
        yield pg.get_connection_url().replace("+psycopg2", "")

@pytest.fixture
def conn(pg_url):
    with psycopg.connect(pg_url) as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id serial PRIMARY KEY, email text UNIQUE)")
        yield c
        c.rollback()                      # isolate tests by rolling back

@pytest.mark.integration
def test_unique_email_enforced(conn):
    conn.execute("INSERT INTO users(email) VALUES ('a@b.com')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO users(email) VALUES ('a@b.com')")
```

Isolation strategies: transaction rollback per test (fast), truncate tables
between tests, or a schema/database per xdist worker. Apply real migrations
in the fixture so migration bugs are caught too.

Consumer-side contract with pact-python (sketch; check current API in docs):

```python
from pact import Consumer, Provider

pact = Consumer("OrderUI").has_pact_with(Provider("OrderService"), port=1234)

def test_get_order():
    (pact.given("order 42 exists")
         .upon_receiving("a request for order 42")
         .with_request("GET", "/orders/42")
         .will_respond_with(200, body={"id": 42, "status": "PAID"}))
    with pact:
        order = OrderClient("http://localhost:1234").get(42)
    assert order.status == "PAID"
# The generated pact file is published to a broker; the provider pipeline
# verifies it, and `can-i-deploy` blocks incompatible releases.
```

Flow: consumer test -> pact file -> broker -> provider verification ->
can-i-deploy gate in both pipelines.

## Trade-offs
- **Real dependency vs stub:** real is truthful but slower and needs Docker in
  CI; stubs are fast but can drift. Cover the drift with a contract/smoke test.
- **Pact (CDC) vs OpenAPI/schema checks:** Pact captures actual usage and
  scales to many internal consumers but needs a broker and discipline; schema
  checks need no consumer participation but flag changes nobody uses.
- **Shared staging environment vs ephemeral per-PR:** shared is cheap and
  flaky; ephemeral is reliable and costs infrastructure.
- **Test-data strategy:** builders/factories per test are clear; shared seed
  data is fast but couples tests.

## Gotchas
- Port collisions and leftover containers in CI; use random ports and
  automatic cleanup (Ryuk in Testcontainers).
- Tests that pass in isolation but share DB rows fail in parallel runs.
- Timing: wait for readiness (health check, polling with deadline), never a
  fixed sleep.
- Contracts that assert exact values instead of matchers (types, regex) become
  brittle; match shape, not data.
- Provider states in CDC must be set up deterministically, or verification is
  flaky.
- A contract tests the interface, not business logic; don't duplicate
  functional tests there.
- Recorded HTTP cassettes rot; re-record on a schedule and scrub secrets.
- Docker-in-Docker and ARM/x86 image mismatches in CI cause confusing
  start-up failures.

## Related
- [[testing-strategy-and-pyramid]] - the mid-tier role of these tests.
- [[unit-testing-and-test-doubles]] - fakes here must be validated by these tests.
- [[api-versioning-and-evolution]] - what counts as a breaking change.
- [[grpc-and-protobuf]] - schema evolution rules and breaking-change tooling.
- [[schema-migrations]] - run real migrations inside integration tests.
- [[containers-and-docker]] - the runtime that makes ephemeral dependencies cheap.

## References
- Martin Fowler, "IntegrationTest" and "Consumer-Driven Contracts".
- Pact documentation, https://docs.pact.io/
- Testcontainers, https://testcontainers.com/
- Fowler, "Testing Strategies in a Microservice Architecture".
