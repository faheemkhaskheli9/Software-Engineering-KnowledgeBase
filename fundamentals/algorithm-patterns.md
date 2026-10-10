---
title: Algorithm patterns (reusable problem-solving techniques)
category: fundamentals
tags: [algorithms, two-pointers, sliding-window, binary-search, dynamic-programming, recursion, graph-search, greedy]
use_cases:
  - "find the longest stretch of log lines meeting a condition without rescanning everything"
  - "search a monotonic answer space, like the minimum capacity that meets a deadline"
  - "compute the cheapest route or minimum edit distance without exponential blowup"
  - "merge or deduplicate large sorted datasets efficiently"
  - "decide whether a problem needs DP, greedy or brute force"
status: draft
last_verified: 2026-10-10
sources:
  - "Introduction to Algorithms (CLRS), Cormen et al."
  - "The Algorithm Design Manual, Steven Skiena"
  - "Algorithms, Sedgewick and Wayne - https://algs4.cs.princeton.edu/"
---

# Algorithm patterns

## Summary
Most practical algorithm problems are variations on a dozen patterns. Recognizing the pattern (windows, pointers, binary search on an answer, DP, graph search, greedy) turns an O(n^2) or exponential brute force into O(n) or O(n log n). This note lists the patterns, the signals that suggest them and a minimal template for each.

## Key concepts
- **Brute force first, then ask which work is repeated.** Repeated work is removed by sorting, hashing, windows or memoization.
- **Two pointers:** two indices moving through sorted data or from both ends. Turns pair searches from O(n^2) into O(n).
- **Sliding window:** maintain a running aggregate over a contiguous range, add the new element, drop the oldest. Contiguous subarray/substring questions.
- **Prefix sums:** precompute cumulative totals so any range sum is O(1).
- **Binary search:** works whenever a predicate is monotonic (false...false true...true), not only on sorted arrays. "Binary search on the answer".
- **Hash map for complement/counting:** one pass with a dict replaces a nested loop (two-sum, group-by, frequency).
- **Divide and conquer:** split, solve halves, combine (merge sort, quickselect).
- **Dynamic programming:** overlapping subproblems plus optimal substructure. Define state, transition, base case; memoize (top-down) or fill a table (bottom-up).
- **Greedy:** locally optimal choice is globally optimal (interval scheduling, Huffman, Dijkstra). Needs a proof; without one, suspect DP.
- **Graph search:** BFS for fewest hops in unweighted graphs, DFS for reachability/cycles/components, Dijkstra for non-negative weights, topological sort for DAG ordering.
- **Backtracking:** enumerate choices with pruning (permutations, N-queens, constraint satisfaction). Exponential in the worst case; pruning is everything.

## When to use / scenarios
- "Longest/shortest contiguous X satisfying Y": sliding window.
- "Pair/triple that sums to...", sorted input, dedupe: two pointers or hashing.
- "Minimum value such that a feasibility check passes" (capacity, rate, batch size): binary search on the answer.
- "Count/minimize/maximize over choices, with repeated subproblems": DP.
- "Fewest steps", "shortest path", "connected": graph search.
- "Top k", "k-th largest", streaming median: heaps; see [[core-data-structures]].
- NOT worth it when n is tiny; clarity beats cleverness. Also not for I/O-bound code, see [[memory-and-performance]].

## How it works / example

Sliding window: longest substring without repeating characters, O(n).

```python
def longest_unique(s):
    last, start, best = {}, 0, 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1          # shrink window past the duplicate
        last[ch] = i
        best = max(best, i - start + 1)
    return best

assert longest_unique("abcabcbb") == 3
```

Binary search on the answer: smallest worker count that finishes tasks by a deadline.

```python
def min_workers(task_minutes, deadline):
    def feasible(w):                      # monotonic: more workers never hurts
        loads = [0] * w
        for t in sorted(task_minutes, reverse=True):
            i = loads.index(min(loads))   # greedy assignment
            loads[i] += t
        return max(loads) <= deadline
    lo, hi = 1, len(task_minutes)
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible(mid): hi = mid
        else: lo = mid + 1
    return lo
```

Dynamic programming: edit distance, O(m*n) time, O(n) space.

```python
def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,            # delete
                           cur[j - 1] + 1,         # insert
                           prev[j - 1] + (ca != cb)))  # substitute
        prev = cur
    return prev[-1]

assert edit_distance("kitten", "sitting") == 3
```

Memoized recursion (top-down DP) with the stdlib:

```python
from functools import lru_cache

@lru_cache(maxsize=None)
def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)   # O(n) instead of O(2^n)
```

Dijkstra with a heap, O((V + E) log V):

```python
import heapq

def dijkstra(graph, src):                 # graph: {u: [(v, weight), ...]}
    dist, pq = {src: 0}, [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue                      # stale entry
        for v, w in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist
```

Choosing pattern quickly:

```
sorted / pairs?        -> two pointers, binary search
contiguous range?      -> sliding window, prefix sums
count / lookup?        -> hash map
optimal over choices?  -> DP (overlap) or greedy (provable)
relationships?         -> graph search
enumerate all?         -> backtracking + pruning
```

## Trade-offs
- **Memoization vs bottom-up DP:** top-down is easier to write and only computes needed states; bottom-up avoids recursion limits and allows space optimization (rolling rows).
- **Greedy vs DP:** greedy is simpler and faster but wrong without a proof. Coin change with arbitrary denominations is the classic counterexample.
- **BFS vs DFS:** BFS gives shortest unweighted paths but holds a wide frontier in memory; DFS uses less memory but can recurse deeply.
- **Exact vs approximate:** NP-hard problems (traveling salesman, bin packing) are solved with heuristics or solvers, not clever DP, at scale.
- **Readability vs speed:** an O(n^2) solution on 1,000 items that is obvious usually beats an opaque O(n log n) one.

## Gotchas
- Binary search off-by-one errors: fix the invariant (`lo` is infeasible/`hi` is feasible) and use `mid = lo + (hi - lo) // 2` in fixed-width languages. Python has `bisect`.
- Sliding window needs the window state to be updatable in O(1); if you need a min/max of the window use a monotonic deque.
- DP state that includes too much (e.g. whole lists) explodes; the state must be small and hashable.
- Dijkstra fails with negative edges; use Bellman-Ford. BFS fails on weighted graphs.
- Recursive DFS on deep graphs hits Python's recursion limit; use an explicit stack.
- Floating-point equality in binary search on real-valued answers: loop a fixed number of iterations or until a tolerance.
- Sorting first changes the problem if original positions matter; keep indices.

## Related
- [[big-o-complexity]] - how to know a pattern actually improved the bound
- [[core-data-structures]] - heaps, graphs, tries these patterns rely on
- [[concurrency-and-parallelism]] - divide and conquer maps onto parallel map-reduce
- [[property-based-and-fuzz-testing]] - checking an optimized algorithm against a brute-force oracle
- [[consistent-hashing]] - a pattern combining hashing and binary search on a ring
- [[graph-algorithms]] - the full graph toolkit: topological sort, union-find, Bellman-Ford, MST, SCC

## References
- CLRS, "Introduction to Algorithms", 4th ed.
- Skiena, "The Algorithm Design Manual", 3rd ed.
- Sedgewick and Wayne, "Algorithms", 4th ed.: https://algs4.cs.princeton.edu/
