---
title: Resilience patterns - timeouts, retries, circuit breakers, bulkheads
category: reliability
tags: [resilience, retry, backoff, jitter, circuit-breaker, bulkhead, timeout, graceful-degradation, load-shedding]
use_cases:
  - make calls to a flaky downstream service without causing a retry storm
  - stop one slow dependency from taking down the whole service
  - add retries with exponential backoff and jitter to an HTTP client
  - degrade gracefully when a recommendation or payment service is down
  - protect an API from overload by shedding load instead of falling over
status: stable
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/handling-overload/
  - https://sre.google/sre-book/addressing-cascading-failures/
  - https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
  - https://martinfowler.com/bliki/CircuitBreaker.html
  - Release It! 2nd ed. (Michael Nygard), Pragmatic Bookshelf
---

# Resilience patterns - timeouts, retries, circuit breakers, bulkheads

## Summary
In a distributed system dependencies will be slow or down; resilience patterns keep a partial failure from becoming a total one. The core kit is timeouts on every call, bounded retries with backoff and jitter, circuit breakers to stop hammering a sick dependency, bulkheads to isolate resource pools, and load shedding plus graceful degradation when demand exceeds capacity.

## Key concepts
- **Timeout**: an upper bound on waiting. Without one, a slow dependency holds threads/connections until your service is also dead.
- **Retry**: repeat a failed call, but only for transient failures and only if the operation is idempotent (see [[idempotency-and-exactly-once]]).
- **Exponential backoff + jitter**: wait `min(cap, base * 2^attempt)` then randomize ("full jitter" picks uniformly from 0 to that value) so clients do not retry in synchronized waves.
- **Retry budget**: cap retries as a fraction of total traffic (for example 10%) so retries cannot multiply load during an outage.
- **Circuit breaker**: states closed (normal), open (fail fast), half-open (probe). Opens after a failure threshold, closes after probes succeed.
- **Bulkhead**: separate thread pools, connection pools or semaphores per dependency so one cannot exhaust shared resources.
- **Load shedding**: reject excess requests early (HTTP 429/503) to keep serving the rest within latency targets.
- **Graceful degradation**: return cached, default or reduced results when a non-critical dependency fails.
- **Backpressure**: propagate "slow down" upstream (bounded queues, rate limits, 429 with `Retry-After`) rather than buffering unboundedly.
- **Deadline propagation**: pass the remaining time budget downstream so deep call chains stop work the caller has already abandoned.

## When to use / scenarios
- Every remote call (HTTP, gRPC, DB, cache, queue): at minimum a timeout.
- Calls to flaky third parties: retry + breaker + fallback.
- Services with several dependencies of different criticality: bulkheads and degradation tiers.
- Traffic spikes or cascading failure risk: load shedding, rate limiting (see [[rate-limiting]]), autoscaling (see [[capacity-planning-and-autoscaling]]).
- When NOT to retry: non-idempotent writes without an idempotency key, 4xx validation errors, auth failures, anything already past the caller's deadline. Retrying at every layer of a deep stack multiplies attempts (3 layers x 3 tries = 27 calls); retry at one layer.

## How it works / example

Retry with exponential backoff and full jitter plus a deadline:

```python
import random, time

class Transient(Exception): ...

def call_with_retry(fn, *, attempts=4, base=0.1, cap=2.0, deadline_s=5.0):
    start = time.monotonic()
    for attempt in range(attempts):
        try:
            return fn()
        except Transient:
            if attempt == attempts - 1:
                raise
            sleep = random.uniform(0, min(cap, base * 2 ** attempt))   # full jitter
            if time.monotonic() - start + sleep > deadline_s:
                raise                                                  # no time left
            time.sleep(sleep)
```

Minimal circuit breaker:

```python
import time, threading

class CircuitOpen(Exception): ...

class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_after=30.0):
        self.failure_threshold, self.reset_after = failure_threshold, reset_after
        self.failures, self.opened_at, self.lock = 0, None, threading.Lock()

    def call(self, fn):
        with self.lock:
            if self.opened_at is not None:
                if time.monotonic() - self.opened_at < self.reset_after:
                    raise CircuitOpen()          # fail fast
                # half-open: let this one call through as a probe
        try:
            result = fn()
        except Exception:
            with self.lock:
                self.failures += 1
                if self.failures >= self.failure_threshold:
                    self.opened_at = time.monotonic()
            raise
        with self.lock:
            self.failures, self.opened_at = 0, None   # success closes the circuit
        return result
```

Combining them, in order from outermost: bulkhead (limit concurrency) -> circuit breaker -> retry -> timeout per attempt -> call. Then wrap with a fallback:

```python
def get_recommendations(user_id):
    try:
        return breaker.call(lambda: call_with_retry(lambda: reco_client.fetch(user_id, timeout=0.3)))
    except (CircuitOpen, Transient):
        return cached_popular_items()      # degrade, do not fail the page
```

Bulkhead via semaphore:

```python
import threading
payments_slots = threading.BoundedSemaphore(20)
def pay(req):
    if not payments_slots.acquire(blocking=False):
        raise RuntimeError("payments bulkhead full")   # shed instead of queueing forever
    try: return payments_client.charge(req)
    finally: payments_slots.release()
```

In production prefer a maintained library (tenacity, resilience4j, Polly, Envoy/service mesh policies) over hand-rolled code; see [[api-gateway-and-service-mesh]] for mesh-level retries and outlier detection.

## Trade-offs
- **Retries vs load**: retries improve success rate for transient errors but amplify load on a struggling service. Use budgets and jitter.
- **Fail fast vs availability**: an aggressive breaker protects dependencies but may reject requests that would have succeeded; tune thresholds on real error rates and minimum request volume.
- **Library vs mesh**: mesh policies are uniform and language-agnostic but blunt; in-code gives business-aware fallbacks.
- **Fallback quality**: stale cache is better than an error, but serving stale or wrong data for money-related flows can be worse than failing.
- **Hedged requests** cut tail latency by sending a second request after a delay, at the cost of extra load; only for idempotent, cheap reads.
- **Queue length**: long queues hide overload and increase latency for everyone; short bounded queues plus shedding fail more honestly.

## Gotchas
- Default client timeouts are often infinite or minutes. Set connect and read timeouts explicitly and verify the library's actual defaults.
- Retrying without jitter makes recovering services get stampeded in lockstep (thundering herd).
- Timeouts at each hop must shrink toward the leaf; if the downstream timeout exceeds the upstream one, work continues for callers who gave up.
- A breaker per process only sees local failures; with many instances, each must discover the outage separately. Pair with outlier detection in the proxy.
- Half-open state letting through a flood of probes defeats the purpose; allow one or a few.
- Treating timeouts as "failed" for writes can double-apply them; the operation may have succeeded. Use idempotency keys.
- Health checks that hit dependencies can turn one dependency blip into the whole fleet being marked unhealthy and restarted.
- Test these paths with fault injection (kill a dependency, add latency); untested fallbacks usually fail when needed.
- Cache stampede after recovery: stagger TTLs and coalesce identical in-flight requests (see [[caching-strategies]]).

## Related
- [[failure-modes-and-fallacies]] - the failure types these patterns defend against.
- [[idempotency-and-exactly-once]] - prerequisite for safe retries of writes.
- [[rate-limiting]] - server-side admission control that complements client-side patterns.
- [[observability-logs-metrics-traces]] - emit breaker state, retry counts and timeouts as metrics.
- [[deployment-strategies]] - safe rollouts reduce the failures you must absorb at runtime.
- [[error-handling-strategies]] - code-level error design that these patterns plug into.
- [[design-rag-chat]] - case study: timeouts, retries and fallbacks around an LLM provider.
- [[design-rate-limiter]] - case study: fail-open vs fail-closed when the counter store is down.
- [[chaos-engineering]] - fault-injection experiments that prove these patterns work before an outage does.
- [[backpressure-and-load-shedding]] - bounded queues, admission control and priority shedding in depth.

## References
- Google SRE Book, ch. 21 "Handling Overload" and ch. 22 "Addressing Cascading Failures": https://sre.google/sre-book/handling-overload/ and https://sre.google/sre-book/addressing-cascading-failures/
- AWS Builders' Library, "Timeouts, retries, and backoff with jitter": https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- Martin Fowler, CircuitBreaker: https://martinfowler.com/bliki/CircuitBreaker.html
- Michael Nygard, Release It! (2nd ed.), Pragmatic Bookshelf.
