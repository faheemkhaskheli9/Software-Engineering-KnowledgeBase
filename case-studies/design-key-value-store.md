---
title: Design a distributed key-value store
category: case-studies
tags: [key-value-store, dynamo, cassandra, lsm-tree, quorum, consistent-hashing, gossip, case-study]
use_cases:
  - "design a Dynamo or Cassandra style highly available distributed key-value store"
  - "choose replication factor and read/write quorums for a tunable-consistency store"
  - "handle node failures with hinted handoff, read repair and anti-entropy"
  - "design the single-node storage engine behind a distributed database (LSM tree)"
  - "explain how a distributed store partitions data and detects failed nodes"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf
  - https://www.cs.cornell.edu/projects/ladis2009/papers/lakshman-ladis2009.pdf
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 6 'Design a Key-Value Store'"
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017, ch. 3, 5, 6, 7"
  - https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/
---

# Design a distributed key-value store

## Summary
A distributed key-value store exposes `put(key, value)` and `get(key)` over a
cluster, partitioning data across nodes and replicating each key for durability and
availability. Dynamo-style designs choose availability and tunable consistency:
consistent hashing for placement, quorum reads and writes, vector clocks or
timestamps for conflicts, gossip for membership, and an LSM-tree engine on each node.
It is the canonical exercise that ties together most of distributed systems.

## Key concepts
- **Partitioning with consistent hashing** and virtual nodes ([[consistent-hashing]], [[partitioning-and-sharding]]).
- **Replication factor N:** each key stored on the N nodes clockwise from its position ([[replication]]).
- **Quorums:** write acked by W replicas, read consults R; if R + W > N, a read overlaps the latest successful write (no guarantee of linearizability, see [[consistency-models]]).
- **CAP/PACELC position:** AP-leaning with tunable consistency per request ([[cap-and-pacelc]]); a CP alternative uses Raft per partition ([[consensus-raft-paxos]]).
- **Conflict handling:** last-write-wins by timestamp (simple, can lose writes) or vector clocks / version vectors surfacing siblings to the client ([[time-clocks-and-ordering]]).
- **Failure handling:** gossip membership and failure detection, sloppy quorum + hinted handoff, read repair, Merkle-tree anti-entropy.
- **Storage engine:** LSM tree (commit log, memtable, SSTables, compaction, Bloom filters) vs B-tree.
- **Coordinator:** any node can receive a request and coordinate it (leaderless).

## When to use / scenarios
Learn from or build this when you need: massive write throughput, always-writable shopping-cart-like data, simple
access by key, linear horizontal scale, multi-datacentre replication. In a real project prefer an existing store
(Cassandra, ScyllaDB, DynamoDB, Riak, etcd/FoundationDB for CP needs) rather than writing your own ([[sql-vs-nosql]]).
Not appropriate if you need joins, multi-key transactions or strict serialisable consistency (use a relational or NewSQL database).

## How it works / example

### 1. Requirements
Functional: `put(key, value)`, `get(key)`, `delete(key)`; values are small blobs (assume under about 10 KB, a design assumption);
optional TTL; optional range scans if keys are ordered (a variant with range partitioning).

Non-functional: high availability (writes accepted even during node and network failures); horizontal scalability (add nodes
with minimal data movement); low latency (single-digit to tens of ms at p99, a target); tunable consistency; automatic
failure detection and recovery; durability; multi-datacentre replication.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 10 TB of data with N = 3: 30 TB raw; with 2 TB usable per node (leave space for compaction headroom) about 15+ nodes before
  growth margin.
- 100k ops/s with 70% reads: per-node load spread over 20 nodes is about 5k ops/s, feasible for an LSM engine on SSD (verify by load test).
- Write amplification from compaction can be 10x or more in leveled compaction (varies with settings); budget disk bandwidth accordingly.

### 3. API
```
put(key, value, {consistency: ONE|QUORUM|ALL, ttl?, context?})  -> ok | error(timeout/unavailable)
get(key, {consistency})  -> [ (value, context/version) ... ]      // multiple values if concurrent siblings
delete(key) -> tombstone write
Admin: add_node, remove_node, repair, status
```
Clients may be partition-aware (hash locally and send to a replica) or go through any coordinator.
Binary protocol or gRPC ([[grpc-and-protobuf]]).

### 4. Data model
Per node:
```
commit_log (append-only, fsynced per batch)
memtable (sorted in-memory structure, e.g. skiplist)
SSTables (immutable sorted files) + index + Bloom filter per file
tombstones (deletes) with GC grace period
```
Logical record: `(key, value, version_metadata, timestamp, ttl/tombstone flag)`.

### 5. High-level architecture
```
                 client
                   | (any node may coordinate)
                   v
            +-- coordinator --+
            |  hash(key) -> ring position -> preference list of N replicas
   write -> send to N replicas in parallel, ack after W   |   read -> query R replicas, return newest/siblings
            |
   ring:  [A] -> [B] -> [C] -> [D] -> ... (virtual nodes spread each physical node around the ring)
   key k lands on first node clockwise, then next N-1 distinct physical nodes

 each node: gossip agent | request handler | commit log + memtable + SSTables | hint store | anti-entropy (Merkle trees)
```

### 6. Deep dive A: partitioning, replication and quorums
Place nodes on a hash ring (many virtual nodes each, e.g. 100-256, to even out load and let heterogenous hardware take
proportional shares). `hash(key)` selects a position; the **preference list** is the next N distinct physical nodes. Adding a node
claims virtual-node ranges from neighbours, moving only about 1/(number of nodes) of data.

Quorum math: with N = 3, W = 2, R = 2 gives R + W > N, so every read intersects the latest acked write. Tuning:
- W = 1, R = N: fast writes, slower reads, weaker write durability.
- W = N, R = 1: fast reads, writes fail if any replica is down.
- R + W <= N: eventual consistency, lowest latency.

**Sloppy quorum + hinted handoff:** if a preference-list node is down, write to the next healthy node on the ring with a hint
"this belongs to X"; when X returns, the hint is replayed. This keeps writes available at the price of stale reads in the meantime.

```python
import hashlib, bisect
class Ring:
    def __init__(self, nodes, vnodes=128):
        self.ring = sorted((self._h(f"{n}#{i}"), n) for n in nodes for i in range(vnodes))
        self.keys = [h for h, _ in self.ring]
    @staticmethod
    def _h(s): return int(hashlib.md5(s.encode()).hexdigest(), 16)
    def preference_list(self, key, n=3):
        i = bisect.bisect(self.keys, self._h(key)) % len(self.ring)
        out = []
        while len(out) < n:
            node = self.ring[i % len(self.ring)][1]
            if node not in out: out.append(node)
            i += 1
        return out
```

### 7. Deep dive B: conflicts, repair and failure detection
- **Conflict resolution:** concurrent writes to the same key on different replicas create divergent versions.
  *LWW by timestamp* drops one write silently and is vulnerable to clock skew. *Vector clocks* (or dotted version vectors) detect true concurrency and
  return siblings for the application to merge (the Dynamo shopping-cart example); CRDTs automate merges for specific data types.
- **Read repair:** on a read, coordinator compares replica responses and writes the newest value back to stale ones.
- **Anti-entropy:** replicas exchange Merkle tree hashes per key range; only differing ranges are synced. Cheap detection of drift for cold keys that are never read.
- **Failure detection:** gossip protocol where each node periodically exchanges membership/heartbeat state with a few random peers; a node is
  suspected if its heartbeat counter does not advance for a threshold (phi-accrual detectors adapt to network jitter).
  Decentralised, no single point of failure.
- **Permanent failure:** after a long outage decommission the node and rebuild replicas by streaming from the others; hints expire and repair takes over.
- **Multi-datacentre:** replicas per DC, `LOCAL_QUORUM` for latency, asynchronous cross-DC replication.

### 8. Deep dive C: the single-node write and read path (LSM tree)
Write: append to the **commit log** (durability), insert into the sorted in-memory **memtable**, acknowledge. When the memtable fills,
flush it to an immutable **SSTable** on disk. Sequential writes make this very fast.
Read: check memtable, then SSTables from newest to oldest; a **Bloom filter** per SSTable skips files that definitely lack the key; a sparse
index locates the block. Reads can touch several files (read amplification).
**Compaction** merges SSTables, dropping overwritten values and expired tombstones (size-tiered favours writes; leveled favours reads and space).
Deletes write tombstones, which must persist longer than the maximum repair interval, otherwise a replica that missed the delete resurrects the data
("zombie" data). Compare with B-trees in [[database-indexing]]. For SSD sizing, plan compaction I/O headroom.

```
write path:  put -> commit log (fsync) -> memtable -> ack ... flush -> SSTable L0 -> compact -> L1..Ln
read path:   get -> memtable -> [bloom filter -> index -> SSTable block] per level, newest wins
```

### 9. Scaling and failure handling
- Scale out by adding nodes; the ring rebalances by streaming ranges in the background with throttling.
- Hot keys/partitions: replicate more, cache at the client or edge ([[caching-strategies]]), or split a key into sub-keys.
- Coordinator timeouts and retries must be idempotent (puts with the same version/timestamp are safe to repeat, [[idempotency-and-exactly-once]]).
- Rolling upgrades and backups via snapshotting immutable SSTables (hard links make this cheap).
- Observability: per-node latency percentiles, pending compactions, hinted-handoff backlog, dropped mutations, repair status
  ([[observability-logs-metrics-traces]]).
- Alternative design (CP): range partitions each replicated by Raft, giving linearizable reads/writes through a leader and unavailability
  on a minority side of a partition (etcd, TiKV, Spanner family).
- Failure-injection testing is mandatory: partition, kill, slow disks, clock jumps ([[failure-modes-and-fallacies]]).

## Trade-offs
- Availability vs consistency per request: QUORUM for important data, ONE for speed; per-operation tunable consistency is the Dynamo contribution.
- LWW simplicity vs vector-clock correctness: LWW is easy and lossy; vector clocks push merge logic to every client.
- Leaderless (Dynamo/Cassandra) vs leader-based per partition (Raft/Paxos): leaderless is always-writable with weaker guarantees; leader-based gives linearizability but loses availability on minority partitions.
- Size-tiered vs leveled compaction: write throughput vs read latency and space amplification.
- Many virtual nodes balance load and speed recovery but increase metadata and repair overhead.
- Partition-aware clients cut a hop but must track topology.

## Gotchas
- Assuming R + W > N gives linearizability; with sloppy quorums, concurrent writes and clock issues it does not.
- Clock skew with LWW silently discarding the newer write; prefer logical clocks or bounded-skew hardware time for critical data.
- Tombstone and GC-grace misconfiguration resurrecting deleted data.
- Hot partitions from monotonic or low-cardinality keys (timestamps as partition key).
- Repair/compaction storms starving foreground traffic; throttle them.
- Large values or unbounded rows in a single key make everything slow; cap sizes.
- Adding many nodes at once triggers heavy streaming; bootstrap one at a time.
- Counting on cross-key atomicity that a plain KV store does not provide.

## Related
- [[consistent-hashing]] - the placement mechanism used throughout
- [[replication]] - leader-based vs leaderless replication background
- [[consistency-models]] - what quorums do and do not guarantee
- [[cap-and-pacelc]] - the availability/consistency choice behind the design
- [[consensus-raft-paxos]] - the CP alternative for strongly consistent KV stores
- [[time-clocks-and-ordering]] - vector clocks and why wall clocks mislead
- [[database-indexing]] - LSM trees compared with B-trees
- [[storage-engines-btree-lsm]] - the per-node LSM engine in depth: compaction strategies, amplification, Bloom filters
- [[gossip-and-failure-detection]] - the membership and failure-detection protocols this design relies on.

## References
- DeCandia et al., "Dynamo: Amazon's Highly Available Key-value Store" (SOSP 2007): https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf
- Lakshman and Malik, "Cassandra: A Decentralized Structured Storage System": https://www.cs.cornell.edu/projects/ladis2009/papers/lakshman-ladis2009.pdf
- Chang et al., "Bigtable": https://research.google/pubs/bigtable-a-distributed-storage-system-for-structured-data/
- Alex Xu, *System Design Interview Vol. 1*, ch. 6
- Kleppmann, *Designing Data-Intensive Applications* (2017)
