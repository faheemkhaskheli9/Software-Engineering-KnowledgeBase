---
title: Graph databases
category: data
tags: [graph-database, property-graph, rdf, neo4j, cypher, gremlin, gql, sparql, recursive-cte, traversal, supernode]
use_cases:
  - "find friends-of-friends, shared connections or the shortest path between two users"
  - "detect fraud rings where accounts share devices, cards or addresses several hops apart"
  - "decide whether Postgres with recursive queries is enough or we need Neo4j"
  - "model an org chart, bill of materials or permission hierarchy of unknown depth"
status: draft
last_verified: 2026-10-11
sources:
  - "Ian Robinson, Jim Webber, Emil Eifrem, Graph Databases, 2nd ed. (O'Reilly, 2015), ch. 6 'Graph Database Internals'"
  - https://neo4j.com/docs/getting-started/graph-database/
  - https://tinkerpop.apache.org/gremlin.html
  - https://www.w3.org/TR/rdf11-concepts/
  - https://www.gqlstandards.org/
  - https://www.postgresql.org/docs/current/queries-with.html
  - https://www.sqlite.org/lang_with.html
---

# Graph databases

## Summary
A graph database stores entities as nodes and relationships as first-class
edges, and answers queries by walking edges (traversal) instead of joining
tables. It pays off when the question is about paths and neighbourhoods of
variable depth: "who is within three hops", "how are these two accounts
connected". For shallow or occasional traversals, a relational database with
recursive CTEs does the same job without a second system.

## Key concepts
- **Property graph**: nodes with labels and key-value properties, relationships with a type, a direction, a start and an end node, and their own properties (Neo4j's model; also the model of the ISO GQL standard, ISO/IEC 39075:2024).
- **RDF**: data as a set of triples, "each consisting of a subject, a predicate and an object" (W3C RDF 1.1), identified by IRIs and queried with SPARQL. Suits linked data, shared vocabularies and inference across sources; property graphs suit application data with attributes on edges.
- **Index-free adjacency**: in a native graph store each node record points directly at its relationships, so following an edge costs a pointer hop rather than an index lookup; traversal cost depends on the part of the graph touched, not total graph size (Robinson et al., ch. 6). Non-native graph layers on top of other stores use index lookups per hop instead.
- **Traversal languages**: Cypher / GQL are declarative pattern matching (`MATCH (a)-[:KNOWS*1..2]->(b)`); Gremlin (Apache TinkerPop) is a step-by-step traversal language that runs as an OLTP query or a batch OLAP job; SPARQL for RDF.
- **Recursive CTE**: `WITH RECURSIVE` in Postgres, SQLite, MySQL 8 and others expresses the same reachability in SQL; it iterates a working table until no new rows appear.
- **Supernode**: a node with a huge number of edges (a celebrity account, a default category, a shared office IP). Any traversal that passes through it fans out to everything it touches.
- **Partitioning difficulty**: a graph has no natural shard key; any cut leaves edges crossing shards, and multi-hop queries then become network round trips per hop.

## When to use / scenarios
- **Graph database fits**: traversals of unknown or variable depth are the main workload (fraud rings, recommendations from co-purchase or social graphs, network and dependency impact analysis, identity resolution, knowledge graphs), the schema of relationships keeps changing, and you need path results (not just aggregates).
- **Relational with recursive CTE is enough** when: depth is bounded and small (org chart, category tree, two-hop friends), traversals are a minority of queries next to normal CRUD and reporting, the graph fits one node, and you want transactions with the rest of your data. Add an index on `(src, dst)` and bound the depth.
- **Graph algorithms in batch** (PageRank, community detection over the whole graph) often belong in an analytics job over an exported edge list rather than in the OLTP store ([[graph-algorithms]], [[batch-and-stream-processing]]).
- **Not a graph problem**: one-hop lookups ("orders of customer 42") are ordinary foreign-key joins; a graph store adds nothing.

## How it works / example
The same question in Cypher, Gremlin and SQL:

```
// Cypher: people within two hops of Ann, not Ann herself
MATCH (a:Person {name: 'ann'})-[:KNOWS*1..2]-(p:Person)
WHERE p <> a
RETURN DISTINCT p.name

// Gremlin
g.V().has('Person','name','ann').as('a').
  repeat(both('KNOWS')).emit().times(2).where(neq('a')).dedup().values('name')
```

SQL with a recursive CTE, checked against a breadth-first search in Python. The
CTE returns each reachable person with their shortest hop count; BFS computes
the same from an adjacency list.

```python
import sqlite3
from collections import deque

edges = [("ann", "bob"), ("bob", "cat"), ("cat", "dan"), ("ann", "eve"),
         ("eve", "cat"), ("dan", "fay"), ("bob", "ann")]

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE knows (src TEXT, dst TEXT, PRIMARY KEY (src, dst))")
db.executemany("INSERT OR IGNORE INTO knows VALUES (?, ?)",
               edges + [(b, a) for a, b in edges])           # store both directions

SQL = """
WITH RECURSIVE reach(person, depth) AS (
    SELECT :start, 0
    UNION                                   -- UNION drops repeated (person, depth) rows
    SELECT k.dst, r.depth + 1
    FROM reach r JOIN knows k ON k.src = r.person
    WHERE r.depth < :max_depth              -- the depth bound is what stops cycles
)
SELECT person, MIN(depth) FROM reach
WHERE person <> :start
GROUP BY person
"""

def sql_reach(start, max_depth):
    return dict(db.execute(SQL, {"start": start, "max_depth": max_depth}))

def bfs_reach(start, max_depth):
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    dist, queue = {start: 0}, deque([start])
    while queue:
        node = queue.popleft()
        if dist[node] == max_depth:
            continue
        for nxt in adj.get(node, ()):
            if nxt not in dist:              # visited set: each node expanded once
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
    del dist[start]
    return dist

for depth in (1, 2, 3, 4):
    assert sql_reach("ann", depth) == bfs_reach("ann", depth)

two_hops = sql_reach("ann", 2)
assert two_hops == {"bob": 1, "eve": 1, "cat": 2}
friends_of_friends = {p for p, d in two_hops.items() if d == 2}
assert friends_of_friends == {"cat"}         # reachable in 2 hops, not a direct friend
assert sql_reach("ann", 4)["fay"] == 4
```

Note the difference in work done: BFS keeps a global visited set, so each node
is expanded once. The CTE only removes identical `(person, depth)` rows, so it
re-expands a node once per depth at which it is reached; on a dense graph the
row count grows with the number of paths, which is why the depth bound (or
Postgres's `CYCLE` clause) is mandatory.

## Trade-offs
- **One database vs two**: Postgres with recursive CTEs keeps transactions, backups and joins in one place; a graph store adds a sync pipeline from the system of record ([[event-driven-architecture]]) and another system to operate, in return for faster and more expressive deep traversals.
- **Property graph vs RDF**: property graphs are simpler for application data with attributes on edges; RDF gives global identifiers, standard vocabularies and reasoning across datasets at the cost of verbosity.
- **Declarative (Cypher/GQL) vs imperative (Gremlin)**: declarative lets the planner choose the order; Gremlin gives explicit control and runs on many TinkerPop-compatible backends.
- **Single node vs distributed graph**: one large node keeps traversals local and fast; sharding gives capacity but turns hops into network calls, so partition along communities (tenant, region) when the data allows it ([[partitioning-and-sharding]]).

## Gotchas
- Unbounded variable-length patterns (`[:KNOWS*]`) on a connected graph can touch most of the database. Always bound depth and `LIMIT` results.
- Supernodes dominate latency and lock contention. Model around them: split by time or type, skip them in traversals, or turn "everyone follows X" into a property rather than millions of edges.
- Recursive CTEs without a depth bound or cycle check loop until they run out of rows or memory when the graph has a cycle; SQLite also notes its default FIFO (breadth-first) queue order is not guaranteed.
- `UNION` vs `UNION ALL` matters: with a depth column, rows are never exact duplicates, so `UNION` alone does not stop cycles (PostgreSQL docs).
- Picking a graph database because the domain diagram looks like a graph. Most domains do; what matters is whether the queries are multi-hop.
- Graph stores are usually poor at large scans and aggregations ("revenue by month"); keep those in the relational or analytics store.

## Related
- [[graph-algorithms]] - BFS, shortest paths and components that traversal queries implement
- [[core-data-structures]] - adjacency lists, the in-memory form of index-free adjacency
- [[data-modeling-and-schema-design]] - modelling hierarchies and many-to-many links relationally first
- [[database-indexing]] - indexing `(src, dst)` edge tables for recursive queries
- [[partitioning-and-sharding]] - why graphs shard badly
- [[sql-vs-nosql]] - where graph stores sit among database families
- [[choosing-a-database]] - when traversals justify a separate store
- [[time-series-databases]] - another specialised store to justify against plain Postgres
- [[vector-databases-for-engineers]] - similarity search, a different "related items" mechanism
- See also (AI KB): [GraphRAG and knowledge graphs](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/graphrag-and-knowledge-graphs.md) - LLM-built knowledge graphs used for retrieval.

## References
- Ian Robinson, Jim Webber, Emil Eifrem, *Graph Databases*, 2nd ed., O'Reilly, 2015, ch. 6 "Graph Database Internals" (native storage, index-free adjacency).
- Neo4j, "What is a graph database": https://neo4j.com/docs/getting-started/graph-database/
- Apache TinkerPop, Gremlin: https://tinkerpop.apache.org/gremlin.html
- W3C, RDF 1.1 Concepts and Abstract Syntax: https://www.w3.org/TR/rdf11-concepts/
- GQL standard (ISO/IEC 39075:2024): https://www.gqlstandards.org/
- PostgreSQL, WITH queries (recursive evaluation, SEARCH and CYCLE): https://www.postgresql.org/docs/current/queries-with.html
- SQLite, WITH clause (recursive CTE queue order): https://www.sqlite.org/lang_with.html
