---
title: CAP theorem and PACELC
category: distributed-systems
tags: [cap, pacelc, consistency, availability, partition-tolerance, trade-offs, cp, ap]
use_cases:
  - "decide whether our new service should favour consistency or availability during a network partition"
  - "explain why our multi-region database gives stale reads and what we can tune"
  - "pick between a CP store (etcd, ZooKeeper) and an AP store (Cassandra, DynamoDB) for a feature"
  - "justify in a design review why we accept eventual consistency for the product catalogue but not for payments"
status: draft
last_verified: 2026-10-10
sources:
  - "Brewer, Towards Robust Distributed Systems (PODC 2000 keynote) https://people.eecs.berkeley.edu/~brewer/cs262b-2004/PODC-keynote.pdf"
  - "Gilbert and Lynch, Brewer's Conjecture and the Feasibility of Consistent, Available, Partition-Tolerant Web Services (2002) https://dl.acm.org/doi/10.1145/564585.564601"
  - "Abadi, Consistency Tradeoffs in Modern Distributed Database System Design (IEEE Computer, 2012) https://www.cs.umd.edu/~abadi/papers/abadi-pacelc.pdf"
  - "Kleppmann, Please stop calling databases CP or AP https://martin.kleppmann.com/2015/05/11/please-stop-calling-databases-cp-or-ap.html"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 9"
---

# CAP theorem and PACELC

## Summary
CAP says that when a network partition happens, a replicated system must choose between answering every request (availability) and answering them all correctly as if there were one copy (linearizable consistency). It is a statement about the failure case only, so it is a weak tool for everyday design. PACELC extends it with the case that matters 99.9% of the time: Else (no partition), you still trade Latency against Consistency.

## Key concepts
- **Consistency (C)** in CAP means linearizability: every read sees the latest completed write, as if there were one copy. It is NOT the "C" in ACID.
- **Availability (A)**: every request to a non-failed node gets a non-error response, however stale. Not the same as "high uptime" SLAs.
- **Partition tolerance (P)**: the system keeps operating when the network drops or delays messages between nodes. Partitions are not optional on a real network, so the real choice is C vs A *during* a partition.
- **CP**: on partition, refuse (error or block) on the minority side to stay consistent. **AP**: on partition, keep serving on both sides and reconcile later.
- **PACELC**: if Partition then Availability vs Consistency; Else Latency vs Consistency. Written PA/EL, PC/EC, PA/EC, PC/EL.
- A system is not "a CP database" in the abstract. Behaviour depends on configuration per operation (quorum sizes, read concern, sync vs async replication).

## When to use / scenarios
- Use CAP/PACELC as a vocabulary when choosing a datastore or tuning one: "what should happen to writes in the minority partition?" "can a user read their own write in another region?"
- Per feature, ask: what is the cost of a stale read vs the cost of an error? Shopping cart or like counter: stale is fine (AP). Account balance, unique username, leader lock, inventory oversell: wrong is worse than down (CP).
- Metadata, locks, leader election, config: put on a CP store (etcd, ZooKeeper, Consul) that uses [[consensus-raft-paxos]].
- When NOT to use it as a decision tool: single-node systems, systems inside one AZ where partitions are rare and the real concern is latency (use PACELC), or arguing about vendor marketing labels.

## How it works / example

Two replicas, partition between them:

```
   Client A --> [ Node 1 ]  X X partition X X  [ Node 2 ] <-- Client B
                  x=1                              x=1
   A writes x=2 on Node 1.  B reads x on Node 2.

   CP choice: Node 2 (cannot reach quorum) returns error / blocks  -> B gets no answer
   AP choice: Node 2 returns x=1 (stale) and accepts writes        -> divergence, must reconcile
```

PACELC classification of common systems (defaults, configurable; verify against the vendor's current docs):

| System | Partition (PA/PC) | Else (EL/EC) | Note |
|---|---|---|---|
| Dynamo-style (Cassandra, Riak, DynamoDB eventually consistent reads) | PA | EL | tunable quorums can move toward EC |
| Spanner, CockroachDB, etcd, ZooKeeper | PC | EC | pay cross-node latency for every write |
| MongoDB (majority writes and reads) | PC | EC | with `w:1` / local reads it behaves PA/EL |
| PNUTS (Yahoo) | PC | EL | the original PC/EL example from Abadi |

A tunable-quorum sketch: with N replicas, write quorum W, read quorum R, reads see the latest write if `R + W > N`.

```python
def quorum_ok(n: int, w: int, r: int) -> bool:
    """True if every read quorum overlaps every write quorum."""
    return r + w > n

assert quorum_ok(3, 2, 2)       # strongly consistent-ish: survives 1 node down
assert not quorum_ok(3, 1, 1)   # fast and available, but may read stale
```

Practical pattern for mixed needs: keep the money path on a CP/strongly-consistent store, serve read-heavy views from caches or replicas that tolerate staleness, and surface staleness explicitly (timestamps, "may be a few seconds old").

## Trade-offs
- **Consistency vs availability on partition**: CP gives simple reasoning and correct invariants but unavailability for part of the users; AP gives uptime but forces conflict resolution (last-write-wins, CRDTs, app merge) onto you.
- **Latency vs consistency in the normal case**: synchronous cross-region replication makes writes slow (PC/EC); async replication makes them fast but loses recent writes on failover (PA/EL). Often the more important axis day to day.
- **Granularity**: you can choose per operation (a strong read for checkout, an eventual read for browse) rather than per system. That is usually the right answer.
- Weaker-than-linearizable models (see [[consistency-models]]) such as causal or read-your-writes give most of the UX benefit at AP-friendly cost.

## Gotchas
- "Pick 2 of 3" is misleading: you cannot give up P, so it is really "C or A when P happens". CA is a single-node system.
- CAP's A (every non-failed node responds) and C (linearizable) are far narrower than how people use the words. A system can be neither CP nor AP by the formal definitions (e.g. an unpartitioned-but-slow system, or one with weak consistency that is also not always available).
- Labels in vendor docs are marketing. Check what a write acknowledgement actually means (replicated to memory on one node? durable on majority?).
- Quorum config does not equal linearizability: sloppy quorums, hinted handoff, clock-based LWW and concurrent writes can still return stale or lost data.
- Partitions are not only network cuts: long GC pauses, overloaded nodes and slow disks look the same to peers. See [[failure-modes-and-fallacies]].
- Forgetting the Else branch: teams agonise over partitions that happen a few times a year and ignore the latency tax paid on every request.

## Related
- [[consistency-models]] - the spectrum between linearizable and eventual that CAP collapses into one bit
- [[replication]] - sync vs async, leader vs leaderless decide where you land in PACELC
- [[consensus-raft-paxos]] - how CP systems stay consistent under partition
- [[sql-vs-nosql]] - datastore choice often reduces to these trade-offs
- [[choosing-a-database]] - applies CAP/PACELC thinking to a concrete selection
- [[failure-modes-and-fallacies]] - why partitions and "slow" failures are the norm

## References
- Brewer, PODC 2000 keynote (conjecture); Gilbert and Lynch 2002 (proof).
- Abadi, "Consistency Tradeoffs in Modern Distributed Database System Design", IEEE Computer 2012 (PACELC).
- Kleppmann, "Please stop calling databases CP or AP" (2015); Designing Data-Intensive Applications, ch. 9.
