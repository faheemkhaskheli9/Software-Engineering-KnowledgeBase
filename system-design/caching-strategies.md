---
title: Caching strategies
category: system-design
tags: [cache, redis, memcached, cache-aside, write-through, ttl, invalidation, eviction]
use_cases:
  - "speed up a read-heavy endpoint that hits the database on every request"
  - "choose between cache-aside, write-through and write-back for a new service"
  - "prevent a cache stampede when a hot key expires"
  - "decide how to invalidate cached data when the source of truth changes"
status: draft
last_verified: 2026-10-10
sources:
  - https://redis.io/docs/latest/develop/use/patterns/
  - "Nishtala et al., Scaling Memcache at Facebook, NSDI 2013"
  - "Vattani, Chierichetti, Lowenstein, Optimal Probabilistic Cache Stampede Prevention, VLDB 2015"
  - "Martin Kleppmann, Designing Data-Intensive Applications, ch. 11-12"
---

# Caching strategies

## Summary
A cache stores the result of expensive work (DB query, computation, remote
call) in faster memory to cut latency and backend load. Correct caching is
mostly about choosing a read/write pattern, an eviction policy, and a plan for
staleness and invalidation. "There are only two hard things: cache invalidation
and naming things."

## Key concepts
- **Cache-aside (lazy loading)**: app checks cache, on miss reads DB then populates cache. Most common; cache failure degrades to DB, not outage.
- **Read-through**: the cache layer itself loads from the source on miss (library/provider handles it).
- **Write-through**: writes go to cache and DB synchronously; cache always fresh, writes slower.
- **Write-behind (write-back)**: write to cache, flush to DB asynchronously; fast and batchable but risks data loss on cache failure.
- **Write-around**: write to DB only, let reads populate cache; avoids polluting cache with write-once data.
- **TTL**: expiry time bounding staleness; the simplest invalidation.
- **Eviction**: LRU (default choice), LFU (better for stable hot sets), FIFO, random. Redis has `allkeys-lru`, `allkeys-lfu`, `volatile-ttl` etc.
- **Hit ratio** = hits / (hits + misses); the metric that matters.
- **Layers**: browser/HTTP cache, CDN ([[cdn-and-edge]]), app in-process cache, distributed cache (Redis/Memcached), DB buffer pool.

## When to use / scenarios
- Read-heavy workload (read:write above ~10:1), expensive queries, computed aggregates, session data, rate-limit counters, feature flags.
- Data tolerates bounded staleness, or has an explicit invalidation event.
- Not for: write-heavy data with strong freshness needs, data that is rarely re-read (low hit ratio just adds a hop), or as a fix for a missing DB index (fix the query first, see [[database-indexing]]).

## How it works / example

```
 read:   client -> app -> cache --hit--> return
                             \--miss--> DB -> populate cache (TTL) -> return
 write:  client -> app -> DB (commit) -> delete cache key   (cache-aside invalidation)
```

Cache-aside with TTL jitter and single-flight to prevent stampedes (runnable
with an in-memory dict; swap for Redis in production):

```python
import random, threading, time

class Cache:
    def __init__(self):
        self.store: dict[str, tuple[float, object]] = {}
        self.locks: dict[str, threading.Lock] = {}
        self.guard = threading.Lock()

    def _lock_for(self, key):
        with self.guard:
            return self.locks.setdefault(key, threading.Lock())

    def get(self, key, loader, ttl=60.0):
        now = time.time()
        hit = self.store.get(key)
        if hit and hit[0] > now:
            return hit[1]
        with self._lock_for(key):              # single-flight per key
            hit = self.store.get(key)          # re-check after waiting
            if hit and hit[0] > time.time():
                return hit[1]
            value = loader()                   # only one caller hits the DB
            jitter = random.uniform(0, ttl * 0.1)   # avoid synchronized expiry
            self.store[key] = (time.time() + ttl + jitter, value)
            return value

    def invalidate(self, key):
        self.store.pop(key, None)

if __name__ == "__main__":
    calls = []
    c = Cache()
    load = lambda: calls.append(1) or "row"
    ts = [threading.Thread(target=c.get, args=("k", load)) for _ in range(50)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(calls) == 1
```

### Invalidation options (strongest to weakest)
1. **Delete on write** after DB commit (cache-aside). Race: a concurrent reader can repopulate stale data between read and delete; mitigate with short TTL as a backstop.
2. **Versioned keys** (`user:42:v17`): bump version on write; old keys age out. No race, costs a version lookup.
3. **Event-driven** invalidation from DB change stream (CDC) or message bus ([[message-queues-and-streams]]); decouples writers from cache knowledge.
4. **TTL only**: simplest; accept staleness up to TTL.

### Stampede / thundering herd defences
- Single-flight / request coalescing (above) or a short lock in Redis (`SET key NX PX`).
- Probabilistic early refresh (refresh before expiry with rising probability).
- Serve stale while revalidate; refresh in background.
- Jittered TTLs so keys loaded together do not expire together.
- Negative caching for known-missing keys (short TTL) to stop penetration by absent ids; Bloom filter in front for adversarial misses.

## Trade-offs
- **Freshness vs hit ratio**: longer TTL means higher hit ratio and more staleness.
- **Cache-aside vs write-through**: aside is simple and resilient; write-through keeps reads fresh but doubles write path and caches data nobody reads.
- **Write-behind**: throughput win, durability loss window; only for data you can afford to lose or can replay.
- **In-process vs distributed**: in-process is fastest and has no network hop but is per-instance and inconsistent between instances; distributed is shared but adds latency and a failure domain. Often use both (small L1 + Redis L2).
- **Memcached vs Redis**: Memcached is a simple multi-threaded key-value cache; Redis adds data structures, persistence, replication, scripting. Choose Redis when you need those, Memcached for plain big-object caching.

## Gotchas
- Caching errors or empty results with the same TTL as good data.
- Unbounded key cardinality (per-user per-filter keys) blows memory and kills hit ratio.
- Hot key: one key takes all traffic on a single cache shard; replicate it, or add a local L1 cache.
- Serialization cost and large values (MB-sized) can make the cache slower than the DB.
- Cold start / cache flush sends full load to the DB; warm up or rate-limit rebuilds ([[rate-limiting]]).
- Cached authorization decisions outliving a permission change (security bug).
- Dual-write inconsistency: updating cache and DB from different code paths without an ordering story.
- Treating the cache as a database; it can lose data any time. The source of truth stays elsewhere.

## Related
- [[cdn-and-edge]] - caching at the network edge for static and cacheable responses.
- [[consistent-hashing]] - how cache clusters spread keys and survive node changes.
- [[rate-limiting]] - counters usually live in the cache; also protects cold starts.
- [[database-indexing]] - fix slow queries before masking them with a cache.
- [[consistency-models]] - what staleness guarantees callers actually get.
- [[memory-and-performance]] - CPU/memory hierarchy that motivates caching.

## References
- Redis patterns docs: https://redis.io/docs/latest/develop/use/patterns/
- Nishtala et al., "Scaling Memcache at Facebook", NSDI 2013.
- Vattani et al., "Optimal Probabilistic Cache Stampede Prevention", VLDB 2015.
- Kleppmann, *Designing Data-Intensive Applications*.
