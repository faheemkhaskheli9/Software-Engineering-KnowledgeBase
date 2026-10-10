---
title: Flaky test handling
category: testing
tags: [flaky-tests, nondeterminism, quarantine, retries, test-isolation, test-order, async-tests, ci-reliability]
use_cases:
  - "a CI test fails sometimes and passes on rerun; find out why"
  - "set a team policy for quarantining and fixing flaky tests"
  - "stop people from clicking 'rerun' until the pipeline goes green"
  - "fix tests that fail only when run in parallel or in a different order"
  - "replace sleep-based waits in async or end-to-end tests"
status: draft
last_verified: 2026-10-10
sources:
  - "An Empirical Analysis of Flaky Tests, Luo, Hariri, Eloussi, Marinov, FSE 2014"
  - "Flaky Tests at Google and How We Mitigate Them, John Micco, Google Testing Blog, 2016 - https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html"
  - "Eradicating Non-Determinism in Tests, Martin Fowler, 2011 - https://martinfowler.com/articles/nonDeterminism.html"
  - "pytest flaky test docs - https://docs.pytest.org/en/stable/explanation/flaky.html"
  - "Software Engineering at Google, Winters, Manshreck, Wright (ch. 11 and 14)"
---

# Flaky test handling

## Summary
A flaky test passes and fails on the same code. Flakiness destroys the value of a suite: people learn to ignore red builds and rerun until green, and real regressions slip through. Handle it as a bug with a process: detect (reruns and history), quarantine so the main signal stays trustworthy, find the root cause (ordering, time, concurrency, shared state, the network), fix it, and return the test to the gate.

## Key concepts
- **Flaky test:** nondeterministic outcome without a code change. The cause can be in the test, the code under test, or the environment.
- **Common root causes** (Luo et al. found async wait, concurrency and test-order dependency among the top categories):
  - *Async wait:* asserting before background work finished; `sleep(1)` instead of waiting on a condition.
  - *Concurrency:* races and deadlocks in the code or the test.
  - *Order dependence:* a test relies on state left by another (globals, DB rows, files, caches, env vars).
  - *Time:* wall clock, time zones, DST, midnight and month-end boundaries, timeouts too tight for slow CI machines.
  - *Randomness:* unseeded random data, hash or set iteration order.
  - *External resources:* network, third-party APIs, DNS, shared staging environments.
  - *Resource leaks:* ports, threads, file handles or memory exhausted late in a run.
  - *Floating point and platform differences.*
- **Detection:** rerun failures automatically and flag pass-on-retry; track per-test pass rates over time; run new tests many times before merge.
- **Quarantine:** move a known-flaky test out of the blocking gate (still running and reporting), with an owner and a ticket.
- **Retry policy:** automatic retries hide flakiness if their results are not recorded; a retry that passes should still be reported as flaky.
- **Isolation:** each test sets up and tears down its own state ([[test-data-management]]).

## When to use / scenarios
- A test fails in CI and passes locally: compare environment (CPU count, parallelism, time zone, locale, network access, order).
- Fails only in the full suite, never alone: order dependence or leaked state; run with randomized order and bisect the preceding tests.
- Fails under parallel runs: shared ports, files, DB rows or global singletons.
- Fails near midnight, month-end or in another region's CI runner: time handling; inject the clock.
- End-to-end UI tests timing out intermittently: replace sleeps with explicit waits on conditions; mock or stub third-party services at the boundary ([[integration-and-contract-testing]]).
- NOT acceptable: deleting the assertion or adding a blanket retry decorator and closing the ticket. That hides a possible real bug in the code under test.

## How it works / example

Process:

```
fail in CI -> auto-rerun once -> passes? -> record as FLAKY (not as pass), notify owner
                                 fails?  -> real failure, block merge
FLAKY rate over threshold -> quarantine (non-blocking job) + ticket with owner and deadline
fix root cause -> run N times in a loop to confirm -> remove from quarantine
```

The most common fix: wait on a condition with a deadline instead of sleeping a fixed time.

```python
import threading
import time

def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout          # monotonic: immune to wall-clock jumps
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise TimeoutError("condition not met within timeout")

results = []
worker = threading.Thread(target=lambda: (time.sleep(0.05), results.append("done")))
worker.start()

# Flaky: assert results == ["done"] right here, or after a sleep(0.03) guess
wait_until(lambda: results == ["done"])            # stable: waits only as long as needed
worker.join()
print(results)
```

Inject time and randomness instead of reading them globally:

```python
import random
from datetime import datetime, timezone

def is_weekend(now=None):
    now = now or datetime.now(timezone.utc)
    return now.weekday() >= 5

def pick_sample(items, k, rng=random):
    return rng.sample(items, k)

assert is_weekend(datetime(2026, 10, 10, tzinfo=timezone.utc))         # a Saturday, always
rng = random.Random(1234)                                              # seeded: same result every run
assert pick_sample(list(range(10)), 3, rng) == pick_sample(list(range(10)), 3, random.Random(1234))
print("deterministic")
```

Reproducing order-dependent or rare failures:

```
pytest                                   # with pytest-randomly installed: random order, seed printed in the header
pytest --randomly-seed=<seed>            # replay the same order
pytest --count=200 tests/test_x.py::test_y   # pytest-repeat: loop one test to measure its flake rate
for i in $(seq 200); do pytest -x -q tests/test_x.py || break; done   # no-plugin version
(plugin flags change between versions; check each plugin's docs)
```

## Trade-offs
- **Auto-retry vs fail fast:** retries keep pipelines moving and protect against infrastructure blips, but without reporting they bury real intermittent bugs. Retry once, record the flake, and alert on rising rates.
- **Quarantine vs delete vs fix now:** quarantine keeps coverage visible while restoring trust in the gate; deleting loses coverage; fixing immediately is best when the cause is obvious. Quarantine without an owner and deadline becomes a graveyard.
- **Real dependencies vs doubles in higher-level tests:** real services catch integration bugs and add flakiness; stubs at the boundary are stable but can drift ([[unit-testing-and-test-doubles]], contract tests).
- **Generous vs tight timeouts:** generous timeouts reduce flakes on slow runners but make genuine hangs slow to detect; wait on conditions so the timeout is an upper bound, not the normal duration.
- **Parallelism vs isolation cost:** parallel runs expose shared-state bugs and speed up CI, but require per-worker databases, ports and directories.

## Gotchas
- `time.sleep(n)` as synchronization is a race with a delay; it fails on a slower or busier machine.
- `datetime.now()` and `time.time()` in tests break around DST, time zones and midnight; use fixed values or `time.monotonic()` for durations.
- Module-level caches, singletons and `lru_cache` keep state across tests; clear them in teardown.
- Tests that pick a fixed port (`8080`) collide under parallel runs; bind to port 0 and read the assigned port.
- Set and dict iteration order assumptions: sets of strings vary with hash randomization between runs (`PYTHONHASHSEED`).
- A "flaky" test is sometimes a real race in production code; check before blaming the test ([[concurrency-and-parallelism]]).
- Mutation and coverage numbers are unreliable while flaky tests exist ([[mutation-testing]]).
- Snapshot outputs with unscrubbed timestamps or IDs fail every run ([[snapshot-and-golden-testing]]).
- Retrying the whole job instead of the failed test hides which test flaked.

## Related
- [[testing-strategy-and-pyramid]] - flakiness as a property of the suite's shape (more E2E, more flakes)
- [[test-data-management]] - isolation and per-test data remove order dependence
- [[unit-testing-and-test-doubles]] - injecting clocks, randomness and network
- [[integration-and-contract-testing]] - ephemeral environments instead of shared staging
- [[concurrency-and-parallelism]] - races that surface as flaky tests
- [[ci-cd-pipelines]] - rerun, quarantine and reporting in the pipeline

## References
- Luo, Hariri, Eloussi, Marinov, "An Empirical Analysis of Flaky Tests" (FSE 2014)
- Micco, "Flaky Tests at Google and How We Mitigate Them" (Google Testing Blog, 2016)
- Fowler, "Eradicating Non-Determinism in Tests" (2011)
- pytest docs, "Flaky tests"
- Winters, Manshreck, Wright, "Software Engineering at Google"
