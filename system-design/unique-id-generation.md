---
title: Unique ID generation
category: system-design
tags: [id, uuid, snowflake, ulid, uuidv7, sequence, base62, distributed-ids]
use_cases:
  - "generate unique, roughly time-sortable IDs across many servers without a central database sequence"
  - "choose between auto-increment, UUIDv4, UUIDv7, ULID and Snowflake IDs for a table primary key"
  - "create short URL slugs without collisions"
  - "avoid leaking record counts or enabling ID enumeration in public URLs"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc9562
  - https://github.com/twitter-archive/snowflake/tree/snowflake-2010
  - https://github.com/ulid/spec
  - "Alex Xu, System Design Interview vol 1, ch. 7 Design a unique ID generator in distributed systems"
  - https://www.postgresql.org/docs/current/datatype-uuid.html
---

# Unique ID generation

## Summary
Every entity needs an identifier that is unique, cheap to produce, and ideally
well behaved in the database index. In a distributed system you want to mint
IDs on any node without coordination. The main options are DB sequences,
random UUIDs, time-ordered UUIDs (UUIDv7)/ULIDs, and Snowflake-style 64-bit
IDs composed of timestamp + machine id + sequence.

## Key concepts
- **Uniqueness vs ordering**: unique is mandatory; time-sortable (k-sortable) is a strong nice-to-have for index locality and pagination; strictly monotonic across nodes is rarely needed and expensive.
- **Auto-increment/sequence**: simple, compact, strictly ordered per DB; single writer bottleneck, hard across shards, leaks volume and is guessable.
- **UUIDv4**: 122 random bits, no coordination, collision probability negligible; but random order fragments B-tree indexes (page splits, poor cache locality) and is 16 bytes.
- **UUIDv7** (RFC 9562): 48-bit Unix ms timestamp + random bits; time-ordered, standard, good index locality.
- **ULID**: 48-bit timestamp + 80 random bits, Crockford base32, 26 chars, lexicographically sortable.
- **Snowflake**: 64-bit = 1 sign bit + 41 bits ms timestamp (about 69 years from a custom epoch) + 10 bits worker id + 12 bits per-ms sequence (4096 IDs/ms/worker). Fits in a BIGINT, sorts by time.
- **Ticket server / range allocation**: a central service hands each app server a block of IDs (e.g. 1000 at a time); server issues from its block locally.
- **Base62/Base58 encoding**: turns numeric ids into short URL-safe strings (7 chars of base62 is 62^7, about 3.5 x 10^12 values).

## When to use / scenarios
- Multi-node writers or sharded tables where a single sequence is a bottleneck ([[partitioning-and-sharding]]).
- Client-generated ids (offline-first apps, idempotency keys, see [[idempotency-and-exactly-once]]).
- Public identifiers that must not reveal counts or be enumerable: use random or hashed external ids alongside an internal numeric key.
- Short links ([[design-url-shortener]]): counter plus base62, or random with collision check.
- Single Postgres/MySQL instance, internal ids only: a plain `bigint generated always as identity` is fine and simplest. Do not over-engineer.

## How it works / example

Snowflake layout:

```
 | 1 | 41 bits timestamp (ms since custom epoch) | 10 bits worker | 12 bits sequence |
   0   0000000000000000000000000000000000000000     0000000000       000000000000
```

Runnable Snowflake generator (thread-safe, handles same-ms overflow and clock regression):

```python
import threading, time

class Snowflake:
    EPOCH = 1_700_000_000_000          # custom epoch in ms
    W_BITS, S_BITS = 10, 12
    MAX_SEQ = (1 << S_BITS) - 1

    def __init__(self, worker_id: int):
        assert 0 <= worker_id < (1 << self.W_BITS)
        self.worker, self.last, self.seq = worker_id, -1, 0
        self.lock = threading.Lock()

    def _now(self):
        return int(time.time() * 1000)

    def next_id(self) -> int:
        with self.lock:
            now = self._now()
            if now < self.last:                     # clock moved backwards
                raise RuntimeError(f"clock regression {self.last - now} ms")
            if now == self.last:
                self.seq = (self.seq + 1) & self.MAX_SEQ
                if self.seq == 0:                   # exhausted this ms; spin to next
                    while now <= self.last:
                        now = self._now()
            else:
                self.seq = 0
            self.last = now
            return ((now - self.EPOCH) << (self.W_BITS + self.S_BITS)
                    | self.worker << self.S_BITS | self.seq)

if __name__ == "__main__":
    g = Snowflake(worker_id=1)
    ids = [g.next_id() for _ in range(10_000)]
    assert len(set(ids)) == len(ids) and ids == sorted(ids)
```

UUIDv7 in Python 3.14+ is `uuid.uuid7()`; on earlier versions use a library
(for example `uuid6`/`uuid-utils`). In Postgres, store as the native `uuid` type
(16 bytes), not `varchar(36)`.

Base62 for short codes:

```python
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

def b62(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 62)
        out = ALPHABET[r] + out
        if n == 0:
            return out

assert b62(125) == "21"
```

### Picking one
| Need | Choice |
|---|---|
| Single DB, internal only | identity/sequence |
| Distributed, no coordination, standard format, index friendly | UUIDv7 |
| Compact 64-bit, sortable, high throughput | Snowflake-style (worker id assignment needed) |
| Human-friendly sortable string | ULID |
| Unguessable public token | 128+ bits from a CSPRNG (UUIDv4 or `secrets.token_urlsafe`) |
| Short code | counter or range allocator + base62 (optionally scrambled) |

## Trade-offs
- **Size**: 64-bit ids halve index size vs 128-bit; matters at billions of rows.
- **Ordering vs privacy**: time-ordered ids leak creation time (and rate); random ids do not but fragment indexes. Common solution: internal sortable id plus separate opaque public id.
- **Coordination**: Snowflake needs unique worker ids (assign via config, ZooKeeper/etcd lease, or K8s StatefulSet ordinal); UUIDs need none.
- **Strict vs approximate ordering**: ids from different nodes sort by ms timestamp only, not by true causal order ([[time-clocks-and-ordering]]). Do not use them to order events that need exact causality.
- **Counter + range allocation**: very fast and compact; gaps appear on crashes and ids are predictable.

## Gotchas
- Clock skew or NTP step backwards can generate duplicates or errors in timestamp-based schemes; refuse or wait, never reuse a timestamp.
- Duplicate worker ids after misconfiguration or autoscaling silently produce colliding Snowflake IDs.
- JavaScript numbers lose precision above 2^53; send 64-bit ids as strings in JSON APIs.
- UUIDv4 as clustered primary key in MySQL/InnoDB causes heavy page splits; prefer ordered ids there.
- Hashing urls (MD5 truncated) for short codes needs collision handling; truncation raises birthday-collision odds.
- Sequential public ids enable scraping and IDOR probing; authorize every access regardless of id secrecy ([[owasp-top-10]]).
- Using `random()` rather than a CSPRNG for security tokens.

## Related
- [[design-url-shortener]] - the classic consumer of id generation.
- [[partitioning-and-sharding]] - why per-shard sequences are insufficient.
- [[time-clocks-and-ordering]] - limits of timestamp-based ordering.
- [[idempotency-and-exactly-once]] - client-generated unique keys.
- [[database-indexing]] - why id randomness affects B-tree performance.

## References
- RFC 9562 (UUIDs, including v7): https://www.rfc-editor.org/rfc/rfc9562
- Twitter Snowflake (archived): https://github.com/twitter-archive/snowflake/tree/snowflake-2010
- ULID spec: https://github.com/ulid/spec
- Alex Xu, *System Design Interview* vol 1, chapter 7.
