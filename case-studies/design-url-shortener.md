---
title: Design a URL shortener
category: case-studies
tags: [url-shortener, tinyurl, bitly, id-generation, caching, read-heavy, redirect, case-study]
use_cases:
  - "design a TinyURL or bit.ly style service that maps short codes to long URLs"
  - "build a link-shortening feature with click analytics and expiry into our product"
  - "generate compact unique IDs for public-facing resources without collisions"
  - "design a read-heavy redirect service that must answer in a few milliseconds"
  - "practice a classic system design interview question end to end"
status: stable
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 8 'Design a URL Shortener'"
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
  - https://github.com/donnemartin/system-design-primer
  - https://www.rfc-editor.org/rfc/rfc9110.html
  - https://en.wikipedia.org/wiki/Base62
---

# Design a URL shortener

## Summary
A service that turns a long URL into a short alias (`https://sho.rt/aZ3kP9q`)
and redirects visitors who open the alias. It is a read-heavy, key-value
workload whose interesting problems are generating short unique codes without
collisions, serving redirects at very low latency with caching, and handling
analytics without slowing the redirect path.

## Key concepts
- Core operations: `create(long_url) -> code`, `resolve(code) -> long_url` (HTTP redirect).
- **Read:write ratio is high** (many clicks per created link), so cache aggressively.
- **Code generation strategies:** hash-and-truncate, random with collision check,
  counter/ID encoded in base62, pre-generated key pool.
- **301 vs 302:** 301 (permanent) is cacheable by browsers and reduces load but
  hides later clicks from analytics and prevents later edits; 302 (found/temporary)
  keeps every click visible. Pick based on whether analytics or editing matter.
- **Base62** (`0-9a-zA-Z`): 62^7 is about 3.5 trillion codes, enough for decades at most scales.
- **Abuse:** malware/phishing links, enumeration of codes, spam creation.

## When to use / scenarios
Use this design for: link shorteners, invite/share links, pastebin-style
object handles, QR-code targets, any "public opaque ID to record" mapping.
For private IDs inside a system use plain UUIDs/sequences instead (see
[[unique-id-generation]]). If custom aliases, vanity domains and per-link
analytics are the product, the analytics pipeline becomes the main design.

## How it works / example

### 1. Requirements
Functional:
- Shorten a URL; optional custom alias and expiry time.
- Redirect short code to original URL.
- Optional: click analytics (count, referrer, geography), delete/disable link, user accounts and API keys.

Non-functional:
- Very high availability for redirects (links embedded in print and emails must not die).
- Low redirect latency (target: tens of milliseconds at the edge).
- Codes unpredictable enough to avoid trivial enumeration of private links.
- Durable: never lose a mapping once confirmed.
- Eventual consistency for analytics is fine; creation should be read-your-writes.

### 2. Back-of-envelope (assumptions, adjust to the real product)
Method: see [[back-of-envelope-estimation]].
- Assume 100 M new URLs per month -> about 40 writes/s average (100e6 / 2.6e6 s).
- Assume 100:1 read:write -> about 4,000 redirects/s average; plan for 5-10x peak.
- Retention 5 years: 100e6 x 60 = 6 B records.
- Row about 500 bytes (code, long URL up to 2 KB worst case but 100-200 typical, timestamps, owner) -> about 3 TB raw over 5 years before replication.
- Code length: 7 base62 chars -> 3.5e12 combinations vs 6e9 used, collisions rare for random.
- Cache: 80/20 rule suggests caching hot 20% of daily reads; a few tens of GB of RAM is plausible.

### 3. API
```
POST /api/v1/urls            { "long_url": "...", "custom_alias"?: "...", "expires_at"?: "..." }
  -> 201 { "code": "aZ3kP9q", "short_url": "https://sho.rt/aZ3kP9q" }
GET  /{code}                  -> 302 Location: <long_url>   (404 if unknown, 410 if expired)
DELETE /api/v1/urls/{code}    -> 204
GET  /api/v1/urls/{code}/stats -> { clicks, by_day, referrers }
```
Authenticate creation (API key) and rate-limit it ([[rate-limiting]]). Make
create idempotent per `(owner, long_url)` or accept an `Idempotency-Key` (see
[[idempotency-and-exactly-once]]).

### 4. Data model
```
urls(code PK, long_url, owner_id, created_at, expires_at, is_disabled)
clicks(code, ts, referrer, country, ua_hash)       -- append-only, goes to the analytics store
users(id, api_key_hash, ...)
```
Access pattern is a pure key lookup by `code`; no joins on the hot path. A
key-value or wide-column store (DynamoDB, Cassandra) or sharded SQL all fit
(see [[sql-vs-nosql]]). A single Postgres primary with read replicas handles
the assumed load until the multi-TB scale; shard by hash of `code`
([[partitioning-and-sharding]], [[consistent-hashing]]).

### 5. High-level architecture
```
 client --> CDN/edge --> LB --> redirect service --> cache (Redis) --miss--> DB (replicas)
                              \                       |
                               \--> create service -->|--> DB primary / KV store
                                          |
   redirect service --async click event--> Kafka --> analytics consumers --> OLAP store
   create service <-- key service (pre-generated unique IDs / counter ranges)
```
Split read (redirect) and write (create) services: they scale differently and
the redirect path is the one that must never fall over. See [[load-balancing]],
[[caching-strategies]], [[cdn-and-edge]], [[message-queues-and-streams]].

### 6. Deep dive A: generating the short code
| Approach | How | Pros | Cons |
|---|---|---|---|
| Hash + truncate | MD5/SHA-256 of long URL, take first 7 base62 chars | Same URL -> same code (dedupe) | Collisions; need check and retry with salt; round trips to DB |
| Random | 7 random base62 chars, insert with unique constraint, retry on conflict | Unguessable, simple | Collision probability rises with fill; retry cost |
| Counter + base62 | Global monotonically increasing ID encoded base62 | No collisions, short | Predictable/enumerable; counter is a hot spot |
| Key-generation service (KGS) | Pre-generate random unique codes into a pool; hand out batches | No collision at request time, fast | Extra component; pool must be durable, reuse protection |

Recommended: counter ranges or Snowflake-like IDs ([[unique-id-generation]])
fed through a reversible shuffle/permutation (or a KGS of random codes) so codes
are unique without a DB round-trip yet not sequential. Each app server leases a
block of, say, 10,000 IDs from a coordinator (ZooKeeper/etcd, see
[[consensus-raft-paxos]], or a DB sequence); a crashed server wastes the unused
rest of its block, which is fine given 3.5e12 space.

Base62 encoding:
```python
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
def encode(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n, 62)
        s = ALPHABET[r] + s
    return s or "0"
def decode(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 62 + ALPHABET.index(ch)
    return n
```
Custom aliases: enforce a unique constraint, a reserved-word list (`api`,
`admin`, `static`), and a length floor so they cannot collide with generated space.

### 7. Deep dive B: the redirect hot path
1. Edge/CDN or in-process LRU answers hot codes. 302 keeps analytics; if links
   are immutable and analytics are server-side-logged at the edge, 301 + short
   `Cache-Control` max-age is acceptable.
2. Redis lookup (`GET code`). Negative-cache misses briefly to stop code-scanning
   traffic from hitting the DB ([[caching-strategies]]).
3. On cache miss, read from a replica, populate the cache with TTL (and
   `expires_at` aware), return.
4. Emit a click event asynchronously (fire-and-forget to a queue). Never block
   the redirect on analytics; losing a few events is acceptable, so use
   at-least-once with dedupe downstream only if exact counts matter.

```python
def resolve(code, cache, db, events):
    url = cache.get(code)
    if url is None:
        row = db.get(code)                       # replica read
        if row is None or row.expired or row.disabled:
            cache.set(code, "", ttl=60)          # negative cache
            return 404
        url = row.long_url
        cache.set(code, url, ttl=3600)
    events.publish({"code": code, "ts": now()})  # async, non-blocking
    return 302, url
```

### 8. Deep dive C: analytics
Clicks are an append-only high-volume stream: Kafka -> stream processor
(Flink/Spark) -> aggregates (per code per hour) in an OLAP store or a
time-series store ([[batch-and-stream-processing]], [[data-warehousing-and-olap]]).
Serve `/stats` from pre-aggregated tables, not by scanning raw events.

### 9. Scaling and failure handling
- **Cache failure:** redirect service falls back to DB replicas; protect them with
  request coalescing and a concurrency limit ([[resilience-patterns]]).
- **DB failure:** replicate synchronously within a region and asynchronously
  across regions ([[replication]]); redirects can be served from any replica,
  creates need the primary or a quorum.
- **Multi-region:** replicate the mapping globally (links are write-once, so
  conflicts are rare), route readers to the nearest region via DNS/anycast.
- **Expiry:** lazy check on read plus a background sweeper to reclaim rows; never
  reuse expired codes immediately (old links in the wild would redirect somewhere new).
- **Abuse:** check destinations against safe-browsing lists, rate-limit by
  IP/key, require login for bulk creation, support takedown.
- **Hot keys:** a viral link concentrates traffic on one cache key; use local
  in-process caches and the CDN to absorb it.

## Trade-offs
- Predictable counters are simple and collision-free but enumerable; random or
  permuted codes are safer for private-ish links at the cost of coordination.
- 301 saves bandwidth, 302 preserves analytics and editability.
- Dedupe (same long URL -> same code) saves space but breaks per-user analytics
  and per-user expiry; usually do not dedupe across users.
- Strong consistency on create is cheap (single key write); do not over-engineer
  global consensus for a write-once mapping.

## Gotchas
- Using a sequential counter exposes your link volume and lets competitors scrape every link.
- Case-insensitive collation or URL decoders treating `l`/`I`/`0`/`O` as lookalikes:
  consider dropping ambiguous characters if codes are typed by humans.
- Redirecting to `javascript:` or internal addresses (open redirect/SSRF-adjacent):
  validate scheme (http/https only) and block private IP ranges when you fetch previews.
- Redirect loops (shortening your own short URLs).
- Cached 301s are effectively permanent in browsers; you cannot change them later.
- Forgetting a canonical form (trailing slash, case) causes duplicate rows.
- Delete must purge the cache and any CDN copies.

## Related
- [[unique-id-generation]] - counters, Snowflake IDs and collision-free code generation
- [[caching-strategies]] - cache-aside, negative caching, hot-key handling
- [[back-of-envelope-estimation]] - the capacity maths used above
- [[rate-limiting]] - protect creation and redirect endpoints
- [[partitioning-and-sharding]] - how the code space is split when one DB is not enough
- [[system-design-interview-framework]] - the generic procedure this case follows
- [[cdn-and-edge]] - serving redirects at the edge

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 8
- Kleppmann, *Designing Data-Intensive Applications* (2017)
- System Design Primer: https://github.com/donnemartin/system-design-primer
- RFC 9110 HTTP Semantics (301/302 redirects): https://www.rfc-editor.org/rfc/rfc9110.html
