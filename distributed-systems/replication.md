---
title: Replication
category: distributed-systems
tags: [replication, leader-follower, multi-leader, leaderless, quorum, failover, replication-lag, high-availability]
use_cases:
  - "make the database survive a node failure without losing committed data"
  - "scale read traffic by adding read replicas without breaking read-your-writes"
  - "run active-active across two regions and handle conflicting writes"
  - "decide between synchronous and asynchronous replication for a financial ledger"
status: stable
last_verified: 2026-10-10
sources:
  - "Kleppmann, Designing Data-Intensive Applications, ch. 5 (Replication)"
  - "DeCandia et al., Dynamo: Amazon's Highly Available Key-value Store (SOSP 2007) https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf"
  - "PostgreSQL docs, High Availability, Load Balancing, and Replication https://www.postgresql.org/docs/current/high-availability.html"
  - "Shapiro et al., Conflict-free Replicated Data Types (2011) https://inria.hal.science/inria-00609399"
---

# Replication

## Summary
Replication keeps copies of the same data on several nodes to survive failures, serve reads closer to users and add read throughput. The hard part is not copying data but keeping copies in agreement when nodes crash, messages lag and clients write concurrently. Choose a topology (single-leader, multi-leader, leaderless) and a sync/async policy deliberately, because they determine your durability and consistency story.

## Key concepts
- **Single-leader (primary/replica)**: all writes go to the leader, which ships a log (WAL, binlog, oplog) to followers. Simple, no write conflicts. Used by Postgres, MySQL, MongoDB replica sets, Redis, Kafka partitions.
- **Multi-leader**: several nodes accept writes (per region, or per offline client) and replicate to each other. Needs conflict resolution. Used for multi-region active-active and offline-first apps.
- **Leaderless (Dynamo-style)**: any replica accepts writes; client or coordinator writes to W of N nodes and reads from R; `R + W > N` gives overlap. Cassandra, Riak, DynamoDB internals.
- **Synchronous vs asynchronous**: sync waits for follower ack (no loss on leader crash, higher latency, blocked if follower is down); async acks immediately (fast, can lose recent writes on failover). **Semi-sync**: one sync follower, rest async.
- **Replication lag** produces stale reads, non-monotonic reads and causality anomalies ([[consistency-models]]).
- **Failover**: detect leader failure, elect a new one, repoint clients, fence the old one. Needs [[consensus-raft-paxos]] or an external coordinator to avoid two leaders (split brain).
- **Conflict resolution**: last-write-wins (lossy), version vectors / siblings, CRDTs, or app-specific merge.
- **Statement vs log shipping vs logical**: ship WAL bytes (exact, version-coupled), logical changes (row-level, cross-version, CDC-friendly), or SQL statements (non-deterministic functions break it).

## When to use / scenarios
- Any production datastore: at least one synchronous or near-sync replica in another failure domain for HA.
- Read-heavy workload (reports, product pages): add async read replicas; accept lag, route freshness-critical reads to the leader.
- Geo-distributed users needing local writes: multi-leader or a globally consistent database (Spanner/Cockroach style); consider whether you really need active-active, it is costly.
- Offline-capable clients (notes, collaborative docs): multi-leader with CRDTs or operational transform.
- When NOT to use: replication is not a backup. A bad `DELETE` or corruption replicates instantly. Keep point-in-time-recoverable backups too.
- If writes exceed one node's capacity, replication will not help; you need [[partitioning-and-sharding]].

## How it works / example

Single-leader with async follower and the failover data-loss window:

```
 client --write--> [Leader] --WAL stream--> [Follower A] (sync)   acked before client sees OK
                      |-----WAL stream--> [Follower B] (async)  may lag
 Leader dies -> promote most up-to-date follower; writes the old leader had but B lacked are lost
                (or conflict when old leader returns; fence/rewind it)
```

Leaderless read repair and quorum in miniature:

```python
import random

class Node:
    def __init__(self): self.store = {}          # key -> (version, value)
    def put(self, k, ver, v):
        if k not in self.store or self.store[k][0] < ver: self.store[k] = (ver, v)
    def get(self, k): return self.store.get(k, (0, None))

def write(nodes, k, ver, v, w):
    acks = 0
    for n in random.sample(nodes, len(nodes)):
        n.put(k, ver, v); acks += 1
        if acks == w: return True           # remaining replicas catch up async
    return False

def read(nodes, k, r):
    polled = random.sample(nodes, r)
    best = max(n.get(k) for n in polled)     # highest version wins
    for n in polled:                         # read repair: fix stale replicas we touched
        n.put(k, *best)
    return best[1]

nodes = [Node() for _ in range(3)]
write(nodes, "x", 1, "a", w=2)
assert read(nodes, "x", r=2) == "a"          # R + W > N: some read node saw the write
```

Operational checklist for leader/follower:
1. Monitor replication lag (bytes and seconds) and alert on it.
2. Use fencing tokens or STONITH so a demoted leader cannot keep writing.
3. Test failover regularly; measure data loss window (RPO) and recovery time (RTO).
4. Promote the most advanced replica; reconfigure the others to follow it.
5. Route reads needing fresh data to the leader or use session tokens for read-your-writes.

## Trade-offs
- **Sync vs async**: durability and zero data loss vs latency and availability. Many teams pick one sync replica in-region plus async cross-region.
- **Single vs multi-leader**: operational simplicity and no conflicts vs write locality and tolerance of inter-region partitions. Multi-leader adds conflict logic, duplicate-key and constraint hazards.
- **Leaderless**: no failover pause, tunable consistency, but anti-entropy, hinted handoff and repair complexity; no transactions across keys.
- **Number of replicas**: 3 tolerates 1 failure with majority quorum; 5 tolerates 2 at higher write cost.
- **Log shipping type**: physical replicas are simple and exact; logical replication allows version upgrades and filtering but has more lag and ordering edge cases.

## Gotchas
- Async failover can lose acknowledged writes or, worse, let the old leader come back and create divergent history (split brain). Use quorum-based election and fencing.
- Auto-increment IDs, sequences and unique constraints reused after promotion of a lagging replica cause duplicate keys across systems that already saw the old IDs.
- A follower being "up" does not mean caught up. Read from stale followers returns time-travelling data to users.
- Replicating through caches and search indexes adds more lag stages that your DB lag metric does not show.
- LWW with wall clocks silently drops writes under clock skew ([[time-clocks-and-ordering]]).
- Schema migrations must be compatible across leader and followers during rolling changes ([[schema-migrations]]).
- Large transactions or long-running queries on a follower can stall replay (query conflicts) and increase lag.

## Related
- [[consistency-models]] - the guarantees (or lack) your replication setup provides
- [[cap-and-pacelc]] - sync/async maps directly onto the C/A and L/C trade-offs
- [[consensus-raft-paxos]] - safe leader election and replicated logs without split brain
- [[partitioning-and-sharding]] - scale writes; usually combined with replication per shard
- [[time-clocks-and-ordering]] - conflict resolution and version vectors
- [[database-indexing]] - read replicas often carry heavier indexes for reporting
- [[multi-region-architecture]] - active-passive, active-active and home-region designs built on cross-region replication
- [[merkle-trees-and-anti-entropy]] - background repair that finds and fixes divergent replicas by comparing hash trees

## References
- Kleppmann, Designing Data-Intensive Applications, ch. 5.
- DeCandia et al., Dynamo (SOSP 2007).
- PostgreSQL documentation on high availability and replication.
- Shapiro et al., CRDTs (2011).
