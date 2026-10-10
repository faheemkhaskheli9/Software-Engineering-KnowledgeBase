---
title: Back-of-envelope estimation
category: system-design
tags: [estimation, capacity, qps, storage, bandwidth, latency-numbers]
use_cases:
  - "estimate QPS, storage and bandwidth for a new service before choosing architecture"
  - "decide whether one database is enough or we need sharding and caching"
  - "sanity check a proposed design against expected traffic"
  - "size a cache or a queue for a given request rate"
status: stable
last_verified: 2026-10-10
sources:
  - "Jeff Dean, Numbers Everyone Should Know, LADIS 2009 keynote (Designs, Lessons and Advice from Building Large Distributed Systems)"
  - https://gist.github.com/jboner/2841832
  - "Alex Xu, System Design Interview vol 1, ch. 2 Back-of-the-envelope estimation"
  - https://github.com/donnemartin/system-design-primer
---

# Back-of-envelope estimation

## Summary
Quick order-of-magnitude arithmetic that turns "100M users" into QPS, storage
and bandwidth so you can pick an architecture on evidence. The goal is the
power of ten, not the exact figure: it tells you if a single machine suffices,
whether data fits in RAM, and where the bottleneck sits.

## Key concepts
- **Powers of two/ten**: 1 KB ~ 10^3 B, 1 MB ~ 10^6, 1 GB ~ 10^9, 1 TB ~ 10^12, 1 PB ~ 10^15 (use 10^x for speed).
- **Seconds per day ~ 86,400 ~ 10^5** (round to 100K). A "1M requests/day" service is ~10 QPS.
- **Peak factor**: peak QPS is a multiple of average; 2-10x is a common assumption. State it.
- **Latency numbers** (Dean / Norvig, order of magnitude, hardware-dependent): L1 cache ~1 ns, main memory ~100 ns, SSD random read ~100 us, round trip in same datacenter ~500 us, disk seek ~10 ms, cross-continent round trip ~150 ms. Memory is ~1000x faster than SSD, SSD far faster than network hop to another region.
- **Little's law**: concurrent requests in flight = arrival rate x average latency.
- **Rule of thumb throughput** (verify for your stack): a single modern relational DB node handles on the order of thousands of simple QPS; a single cache node handles on the order of 10^5. Treat these as starting guesses, not facts, and replace with measurements.

## When to use / scenarios
- First 5 minutes of any design: decide whether sharding, a cache or a CDN is justified at all.
- Capacity planning for a new feature: how many bytes per row times rows per year.
- Cost sketching: storage and egress dominate cloud bills; estimate them early.
- Do not use for: precision SLAs or contracts. Load test instead (see [[performance-and-load-testing]]).

## How it works / example

Method: users -> actions/day -> QPS -> peak QPS -> bytes per action -> storage/bandwidth.

Worked example: a photo-sharing service, 100M DAU (assumptions are inputs, state them).

```
Assumptions
  DAU                      100M
  uploads / user / day     0.1      (1 in 10 users upload)
  views   / user / day     50
  avg photo size           500 KB   (after compression)
  retention                5 years

Writes
  uploads/day   = 100M * 0.1          = 10M/day
  write QPS     = 10M / 1e5           = ~100 QPS   (peak 2x => ~200)

Reads
  views/day     = 100M * 50           = 5B/day
  read QPS      = 5B / 1e5            = ~50,000 QPS (peak 2x => ~100K)
  read:write    = 500:1               => read-heavy: cache + CDN

Storage
  per day       = 10M * 500 KB        = 5 TB/day
  5 years       = 5 TB * 365 * 5      = ~9 PB      => object storage, not a DB
  (x3 replication or erasure coding overhead on top)

Bandwidth
  ingress       = 100 QPS * 500 KB    = 50 MB/s
  egress        = 50K QPS * 500 KB    = 25 GB/s    => needs a CDN
```

Conclusions drawn from numbers: metadata (small rows) fits a sharded or
replicated DB, photo bytes go to [[blob-object-storage]], 25 GB/s egress is
served through a [[cdn-and-edge]], and 100 write QPS means writes are not the
scaling problem.

Tiny helper to keep the arithmetic honest:

```python
SECONDS_PER_DAY = 86_400

def qps(events_per_day: float, peak_factor: float = 2.0) -> tuple[float, float]:
    avg = events_per_day / SECONDS_PER_DAY
    return avg, avg * peak_factor

def storage_bytes(events_per_day: float, bytes_each: float,
                  years: float, replication: float = 3.0) -> float:
    return events_per_day * bytes_each * 365 * years * replication

if __name__ == "__main__":
    avg, peak = qps(5e9)                       # 5B views/day
    print(f"read qps avg={avg:,.0f} peak={peak:,.0f}")
    pb = storage_bytes(10e6, 500e3, 5) / 1e15  # photos
    print(f"photo storage with 3x replication: {pb:.1f} PB")
```

### Handy memory tricks
- 1M req/day ~ 12 QPS; 100M/day ~ 1,200 QPS; 1B/day ~ 12,000 QPS.
- 1 char ASCII = 1 B; typical UUID 16 B binary / 36 B text; int64 8 B; timestamp 8 B.
- A tweet-sized text row with metadata ~ 200-300 B; a 1 KB row at 1B rows = 1 TB.
- Hot working set often ~20% of data (Pareto assumption; state it) so cache ~20% of daily read volume.

## Trade-offs
- **Precision vs speed**: round hard (86,400 -> 100,000); a factor of 2 rarely changes the design, a factor of 100 always does.
- **Average vs peak vs burst**: size for peak; autoscaling handles the rest. Events like launches or sales are 10-100x spikes and need queues or rate limits.
- **Replication/overhead**: remember 3x replication, indexes (often 30-100% extra), and backups when sizing storage.
- **Assumption transparency**: a number with a stated assumption beats a confident unstated one.

## Gotchas
- Mixing bits and bytes (network in Gbps, storage in GB).
- Forgetting growth: size for 1-3 years, and say the growth rate.
- Estimating averages for a spiky workload (chat, trading, sports events).
- Treating cache hit rate as given; a 90% hit rate leaves 10% of 100K QPS = 10K QPS hitting the DB.
- Ignoring fan-out: one post to a user with 1M followers is 1M writes in a push model.
- Quoting latency numbers as exact; they vary by hardware and year. Use ratios.

## Related
- [[system-design-interview-framework]] - where estimation sits in the sequence.
- [[capacity-planning-and-autoscaling]] - turning estimates into provisioning.
- [[caching-strategies]] - sizing a cache from the hot set.
- [[partitioning-and-sharding]] - the step you take when numbers exceed one node.
- [[memory-and-performance]] - latency hierarchy background.

## References
- Jeff Dean, "Numbers Everyone Should Know": https://gist.github.com/jboner/2841832
- Alex Xu, *System Design Interview* vol 1, chapter 2.
- System Design Primer: https://github.com/donnemartin/system-design-primer
