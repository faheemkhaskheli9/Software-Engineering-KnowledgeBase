---
title: Performance and load testing
category: testing
tags: [load-testing, performance, locust, k6, latency, percentiles, soak-test, benchmarking]
use_cases:
  - "find out how many requests per second our API can handle before it degrades"
  - "write a Locust or k6 load test and run it in CI"
  - "check that a release did not regress p99 latency"
  - "validate that autoscaling and rate limits behave under a traffic spike"
  - "benchmark a function or query reliably"
status: draft
last_verified: 2026-10-10
sources:
  - https://locust.io/
  - https://grafana.com/docs/k6/latest/
  - https://sre.google/sre-book/monitoring-distributed-systems/
  - https://www.brendangregg.com/usemethod.html
  - https://www.infoq.com/presentations/latency-response-time/
---

# Performance and load testing

## Summary
Performance testing measures how a system behaves under load: throughput,
latency percentiles, error rate and resource use. It answers capacity and
regression questions with evidence before users find out. The common kinds
are load (expected traffic), stress (beyond capacity), spike (sudden surge),
soak (long duration, to find leaks), and breakpoint tests.

## Key concepts
- **Metrics:** throughput (req/s), latency distribution (p50, p95, p99,
  p99.9; never just the mean), error rate, saturation (CPU, memory, connection
  pool, queue depth). Track them against SLOs.
- **Little's Law:** concurrency = throughput x latency. Use it to size pools
  and to sanity-check test setups.
- **Open vs closed workload model:** closed (N virtual users each waiting for
  a response) throttles itself when the server slows down; open (arrivals at
  a fixed rate, e.g. k6 `constant-arrival-rate`) models real internet traffic
  and exposes queueing collapse.
- **Coordinated omission:** a load generator that pauses when the server
  stalls under-reports tail latency. Use tools/executors that schedule by
  intended send time (wrk2, k6 arrival-rate, HdrHistogram correction).
- **Knee of the curve:** latency rises sharply near saturation; capacity is
  the load just before the knee, minus headroom.
- **USE method (Gregg):** for each resource check Utilisation, Saturation,
  Errors to find the bottleneck.
- **Micro-benchmarks** (timeit, pytest-benchmark, JMH) vs **system load
  tests**: different tools for different questions.

## When to use / scenarios
- Before a launch, a marketing event or a migration: confirm capacity.
- On every release for key endpoints: a short smoke load test with thresholds
  (p95 < X, error rate < Y) as a CI gate.
- After architecture changes (cache added, DB moved, pool resized).
- To tune autoscaling, rate limits, timeouts and circuit breakers.
- Nightly soak runs to catch memory leaks and connection exhaustion.
- Not meaningful on a laptop against a dev stack with a tiny dataset; use a
  production-like environment and data volume, or accept results are relative.

## How it works / example

Locust (`pip install locust`), run headless in CI:

```python
# locustfile.py
from locust import HttpUser, task, between

class ShopUser(HttpUser):
    wait_time = between(1, 3)            # think time between actions

    def on_start(self):
        r = self.client.post("/login", json={"user": "load", "password": "x"})
        self.headers = {"Authorization": f"Bearer {r.json()['token']}"}

    @task(10)
    def browse(self):
        self.client.get("/products?limit=20", headers=self.headers, name="/products")

    @task(1)
    def checkout(self):
        self.client.post("/cart/checkout", headers=self.headers)
```

```
locust -f locustfile.py --headless -u 200 -r 20 -t 5m --host https://staging.example.com \
       --csv results --exit-code-on-error 1
```

k6 with pass/fail thresholds and an open arrival model (k6 scripts are
JavaScript):

```javascript
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: { steady: { executor: 'constant-arrival-rate', rate: 200,
    timeUnit: '1s', duration: '5m', preAllocatedVUs: 100, maxVUs: 500 } },
  thresholds: { http_req_failed: ['rate<0.01'],
                http_req_duration: ['p(95)<300', 'p(99)<800'] },
};

export default function () {
  const res = http.get('https://staging.example.com/products');
  check(res, { 'status 200': (r) => r.status === 200 });
}
```

Micro-benchmark in Python:

```python
import timeit, statistics
runs = timeit.repeat("sorted(data)", setup="data=list(range(10000))[::-1]",
                     repeat=7, number=200)
print(min(runs) / 200, statistics.stdev(runs) / 200)   # report min and spread
```

Method: define SLOs and a workload model from production logs -> baseline run
-> ramp load stepwise -> watch latency percentiles and saturation metrics
(see observability) -> locate bottleneck -> fix one thing -> re-run and compare.
Keep every run's config, commit hash and results so comparisons are valid.

## Trade-offs
- **Realism vs repeatability:** replaying production traffic is realistic but
  messy; synthetic scripts are repeatable but may miss hot keys and cache
  behaviour. Use synthetic for gating, replay for validation.
- **Test in production-like staging vs in production:** staging is safe but
  differs; production with a canary slice and guard rails shows truth but
  risks users. Use feature flags and abort conditions.
- **Tool choice:** Locust (Python, flexible scenarios), k6 (efficient, JS,
  great thresholds), JMeter (GUI, plugins), Gatling (Scala/Java DSL), wrk2/
  vegeta (simple constant-rate HTTP).
- **Load generator capacity:** one machine may become the bottleneck; scale
  generators out and monitor their CPU.

## Gotchas
- Reporting averages. A p50 of 50 ms with a p99 of 5 s is a failing system.
- Coordinated omission and closed-loop tests that hide queueing collapse.
- Testing with empty or tiny databases; query plans and cache hit rates differ
  at real data size.
- Cold caches, JIT warm-up and connection-pool ramp skew early samples;
  discard a warm-up window.
- Load generator, network or test-environment limits being measured instead
  of the system under test.
- Hitting third-party services or sending real emails/payments during tests;
  stub or sandbox them, and get permission before load-testing anything you do
  not own.
- Ignoring the dependency graph: one slow downstream or an exhausted DB pool
  dominates results.
- Forgetting to clean up generated data, which then pollutes later runs.
- Optimising before measuring; profile first (cProfile, py-spy, flame graphs).

## Related
- [[testing-strategy-and-pyramid]] - non-functional tier alongside functional tests.
- [[observability-logs-metrics-traces]] - the signals you read during a test.
- [[slis-slos-error-budgets]] - source of the thresholds a test enforces.
- [[capacity-planning-and-autoscaling]] - turns results into provisioning decisions.
- [[rate-limiting]] - verify limits protect the system under overload.
- [[back-of-envelope-estimation]] - sanity-check expected load before testing.

## References
- Locust and Grafana k6 documentation.
- Google SRE Book, ch. 6 "Monitoring Distributed Systems" (latency percentiles).
- Gil Tene, "How NOT to Measure Latency" (coordinated omission).
- Brendan Gregg, Systems Performance (2nd ed.), USE method.
