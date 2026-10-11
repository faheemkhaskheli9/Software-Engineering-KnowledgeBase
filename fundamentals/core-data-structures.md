---
title: Core data structures and when to pick each
category: fundamentals
tags: [data-structures, hash-table, heap, tree, graph, queue, array, trie, bloom-filter]
use_cases:
  - "choose a container for a lookup-heavy hot path that also needs ordered iteration"
  - "implement a task scheduler that always runs the earliest-deadline job next"
  - "check whether a username or URL was already seen without storing every key"
  - "build autocomplete suggestions over a few million strings"
  - "model dependencies between build steps and find a valid execution order"
status: stable
last_verified: 2026-10-10
sources:
  - "Introduction to Algorithms (CLRS), Cormen et al."
  - "Designing Data-Intensive Applications, Martin Kleppmann, chapter 3 (storage structures)"
  - "https://docs.python.org/3/library/collections.html"
  - "https://docs.python.org/3/library/heapq.html"
---

# Core data structures and when to pick each

## Summary
Most performance and correctness problems at the code level reduce to picking the wrong container. This note maps requirements ("fast lookup", "ordered", "smallest first", "have I seen this") to the structure that fits, with the Python tool for each and the costs that matter.

## Key concepts
- **Access pattern drives the choice.** Ask: lookup by key, by position, by order, or by priority? Insert/delete where? Need sorted iteration? Range queries?
- **Array / dynamic array (`list`)**: O(1) index, O(1) amortized append, O(n) insert/delete in the middle. Contiguous memory is cache-friendly.
- **Hash table (`dict`, `set`)**: O(1) average lookup, insert, delete; no ordering by key (Python dicts keep insertion order). Needs hashable, immutable keys.
- **Linked list**: O(1) splice given a node, O(n) search. Rarely the right answer in Python; `collections.deque` covers queue/stack needs.
- **Stack (LIFO) / queue (FIFO) / deque**: `list` for a stack, `collections.deque` for queues (O(1) at both ends; `list.pop(0)` is O(n)).
- **Heap / priority queue (`heapq`)**: O(log n) push and pop-min, O(1) peek. Not sorted overall, only the root is guaranteed.
- **Balanced search tree (B-tree, red-black, skip list)**: O(log n) ordered operations, range scans. Python has no stdlib one; `bisect` on a sorted list gives O(log n) search with O(n) insert, fine for read-mostly data. Databases use B-trees; see [[database-indexing]].
- **Trie**: prefix lookups in O(length of key), independent of the number of keys. Autocomplete, routing tables.
- **Graph**: adjacency list (`dict[node, list[node]]`) for sparse graphs, adjacency matrix for dense. BFS/DFS in O(V + E).
- **Union-Find (disjoint set)**: near O(1) "are these connected" and merge. Connected components, Kruskal.
- **Probabilistic structures**: Bloom filter (membership with false positives, no false negatives), HyperLogLog (approximate distinct count), Count-Min Sketch (approximate frequency). Trade exactness for tiny memory.

## When to use / scenarios

| Need | Use |
|---|---|
| Lookup by key | `dict` |
| Membership / dedupe | `set` |
| Ordered iteration by key plus fast insert | sorted structure (B-tree, skip list; `sortedcontainers.SortedDict` if a dependency is OK) |
| FIFO work queue | `collections.deque` |
| Next-smallest / top-k | `heapq` |
| Prefix search | trie |
| Relationships, dependencies, routes | graph + BFS/DFS/Dijkstra, topological sort |
| "Probably seen before" on huge streams | Bloom filter |
| LRU cache | `OrderedDict` or `functools.lru_cache` |
| Count things | `collections.Counter` |

Avoid fancy structures when n is small. A list of 30 items scanned linearly is fine and clearer.

## How it works / example

Priority queue for a scheduler (earliest deadline first):

```python
import heapq

jobs = []
heapq.heappush(jobs, (1700000300, "send-report"))
heapq.heappush(jobs, (1700000100, "refresh-cache"))
heapq.heappush(jobs, (1700000200, "cleanup"))
while jobs:
    deadline, name = heapq.heappop(jobs)   # always the smallest deadline
    print(name)                            # refresh-cache, cleanup, send-report
```

Top-k without sorting everything, O(n log k):

```python
import heapq
top3 = heapq.nlargest(3, [5, 1, 9, 3, 7, 8])   # [9, 8, 7]
```

Topological order of dependencies (graph + BFS, Kahn's algorithm):

```python
from collections import defaultdict, deque

def topo(edges):
    g, indeg = defaultdict(list), defaultdict(int)
    nodes = set()
    for a, b in edges:             # a must come before b
        g[a].append(b); indeg[b] += 1; nodes |= {a, b}
    q = deque(n for n in nodes if indeg[n] == 0)
    out = []
    while q:
        n = q.popleft(); out.append(n)
        for m in g[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(out) != len(nodes):
        raise ValueError("cycle detected")
    return out

assert topo([("compile", "test"), ("test", "package")]) == ["compile", "test", "package"]
```

A minimal Bloom filter (membership with tunable false positives):

```python
import hashlib

class Bloom:
    def __init__(self, m=1 << 20, k=4):
        self.m, self.k, self.bits = m, k, bytearray(m // 8)
    def _idx(self, item):
        for i in range(self.k):
            h = hashlib.blake2b(f"{i}:{item}".encode(), digest_size=8).digest()
            yield int.from_bytes(h, "big") % self.m
    def add(self, item):
        for i in self._idx(item):
            self.bits[i // 8] |= 1 << (i % 8)
    def __contains__(self, item):
        return all(self.bits[i // 8] >> (i % 8) & 1 for i in self._idx(item))
```

Trie sketch: each node is a `dict[char, node]` plus an `end` flag; insert and prefix walk are O(len(word)).

## Trade-offs
- **Hash table vs sorted tree:** hash is faster for point lookups; tree gives order, range scans and predictable worst case. If you ever need "all keys between a and b", you need ordering.
- **Array vs linked structures:** arrays win on cache locality and memory overhead even when theory says linked is better. Prefer arrays until measured otherwise.
- **Exact vs probabilistic:** a Bloom filter in front of a database or cache avoids expensive misses; accept a known false-positive rate and no deletes (use a counting or cuckoo filter if you need deletion).
- **Adjacency list vs matrix:** list is O(V + E) memory; matrix O(V^2) but O(1) edge test. Dense, small graphs only.
- **Memory vs speed:** indexes, memo tables and tries consume memory; know the budget; see [[memory-and-performance]].

## Gotchas
- Mutable objects (lists) cannot be dict keys; convert to `tuple` or `frozenset`.
- Modifying a dict or list while iterating it raises or skips elements; iterate over a copy.
- `heapq` is a min-heap and compares whole tuples; ties fall through to the next element, which may be unorderable (use `(priority, counter, item)`).
- Floating-point keys and NaN behave badly in hash tables.
- Default-dict and `dict.get` patterns hide missing-key bugs; decide whether a missing key is an error.
- A hash table with adversarial keys degrades to O(n); do not roll your own hash for untrusted input.
- Bloom filters cannot be resized or have items removed; size them for the expected item count up front.
- Python `list` of 10M small ints is far heavier than `array.array` or numpy; see [[memory-and-performance]].

## Related
- [[big-o-complexity]] - the cost model behind every choice here
- [[algorithm-patterns]] - algorithms that operate on these structures
- [[database-indexing]] - B-trees and hash indexes on disk
- [[caching-strategies]] - LRU and eviction structures in practice
- [[consistent-hashing]] - hash ring as a distributed data structure
- [[graph-algorithms]] - what to run on a graph once you have built one
- [[strings-and-text-encoding]] - strings as bytes, code points and graphemes
- [[design-search-autocomplete]] - case study: tries and top-k heaps in a typeahead service

## References
- CLRS, "Introduction to Algorithms", 4th ed.
- Kleppmann, "Designing Data-Intensive Applications", ch. 3
- Python docs: collections, heapq, bisect
