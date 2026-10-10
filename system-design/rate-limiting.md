---
title: Rate limiting
category: system-design
tags: [rate-limit, token-bucket, leaky-bucket, sliding-window, throttling, redis, abuse]
use_cases:
  - "limit each API key to N requests per minute and return 429 with Retry-After"
  - "protect a downstream service or database from overload by a noisy client"
  - "implement a distributed rate limiter shared across many app servers"
  - "choose between token bucket, fixed window and sliding window algorithms"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc6585
  - https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
  - https://redis.io/docs/latest/commands/eval/
  - "Alex Xu, System Design Interview vol 1, ch. 4 Design a rate limiter"
  - https://stripe.com/blog/rate-limiters
---

# Rate limiting

## Summary
Rate limiting caps how much work a client (user, API key, IP, tenant) can
request per unit time. It protects availability against abuse and accidents,
enforces fair use and pricing tiers, and keeps cost predictable. The core
choices are the algorithm, the key being limited, where the counter lives, and
what the client sees on rejection.

## Key concepts
- **Identity/key**: user id, API key, IP, tenant, route, or a combination. IP alone punishes shared NATs and is evaded by botnets.
- **Token bucket**: bucket of capacity B refilled at rate R tokens/s; each request spends a token. Allows bursts up to B, long-run rate R. Most popular (used by Stripe, AWS API Gateway).
- **Leaky bucket**: queue drained at constant rate; smooths output, rejects when full.
- **Fixed window counter**: count per clock window (e.g. per minute). Simple but allows a 2x burst at window boundaries.
- **Sliding window log**: store request timestamps; exact but memory-heavy.
- **Sliding window counter**: weighted blend of current and previous window counts; cheap and close to exact.
- **Concurrency limiter**: cap in-flight requests rather than rate; protects slow endpoints.
- **Load shedding**: reject by server health (queue depth, CPU) rather than per-client quota; complementary.
- **Response**: HTTP `429 Too Many Requests` (RFC 6585) with `Retry-After`; many APIs also send `RateLimit-Limit/Remaining/Reset` headers (IETF draft, check current status).

## When to use / scenarios
- Public or partner APIs with tiered quotas.
- Login, OTP, password reset, and search endpoints against brute force and scraping.
- Protecting a fragile dependency (payment gateway, third-party API) from being hammered by retries.
- Multi-tenant SaaS "noisy neighbour" isolation.
- Not a substitute for authentication, WAF/DDoS protection (volumetric attacks should be stopped at the edge, see [[cdn-and-edge]]), or capacity planning.

## How it works / example

Where to enforce:

```
 client -> CDN/WAF (coarse, per-IP) -> API gateway (per-key quotas) -> service (per-route, concurrency)
                                              |
                                      shared counter store (Redis)
```

In-process token bucket (single node), runnable:

```python
import time

class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate, self.capacity = rate, capacity
        self.tokens, self.ts = capacity, time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.ts) * self.rate)
        self.ts = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

if __name__ == "__main__":
    b = TokenBucket(rate=5, capacity=10)
    allowed = sum(b.allow() for _ in range(30))
    assert allowed == 10          # burst capacity, then throttled
```

Distributed version: do the read-modify-write atomically, otherwise two app
servers both see "1 token left". With Redis use a Lua script (runs atomically):

```lua
-- KEYS[1]=bucket key; ARGV: rate, capacity, now_ms, cost
local d = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(d[1]) or tonumber(ARGV[2])
local ts = tonumber(d[2]) or tonumber(ARGV[3])
tokens = math.min(tonumber(ARGV[2]), tokens + (tonumber(ARGV[3]) - ts) / 1000 * tonumber(ARGV[1]))
local ok = 0
if tokens >= tonumber(ARGV[4]) then tokens = tokens - tonumber(ARGV[4]); ok = 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', ARGV[3])
redis.call('PEXPIRE', KEYS[1], math.ceil(tonumber(ARGV[2]) / tonumber(ARGV[1]) * 1000) * 2)
return ok
```

Rejection response:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
Content-Type: application/json
{"error":"rate_limited","retry_after_seconds":12}
```

## Trade-offs
- **Algorithm**: token bucket for bursty-but-bounded APIs; leaky bucket for smooth egress to a fragile dependency; sliding window counter for accurate, cheap per-user quotas; fixed window only when boundary bursts are acceptable.
- **Strict vs approximate**: exact global limits need a round trip to a shared store per request; approximate (local buckets that sync periodically, or limit = N/servers) is faster but can overshoot.
- **Fail open vs fail closed** when the limiter store is down: fail open keeps the API up (preferred for most APIs); fail closed for security-critical paths like login.
- **Centralized (gateway) vs in-service**: gateway is uniform and cheap to operate; in-service sees business context (cost per call, plan).
- **Hard reject vs queue/delay**: queueing smooths bursts but adds latency and memory; reject is simpler and honest.

## Gotchas
- Non-atomic check-then-increment in a multi-server setup lets limits be exceeded.
- Clock skew across servers when using wall-clock windows; use the store's clock (Redis `TIME`) or monotonic local time.
- Unbounded keys (per-IP for IPv6) and no key expiry leak memory; always set TTLs.
- Clients retry immediately on 429 and make it worse; send `Retry-After` and document exponential backoff with jitter ([[resilience-patterns]]).
- Rate-limiting by user after authentication is expensive for floods; do a cheap coarse limit before auth.
- Different costs per request (cheap read vs expensive search) need weighted tokens, not a flat count.
- Limits behind a proxy see the proxy IP unless you trust `X-Forwarded-For` only from known hops.
- Forgetting retries and batch jobs from your own services in the quota math.

## Related
- [[api-gateway-and-service-mesh]] - the usual enforcement point.
- [[resilience-patterns]] - backoff, circuit breakers and bulkheads as the client-side counterpart.
- [[caching-strategies]] - Redis counters and protecting backends during cold starts.
- [[authentication-and-sessions]] - throttling credential-stuffing and brute force.
- [[load-balancing]] - overload handling at the traffic layer.

## References
- RFC 6585 (429 status): https://www.rfc-editor.org/rfc/rfc6585
- IETF HTTPAPI RateLimit headers draft: https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
- Stripe, "Scaling your API with rate limiters": https://stripe.com/blog/rate-limiters
- Alex Xu, *System Design Interview* vol 1, chapter 4.
