---
title: Choosing a caching strategy
category: scenarios
tags: [cache, http-caching, cdn, redis, in-process-cache, etag, invalidation, ttl, semantic-cache, decision-guide]
use_cases:
  - "our API is slow and the database is overloaded, where should we cache"
  - "choose between browser/HTTP caching, a CDN, an in-process cache and Redis"
  - "decide how stale cached data may be and how to invalidate it"
  - "cache expensive LLM or third-party API calls"
status: stable
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc9111
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching
  - https://redis.io/docs/latest/develop/use/patterns/
  - "Nishtala et al., Scaling Memcache at Facebook, NSDI 2013"
  - "Martin Kleppmann, Designing Data-Intensive Applications (1st ed.), ch. 11-12 (derived data)"
---

# Choosing a caching strategy

## Summary
Decide three things in order: whether to cache at all (measure and fix the query first), at which layer (browser/HTTP, CDN, in-process, distributed cache, materialised view), and how staleness is bounded (TTL, explicit invalidation, versioned keys, or validation with ETags). Cache as close to the user as the data's privacy and freshness allow; the cache is always a derived copy that can be dropped, never the system of record.

## Key concepts
- **Measure first.** Hit ratio, read:write ratio, and where latency is spent ([[observability-logs-metrics-traces]]). A missing index is not a caching problem ([[database-indexing]]).
- **Layers.** Browser cache, CDN/edge ([[cdn-and-edge]]), reverse proxy, in-process memory, distributed cache (Redis/Memcached), database-side (materialised views, buffer pool).
- **Staleness budget.** How old may a value be before it is wrong for the business? This number picks the TTL and the invalidation method.
- **Scope.** Public (same for everyone), per-user, or per-tenant. Scope decides which layers are safe: private data never goes into a shared cache keyed only by URL.
- **Read/write pattern.** Cache-aside, read-through, write-through, write-behind, write-around ([[caching-strategies]]).
- **Validation vs expiry.** HTTP caches can revalidate (`ETag` / `If-None-Match`, `304 Not Modified`) instead of refetching the body.

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Static assets (JS, CSS, images) | Fingerprinted filenames + long `Cache-Control` max-age, served by CDN | [[cdn-and-edge]] |
| Public, same-for-everyone API responses or pages | CDN / reverse proxy with short TTL, `stale-while-revalidate` | [[cdn-and-edge]], [[rest-api-design]] |
| Per-user responses that rarely change | `Cache-Control: private` + `ETag` revalidation in the browser | [[rest-api-design]] |
| Hot DB reads shared across app instances | Cache-aside in Redis/Memcached, TTL + delete on write | [[caching-strategies]] |
| Tiny, read-mostly config or reference data | In-process cache with TTL (per instance) | [[caching-strategies]], [[memory-and-performance]] |
| Expensive aggregates, dashboards | Precompute: materialised view, rollup table, or warehouse | [[data-warehousing-and-olap]], [[batch-and-stream-processing]] |
| Sessions, rate-limit counters | Redis with TTLs (a store, not a pure cache: plan persistence) | [[authentication-and-sessions]], [[rate-limiting]] |
| Slow or metered third-party API | Cache-aside with TTL matching the provider's freshness, plus negative caching | [[resilience-patterns]], [[caching-strategies]] |
| Hot key overloads one cache node | Local L1 cache in front of Redis, or replicate the key | [[caching-strategies]], [[consistent-hashing]] |
| Data must be fresh after every write (balances, stock) | Do not cache, or write-through with read-your-writes routing | [[consistency-models]], [[transactions-and-isolation-levels]] |
| LLM responses or embeddings | Exact-match cache on normalised input; provider prompt caching; semantic cache only with a quality check | AI KB links below |

Decision flow:

```
Is the slow path fixed already (index, N+1, query shape)? no -> fix that first
Same response for every user?
  yes -> HTTP caching + CDN (TTL, stale-while-revalidate); purge or version on change
  no  -> per-user: browser private cache + ETag
Shared across instances and expensive to compute?
  yes -> Redis cache-aside (TTL + delete on write, single-flight on miss)
  small + read-mostly -> in-process TTL cache
Freshness must be exact after writes? -> do not cache that read; route it to the primary
```

AI-specific angle: for LLM calls, see the AI Knowledge Base on [prompt caching and cost](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/prompt-caching-and-cost.md) and [LLM cost and latency](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/cost-and-latency.md). Semantic (similarity-based) caching can return a wrong answer for a near-miss query, so treat it as a quality trade-off, not a free win.

## How it works / example
HTTP validation needs no cache infrastructure at all: the server computes an `ETag` from the representation and answers `304` when the client already has it. Runnable stdlib sketch:

```python
import hashlib, json

def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'   # strong validator

def respond(resource: dict, if_none_match: str | None):
    body = json.dumps(resource, sort_keys=True).encode()
    tag = etag_for(body)
    headers = {"ETag": tag, "Cache-Control": "private, max-age=0, must-revalidate"}
    if if_none_match == tag:
        return 304, headers, b""          # client copy is current: no body sent
    return 200, headers, body

if __name__ == "__main__":
    status, h, body = respond({"id": 1, "name": "a"}, None)
    assert status == 200 and body
    status, _, body = respond({"id": 1, "name": "a"}, h["ETag"])
    assert status == 304 and body == b""
    status, _, _ = respond({"id": 1, "name": "b"}, h["ETag"])   # changed -> full body
    assert status == 200
    print("ok")
```

For the shared-cache layer (cache-aside, single-flight, jittered TTL, invalidation options, stampede defences) use the runnable example in [[caching-strategies]].

Worked layering for a product page:

```
 browser (private, ETag) -> CDN (public HTML/JSON, short TTL, stale-while-revalidate)
   -> app (in-process: feature flags, currency table)
   -> Redis (cache-aside: product rows, delete on write)
   -> Postgres (system of record; price and stock read uncached at checkout)
```

## Trade-offs
- **Closer to the user vs control:** browser and CDN caches cut the most latency and load but are hardest to invalidate; purge APIs and versioned URLs are the levers.
- **TTL vs explicit invalidation:** TTL is simple and self-healing but bounds staleness only loosely; delete-on-write is fresher but couples writers to cache keys and has races ([[caching-strategies]]).
- **In-process vs distributed:** in-process has no network hop but each instance holds its own possibly different copy; distributed is shared but is another dependency that can fail.
- **Precompute vs cache on read:** materialised data is predictable and always warm but costs storage and refresh work even for unread items.
- **More layers vs debuggability:** every layer is another place a stale value can hide; add one at a time and expose cache headers and hit ratios.

## Gotchas
- Caching private responses in a shared cache (missing `Cache-Control: private` or `Vary` on auth-dependent content) leaks one user's data to another.
- Caching authorization decisions longer than permission changes allow.
- Cold cache after a deploy or flush sends full load to the DB; warm up or throttle rebuilds.
- Unbounded key cardinality (per-user, per-filter keys) gives a low hit ratio and memory pressure.
- Caching errors and empty results with the same TTL as good data.
- Two code paths updating DB and cache in different orders; pick one invalidation story.
- Assuming the cache is durable: Redis used as a cache can evict or lose data at any time.

## Related
- [[caching-strategies]] - patterns, eviction, stampede defences, runnable cache-aside.
- [[cdn-and-edge]] - HTTP caching at the edge, purging, signed URLs.
- [[database-indexing]] - fix slow queries before caching them.
- [[consistency-models]] - what staleness guarantees callers get.
- [[scaling-from-zero-to-millions]] - when each cache layer enters a growing system.
- [[scenario-chooser]] - other problem-to-topic mappings.
- [[web-performance]] - HTTP caching headers and content-hashed assets for the browser layer.

## References
- RFC 9111, HTTP Caching.
- MDN, HTTP caching guide.
- Redis patterns documentation.
- Nishtala et al., "Scaling Memcache at Facebook", NSDI 2013.
- Kleppmann, *Designing Data-Intensive Applications* (1st ed.), ch. 11 "Stream Processing" and ch. 12 "The Future of Data Systems" (caches and indexes as derived data).
