---
title: Gossip protocols and failure detection
category: distributed-systems
tags: [gossip, epidemic-protocols, swim, phi-accrual, failure-detector, heartbeat, membership, anti-entropy, memberlist, cassandra]
use_cases:
  - "keep a list of live cluster members without a central coordinator"
  - "detect crashed nodes quickly without false alarms during GC pauses or network jitter"
  - "spread cluster metadata (ring ownership, schema version) to hundreds of nodes"
  - "heartbeats to every node do not scale as the cluster grows"
  - "choose a failure detector timeout or phi threshold for a peer-to-peer cluster"
status: draft
last_verified: 2026-10-24
sources:
  - "Demers et al., Epidemic Algorithms for Replicated Database Maintenance (PODC 1987)"
  - "Das, Gupta and Motivala, SWIM: Scalable Weakly-consistent Infection-style Process Group Membership Protocol (DSN 2002)"
  - "Hayashibara, Defago, Yared and Katayama, The Phi Accrual Failure Detector (SRDS 2004)"
  - "Chandra and Toueg, Unreliable Failure Detectors for Reliable Distributed Systems (JACM 1996)"
  - "Dadgar, Phillips and Currey, Lifeguard: Local Health Awareness for More Accurate Failure Detection (2018), https://arxiv.org/abs/1707.00788"
  - https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf
  - https://github.com/hashicorp/memberlist
  - https://cassandra.apache.org/doc/latest/cassandra/architecture/dynamo.html
---

# Gossip protocols and failure detection

## Summary
A gossip (epidemic) protocol spreads information by having each node
periodically exchange state with a few randomly chosen peers, so an update
reaches the whole cluster in a number of rounds that grows with the logarithm
of the cluster size, with no coordinator and constant work per node. A failure
detector decides when a silent node should be treated as dead. Peer-to-peer
systems (Cassandra, Riak, Consul/Serf via HashiCorp memberlist, Akka Cluster)
combine the two: gossip carries membership, and a detector such as SWIM's
probe scheme or the phi accrual detector turns missing heartbeats into
suspicion and then removal.

## Key concepts
- **Why detection is hard**: in an asynchronous network a slow node and a
  dead node look the same, so every detector trades detection time against
  false positives (Chandra and Toueg: detectors are classified by
  completeness and accuracy; perfect ones are impossible in this model).
- **All-to-all heartbeats** cost O(n^2) messages per interval; a central
  monitor is a single point of failure. Gossip spreads the load.
- **Gossip styles** (Demers et al.): *anti-entropy* (peers compare full state
  or digests and reconcile, so everything converges eventually) and *rumor
  mongering* (spread a new update for a while, then stop). Exchanges can be
  push, pull or push-pull.
- **Dissemination speed**: each informed node tells a few random peers per
  round, so the informed set roughly multiplies each round and the whole
  cluster learns in O(log n) rounds; a small fraction may be missed, which
  anti-entropy repairs.
- **Heartbeat counters and versions**: each node increments its own counter;
  gossip merges by taking the higher version per node, so stale information
  never overwrites newer information.
- **SWIM**: each protocol period a node pings one random member; with no ack,
  it asks k other members to ping it (*indirect probe*) before declaring it
  *suspect*; a suspect that does not refute (by gossiping a higher
  incarnation number) is declared *dead*. Membership changes ride piggybacked
  on probe messages. Load per member is constant regardless of cluster size.
- **Phi accrual detector**: instead of a yes/no timeout, keep a window of
  recent heartbeat inter-arrival times and output a suspicion level
  `phi = -log10(P(next heartbeat arrives later than now))`. Suspecting at
  phi 1 is wrong about 10% of the time, at phi 2 about 1%, and so on (under
  the detector's model of inter-arrival times). The application
  picks a threshold; Cassandra exposes it as `phi_convict_threshold`.
- **Lifeguard** (memberlist): a node that is itself slow (CPU starved, GC)
  should not accuse others; local health awareness widens its own timeouts
  and lowers false positives.

## When to use / scenarios
- Peer-to-peer data stores and clusters of tens to thousands of nodes that
  need membership and metadata without a coordinator
  ([[design-key-value-store]], [[consistent-hashing]]).
- Service discovery and health propagation across many agents (Consul and
  Serf use memberlist).
- Spreading slowly changing cluster metadata: ring ownership, schema
  versions, load figures.
- When NOT to: when you need agreement (exactly one leader, a linearizable
  config change, a lock), gossip only gives eventual convergence; use
  consensus ([[consensus-raft-paxos]], [[distributed-locks-and-leader-election]]).
  For a handful of services behind a load balancer or Kubernetes, use the
  platform's health checks ([[health-checks-and-graceful-shutdown]]).

## How it works / example

```
round 0: A knows update U
round 1: A -> C            (informed: A, C)
round 2: A -> F, C -> B    (informed: A, B, C, F)
round 3: each of 4 tells 1 (up to 8) ... ~log2(n) rounds to reach everyone

SWIM probe from A to D:
A --ping--> D        no ack within timeout
A --ping-req(D)--> B, E      B, E --ping--> D
no ack via anyone -> D suspect -> (no refutation in time) -> D dead, gossiped
```

A simulation of push gossip spread plus a phi accrual detector (stdlib only):

```python
import math
import random
import statistics

random.seed(7)

# 1. Push gossip: each informed node tells `fanout` random peers per round.
def rounds_to_spread(n, fanout=1):
    informed, rounds = {0}, 0
    while len(informed) < n:
        for node in list(informed):
            for peer in random.sample(range(n), fanout):
                informed.add(peer)
        rounds += 1
    return rounds

for n in (16, 256, 4096):
    r = rounds_to_spread(n)
    print(f"n={n:5d} rounds={r:2d} log2(n)={math.log2(n):.0f}")
    assert r <= 4 * math.log2(n)          # logarithmic, not linear, in n

# 2. Phi accrual: suspicion grows with silence relative to past intervals.
class PhiAccrual:
    def __init__(self, window=100, min_std=0.05):
        self.intervals, self.window, self.min_std = [], window, min_std
        self.last = None

    def heartbeat(self, t):
        if self.last is not None:
            self.intervals = (self.intervals + [t - self.last])[-self.window:]
        self.last = t

    def phi(self, now):
        mean = statistics.fmean(self.intervals)
        std = max(statistics.pstdev(self.intervals), self.min_std)
        # P(heartbeat arrives later than `now`) under a normal model
        p_later = 0.5 * math.erfc((now - self.last - mean) / (std * math.sqrt(2)))
        return -math.log10(max(p_later, 1e-300))

det = PhiAccrual()
t = 0.0
for _ in range(50):                       # heartbeats every ~1 s with jitter
    t += random.uniform(0.9, 1.1)
    det.heartbeat(t)

phis = {silence: det.phi(t + silence) for silence in (0.5, 1.0, 1.3, 2.0)}
for silence, value in phis.items():
    print(f"silent {silence:.1f}s -> phi {value:.1f}")
THRESHOLD = 8.0
assert phis[0.5] < 1 and phis[1.0] < THRESHOLD   # normal gap: not suspected
assert phis[2.0] > THRESHOLD                      # two missed beats: convict
assert phis[0.5] < phis[1.3] < phis[2.0]          # monotonic in silence
```

## Trade-offs
- **Detection time vs false positives**: a low threshold or short timeout
  fails over quickly but evicts nodes during GC pauses or brief packet loss;
  each false eviction causes data movement or a needless failover.
- **Fanout and interval vs bandwidth**: more peers per round and shorter
  periods converge faster and cost more network and CPU.
- **Rumor mongering vs anti-entropy**: rumors are cheap but can miss nodes;
  periodic full-state or digest exchange guarantees convergence at higher
  cost. Most systems run both.
- **Gossip vs coordination service**: gossip has no single point of failure
  and scales, but views are only eventually consistent; ZooKeeper or etcd
  give one agreed view at the cost of a quorum-based cluster to run.
- **Fixed timeout vs accrual**: a fixed timeout is easy to reason about; an
  accrual detector adapts to each link's observed jitter but needs a warm-up
  window and a chosen threshold.

## Gotchas
- Treating "suspected" as "dead": a partition can make each side suspect the
  other. Pair detection with fencing or quorum before taking irreversible
  action ([[distributed-locks-and-leader-election]]).
- A restarted node reusing an old identity without bumping its generation or
  incarnation number is ignored as stale, or its old state resurrects.
- Removed nodes coming back through gossip from a peer that has not heard of
  the removal; keep tombstones for removed members long enough to spread.
- Gray failure: a node answers heartbeats but fails real requests. Combine
  membership liveness with request-level signals (error rates, outlier
  ejection) ([[failure-modes-and-fallacies]], [[resilience-patterns]]).
- Mixed network: gossip over WAN links with the same timeouts as LAN causes
  churn; tune per network or use separate pools (memberlist has WAN and LAN
  default configs).
- Clock-based heartbeats compare wall clocks across machines; measure
  intervals with the receiver's monotonic clock ([[time-clocks-and-ordering]]).
- Large cluster state in every gossip message grows bandwidth with n; gossip
  digests and send only differences.

## Related
- [[failure-modes-and-fallacies]] - why a silent node cannot be told apart from a slow one.
- [[design-key-value-store]] - gossip membership, hinted handoff and anti-entropy in a Dynamo-style store.
- [[consistent-hashing]] - the ring whose membership gossip distributes.
- [[consensus-raft-paxos]] - when you need agreement rather than eventual convergence.
- [[distributed-locks-and-leader-election]] - fencing tokens before acting on a suspicion.
- [[replication]] - read repair and Merkle-tree anti-entropy, the data-level cousins of gossip.
- [[health-checks-and-graceful-shutdown]] - platform-level health checking for services behind a load balancer.

## References
- A. Demers et al., "Epidemic Algorithms for Replicated Database Maintenance", PODC 1987 (anti-entropy and rumor mongering).
- A. Das, I. Gupta, A. Motivala, "SWIM: Scalable Weakly-consistent Infection-style Process Group Membership Protocol", DSN 2002: https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf
- N. Hayashibara, X. Defago, R. Yared, T. Katayama, "The Phi Accrual Failure Detector", SRDS 2004.
- T. D. Chandra, S. Toueg, "Unreliable Failure Detectors for Reliable Distributed Systems", JACM 43(2), 1996.
- A. Dadgar, J. Phillips, J. Currey, "Lifeguard: Local Health Awareness for More Accurate Failure Detection": https://arxiv.org/abs/1707.00788
- HashiCorp memberlist (SWIM implementation used by Consul and Serf): https://github.com/hashicorp/memberlist
- Apache Cassandra documentation, "Dynamo" architecture (gossip and failure detection): https://cassandra.apache.org/doc/latest/cassandra/architecture/dynamo.html
- Martin Kleppmann, *Designing Data-Intensive Applications* (1st ed., 2017), ch. 8 "The Trouble with Distributed Systems" (timeouts and unreliable networks).
