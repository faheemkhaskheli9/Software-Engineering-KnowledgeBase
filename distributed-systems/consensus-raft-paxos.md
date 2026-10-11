---
title: Consensus (Raft and Paxos)
category: distributed-systems
tags: [consensus, raft, paxos, leader-election, replicated-log, quorum, etcd, zookeeper, split-brain]
use_cases:
  - "elect exactly one leader among several service instances without split brain"
  - "store cluster configuration or locks in a strongly consistent store (etcd, ZooKeeper, Consul)"
  - "understand why our 2-node database cluster cannot fail over safely and needs a third voter"
  - "build a replicated state machine or a strongly consistent metadata service"
status: draft
last_verified: 2026-10-10
sources:
  - "Ongaro and Ousterhout, In Search of an Understandable Consensus Algorithm (Raft, USENIX ATC 2014) https://raft.github.io/raft.pdf"
  - "Lamport, Paxos Made Simple (2001) https://lamport.azurewebsites.net/pubs/paxos-simple.pdf"
  - "Fischer, Lynch, Paterson, Impossibility of Distributed Consensus with One Faulty Process (1985) https://dl.acm.org/doi/10.1145/3149.214121"
  - "The Raft visualisation and resources https://raft.github.io/"
  - "Hunt et al., ZooKeeper: Wait-free coordination for Internet-scale systems (USENIX ATC 2010) https://www.usenix.org/legacy/event/atc10/tech/full_papers/Hunt.pdf"
---

# Consensus (Raft and Paxos)

## Summary
Consensus lets a group of nodes agree on a value (or an ordered log of values) even when some nodes crash and messages are delayed or lost, as long as a majority is alive and connected. It is the foundation for leader election, distributed locks, configuration stores and strongly consistent replicated databases. You almost never implement it yourself; you consume it via etcd, ZooKeeper, Consul, Kafka KRaft, or a database that embeds Raft.

## Key concepts
- **Replicated state machine**: all nodes apply the same commands in the same order from a replicated log, so they end in the same state. Consensus agrees on the log order.
- **Quorum (majority)**: decisions need `floor(N/2)+1` nodes. Any two majorities overlap, so a decided value cannot be lost or contradicted. A cluster of `2f+1` tolerates `f` failures: 3 tolerates 1, 5 tolerates 2.
- **Safety vs liveness**: safety (never two different decisions) always holds; liveness (progress) needs a majority reachable and some timing assumptions (FLP says no deterministic algorithm guarantees both in a fully asynchronous system).
- **Raft** roles: leader, follower, candidate. Time is split into **terms**. Followers time out and start an election; a candidate needs a majority of votes and an up-to-date log. The leader appends entries, replicates via `AppendEntries`, and an entry is **committed** once a majority stores it.
- **Multi-Paxos**: the same idea expressed as repeated Paxos instances (prepare/promise, accept/accepted) with a stable leader skipping the prepare phase. Harder to implement correctly from the paper.
- **Leases and fencing tokens**: a leader that believes it is leader after being replaced is dangerous; monotonically increasing tokens let resources reject stale leaders.
- **Membership changes**: add or remove nodes through the log itself (joint consensus or single-server change in Raft), never by editing configs in place.
- **Byzantine fault tolerance (PBFT, etc.)** handles malicious nodes and is a different, costlier problem. Raft/Paxos assume crash faults only.

## When to use / scenarios
- You need exactly one active instance (job scheduler, primary DB, singleton worker): elect it via an etcd/ZooKeeper lease rather than rolling your own heartbeat logic.
- Coordination data that must never diverge: cluster membership, shard maps, feature flags with strict ordering, distributed locks (see caveat below), service discovery with strong semantics.
- Strongly consistent ([[consistency-models]]) databases: Spanner (Paxos), CockroachDB/TiKV/etcd (Raft), MongoDB replica sets (Raft-like protocol).
- When NOT to use: high-volume data path (keep consensus on the control plane or per-shard small logs), systems where availability during partition matters more than consistency ([[cap-and-pacelc]]), or when a single database transaction already gives you what you need.
- Do not run consensus across high-latency links casually: every commit needs a majority round trip.

## How it works / example

Raft log replication, 3 nodes:

```
 client --cmd--> [Leader L, term 4]
                    | AppendEntries(term 4, prevIdx, entries)
                    |------------------> [Follower A]  ack
                    |------------------> [Follower B]  (slow / partitioned)
 L has own copy + A's ack = 2 of 3 = majority -> entry COMMITTED -> apply to state machine -> reply to client
 B catches up later; if L dies before majority, uncommitted entries may be discarded by the new leader.
```

Leader election timeline:

```
 follower: no heartbeat within randomized timeout (e.g. 150-300 ms range in the Raft paper)
   -> becomes candidate, term++ , votes for itself, sends RequestVote
   -> grants only if candidate's log is at least as up to date
   -> majority of votes => leader, sends heartbeats; otherwise random timeout, retry
```

A minimal single-decree Paxos acceptor and the quorum rule, to show the safety core:

```python
class Acceptor:
    def __init__(self): self.promised = -1; self.accepted = (-1, None)
    def prepare(self, n):
        if n > self.promised: self.promised = n; return ("promise", self.accepted)
        return ("nack", None)
    def accept(self, n, v):
        if n >= self.promised: self.promised = n; self.accepted = (n, v); return True
        return False

def propose(acceptors, n, value):
    promises = [a.prepare(n) for a in acceptors]
    ok = [acc for tag, acc in promises if tag == "promise"]
    if len(ok) <= len(acceptors) // 2: return None
    prior = max(ok)                           # must adopt highest-numbered accepted value
    v = prior[1] if prior[1] is not None else value
    acks = sum(a.accept(n, v) for a in acceptors)
    return v if acks > len(acceptors) // 2 else None

accs = [Acceptor() for _ in range(5)]
assert propose(accs, 1, "A") == "A"
assert propose(accs, 2, "B") == "A"           # later proposer is forced to keep the chosen value
```

Using it in practice:
- Run 3 or 5 voters in separate failure domains (AZs). Never 2 or 4 (no gain in fault tolerance, more cost).
- Use the client library's lease/lock/election recipe (etcd `concurrency` package, ZooKeeper Curator recipes, Consul sessions).
- Attach a fencing token (etcd revision, ZooKeeper zxid) to writes against the protected resource.
- Keep payloads small (kilobytes); store big data elsewhere and keep pointers in the consensus store.

## Trade-offs
- **Raft vs Paxos**: same guarantees; Raft is easier to teach and implement, and has mature libraries (etcd/raft, HashiCorp raft). Paxos variants have more design freedom (leaderless, flexible quorums, EPaxos).
- **3 vs 5 voters**: 5 tolerates two failures and a rolling upgrade plus a failure, at higher write latency and cost.
- **Write latency**: at least one majority round trip plus fsync; geographic spread directly adds latency. Read options: via leader (linearizable), via lease reads, or stale follower reads.
- **Consensus per cluster vs per shard**: one global log is a bottleneck; sharded systems run a Raft group per shard/range (multi-Raft).

## Gotchas
- A distributed lock built on a lease is only safe with fencing tokens; a paused (GC, VM stall) holder resumes thinking it still holds the lock. Clocks cannot fix this ([[time-clocks-and-ordering]]).
- Timeouts too tight cause election storms under GC pauses or noisy neighbours; too loose slows failover. Tune to measured network and disk latency.
- Slow disks hurt the whole cluster because leaders must fsync before acking; use fast, dedicated disks for the log.
- Reading from a follower or an old leader returns stale data unless you use linearizable read protocols (ReadIndex/lease reads).
- Two-node "clusters" and even-sized clusters give a false sense of safety; you need an odd quorum or a witness.
- Membership and config changes done by hand are the leading cause of lost quorum and data loss.
- Consensus does not make your application logic idempotent; retries after leader change still duplicate side effects ([[idempotency-and-exactly-once]]).

## Related
- [[replication]] - consensus is how leader-based replication achieves safe failover
- [[cap-and-pacelc]] - consensus systems are the CP side of the trade-off
- [[distributed-transactions-and-sagas]] - 2PC needs a durable coordinator; Paxos/Raft commit can make it fault tolerant
- [[time-clocks-and-ordering]] - why leases and fencing, not clocks, protect leaders
- [[design-key-value-store]] - worked design using Raft for metadata and per-shard logs
- [[message-queues-and-streams]] - Kafka's controller (KRaft) and ZooKeeper era examples
- [[distributed-locks-and-leader-election]] - ZooKeeper/etcd lock and election recipes built on consensus

## References
- Ongaro and Ousterhout, Raft (USENIX ATC 2014); Lamport, Paxos Made Simple (2001).
- Fischer, Lynch, Paterson (1985), FLP impossibility.
- Hunt et al., ZooKeeper (USENIX ATC 2010); etcd documentation.
- Kleppmann, Designing Data-Intensive Applications, ch. 8-9.
