---
title: Big-O complexity and cost analysis
category: fundamentals
tags: [big-o, complexity, algorithms, performance, amortized-analysis, scalability]
use_cases:
  - "figure out why this endpoint gets slower as the table grows and what complexity class the code is in"
  - "pick between a list scan, a set lookup and a sorted index for a membership check"
  - "review a pull request for accidental quadratic behavior in a loop"
  - "estimate whether a nightly job over 100M rows can finish in its time window"
status: stable
last_verified: 2026-10-10
sources:
  - "Introduction to Algorithms (CLRS), Cormen, Leiserson, Rivest, Stein - chapters 3 and 17 (amortized analysis)"
  - "The Algorithm Design Manual, Steven Skiena"
  - "https://wiki.python.org/moin/TimeComplexity"
---

# Big-O complexity and cost analysis

## Summary
Big-O describes how the cost (time or memory) of an operation grows with input size n, ignoring constants and lower-order terms. It is the fastest way to predict whether code that works on 1,000 rows will survive 10 million, and to spot accidental O(n^2) in reviews. It is a model of growth, not a stopwatch: constants, cache behavior and I/O still decide real speed for small n.

## Key concepts
- **Upper bound, usually worst case.** O(f(n)) means "grows no faster than f(n)". In practice people say it for the typical or worst case; state which.
- **Common classes, slow growth to fast:** O(1), O(log n), O(n), O(n log n), O(n^2), O(2^n), O(n!).
- **Drop constants and lower terms:** 3n^2 + 50n + 7 is O(n^2). But a constant of 1000x matters when comparing two O(n) options.
- **Multiple inputs get multiple variables:** nested loop over a (size n) and b (size m) is O(n*m), not O(n^2).
- **Amortized cost:** average over a sequence of operations. `list.append` is O(1) amortized though an occasional append copies the array.
- **Space complexity:** auxiliary memory used, counted the same way. Recursion depth counts (call stack).
- **Theta and Omega:** Theta is a tight bound, Omega a lower bound. Sorting by comparison is Omega(n log n).
- **Input size is bits for numbers:** an algorithm that loops up to N is exponential in the number of bits of N (pseudo-polynomial).

## When to use / scenarios
- Reviewing loops that call functions which hide their own loops (`x in list`, `str +=`, `list.pop(0)`, `sorted()` inside a loop).
- Choosing a data structure for a hot path; see [[core-data-structures]].
- Sanity-checking a design before building it: 10^9 simple ops is about seconds-to-tens-of-seconds in a compiled language, far worse in pure Python. Do the arithmetic, see [[back-of-envelope-estimation]].
- NOT the right tool when n is small and bounded (a 20-element list: just scan it), or when the cost is dominated by I/O, network round trips or lock contention. There, count round trips and measure; see [[memory-and-performance]] and [[orm-and-n-plus-one]].

## How it works / example

Growth table (operations for n items):

```
n        log n   n      n log n    n^2        2^n
10       3       10     33         100        1,024
1,000    10      1e3    1e4        1e6        astronomically large
1e6      20      1e6    2e7        1e12       --
```

Reading code:

```python
def has_duplicate_slow(items):          # O(n^2): inner `in` on list is O(n)
    seen = []
    for x in items:                     # n iterations
        if x in seen:                   # up to n comparisons
            return True
        seen.append(x)                  # O(1) amortized
    return False

def has_duplicate_fast(items):          # O(n) time, O(n) space
    seen = set()
    for x in items:
        if x in seen:                   # O(1) average (hashing)
            return True
        seen.add(x)
    return False

def has_duplicate_sorted(items):        # O(n log n) time, O(n) space for the copy
    s = sorted(items)
    return any(a == b for a, b in zip(s, s[1:]))
```

Rules of thumb for reading complexity:
1. Sequential blocks add: O(n) then O(n log n) is O(n log n).
2. Nested loops multiply.
3. Halving the problem each step (binary search) is log n; halving *and* doing linear work per level (merge sort) is n log n.
4. Recursion: write the recurrence. T(n) = 2T(n/2) + O(n) gives n log n (Master theorem). T(n) = T(n-1) + T(n-2) with no memoization gives exponential; memoize and it becomes O(n).
5. Hidden cost: string concatenation in a loop (`s += x`) may be O(n^2) in total in languages with immutable strings; use `"".join`.

Quick empirical check that complements analysis:

```python
import timeit
for n in (10_000, 20_000, 40_000):
    data = list(range(n))
    t = timeit.timeit(lambda: has_duplicate_slow(data), number=1)
    print(n, round(t, 3))   # doubling n should roughly quadruple t if O(n^2)
```

## Trade-offs
- **Time vs space:** hash sets and memo tables buy speed with memory. Pre-sorting and binary search buy lookups with an O(n log n) setup cost - worth it only if you query many times.
- **Asymptotics vs constants:** for small n, a linear scan over a contiguous array often beats a hash table or tree because of cache locality. Switch on measured data, not on the O notation alone.
- **Average vs worst case:** hash tables are O(1) average, O(n) worst (collisions or adversarial keys); quicksort is O(n log n) average, O(n^2) worst. Where input is attacker-controlled, prefer algorithms with guaranteed bounds (Python's Timsort, randomized hash seeds).
- **Amortized vs per-operation:** amortized O(1) can still produce a latency spike on the resize. Latency-sensitive systems may need pre-sizing or incremental rehashing.

## Gotchas
- `x in some_list`, `list.remove`, `list.insert(0, x)`, `list.pop(0)` are O(n). Use `set`, `dict`, `collections.deque`.
- Slicing and copying (`lst[1:]` in a recursive function) is O(n) each, turning an O(n) recursion into O(n^2).
- Database queries inside a loop are O(n) round trips, each far costlier than a CPU op. Complexity of the app code is irrelevant if each iteration is a network call.
- Big-O hides constants: O(n) with a regex per element can lose to O(n log n) with cheap comparisons.
- Sorting is not free inside a loop: `sorted()` in each iteration is O(n^2 log n) overall.
- Space complexity of recursion is often forgotten; deep recursion in Python hits the recursion limit long before memory runs out.
- Measuring only one input size cannot reveal complexity. Measure at least three sizes in geometric progression.

## Related
- [[core-data-structures]] - complexity of each operation per structure
- [[algorithm-patterns]] - techniques that cut a class (two pointers, memoization, binary search)
- [[memory-and-performance]] - when constants, caches and I/O override asymptotics
- [[back-of-envelope-estimation]] - turning complexity into time and capacity estimates
- [[orm-and-n-plus-one]] - the most common real-world accidental O(n) round trips

## References
- CLRS, "Introduction to Algorithms", 4th ed.
- Skiena, "The Algorithm Design Manual", 3rd ed.
- Python wiki, TimeComplexity: https://wiki.python.org/moin/TimeComplexity
