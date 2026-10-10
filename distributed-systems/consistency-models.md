---
title: Consistency models
category: distributed-systems
tags: [consistency, linearizability, serializability, eventual-consistency, causal, read-your-writes, session-guarantees]
use_cases:
  - "users update their profile then see the old value on the next page load, fix it"
  - "choose which read consistency level to use for checkout vs browse in a replicated database"
  - "explain the difference between serializable and linearizable to the team"
  - "make comments appear in a sensible order (replies after the thing they reply to) across regions"
status: draft
last_verified: 2026-10-10
sources:
  - "Jepsen consistency models map https://jepsen.io/consistency"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 5 and 9"
  - "Terry et al., Session Guarantees for Weakly Consistent Replicated Data (1994) https://www.cs.cornell.edu/courses/cs734/2000FA/cached%20papers/SessionGuaranteesPDIS_1.html"
  - "Herlihy and Wing, Linearizability: A Correctness Condition for Concurrent Objects (1990) https://dl.acm.org/doi/10.1145/78969.78972"
  - "Bailis, Highly Available Transactions (2013) http://www.bailis.org/papers/hat-vldb2014.pdf"
---

# Consistency models

## Summary
A consistency model is a contract about which values a read may return given the history of writes across replicas and clients. The strongest (linearizable) behaves like one copy; the weakest (eventual) only promises convergence. Pick the weakest model your feature tolerates, because every step up costs latency and availability.

## Key concepts
- **Linearizability** (strong consistency, "atomic"): operations appear to take effect instantaneously at some point between invocation and response, respecting real time. Single-object, recency guarantee.
- **Serializability**: transactions (multi-object) behave as if run one at a time in SOME order, not necessarily real-time order. **Strict serializability** = serializable + linearizable. Different axes; do not conflate (see [[transactions-and-isolation-levels]]).
- **Sequential consistency**: all clients see operations in the same total order that respects each client's program order, but not real time.
- **Causal consistency**: operations that are causally related (a reply to a post) are seen in that order by everyone; concurrent ones may differ. Strongest model achievable while staying available under partition.
- **Eventual consistency**: if writes stop, replicas converge. Says nothing about what you read meanwhile.
- **Session guarantees** (client-centric, cheap and very useful):
  - read-your-writes: you see your own updates
  - monotonic reads: you never see time go backwards
  - monotonic writes: your writes apply in the order issued
  - writes-follow-reads: a write is ordered after the reads that influenced it
- Anomalies to name: stale read, lost update, write skew, non-repeatable read, causality violation (seeing a reply before the question).

## When to use / scenarios
- **Linearizable**: unique constraints (usernames), leader leases and locks, balances that must never overspend, inventory with hard limits, coordination metadata. Use a consensus-backed store ([[consensus-raft-paxos]]).
- **Causal / session guarantees**: social feeds, comments, collaborative apps, profile edits. Delivers "makes sense to the user" without global coordination.
- **Eventual**: counters, analytics, caches, search indexes, recommendations, anything with an idempotent merge (CRDTs, last-write-wins on non-critical fields).
- Typical fix for "I saved but see old data": read-your-writes by routing that user's reads to the leader or the replica they wrote to for a short window, or by passing a version/LSN token with the session.
- When NOT to over-invest: do not demand linearizability for read-mostly content, and do not accept eventual consistency where you enforce an invariant across records.

## How it works / example

The strength hierarchy (stronger at top; arrows mean "implies"):

```
Strict serializable
   |-- Serializable          Linearizable
                                 |
                          Sequential
                                 |
                              Causal   <- best you can do and stay available in a partition
                                 |
        read-your-writes / monotonic reads / writes-follow-reads
                                 |
                             Eventual
```

Read-your-writes with a version token (leader writes, replicas lag):

```python
import time

class Replica:
    def __init__(self): self.data, self.applied = {}, 0
class Cluster:
    def __init__(self): self.leader, self.follower = Replica(), Replica(); self.log = []
    def write(self, k, v):
        self.log.append((k, v)); self.leader.data[k] = v; self.leader.applied = len(self.log)
        return self.leader.applied                      # token = log position
    def replicate(self):                                 # async, runs "later"
        for k, v in self.log[self.follower.applied:]: self.follower.data[k] = v
        self.follower.applied = len(self.log)
    def read(self, k, min_token=0):
        node = self.follower if self.follower.applied >= min_token else self.leader
        return node.data.get(k)

c = Cluster()
token = c.write("name", "Ada")
assert c.read("name") is None or True        # plain follower read may be stale
assert c.read("name", min_token=token) == "Ada"   # session guarantee holds
```

Real systems expose this as knobs: Postgres `synchronous_commit` and read-from-primary after write, MongoDB read/write concern (`majority`, causal sessions), Cassandra consistency levels (`ONE`, `QUORUM`, `LOCAL_QUORUM`), DynamoDB `ConsistentRead`, Spanner's external consistency / stale reads with bounded staleness (check each product's docs for current names).

## Trade-offs
- **Strength vs latency/availability**: linearizable reads/writes need a quorum or leader round trip; across regions that is tens to hundreds of ms. Weaker models can answer from the nearest replica.
- **Per-operation vs global choice**: most stores let you pick per request. Do that instead of choosing one level for everything.
- **Bounded staleness** (read at most N seconds / N versions behind) is a pragmatic middle ground when you can measure replication lag.
- **Application-level resolution**: weaker models push conflict handling to code: LWW (loses data), CRDTs (merge by construction), or "keep siblings and ask the app".

## Gotchas
- "Strong consistency" in a product page often means only "read from primary"; it can break on failover or with lagging followers. Verify the guarantee, ideally against Jepsen reports.
- Serializable does not imply you read the latest data: a serializable system may legally order your read before a write that finished earlier in wall-clock time.
- Isolation level names differ by database (Postgres Repeatable Read is snapshot isolation and allows write skew; MySQL InnoDB differs). Test the anomaly you care about.
- Read-your-writes breaks across devices and after cache hits; session stickiness is not enough if the cache is eventual.
- Last-write-wins uses clocks; skew silently drops the "newer" write. See [[time-clocks-and-ordering]].
- Mixing models in one flow (strong write, eventual index) creates "I created it but search cannot find it". Show the new item from the write response instead of re-querying.

## Related
- [[cap-and-pacelc]] - why the stronger models cost availability and latency
- [[replication]] - the mechanism whose lag creates these anomalies
- [[transactions-and-isolation-levels]] - the multi-object (serializability) side of the story
- [[time-clocks-and-ordering]] - causality, vector clocks and the ordering behind causal consistency
- [[caching-strategies]] - caches are a common, silent source of stale reads

## References
- Jepsen, "Consistency Models" map (jepsen.io/consistency).
- Kleppmann, Designing Data-Intensive Applications, ch. 5 (replication lag) and ch. 9 (consistency and consensus).
- Terry et al. 1994 (session guarantees); Herlihy and Wing 1990 (linearizability).
