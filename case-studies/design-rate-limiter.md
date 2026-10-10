---
title: Design a rate limiter service
category: case-studies
tags: [rate-limiter, throttling, token-bucket, gcra, sliding-window, redis, api-gateway, quota, case-study]
use_cases:
  - "design a distributed rate limiter shared by many API servers and gateways"
  - "enforce per-user, per-API-key and per-tenant request quotas across a fleet"
  - "return 429 with Retry-After consistently no matter which server takes the request"
  - "protect a fragile downstream from bursts while keeping limiter latency to a few milliseconds"
  - "practice the rate limiter system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 4 'Design a Rate Limiter'"
  - https://stripe.com/blog/rate-limiters
  - https://blog.cloudflare.com/counting-things-a-lot-of-different-things/
  - https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_features/global_rate_limiting
  - https://brandur.org/rate-limiting
  - https://www.rfc-editor.org/rfc/rfc6585.html
---

# Design a rate limiter service

## Summary
A shared service (or library plus shared store) that decides, per request,
whether a caller identified by a key (user, API key, IP, tenant, route) is
within its quota, and answers in a millisecond or two. The algorithms are
covered in [[rate-limiting]]; this case study is about running one at fleet
scale: where the check sits, where the counters live, how to stay atomic
across many servers, how to configure rules, and what to do when the limiter
itself is slow or down.

## Key concepts
- **Rule** = (match on key dimensions, limit, period, algorithm, action). Example: `api_key=*, route=/v1/search, 100 req/min, token bucket, reject`.
- **Decision must be atomic** per key: read-modify-write of a counter from many servers needs a single atomic operation (Redis `INCR`, a Lua script, or a compare-and-set), otherwise concurrent requests all pass.
- **GCRA / token bucket** store one or two numbers per key, which keeps memory per key tiny compared with a sliding-window log.
- **Local vs global**: a per-process limiter is free but each of N servers lets the full limit through; a global limiter costs a network hop per decision.
- **Fail open vs fail closed** when the counter store is unavailable.
- **Response contract**: HTTP 429 (RFC 6585) with `Retry-After`, plus remaining-quota headers so well-behaved clients slow down.

## When to use / scenarios
- Public API with paid tiers and per-key quotas; multi-tenant SaaS fairness.
- Protecting login, signup, password reset and OTP endpoints from brute force.
- Shielding a downstream (payment provider, LLM API, legacy DB) that has its own hard limits.
- Not needed when a single process serves all traffic: an in-memory bucket is the whole design.
- Not the right tool for overload of your own servers by aggregate traffic: that is load shedding and autoscaling ([[resilience-patterns]], [[capacity-planning-and-autoscaling]]).

## How it works / example

### 1. Requirements
Functional:
- Limit requests per key over a period, with several rules per request (per-IP and per-user and per-route).
- Rules are configurable without redeploying services.
- Reject with 429 and `Retry-After`; optionally "shadow mode" (log only) for new rules.

Non-functional:
- Added latency at p99 of a few ms; the limiter must not become the slowest hop.
- Highly available: a limiter outage must not take the API down.
- Accuracy: small overshoot (a few percent) is acceptable for API quotas; login limits should be strict.
- Scales with the number of keys (millions of API keys/IPs) and request rate.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 1 M requests/s peak at the edge, 2 rules checked per request -> 2 M counter operations/s.
- A single Redis node handles on the order of 100k simple ops/s (verify by benchmark on your hardware), so plan a sharded cluster of tens of nodes, or cut traffic to the store with local pre-checks.
- Keys: assume 10 M active keys x 2 rules x ~50 bytes (key name + value + overhead) -> about 1 GB, fits in memory easily; with TTLs, idle keys disappear.

### 3. API
Internal decision API (gRPC, called by gateways and services):
```
ShouldRateLimit(domain="api", descriptors=[{"api_key":"k1"},{"route":"/v1/search"}], hits=1)
  -> { allowed: bool, limit, remaining, reset_after_ms, retry_after_ms }
```
This mirrors Envoy's global rate limit service model, where the proxy sends
descriptors and a separate service owns rules and counters. Client-facing
response on rejection:
```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
RateLimit-Limit: 100
RateLimit-Remaining: 0
```

### 4. Data model
```
rules (config store, versioned, pushed to limiters):
  domain, descriptor match, limit, period, algorithm, mode(enforce|shadow)
counters (Redis, sharded by key, TTL = period):
  rl:{rule_id}:{key}  ->  GCRA: theoretical arrival time (TAT) as a timestamp
                          or token bucket: (tokens, last_refill_ts)
                          or fixed/sliding window: count per window id
```
No durable storage is needed for counters; losing them resets quotas, which
is acceptable for most rules.

### 5. High-level architecture
```
 client -> edge/LB -> API gateway (or sidecar) --gRPC--> rate limit service (stateless, N)
                         |   local token cache            |  atomic script per key
                         v                                 v
                    backend services               Redis cluster (sharded by key)
 config repo -> rules service -> push to limiters (watch / poll, versioned)
 decisions --> metrics + sampled logs (allowed/denied per rule)
```
Enforcement sits at the gateway for uniform per-key limits
([[api-gateway-and-service-mesh]]); business-aware limits (cost per call, plan
features) are checked inside the service using the same library.

### 6. Deep dive A: atomic decision with GCRA
GCRA keeps one timestamp per key (the theoretical arrival time). A request is
allowed if it does not arrive too early relative to it; it behaves like a token
bucket with burst capacity. In Redis, run the same logic as a Lua script (or
use a module) so read-compute-write is one atomic step per key.

```python
import time

class GCRA:
    """Generic cell rate algorithm: `rate` requests per `period` seconds, bursts up to `burst`."""
    def __init__(self, rate, period, burst):
        self.interval = period / rate          # emission interval T
        self.tolerance = self.interval * burst  # how far ahead of schedule we allow
        self.tat = {}                           # key -> theoretical arrival time (Redis in production)

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        tat = max(self.tat.get(key, now), now)
        if tat - now > self.tolerance - self.interval:
            retry_after = tat - now - (self.tolerance - self.interval)
            return False, retry_after
        self.tat[key] = tat + self.interval
        return True, 0.0

lim = GCRA(rate=10, period=1.0, burst=5)       # 10/s, burst of 5
results = [lim.allow("k1", now=0.0)[0] for _ in range(7)]
assert results == [True] * 5 + [False] * 2      # burst of 5 then rejected
assert lim.allow("k1", now=0.1)[0]              # one interval later a slot frees up
assert lim.allow("k2", now=0.0)[0]              # keys are independent
ok, retry = lim.allow("k1", now=0.1)
assert not ok and retry > 0
```

### 7. Deep dive B: reducing store load and latency
- **Local pre-check**: each limiter node keeps a short-lived local copy of hot keys that are already over limit and rejects them without a store hop until `reset`.
- **Batching / token leasing**: a node takes a batch of tokens (say 10% of the limit) from the shared counter and spends them locally; overshoot is bounded by batch x nodes. This is the "approximate" side of the trade-off in [[rate-limiting]].
- **Sliding window counter** instead of a log keeps two counters per key; Cloudflare describes this approximation for counting at their scale.
- **Shard by key** with consistent hashing ([[consistent-hashing]]); a key's counter lives on exactly one shard, so there is no cross-shard coordination.
- **Hot keys** (one abusive IP at very high rate) concentrate on one shard: the local over-limit cache absorbs them.

### 8. Deep dive C: multi-region and rule rollout
- Per-region counters with per-region limits (limit / regions, or weighted by traffic) avoid cross-region round trips; accept that a client hopping regions can exceed the global limit.
- Global strict quotas (billing-grade monthly quotas) are a different problem: count asynchronously from usage events and enforce with a slower check ([[batch-and-stream-processing]]).
- New rules ship in shadow mode first: log would-be rejections, compare with expectations, then enforce. Stripe's post describes rolling out limiters gradually and using dark launches.

### 9. Scaling and failure handling
- **Store down or slow**: per-call timeout of a few ms; on timeout, fail open for ordinary API rules and fail closed (or fall back to strict local limits) for security rules ([[resilience-patterns]]).
- **Limiter service down**: gateways fall back to local in-process buckets with conservative limits.
- **Clock**: compute time on the store (Redis `TIME`) or use one clock source per shard so skew between app servers does not distort windows ([[time-clocks-and-ordering]]).
- **Monitoring**: decision latency p99, store error rate, allowed/denied per rule, top denied keys.
- **Client behaviour**: document headers; clients retry with exponential backoff and jitter, or 429s cause retry storms.

## Trade-offs
- Global accuracy vs latency: a store hop per request is exact; local buckets or token leasing are faster with bounded overshoot.
- Gateway enforcement is uniform and cheap; in-service enforcement knows business cost per request. Most systems use both.
- Fail open keeps availability; fail closed keeps protection. Choose per rule.
- Token bucket/GCRA allow bursts; leaky bucket smooths output for fragile downstreams.

## Gotchas
- Non-atomic `GET` then `SET` across servers: concurrent requests all read the same count and all pass.
- Keying only by IP punishes users behind carrier NAT and is evaded by botnets; combine with account/API key.
- Counting rejected requests against the quota can lock a client out forever if it retries aggressively; decide explicitly.
- Forgetting TTLs: counter keys for every IP ever seen fill memory.
- Rate limiting after expensive work (auth, DB lookups) defeats the purpose; check as early as possible.
- Limits per server instance silently multiply when you autoscale.

## Related
- [[rate-limiting]] - the algorithms (token bucket, windows, GCRA-like behaviour) this service implements
- [[api-gateway-and-service-mesh]] - the usual enforcement point
- [[caching-strategies]] - Redis as the counter store
- [[consistent-hashing]] - sharding counters by key
- [[resilience-patterns]] - fail open/closed, timeouts, client backoff
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 4
- Stripe, "Scaling your API with rate limiters": https://stripe.com/blog/rate-limiters
- Cloudflare, "How we built rate limiting capable of scaling to millions of domains": https://blog.cloudflare.com/counting-things-a-lot-of-different-things/
- Envoy global rate limiting: https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/other_features/global_rate_limiting
- Brandur Leach, "Rate limiting, cells, and GCRA": https://brandur.org/rate-limiting
- RFC 6585 (429 Too Many Requests): https://www.rfc-editor.org/rfc/rfc6585.html
