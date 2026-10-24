---
title: Consistent hashing
category: distributed-systems
tags: [consistent-hashing, hash-ring, virtual-nodes, rendezvous-hashing, load-distribution, cache-sharding, dynamo]
use_cases:
  - "spread cache keys over nodes so adding or removing a node moves few keys"
  - "route each user or session to a stable backend so local state stays warm"
  - "build a sharded key-value store that rebalances smoothly when nodes join"
  - "pick a load-balancing hash that does not reshuffle all connections on a scale event"
status: draft
last_verified: 2026-10-10
sources:
  - "Karger et al., Consistent Hashing and Random Trees (STOC 1997) https://dl.acm.org/doi/10.1145/258533.258660"
  - "DeCandia et al., Dynamo (SOSP 2007) https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf"
  - "Lamping and Veach, A Fast, Minimal Memory, Consistent Hash Algorithm (jump hash, 2014) https://arxiv.org/abs/1406.2294"
  - "Mirrokni et al., Consistent Hashing with Bounded Loads (2016) https://arxiv.org/abs/1608.01350"
  - "Xu, System Design Interview (Alex Xu), ch. 5 Design Consistent Hashing"
---

# Consistent hashing

## Summary
Consistent hashing maps keys and nodes into the same hash space so that when a node is added or removed only about `1/N` of the keys move, instead of nearly all of them as with `hash(key) % N`. It is the standard way to distribute caches, shards and sessions over a changing set of servers.

## Key concepts
- **Hash ring**: hash space treated as a circle (for example 0..2^32-1). Hash each node onto the ring; a key belongs to the first node clockwise from `hash(key)`.
- **Minimal movement**: adding node X takes keys only from X's clockwise successor; removing a node hands its keys only to its successor.
- **Virtual nodes (vnodes)**: each physical node appears at many ring positions (typically tens to hundreds). Smooths the load distribution, lets heterogeneous machines take weighted shares, and spreads a failed node's load over many peers instead of one.
- **Replication on the ring**: store each key on the next R distinct physical nodes clockwise (the preference list in Dynamo, Cassandra token ring).
- **Alternatives**:
  - *Rendezvous (HRW) hashing*: for each key compute `hash(node, key)` for every node and pick the highest. No ring, trivially even, O(N) per lookup.
  - *Jump consistent hash*: O(log N), no memory, but nodes can only be added/removed at the end (buckets numbered 0..N-1).
  - *Maglev hashing* (Google's load balancer): lookup table giving near-even spread with minimal disruption.
  - *Bounded-load variant*: cap each node's load at c x average and spill over to the next node; protects against hot nodes.

## When to use / scenarios
- Distributed cache (memcached clients, CDN edge selection): a node joins or dies without a cache stampede from remapping everything ([[caching-strategies]]).
- Sharded stores that rebalance by key range ownership (Dynamo, Cassandra, Riak) - see [[partitioning-and-sharding]].
- Sticky routing of users/tenants/connections to stateful workers; consistent hashing at a load balancer ([[load-balancing]]).
- Distributed rate limiters or pub/sub topics where one node must own each key.
- When NOT to use: a small fixed set of nodes that never changes (plain modulo is fine); when you need range queries (hashing destroys key order); when a central directory is acceptable and gives exact control.

## How it works / example

```
              0
          .-------.
       n3 |       | n1          key k hashes to position p; walk clockwise
     (v2) |  ring | (v1)        to the first vnode: owner(k) = n1
          |       |
       n2 |       | n3          add node n4: only keys between n4's predecessor
          '-------'             and n4 change owner (taken from n4's successor)
```

Runnable implementation with virtual nodes and a movement check:

```python
import bisect, hashlib

def h(s: str) -> int:
    return int.from_bytes(hashlib.md5(s.encode()).digest()[:8], "big")

class Ring:
    def __init__(self, nodes=(), vnodes=100):
        self.vnodes, self.keys, self.map = vnodes, [], {}
        for n in nodes: self.add(n)
    def add(self, node):
        for i in range(self.vnodes):
            p = h(f"{node}#{i}")
            bisect.insort(self.keys, p); self.map[p] = node
    def remove(self, node):
        for i in range(self.vnodes):
            p = h(f"{node}#{i}")
            self.keys.remove(p); del self.map[p]
    def get(self, key):
        i = bisect.bisect(self.keys, h(key)) % len(self.keys)   # wrap around
        return self.map[self.keys[i]]

keys = [f"user:{i}" for i in range(20000)]
r = Ring(["a", "b", "c", "d"])
before = {k: r.get(k) for k in keys}
r.add("e")
moved = sum(before[k] != r.get(k) for k in keys) / len(keys)
assert all(r.get(k) == "e" for k in keys if before[k] != r.get(k))  # keys only move TO the new node
print(f"moved fraction: {moved:.2f} (expect roughly 1/5)")
```

Rendezvous hashing in four lines, often simpler than a ring for small N:

```python
def hrw(nodes, key):
    return max(nodes, key=lambda n: h(f"{n}:{key}"))
```

Practical choices:
- Use 100-ish vnodes per node as a starting point and measure the distribution on your real keys; more vnodes means better balance but more memory and slower membership changes.
- Use a stable, well-mixed hash (MD5/xxHash/Murmur3); do not use Python's built-in `hash()` (randomised per process) or a non-uniform hash.
- Weight machines by giving bigger ones more vnodes.
- Distribute the ring membership via gossip or a coordination service so all clients agree, since disagreement means routing to the wrong node.

## Trade-offs
- **Ring with vnodes vs rendezvous**: ring is O(log V) lookup with memory proportional to nodes x vnodes; rendezvous is O(N) per lookup but no state and perfect symmetry. Ring wins for hundreds of nodes, rendezvous for small clusters and per-request routing.
- **Jump hash**: fastest and tiny, but bucket numbers must be contiguous, so it suits shard counts you only grow (and needs a bucket-to-server table).
- **Vnode count**: balance vs overhead; Cassandra moved from 256 to a smaller default for operational cost reasons (check current docs).
- **Strict balance vs minimal movement**: bounded-load hashing reduces hot spots but moves a few more keys.

## Gotchas
- Without vnodes, load is badly uneven (one node can own several times its fair share) and a failure dumps all its load on one neighbour, possibly cascading.
- Consistent hashing balances *keys*, not *load*: a hot key still lands on a single node. Mitigate with replication of hot items, key salting, or bounded loads. See also [[partitioning-and-sharding]].
- Different clients with different node lists (during deploys) route the same key to different nodes; cache hit rate drops or data goes to the wrong shard.
- Adding a node to a cache ring creates cold misses for the moved keys; warm it or ramp it up gradually.
- Changing the hash function or vnode naming scheme remaps everything; treat them as part of the data format.
- The ring only decides placement. Durability needs [[replication]]; failure detection needs health checks or gossip.

## Related
- [[partitioning-and-sharding]] - the problem consistent hashing is the placement answer to
- [[caching-strategies]] - the classic use: sharding a cache tier without stampedes
- [[load-balancing]] - hash-based stickiness and Maglev at the L4/L7 layer
- [[replication]] - preference lists place R replicas on successive ring nodes
- [[design-key-value-store]] - worked design that uses a ring plus quorum replication
- [[gossip-and-failure-detection]] - spreading ring membership and detecting failed nodes.

## References
- Karger et al., Consistent Hashing and Random Trees (STOC 1997).
- DeCandia et al., Dynamo (SOSP 2007).
- Lamping and Veach, Jump Consistent Hash (2014); Mirrokni et al., Bounded Loads (2016).
