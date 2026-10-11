---
title: Time, clocks and ordering
category: distributed-systems
tags: [lamport-clock, vector-clock, hybrid-logical-clock, clock-skew, ntp, truetime, happens-before, last-write-wins]
use_cases:
  - "order events from multiple services without trusting their wall clocks"
  - "detect concurrent conflicting edits to the same record across replicas"
  - "explain why last-write-wins lost a user's update"
  - "generate timestamps for a multi-region database that respect causality"
status: stable
last_verified: 2026-10-10
sources:
  - "Lamport, Time, Clocks, and the Ordering of Events in a Distributed System (CACM 1978) https://lamport.azurewebsites.net/pubs/time-clocks.pdf"
  - "Fidge / Mattern vector clocks; Mattern, Virtual Time and Global States of Distributed Systems (1989)"
  - "Kulkarni et al., Logical Physical Clocks and Consistent Snapshots in Globally Distributed Databases (HLC, 2014) https://cse.buffalo.edu/tech-reports/2014-04.pdf"
  - "Corbett et al., Spanner (OSDI 2012) https://research.google/pubs/spanner-googles-globally-distributed-database-2/"
  - "Kleppmann, Designing Data-Intensive Applications, ch. 8 (Unreliable Clocks)"
---

# Time, clocks and ordering

## Summary
In a distributed system there is no shared clock, and wall clocks on different machines disagree and can jump. Correct ordering of events must come from causality (happens-before), tracked with logical clocks, or from clocks with explicit error bounds. Use wall-clock time for humans and TTLs, not for deciding which write wins.

## Key concepts
- **Physical clocks**: time-of-day (can jump backwards on NTP step or leap-second handling) vs monotonic clocks (only for measuring durations on one machine; meaningless across machines).
- **Clock skew and drift**: NTP typically keeps machines within milliseconds on a good network, but errors of much more happen (VM pauses, misconfig, partitions). Never assume a bound unless your infrastructure guarantees one.
- **Happens-before (a -> b)**: a precedes b on the same process, or a is a send and b its receive, or transitively. Events with no path are **concurrent**.
- **Lamport clock**: a counter per process; increment on each event; on receive set `c = max(local, msg) + 1`. If a -> b then L(a) < L(b), but not the converse; it gives a total order consistent with causality, but cannot detect concurrency.
- **Vector clock**: a vector of counters, one per process. Compare to tell before / after / concurrent exactly. Size grows with participants (Dynamo-style systems prune or use dotted version vectors).
- **Hybrid logical clock (HLC)**: physical time plus a logical counter; stays close to wall time, monotonic, and preserves causality. Used by CockroachDB and others.
- **TrueTime (Spanner)**: clock API returning an interval `[earliest, latest]` from GPS and atomic clocks; commit-wait until the uncertainty passes gives external consistency.
- **Total order vs partial order**: causal order is partial. A single total order needs a sequencer, consensus ([[consensus-raft-paxos]]) or tie-breaking by node ID.
- **Fencing token**: monotonically increasing number issued with a lease so resources reject stale holders; avoids reliance on clocks.

## When to use / scenarios
- Detect and resolve conflicting concurrent writes in multi-leader or leaderless stores: version vectors, then merge, siblings or CRDTs ([[replication]]).
- Order log/trace events across services: propagate a trace/causal ID and logical timestamps; do not sort by host timestamps alone ([[observability-logs-metrics-traces]]).
- Causal consistency in collaboration or feeds ([[consistency-models]]): ship dependency metadata (vector or HLC) with writes.
- Snapshot reads and MVCC timestamps in distributed SQL: HLC or TrueTime-like bounds.
- Leader leases and distributed locks: use fencing tokens, never "my lease has not expired by my clock".
- When NOT needed: single-writer systems where a database sequence or a log offset gives a total order for free (Kafka partition offsets, a leader's WAL position).

## How it works / example

Three processes, messages carry clocks:

```
 P1: a(1)--send m1(1)-------------------------.
 P2:            b(1)-----recv m1 -> c(2)--send m2(3)-----.
 P3:  d(1)----------------------------------recv m2 -> e(4)
 Lamport: a<c<... causal chain gets increasing numbers; d (1) vs a (1) are concurrent but
 Lamport alone cannot tell you that; vector clocks can.
```

Lamport and vector clocks in Python:

```python
class Lamport:
    def __init__(self): self.t = 0
    def tick(self): self.t += 1; return self.t
    def send(self): return self.tick()
    def recv(self, ts): self.t = max(self.t, ts) + 1; return self.t

class Vector:
    def __init__(self, me, procs): self.me, self.v = me, {p: 0 for p in procs}
    def tick(self): self.v[self.me] += 1; return dict(self.v)
    def recv(self, other):
        for p, n in other.items(): self.v[p] = max(self.v[p], n)
        return self.tick()

def compare(a, b):
    le = all(a[p] <= b[p] for p in a); ge = all(a[p] >= b[p] for p in a)
    return "equal" if le and ge else "before" if le else "after" if ge else "concurrent"

P = ["A", "B"]
a, b = Vector("A", P), Vector("B", P)
x = a.tick()            # A writes
y = b.tick()            # B writes without having seen x
assert compare(x, y) == "concurrent"      # a conflict a wall clock would hide
z = b.recv(x)           # B now merges A's history
assert compare(x, z) == "before"
```

Choosing a mechanism:
1. Need only a consistent total order, not concurrency detection: Lamport (with node ID tie-break) or a sequencer/log.
2. Need to detect conflicts between replicas: vector clocks / version vectors.
3. Need timestamps near real time that stay causal: HLC.
4. Need cross-region external consistency and own the hardware or cloud offering it: TrueTime-style bounded uncertainty.
5. Need mutual exclusion: lease plus fencing token via a consensus store.

## Trade-offs
- **Logical vs physical**: logical clocks are correct by construction but have no relation to real time (cannot answer "events in the last hour"); HLC bridges both.
- **Vector clock size vs precision**: per-client vectors grow without bound; per-replica vectors are compact but lose fidelity for client-side concurrency.
- **LWW vs conflict-preserving merge**: LWW is simple and lossy; siblings or CRDTs keep all information and push complexity to reads or merge functions.
- **Bounded-uncertainty clocks**: strong guarantees for latency cost (commit wait) and specialised infrastructure.

## Gotchas
- Last-write-wins on wall clocks: a node with a fast clock wins every conflict, and concurrent writes silently disappear (the classic Cassandra/Riak LWW data-loss story). Use it only where losing a write is acceptable.
- Time-of-day can go backwards; compute durations and timeouts from the monotonic clock.
- A paused process (GC, VM migration, laptop sleep) resumes believing its lease is valid. Check fencing tokens at the resource.
- Leap seconds, DST and time zones: store UTC and an offset or zone ID; many outages come from smearing differences between providers.
- Sorting logs by timestamp across hosts yields impossible orderings (response before request). Propagate causal IDs ([[unique-id-generation]] for sortable IDs, with the same skew caveats).
- Snowflake-style IDs embed wall time and break ordering guarantees under skew or rollback.
- Lamport timestamps of equal value are not "simultaneous"; they need a deterministic tie-break for total order.

## Related
- [[consistency-models]] - causal consistency is defined by happens-before
- [[replication]] - version vectors and LWW appear in multi-leader and leaderless setups
- [[consensus-raft-paxos]] - the alternative: agree on a total order instead of inferring it
- [[unique-id-generation]] - time-based IDs and their clock assumptions
- [[observability-logs-metrics-traces]] - trace IDs and span ordering across services
- [[failure-modes-and-fallacies]] - why you cannot distinguish a slow node from a dead one
- [[internationalization-and-localization]] - storing UTC plus IANA zones and DST-correct display

## References
- Lamport, Time, Clocks, and the Ordering of Events (CACM 1978).
- Kulkarni et al., Hybrid logical clocks (2014); Corbett et al., Spanner (OSDI 2012).
- Kleppmann, Designing Data-Intensive Applications, ch. 8 and 9.
