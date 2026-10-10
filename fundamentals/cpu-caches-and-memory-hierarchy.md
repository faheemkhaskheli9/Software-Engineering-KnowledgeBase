---
title: CPU caches and the memory hierarchy
category: fundamentals
tags: [memory-hierarchy, cpu-cache, cache-line, locality, false-sharing, tlb, numa, prefetching, data-oriented-design]
use_cases:
  - "explain why iterating a 2D array by column is much slower than by row"
  - "find out why adding threads made a counter-heavy loop slower"
  - "lay out data for a hot loop so it stays in cache"
  - "understand why an array scan beats a linked list or tree for small n"
  - "reason about NUMA effects on a multi-socket database server"
status: draft
last_verified: 2026-10-10
sources:
  - "Computer Systems: A Programmer's Perspective, Bryant and O'Hallaron (ch. 6, The Memory Hierarchy)"
  - "What Every Programmer Should Know About Memory, Ulrich Drepper, 2007 - https://people.freebsd.org/~lstewart/articles/cpumemory.pdf"
  - "Computer Architecture: A Quantitative Approach, Hennessy and Patterson"
  - "Intel 64 and IA-32 Architectures Optimization Reference Manual"
---

# CPU caches and the memory hierarchy

## Summary
Storage is arranged in levels: registers, several levels of CPU cache, main memory, then SSD/disk and the network, each level larger and slower than the one above. Hardware moves data between levels in fixed-size blocks (cache lines, pages), so programs that touch memory sequentially and reuse what they just touched run far faster than programs that jump around. Locality, not instruction count, often decides real-world performance.

## Key concepts
- **Hierarchy:** registers -> L1 -> L2 -> L3 (often shared by cores) -> DRAM -> SSD/disk -> network. Each step down is bigger, cheaper per byte and slower. Look up current latencies for your hardware rather than memorizing a table.
- **Cache line:** the unit of transfer between cache and memory (64 bytes on most current x86 and many ARM cores; check your CPU). Reading one byte loads the whole line.
- **Temporal locality:** recently used data is likely used again soon, so keep it in cache.
- **Spatial locality:** data near recently used data is likely used next, so the rest of the line is useful.
- **Hit, miss, miss rate:** a miss stalls the core while the line is fetched from the next level. Miss kinds: compulsory (first touch), capacity (working set too big), conflict (addresses map to the same set).
- **Associativity:** a set-associative cache maps each address to one set of N slots; power-of-two strides can collide in the same set.
- **Prefetching:** hardware detects sequential or strided access and fetches ahead. Pointer chasing defeats it because the next address is unknown until the load completes.
- **Write-back vs write-through:** caches usually buffer writes and flush dirty lines later.
- **Cache coherence (MESI and variants):** cores keep private caches consistent; a write by one core invalidates the line in others.
- **False sharing:** two threads write different variables on the same line, so the line bounces between cores even though no data is shared logically.
- **TLB:** caches virtual-to-physical page translations. Random access across a large heap misses the TLB too; huge pages reduce that.
- **NUMA:** on multi-socket machines, memory attached to another socket is slower to reach; thread and memory placement matter.
- **Page cache:** the OS keeps recently read file blocks in RAM, the same idea one level down; databases and Kafka rely on it.

## When to use / scenarios
- A hot loop over large data is slower than its operation count suggests: check access pattern and layout before micro-optimizing instructions.
- Choosing between array, linked list, tree or hash for small to medium n: contiguous arrays often win on locality ([[core-data-structures]]).
- Analytics over a few columns of many rows: columnar layout reads only the needed columns ([[data-warehousing-and-olap]]).
- Per-thread counters or queues that scale badly with more threads: suspect false sharing; pad or shard per thread and combine at the end.
- Database and cache servers on big machines: NUMA-aware placement or one instance per socket.
- NOT worth thinking about for code dominated by network or disk waits; fix those first ([[memory-and-performance]]).

## How it works / example

Row-major layout and why traversal order matters:

```
2D array stored row by row:  [r0c0 r0c1 r0c2 r0c3][r1c0 r1c1 ...]
                              <---- one cache line ---->
Row-wise loop:    r0c0 r0c1 r0c2 r0c3 ...  -> one miss, then hits on the same line
Column-wise loop: r0c0 r1c0 r2c0 ...       -> each access lands on a different line
```

Python objects add pointer indirection, so timing it in pure Python mostly measures the interpreter. A tiny direct-mapped cache simulator shows the effect deterministically:

```python
LINE = 64          # bytes per cache line
LINES = 64         # cache holds 64 lines (4 KiB), direct-mapped

def miss_rate(addresses):
    cache = [None] * LINES
    misses = 0
    for addr in addresses:
        line = addr // LINE
        slot = line % LINES
        if cache[slot] != line:
            misses += 1
            cache[slot] = line
    return misses / len(addresses)

ROWS, COLS, ELEM = 256, 256, 8          # 256x256 matrix of 8-byte values
addr = lambda r, c: (r * COLS + c) * ELEM

row_major = [addr(r, c) for r in range(ROWS) for c in range(COLS)]
col_major = [addr(r, c) for c in range(COLS) for r in range(ROWS)]

print(f"row-wise miss rate:    {miss_rate(row_major):.3f}")   # 1 miss per 8 elements
print(f"column-wise miss rate: {miss_rate(col_major):.3f}")   # every access misses
```

Array of structs vs struct of arrays (data-oriented layout):

```
AoS: [x y z vx vy vz][x y z vx vy vz]...   summing x drags y..vz into cache too
SoA: x: [x x x x ...]  y: [y y y ...] ...   summing x streams one dense array
```

False sharing and the fix:

```
counter_a | counter_b   <- same 64-byte line, two threads writing: line ping-pongs
counter_a | pad... | counter_b | pad...  <- each counter on its own line
or: each thread counts locally, merge once at the end
```

## Trade-offs
- **AoS vs SoA:** SoA is fast for column-style scans and SIMD; AoS is better when you touch all fields of one record together and keeps code simpler.
- **Padding vs memory:** padding to cache-line size removes false sharing but multiplies memory per item; use it only for a few hot, contended fields.
- **Compact representations vs CPU work:** compression and bit-packing fit more in cache at the cost of decode work; often a win for scans.
- **Blocking/tiling:** reorganizing loops into cache-sized tiles (matrix multiply) helps a lot but makes code harder to read; libraries (BLAS, numpy) already do it.
- **Huge pages:** fewer TLB misses for big heaps, but more memory waste and allocation latency; some databases recommend disabling transparent huge pages, check yours.

## Gotchas
- Benchmarks with a small working set fit in cache and overstate production speed; test with realistic data sizes.
- Python lists hold pointers to boxed objects, so "contiguous" Python data is not contiguous in memory; use `array`, `bytes`, numpy or a columnar library for dense data.
- Linked lists, trees of small nodes and hash maps with chaining scatter nodes across the heap; the asymptotic win can vanish for small n ([[big-o-complexity]]).
- Power-of-two strides (matrix widths of 1024, 4096) can cause conflict misses; padding a row breaks the pattern.
- Adding threads to a memory-bandwidth-bound loop does not speed it up once bandwidth is saturated.
- Cache sizes, line sizes and latencies vary by CPU generation and cloud instance type; measure on the target hardware.
- A process migrating between cores or sockets loses its warm cache; pinning can help latency-critical services.

## Related
- [[memory-and-performance]] - profiling first, then applying locality fixes where they matter
- [[core-data-structures]] - representation choices and their locality
- [[big-o-complexity]] - where constant factors from the hierarchy overturn asymptotics
- [[concurrency-and-parallelism]] - false sharing and contention in multithreaded code
- [[processes-threads-and-io-models]] - context switches and their cache cost
- [[caching-strategies]] - the same hit/miss/eviction ideas at the application level
- [[data-warehousing-and-olap]] - columnar storage as locality at the storage layer

## References
- Bryant and O'Hallaron, "Computer Systems: A Programmer's Perspective", ch. 6
- Drepper, "What Every Programmer Should Know About Memory" (2007)
- Hennessy and Patterson, "Computer Architecture: A Quantitative Approach"
- Intel 64 and IA-32 Architectures Optimization Reference Manual (cache line size, false sharing)
