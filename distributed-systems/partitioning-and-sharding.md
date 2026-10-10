---
title: Partitioning and sharding
category: distributed-systems
tags: [sharding, partitioning, shard-key, hot-spots, rebalancing, range-partitioning, hash-partitioning, scatter-gather]
use_cases:
  - "our single database cannot handle the write volume, split the data across multiple nodes"
  - "choose a shard key for a multi-tenant SaaS or an orders table"
  - "one shard is overloaded by a celebrity user or hot key, fix the hot spot"
  - "add nodes to a sharded cluster without downtime or a massive data shuffle"
status: draft
last_verified: 2026-10-10
sources:
  - "Kleppmann, Designing Data-Intensive Applications, ch. 6 (Partitioning)"
  - "Vitess documentation https://vitess.io/docs/"
  - "MongoDB manual, Sharding https://www.mongodb.com/docs/manual/sharding/"
  - "Citus documentation, choosing a distribution column https://docs.citusdata.com/"
  - "Corbett et al., Spanner: Google's Globally-Distributed Database (OSDI 2012) https://research.google/pubs/spanner-googles-globally-distributed-database-2/"
---

# Partitioning and sharding

## Summary
Partitioning splits a dataset into disjoint pieces (partitions/shards), each stored on different nodes, so that storage, writes and queries scale beyond one machine. The decisive choices are the shard key and the placement scheme (range, hash, directory). A poor key gives hot spots and expensive cross-shard queries that no hardware fixes.

## Key concepts
- **Partition vs replica**: partitioning divides data; [[replication]] copies it. Production systems do both: each shard has its own replicas.
- **Range partitioning**: contiguous key ranges per shard (Bigtable, HBase, Spanner, MongoDB ranged). Great for range scans, prone to hot spots on monotonic keys (timestamps, auto-increment).
- **Hash partitioning**: hash(key) decides the shard. Even spread, destroys range-scan locality. Often via [[consistent-hashing]] or fixed hash slots (Redis Cluster uses 16384).
- **Directory/lookup partitioning**: a mapping table of key (or tenant) to shard. Flexible, but the directory is a dependency and bottleneck.
- **Composite keys**: hash the first part, range the rest (Cassandra partition key + clustering key). Spread users, keep one user's data ordered and co-located.
- **Local vs global secondary indexes**: local (document-partitioned) indexes make writes cheap but reads scatter-gather; global (term-partitioned) indexes make reads targeted but writes cross shards and are usually async.
- **Routing**: client library, proxy/router (Vitess vtgate, mongos), or any-node forwarding with a gossip table.
- **Rebalancing**: moving partitions when nodes join or leave. Prefer many more fixed partitions than nodes, then move whole partitions.

## When to use / scenarios
- Dataset or write rate exceeds one node after you have exhausted cheaper options: indexing, caching, read replicas, vertical scaling, archiving old data. Sharding is the last step, not the first.
- Multi-tenant SaaS: shard by tenant_id so tenant queries and transactions stay single-shard; handle huge tenants separately.
- Time-series/events: partition by time (range) for cheap retention (drop old partitions) combined with a hash prefix (device id) to avoid a single hot "current" shard.
- Key-value and wide-column stores: hash by primary key.
- When NOT to: when a single Postgres with replicas fits your next 2-3 years. Native table partitioning inside one node (for pruning, retention) is a simpler cousin and often enough.
- Cross-shard joins/transactions across many entities usually mean the model or key is wrong, or you want a distributed SQL database.

## How it works / example

```
 client -> router -> shard = f(shard_key)
                      |-- shard 0: keys with hash slot 0..5461   (primary + replicas)
                      |-- shard 1: 5462..10922                    (primary + replicas)
                      |-- shard 2: 10923..16383                   (primary + replicas)
 query without shard key -> scatter to all shards, gather, merge (slow, tail-latency bound)
```

Fixed-slot hash partitioning with a rebalancing map (move slots, not keys):

```python
import hashlib

SLOTS = 1024                      # many more slots than nodes -> small, even moves

def slot(key: str) -> int:
    return int.from_bytes(hashlib.md5(key.encode()).digest()[:4], "big") % SLOTS

class Cluster:
    def __init__(self, nodes):
        self.owner = {s: nodes[s % len(nodes)] for s in range(SLOTS)}
    def node_for(self, key): return self.owner[slot(key)]
    def add_node(self, new):
        # steal an equal share of slots from the most loaded nodes
        target = SLOTS // (len(set(self.owner.values())) + 1)
        moved = 0
        for s in range(SLOTS):
            if moved >= target: break
            if self.owner[s] != new: self.owner[s] = new; moved += 1
        return moved

c = Cluster(["a", "b", "c"])
before = {k: c.node_for(k) for k in map(str, range(10000))}
moved = c.add_node("d")
changed = sum(before[k] != c.node_for(k) for k in before)
assert changed < 10000 * 0.5      # only the moved slots' keys relocate (not ~75% as with hash % N)
```

Choosing a shard key checklist:
1. High cardinality, so data can spread over many shards.
2. Even access distribution (watch for celebrity keys and tenants).
3. Appears in the WHERE of your hottest queries, so each hits one shard.
4. Not monotonic, unless you hash or salt it.
5. Rarely changes (changing a key means moving a row across shards).

Hot key mitigation: append a random suffix/bucket to the key for writes and fan-in on read, cache hot reads, split the large tenant onto a dedicated shard, or use adaptive splitting where the database supports it.

## Trade-offs
- **Range vs hash**: range supports scans and ordered access but needs hot-spot care and splitting; hash gives balance but kills ordered queries.
- **Many small partitions vs few big**: many small ones rebalance smoothly; too many adds metadata and per-partition overhead.
- **Static slots vs dynamic splitting**: fixed slots are predictable; dynamic splits (Bigtable-style) adapt automatically but are harder to reason about.
- **Application-level sharding vs sharding middleware vs distributed SQL**: DIY gives control and maximum pain; Vitess/Citus/Mongo give routing and resharding; Spanner/CockroachDB/Yugabyte give cross-shard transactions at latency cost.
- **Global secondary indexes**: faster reads vs slower, eventually consistent writes.

## Gotchas
- `hash(key) % N` reshuffles almost all keys when N changes. Use fixed slots or [[consistent-hashing]].
- Cross-shard transactions need 2PC or sagas ([[distributed-transactions-and-sagas]]); unique constraints only hold within a shard unless the unique column is the shard key.
- Auto-increment IDs per shard collide globally; use a scheme from [[unique-id-generation]].
- Scatter-gather latency is the slowest shard; p99 grows with fan-out. Queries that omit the shard key are the silent killer.
- Resharding live: dual-writes, backfill, verify, cut over. Plan and rehearse it before you need it; it is the most expensive operation you will do.
- A good key today can turn bad when product usage changes (one tenant becomes 40% of traffic).
- Backups, schema changes and analytics all become N-times operations; automate them.

## Related
- [[consistent-hashing]] - placement scheme that limits data movement on resize
- [[replication]] - every shard still needs copies for HA
- [[distributed-transactions-and-sagas]] - what to do when a business operation spans shards
- [[sql-vs-nosql]] - some stores shard natively, which affects the choice
- [[database-indexing]] - exhaust indexing and caching before you shard
- [[unique-id-generation]] - IDs that remain unique and sortable across shards

## References
- Kleppmann, Designing Data-Intensive Applications, ch. 6.
- Vitess, MongoDB and Citus documentation on shard keys and resharding.
- Corbett et al., Spanner (OSDI 2012).
