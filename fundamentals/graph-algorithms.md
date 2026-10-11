---
title: Graph algorithms
category: fundamentals
tags: [graphs, bfs, dfs, topological-sort, union-find, shortest-path, minimum-spanning-tree, strongly-connected-components, cycle-detection]
use_cases:
  - "order build steps, migrations or tasks that depend on each other"
  - "detect a circular dependency between packages or services"
  - "find the cheapest or fastest route between two locations"
  - "group users or accounts that are linked into clusters"
  - "decide whether a problem is really a graph problem and which algorithm fits"
status: draft
last_verified: 2026-10-10
sources:
  - "Introduction to Algorithms (CLRS), Cormen, Leiserson, Rivest, Stein - Part VI, Graph Algorithms"
  - "Algorithms, 4th ed., Sedgewick and Wayne - ch. 4, Graphs"
  - "Depth-first search and linear graph algorithms, Robert Tarjan, SIAM J. Computing, 1972"
  - "A Formal Basis for the Heuristic Determination of Minimum Cost Paths, Hart, Nilsson, Raphael, 1968"
  - "Python graphlib docs - https://docs.python.org/3/library/graphlib.html"
---

# Graph algorithms

## Summary
Many engineering problems are graphs in disguise: dependencies, networks, routes, social links, state transitions. A small toolkit covers most of them: BFS and DFS for reachability, layering and cycles; topological sort for dependency order; union-find for dynamic connectivity; Dijkstra, Bellman-Ford and A* for shortest paths; Kruskal or Prim for minimum spanning trees; Tarjan or Kosaraju for strongly connected components. Recognize the shape, then reuse a known algorithm instead of inventing one.

## Key concepts
- **Graph:** vertices V and edges E; directed or undirected; weighted or unweighted. Store sparse graphs as adjacency lists ([[core-data-structures]]).
- **BFS:** explores in layers from a source; gives fewest-edge paths in unweighted graphs. O(V + E).
- **DFS:** goes deep first; the basis for cycle detection, topological sort, connected and strongly connected components. O(V + E).
- **Topological sort:** linear order of a DAG where every edge points forward. Kahn's algorithm (repeatedly remove zero in-degree nodes) or DFS post-order. Fails exactly when there is a cycle.
- **Cycle detection:** directed graphs: DFS with three colors (white/gray/black), a gray-to-gray edge is a back edge. Undirected graphs: union-find, or DFS ignoring the parent edge.
- **Union-find (disjoint set union):** merge sets and ask "same set?" in nearly constant amortized time with path compression and union by rank.
- **Shortest paths:**
  - *Dijkstra:* non-negative weights, O((V + E) log V) with a binary heap.
  - *Bellman-Ford:* handles negative weights and detects negative cycles, O(V * E).
  - *A\*:* Dijkstra plus an admissible heuristic toward a target; the norm for maps and games.
  - *Floyd-Warshall:* all pairs, O(V^3); only for small dense graphs.
- **Minimum spanning tree:** cheapest set of edges connecting all vertices of an undirected weighted graph. Kruskal (sort edges + union-find) or Prim (heap).
- **Strongly connected components (SCC):** maximal sets where every vertex reaches every other; condensing SCCs turns any directed graph into a DAG.
- **Bipartite check:** 2-color with BFS; fails on an odd cycle.
- **Max flow / min cut:** capacity problems (matching, assignment); Ford-Fulkerson family. Usually reach for a library.

## When to use / scenarios

| Problem | Algorithm |
|---|---|
| Build order, migration order, task scheduling | topological sort (`graphlib.TopologicalSorter`) |
| "Is there a circular import or dependency?" | DFS cycle detection or failed topological sort |
| Fewest hops (degrees of separation, minimal retries) | BFS |
| Route by cost/time with non-negative weights | Dijkstra; A* with a target and a good heuristic |
| Weights can be negative (arbitrage, credits) | Bellman-Ford |
| Merge linked accounts, entity resolution, network partitions | union-find |
| Cheapest network to connect sites | Kruskal or Prim |
| Mutually dependent modules to break apart | SCC, then work on the condensed DAG |

- NOT for huge graphs that do not fit in memory: use a graph database or a distributed engine, and expect different algorithms (approximate, iterative, partitioned) ([[partitioning-and-sharding]]).
- Production libraries (networkx, igraph, a database's recursive CTEs) beat hand-written code once the graph is real; the examples show the mechanics.

## How it works / example

Dependency order with the stdlib (raises `CycleError` on a cycle):

```python
from graphlib import TopologicalSorter, CycleError

deps = {"app": {"db", "cache"}, "db": {"config"}, "cache": {"config"}, "config": set()}
print(list(TopologicalSorter(deps).static_order()))   # config first, app last

try:
    list(TopologicalSorter({"a": {"b"}, "b": {"a"}}).static_order())
except CycleError as e:
    print("cycle:", e.args[1])
```

Directed cycle detection with three-color DFS (iterative, so deep graphs do not hit the recursion limit):

```python
def has_cycle(graph):                       # graph: {node: [neighbors]}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    for start in graph:
        if color[start] != WHITE:
            continue
        stack = [(start, iter(graph[start]))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK          # all descendants done
                stack.pop()
            elif color.get(nxt, WHITE) == GRAY:
                return True                  # back edge
            elif color.get(nxt, WHITE) == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(graph.get(nxt, []))))
    return False

assert has_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
assert not has_cycle({"a": ["b", "c"], "b": ["c"], "c": []})
```

Union-find for grouping linked records, and Kruskal's MST on top of it:

```python
class DSU:
    def __init__(self):
        self.parent, self.rank = {}, {}
    def find(self, x):
        self.parent.setdefault(x, x); self.rank.setdefault(x, 0)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]   # path halving
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.rank[ra] += self.rank[ra] == self.rank[rb]
        return True

# accounts sharing an email or phone belong to one person
d = DSU()
for a, b in [("acct1", "acct2"), ("acct3", "acct4"), ("acct2", "acct5")]:
    d.union(a, b)
print(d.find("acct1") == d.find("acct5"), d.find("acct1") == d.find("acct3"))  # True False

def kruskal(edges):                          # edges: [(weight, u, v)]
    dsu, tree = DSU(), []
    for w, u, v in sorted(edges):
        if dsu.union(u, v):
            tree.append((u, v, w))
    return tree

print(kruskal([(4, "A", "B"), (1, "B", "C"), (3, "A", "C"), (2, "C", "D")]))
```

Bellman-Ford with negative-cycle detection:

```python
def bellman_ford(nodes, edges, src):         # edges: [(u, v, w)]
    dist = {n: float("inf") for n in nodes}
    dist[src] = 0
    for _ in range(len(nodes) - 1):
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            raise ValueError("negative cycle")
    return dist

print(bellman_ford("ABC", [("A", "B", 4), ("A", "C", 5), ("C", "B", -2)], "A"))  # B = 3 via C
```

Dijkstra with a heap is in [[algorithm-patterns]]; Kahn's algorithm by hand is in [[core-data-structures]].

## Trade-offs
- **BFS vs DFS:** BFS finds shortest unweighted paths but keeps a wide frontier; DFS uses memory proportional to depth and gives the structure (back edges, finish order) that cycle and SCC algorithms need.
- **Dijkstra vs A\*:** A* explores fewer nodes when the heuristic is good and admissible; a non-admissible heuristic is faster but can return non-optimal paths.
- **Dijkstra vs Bellman-Ford:** Dijkstra is much faster but wrong with negative edges; Bellman-Ford is slower but detects negative cycles.
- **Kruskal vs Prim:** Kruskal is simple with an edge list and union-find, good for sparse graphs; Prim with a heap suits dense graphs or adjacency lists.
- **Adjacency list vs matrix vs database:** in-memory lists are fastest for algorithms; a graph or relational DB (recursive CTEs) handles persistence and size but makes multi-hop traversals costly.

## Gotchas
- Recursive DFS in Python hits the recursion limit on deep graphs; use an explicit stack.
- Dijkstra with negative edges gives wrong answers silently, it does not error.
- Topological sort on a graph with a cycle: Kahn's algorithm quietly returns fewer nodes than exist; check the count (or use `graphlib`, which raises).
- Undirected cycle detection that does not skip the parent edge reports every edge as a cycle.
- Mutable default or shared `visited` sets across calls leak state between traversals.
- Unbounded BFS on a social or web graph explodes; cap depth or frontier size ([[design-web-crawler]]).
- Edge direction conventions ("A depends on B" vs "B must run before A") flip the order; write it down.

## Related
- [[algorithm-patterns]] - graph search as one pattern among many, with Dijkstra
- [[core-data-structures]] - adjacency lists, heaps and Kahn's topological sort
- [[big-o-complexity]] - the O(V + E) and heap-based costs above
- [[design-web-crawler]] - BFS over the web graph at scale
- [[design-ride-sharing]] - shortest paths and routing on road graphs
- [[state-machines]] - a state machine is a directed graph of states and transitions
- [[graph-databases]] - running traversals inside a database (Cypher, Gremlin, recursive CTE)

## References
- Cormen, Leiserson, Rivest, Stein, "Introduction to Algorithms", Part VI
- Sedgewick and Wayne, "Algorithms", 4th ed., ch. 4
- Tarjan, "Depth-first search and linear graph algorithms" (1972)
- Hart, Nilsson, Raphael, "A Formal Basis for the Heuristic Determination of Minimum Cost Paths" (1968)
- Python docs: graphlib
