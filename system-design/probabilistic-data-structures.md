---
title: Probabilistic data structures (Bloom filter, Count-Min Sketch, HyperLogLog)
category: system-design
tags: [probabilistic, bloom-filter, cuckoo-filter, count-min-sketch, hyperloglog, cardinality, heavy-hitters, sketches, redis, approximation]
use_cases:
  - "count unique visitors per page per day without storing every user id"
  - "skip a disk or network lookup for keys that are definitely not there"
  - "find the most frequent search queries or heaviest API clients in a high-volume stream"
  - "deduplicate billions of crawled URLs with a fixed memory budget"
  - "choose between an exact set, a Bloom filter and a cuckoo filter and size it for a false-positive target"
status: draft
last_verified: 2026-10-24
sources:
  - https://doi.org/10.1145/362686.362692
  - https://doi.org/10.1016/j.jalgor.2003.12.001
  - https://algo.inria.fr/flajolet/Publications/FlFuGaMe07.pdf
  - https://research.google/pubs/hyperloglog-in-practice-algorithmic-engineering-of-a-state-of-the-art-cardinality-estimation-algorithm/
  - https://www.cs.cmu.edu/~dga/papers/cuckoo-conext2014.pdf
  - https://redis.io/docs/latest/develop/data-types/probabilistic/
---

# Probabilistic data structures (Bloom filter, Count-Min Sketch, HyperLogLog)

## Summary
Probabilistic data structures (sketches) answer membership, frequency and
distinct-count questions over huge sets or streams in a small, fixed amount of
memory, in exchange for a bounded, tunable error. A Bloom filter says "definitely
not present" or "maybe present"; a Count-Min Sketch estimates how often an item
occurred and never underestimates; HyperLogLog estimates how many distinct items
were seen. Use them when an exact answer would need memory proportional to the
data and an approximate answer with a known error bound is acceptable.

## Key concepts
- **Bloom filter** (Bloom, 1970): a bit array of `m` bits and `k` hash
  functions. Insert sets `k` bits; a lookup that finds any of its `k` bits
  unset proves absence. False positives possible, false negatives impossible.
  For `n` expected items and target false-positive rate `p`, the standard
  sizing is `m = -n ln p / (ln 2)^2` bits and `k = (m / n) ln 2` hashes.
- **No deletes, no resize**: clearing a bit could remove other items. A
  counting Bloom filter (counters instead of bits) or a **cuckoo filter**
  (Fan et al., 2014, stores short fingerprints) supports deletion. To grow,
  allocate a new filter or use a scalable (stacked) variant.
- **Count-Min Sketch** (Cormode and Muthukrishnan, 2005): `d` rows of `w`
  counters, one hash per row. Add increments one counter per row; estimate is
  the minimum across rows. With `w = ceil(e / epsilon)` and
  `d = ceil(ln(1 / delta))`, the estimate exceeds the true count by at most
  `epsilon * N` (N = total of all counts) with probability `1 - delta`. It only
  overestimates, so it is good for heavy hitters and poor for rare items.
- **HyperLogLog** (Flajolet et al., 2007): hash each item, use the first `p`
  bits to pick one of `m = 2^p` registers and store the longest run of leading
  zeros seen in the rest. A harmonic mean over registers gives the cardinality.
  The relative standard error is about `1.04 / sqrt(m)`. Google's HyperLogLog++
  (Heule et al., 2013) adds a 64-bit hash, bias correction and a sparse
  representation for small counts.
- **Mergeability**: sketches built with the same parameters and hash functions
  combine losslessly. Bloom filters merge by bitwise OR, Count-Min by adding
  matrices, HyperLogLog by taking the register-wise max. This is why they fit
  distributed and per-shard aggregation (daily uniques = merge of hourly HLLs).
- **Top-k / heavy hitters**: a Count-Min Sketch plus a small heap of current
  leaders, or dedicated algorithms (Misra-Gries, Space-Saving).

## When to use / scenarios
- **Avoid expensive misses**: LSM-tree storage engines keep a Bloom filter per
  SSTable so a point read skips files that cannot hold the key
  ([[storage-engines-btree-lsm]]); a cache can put one in front of the database
  to reject ids that never existed ([[caching-strategies]]).
- **Dedup at scale**: "have we crawled this URL" in a crawler frontier
  ([[design-web-crawler]]), "has this user already seen this item" in a feed.
  A false positive means one item is skipped, which must be acceptable.
- **Distinct counts**: unique visitors, distinct IPs per minute, distinct
  devices per campaign, `COUNT(DISTINCT)` in analytics engines
  ([[data-warehousing-and-olap]]). HyperLogLog sketches can be stored per time
  bucket and merged for any range.
- **Frequencies in streams**: top queries, noisy tenants, abusive clients for
  [[rate-limiting]], hot keys in a cache, trending hashtags in
  [[batch-and-stream-processing]].
- When NOT to use: billing, quotas you enforce to the unit, security decisions
  (a false positive in an allowlist is an authorization bug), or sets small
  enough to hold exactly. A `set` of a few million 8-byte ids is often fine;
  measure before reaching for a sketch. Use an exact structure from
  [[core-data-structures]] when the error is not acceptable.

## How it works / example
```
Bloom filter, k=3, m=16           Count-Min Sketch, d=3 rows, w=8
insert "a": bits 2, 7, 11         add "x": row0[h0(x)]++, row1[h1(x)]++, row2[h2(x)]++
query  "b": bits 2, 5, 11         estimate "x" = min(row0[h0], row1[h1], row2[h2])
        bit 5 unset -> absent     collisions only add, so min >= true count
```

A self-contained implementation of all three, checked against exact answers.
Hashing uses BLAKE2b with a per-row salt; the Bloom filter derives its `k`
indexes from two hashes (the Kirsch-Mitzenmacher double-hashing technique).

```python
import hashlib
import math

def h64(item: str, salt: int = 0) -> int:
    d = hashlib.blake2b(item.encode(), digest_size=8, salt=salt.to_bytes(16, "little"))
    return int.from_bytes(d.digest(), "big")

class BloomFilter:
    def __init__(self, n: int, p: float):
        self.m = math.ceil(-n * math.log(p) / math.log(2) ** 2)
        self.k = max(1, round(self.m / n * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)

    def _idx(self, item):
        a, b = h64(item, 1), h64(item, 2) | 1
        return [(a + i * b) % self.m for i in range(self.k)]

    def add(self, item):
        for i in self._idx(item):
            self.bits[i // 8] |= 1 << (i % 8)

    def __contains__(self, item):
        return all(self.bits[i // 8] >> (i % 8) & 1 for i in self._idx(item))

class CountMinSketch:
    def __init__(self, epsilon: float, delta: float):
        self.w = math.ceil(math.e / epsilon)
        self.d = math.ceil(math.log(1 / delta))
        self.rows = [[0] * self.w for _ in range(self.d)]

    def add(self, item, count=1):
        for r in range(self.d):
            self.rows[r][h64(item, r) % self.w] += count

    def estimate(self, item):
        return min(self.rows[r][h64(item, r) % self.w] for r in range(self.d))

class HyperLogLog:
    def __init__(self, p: int = 12):
        self.p, self.m = p, 1 << p
        self.reg = [0] * self.m

    def add(self, item):
        x = h64(item)
        idx = x >> (64 - self.p)
        rest = x & ((1 << (64 - self.p)) - 1)
        rank = (64 - self.p) - rest.bit_length() + 1      # leading zeros + 1
        self.reg[idx] = max(self.reg[idx], rank)

    def merge(self, other):
        self.reg = [max(a, b) for a, b in zip(self.reg, other.reg)]

    def count(self) -> float:
        alpha = 0.7213 / (1 + 1.079 / self.m)
        est = alpha * self.m ** 2 / sum(2.0 ** -r for r in self.reg)
        zeros = self.reg.count(0)
        if est <= 2.5 * self.m and zeros:                 # small-range correction
            est = self.m * math.log(self.m / zeros)
        return est

# Bloom: 10,000 items at a 1% target, then probe 10,000 items never inserted.
bf = BloomFilter(n=10_000, p=0.01)
for i in range(10_000):
    bf.add(f"user:{i}")
assert all(f"user:{i}" in bf for i in range(10_000))           # no false negatives
fp = sum(f"other:{i}" in bf for i in range(10_000)) / 10_000
print(f"bloom: m={bf.m} bits ({bf.m / 8 / 1024:.1f} KiB), k={bf.k}, false positives={fp:.3%}")
assert fp < 0.02

# Count-Min: a skewed stream; estimates never undercount, error <= eps*N w.h.p.
cms = CountMinSketch(epsilon=0.001, delta=0.01)
true = {}
for i in range(50_000):
    key = f"q{i % 7}" if i % 2 else f"rare{i}"                 # 7 heavy keys + long tail
    cms.add(key)
    true[key] = true.get(key, 0) + 1
N = sum(true.values())
for key in ["q0", "q3", "rare10", "rare4000"]:
    est = cms.estimate(key)
    assert true[key] <= est <= true[key] + 0.001 * N, (key, est, true[key])
print(f"cms: {cms.d}x{cms.w} counters, q0 true={true['q0']} est={cms.estimate('q0')}")

# HyperLogLog: two shards, merged; expected error about 1.04/sqrt(4096) = 1.6%.
a, b = HyperLogLog(), HyperLogLog()
for i in range(60_000):
    a.add(f"visitor:{i}")
for i in range(40_000, 100_000):                              # 20k overlap
    b.add(f"visitor:{i}")
a.merge(b)
est = a.count()
print(f"hll: {a.m} registers, distinct est={est:.0f} (true 100000)")
assert abs(est - 100_000) / 100_000 < 3 * 1.04 / math.sqrt(a.m)
```

In production use a maintained implementation rather than your own: Redis has
HyperLogLog built in (`PFADD`, `PFCOUNT`, `PFMERGE`) and Bloom, cuckoo,
Count-Min and Top-K types (`BF.*`, `CF.*`, `CMS.*`, `TOPK.*`) in its
probabilistic data types; analytical databases expose approximate distinct
counts as SQL functions.

## Trade-offs
- **Memory vs error**: every halving of the error costs memory. Bloom filter
  bits grow with `ln(1/p)`, HyperLogLog registers with `1/error^2`, Count-Min
  width with `1/epsilon`. Pick the error the product can tolerate first.
- **Bloom vs cuckoo filter**: Bloom is simplest and merges by OR; cuckoo
  supports deletion and, per its paper, uses less space than Bloom at low
  false-positive rates, but inserts can fail when the table is nearly full.
- **Sketch vs exact store**: an exact set or counter table is simpler,
  debuggable and correct; a sketch wins only when memory, network transfer or
  merge cost of the exact version is the real constraint.
- **Count-Min vs exact counters for top-k**: Count-Min with a heap uses fixed
  memory but overestimates colliding items; exact counters per key are fine
  when the key space is bounded.
- **Local vs shared sketch**: per-node sketches merged later avoid a hot
  shared structure but give answers only after aggregation.

## Gotchas
- Sizing a Bloom filter for today's item count: once `n` is exceeded the
  false-positive rate climbs quickly and silently. Track the fill ratio and
  rebuild or stack filters.
- Merging sketches built with different sizes, precisions or hash seeds gives
  garbage, without an error. Version the parameters with the data.
- Weak or correlated hash functions (Python's built-in `hash()` is randomized
  per process for strings, so it also breaks persisted or shared sketches). Use
  a stable hash such as BLAKE2, xxHash or MurmurHash.
- Treating a "maybe present" as "present": a Bloom filter only rules things out;
  confirm positives against the real store when correctness matters.
- Using Count-Min for low-frequency items: the additive error `epsilon * N`
  can be larger than their true counts.
- HyperLogLog cannot list members or answer "is X in the set"; it also cannot
  subtract. Intersections computed by inclusion-exclusion have large relative
  error when the overlap is small.
- Adversarial inputs: an attacker who knows the hash can craft keys that
  collide and push the false-positive rate up; use a keyed hash for untrusted
  input.

## Related
- [[core-data-structures]] - exact structures and the short Bloom filter overview this topic expands.
- [[storage-engines-btree-lsm]] - per-SSTable Bloom filters that skip disk reads.
- [[caching-strategies]] - Bloom filter in front of a cache to stop penetration by absent keys.
- [[design-web-crawler]] - URL dedup in the frontier with a fixed memory budget.
- [[data-warehousing-and-olap]] - approximate distinct counts in analytical queries.
- [[batch-and-stream-processing]] - sketches as mergeable state in stream aggregations.
- [[rate-limiting]] - finding heavy clients with frequency sketches.

## References
- Burton H. Bloom, "Space/time trade-offs in hash coding with allowable errors", *Communications of the ACM* 13(7), 1970: https://doi.org/10.1145/362686.362692
- Graham Cormode and S. Muthukrishnan, "An improved data stream summary: the count-min sketch and its applications", *Journal of Algorithms* 55(1), 2005: https://doi.org/10.1016/j.jalgor.2003.12.001
- Philippe Flajolet, Eric Fusy, Olivier Gandouet and Frederic Meunier, "HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm", AofA 2007: https://algo.inria.fr/flajolet/Publications/FlFuGaMe07.pdf
- Stefan Heule, Marc Nunkesser and Alexander Hall, "HyperLogLog in Practice: Algorithmic Engineering of a State of The Art Cardinality Estimation Algorithm", EDBT 2013: https://research.google/pubs/hyperloglog-in-practice-algorithmic-engineering-of-a-state-of-the-art-cardinality-estimation-algorithm/
- Bin Fan, David G. Andersen, Michael Kaminsky and Michael D. Mitzenmacher, "Cuckoo Filter: Practically Better Than Bloom", CoNEXT 2014: https://www.cs.cmu.edu/~dga/papers/cuckoo-conext2014.pdf
- Adam Kirsch and Michael Mitzenmacher, "Less Hashing, Same Performance: Building a Better Bloom Filter", ESA 2006 (double hashing for the `k` indexes).
- Redis documentation, probabilistic data types: https://redis.io/docs/latest/develop/data-types/probabilistic/
