---
title: Memory and performance engineering
category: fundamentals
tags: [performance, profiling, memory, cache-locality, garbage-collection, latency, throughput, optimization]
use_cases:
  - "find out why a Python service uses several GB of RAM and keeps growing"
  - "speed up a slow endpoint without guessing which function is the bottleneck"
  - "decide whether to optimize code, add a cache or just scale out"
  - "process a file larger than memory without crashing"
  - "explain p99 latency spikes that averages do not show"
status: draft
last_verified: 2026-10-10
sources:
  - "Systems Performance, Brendan Gregg, 2nd ed."
  - "https://docs.python.org/3/library/profile.html"
  - "https://docs.python.org/3/library/tracemalloc.html"
  - "What Every Programmer Should Know About Memory, Ulrich Drepper - https://people.freebsd.org/~lstewart/articles/cpumemory.pdf"
  - "The Tail at Scale, Dean and Barroso, CACM 2013"
---

# Memory and performance engineering

## Summary
Performance work is a measurement discipline: find the real bottleneck with a profiler, change one thing, re-measure. Memory hierarchy (registers, cache, RAM, disk, network) and allocation behavior explain most gaps between theory ([[big-o-complexity]]) and reality. Optimize the slowest dominant cost, not what feels slow.

## Key concepts
- **Latency vs throughput:** time per operation vs operations per second. They trade off (batching raises throughput and latency).
- **Percentiles, not averages:** report p50, p95, p99. Tail latency dominates user experience and compounds across fan-out calls (The Tail at Scale).
- **Amdahl's law:** speeding up a fraction p of the work by factor s yields at most 1 / ((1 - p) + p/s) overall. Optimizing a 5% hot spot cannot give more than 5%.
- **Memory hierarchy:** each level is roughly an order of magnitude or more slower than the one above (CPU cache, RAM, SSD, network). The exact figures vary by hardware; the shape is what matters.
- **Cache locality:** sequential access over contiguous memory is fast (prefetching, cache lines); pointer chasing is slow. Arrays and columnar layouts beat scattered objects.
- **Allocation cost:** many small short-lived objects stress the allocator and garbage collector. Reuse buffers, avoid needless copies.
- **Garbage collection:** reference counting plus cyclic GC (CPython), or tracing GC with pauses (JVM, Go). GC pauses show up as tail latency.
- **Memory leak vs bloat:** a leak is unbounded growth from references you keep (global caches, listeners, closures); bloat is just heavy representation.
- **Working set:** the data actually touched; if it fits in cache/RAM, things are fast, otherwise you page or hit disk.
- **I/O dominates:** disk and network waits usually dwarf CPU in business apps. The cheapest optimization is fewer round trips.

## When to use / scenarios
- Slow endpoint: profile first. Typical culprits, in rough order: N+1 queries ([[orm-and-n-plus-one]]), missing index ([[database-indexing]]), serialization, accidental quadratic loops, synchronous remote calls in series.
- Growing memory: take allocation snapshots at two points and diff them.
- Larger-than-memory data: stream/iterate (generators, chunked reads), or push work into the database; see [[batch-and-stream-processing]].
- Repeated expensive results: cache with a clear invalidation story; see [[caching-strategies]].
- NOT worth it: micro-optimizing code that is not on the profile's hot path, or before correctness and a baseline measurement exist.

## How it works / example

The loop:

```
define goal (p99 < X ms at Y rps)  ->  measure baseline  ->  profile
   -> change ONE thing  ->  re-measure  ->  keep or revert  ->  repeat
```

CPU profile in Python:

```python
import cProfile, pstats

def work():
    return sorted(str(i) for i in range(200_000))

cProfile.run("work()", "prof.out")
pstats.Stats("prof.out").sort_stats("cumulative").print_stats(10)
# For production sampling without code changes: py-spy (external tool)
```

Memory snapshot diff:

```python
import tracemalloc

tracemalloc.start()
before = tracemalloc.take_snapshot()
leak = [bytearray(1024) for _ in range(10_000)]     # code under suspicion
after = tracemalloc.take_snapshot()
for stat in after.compare_to(before, "lineno")[:3]:
    print(stat)                                      # top growth by line
```

Streaming instead of loading everything:

```python fragment
def total_bytes(path):
    n = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):   # 1 MiB at a time, constant memory
            n += len(chunk)
    return n

# generator pipelines stay lazy:
lines = (l for l in open("big.log") if "ERROR" in l)
```

Compact representation in Python:

```python
import sys
from array import array

lst = list(range(1_000_000))           # list of int objects: pointers + objects
arr = array("i", range(1_000_000))     # packed 4-byte ints
print(sys.getsizeof(lst), sys.getsizeof(arr))   # compare on your machine
# __slots__ on classes with millions of instances removes per-instance dicts
```

Benchmark properly: warm up, repeat, take the median or min of several runs, use `timeit` or `pyperf`, run on representative data and hardware, compare against a recorded baseline.

## Trade-offs
- **Optimize vs scale out:** if the code is simple and the load is linear, adding instances is cheaper than engineering time; if the bottleneck is a shared resource (database), scaling the app tier does nothing.
- **Cache vs recompute:** caches buy speed with memory and staleness risk.
- **Latency vs throughput:** batching, buffering and larger pages raise throughput and add queueing delay.
- **Memory vs CPU:** compression, lazy loading and recomputation save RAM at CPU cost; precomputation does the reverse.
- **Readability vs speed:** keep the clear version unless a measurement proves the fast one is needed; comment why.
- **Language rewrite vs algorithm change:** an algorithmic fix ([[algorithm-patterns]]) almost always beats rewriting in a faster language; native extensions (numpy, a Rust module) are the next step for numeric hot loops.

## Gotchas
- Optimizing without profiling; the guess is wrong most of the time.
- Profiling in debug mode or with tiny data: results do not transfer.
- Averages hide tail latency; one slow dependency in a fan-out of 100 calls dominates.
- Unbounded caches and global lists are the most common Python leaks; bound them (`lru_cache(maxsize=...)`, TTL).
- Reading a whole file or full query result into a list "just to iterate" works in dev and OOMs in prod.
- `copy` and `deepcopy`, JSON encode/decode and logging with eager string formatting are frequent silent hot spots.
- Container memory limits: the process is killed (OOM) rather than slowed; JVM and Python do not always see the cgroup limit unless configured.
- Benchmark noise: CPU frequency scaling, noisy neighbors, cold caches, GC timing; control or repeat.
- Premature use of threads for CPU work in Python; see [[concurrency-and-parallelism]].

## Related
- [[big-o-complexity]] - the asymptotic side; this note covers where constants and hardware take over
- [[core-data-structures]] - representation choices that change memory and locality
- [[concurrency-and-parallelism]] - after profiling shows the workload is parallelizable
- [[observability-logs-metrics-traces]] - production profiling and percentile metrics
- [[performance-and-load-testing]] - measuring under realistic load
- [[capacity-planning-and-autoscaling]] - when the answer is more hardware
- [[cpu-caches-and-memory-hierarchy]] - cache lines, locality, false sharing and NUMA in depth

## References
- Gregg, "Systems Performance", 2nd ed.
- Drepper, "What Every Programmer Should Know About Memory"
- Dean and Barroso, "The Tail at Scale", Communications of the ACM, 2013
- Python docs: profile/cProfile, tracemalloc, timeit
