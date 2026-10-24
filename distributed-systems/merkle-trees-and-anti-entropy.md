---
title: Merkle trees and anti-entropy
category: distributed-systems
tags: [merkle-tree, anti-entropy, hash-tree, replica-repair, data-reconciliation, inclusion-proof, transparency-log, content-addressing, dynamo, cassandra-repair]
use_cases:
  - "find which keys differ between two replicas of millions of rows without shipping all the data"
  - "repair replicas that drifted after missed writes, hinted handoff loss or a restored backup"
  - "sync files or directories between devices by comparing hashes top-down"
  - "prove a record is in an append-only log without sending the whole log"
  - "verify that two copies of a dataset (backup, migration, cross-region) are identical"
status: draft
last_verified: 2026-10-24
sources:
  - "Ralph C. Merkle, A Digital Signature Based on a Conventional Encryption Function, CRYPTO 1987"
  - "Alan Demers et al., Epidemic Algorithms for Replicated Database Maintenance, PODC 1987"
  - "Giuseppe DeCandia et al., Dynamo: Amazon's Highly Available Key-value Store, SOSP 2007"
  - https://www.rfc-editor.org/rfc/rfc6962
  - https://cassandra.apache.org/doc/latest/cassandra/managing/operating/repair.html
  - https://git-scm.com/book/en/v2/Git-Internals-Git-Objects
---

# Merkle trees and anti-entropy

## Summary
A Merkle tree (hash tree) hashes data blocks into leaves and hashes each pair
or group of child hashes into a parent, up to a single root. Two parties with
equal roots hold equal data (up to hash collisions); with different roots
they walk down only the subtrees whose hashes differ, finding the changed
blocks while exchanging a number of hashes proportional to the number of
differences times the tree depth, not to the data size. Anti-entropy is the
background process that uses this to make replicas converge (Dynamo,
Cassandra, Riak); the same structure gives inclusion proofs for transparency
logs (Certificate Transparency) and content addressing for Git and file sync.

## Key concepts
- **Leaf, interior node, root**: leaf = `H(block)`; parent =
  `H(child_1 || ... || child_k)`; root summarises everything. Any change to a
  block changes every hash on its path to the root.
- **Comparison by descent**: compare roots; if equal, stop. Otherwise compare
  children and recurse only into the differing ones. Cost is about
  `differences x fanout x depth` hashes, so it is cheap when replicas are
  nearly in sync and degrades towards "compare every leaf" when they are not.
- **Anti-entropy vs read repair vs hinted handoff** (Dynamo-style stores):
  read repair fixes stale replicas a read happens to touch; hinted handoff
  replays writes a peer missed while down; anti-entropy periodically compares
  whole key ranges and catches everything else (cold keys, lost hints).
  Demers et al. (1987) named and analysed anti-entropy for replicated
  databases ([[replication]], [[gossip-and-failure-detection]]).
- **Key-range trees**: Dynamo keeps one Merkle tree per key range a node
  owns, so two replicas of the same range can compare trees directly.
  Leaves are buckets of keys (by token or hash range), not single keys.
- **Inclusion (audit) proof**: to prove leaf `i` is in a tree with root `R`,
  send the sibling hashes along its path (about `log2(n)` hashes); the
  verifier recomputes the root. **Consistency proofs** show that a newer tree
  is an append-only extension of an older one (RFC 6962).
- **Domain separation**: RFC 6962 hashes leaves as `H(0x00 || data)` and
  interior nodes as `H(0x01 || left || right)` so a leaf can never be passed
  off as an interior node (a second-preimage attack on naive trees).
- **Merkle DAG / content addressing**: identify every object by the hash of
  its content and its children's hashes. Git trees and commits, IPFS and
  many backup and sync tools work this way: an unchanged subtree has the same
  hash, so it is neither re-sent nor re-stored.

## When to use / scenarios
- Leaderless or multi-leader replicated stores that need periodic repair of
  silent divergence ([[design-key-value-store]]).
- Verifying a migration, backup restore or cross-region copy: compare
  per-range hashes on both sides instead of row-by-row diffs over the network
  ([[backup-and-disaster-recovery]]).
- File and directory sync between devices or to a server: hash a directory
  as the hash of its entries and skip unchanged subtrees ([[design-file-sync]]).
- Tamper-evident, append-only logs where third parties need small proofs
  (certificate transparency, signed artifact logs such as Sigstore's Rekor)
  ([[audit-logs-and-temporal-data]], [[software-supply-chain-security]]).
- When NOT to use: a single leader with a replication log already tells you
  exactly what each follower has applied; compare log positions instead. For
  one large file with insertions that shift offsets, rsync's rolling checksum
  finds matching blocks at any offset, which fixed-boundary leaves cannot.
  For "what changed since time T", change data capture or a version column is
  simpler ([[change-data-capture]]).

## How it works / example

```
                    root = H(01 | A | B)
                   /                    \
        A = H(01 | L0 | L1)        B = H(01 | L2 | L3)
         /          \               /           \
   L0=H(00|b0)  L1=H(00|b1)   L2=H(00|b2)   L3=H(00|b3)

 replica X root != replica Y root  ->  compare A, B
 A equal, B differs                ->  compare L2, L3
 only L3 differs                   ->  sync keys in bucket 3 only
```

Two replicas bucket their keys by hash, build trees, find the differing
buckets by descent, sync only those keys, and verify an inclusion proof:

```python
import hashlib

def h(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()

def leaf_hash(data: bytes) -> bytes:
    return h(b"\x00", data)                       # RFC 6962 domain separation

def node_hash(left: bytes, right: bytes) -> bytes:
    return h(b"\x01", left, right)

BUCKETS = 16                                      # leaves; a power of two here

def bucket_of(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big") % BUCKETS

def build_tree(store: dict) -> list:
    """Return levels: levels[0] = leaf hashes, levels[-1] = [root]."""
    buckets = [[] for _ in range(BUCKETS)]
    for k, v in store.items():
        buckets[bucket_of(k)].append(f"{k}={v}")
    level = [leaf_hash("\n".join(sorted(b)).encode()) for b in buckets]
    levels = [level]
    while len(level) > 1:
        level = [node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        levels.append(level)
    return levels

def diff_buckets(a: list, b: list) -> tuple:
    """Descend from the root, comparing only children of differing nodes."""
    compared, frontier = 1, [0]
    if a[-1][0] == b[-1][0]:
        return [], compared
    for depth in range(len(a) - 2, -1, -1):           # root's children down to leaves
        nxt = []
        for parent in frontier:
            for child in (2 * parent, 2 * parent + 1):
                compared += 1
                if a[depth][child] != b[depth][child]:
                    nxt.append(child)
        frontier = nxt
    return frontier, compared

# Two replicas of 10,000 keys; replica y missed three writes.
x = {f"user:{i}": f"v{i}" for i in range(10_000)}
y = dict(x)
for k in ("user:42", "user:4242", "user:9001"):
    x[k] = "updated"

tx, ty = build_tree(x), build_tree(y)
bad, hashes_compared = diff_buckets(tx, ty)
assert 1 <= len(bad) <= 3
print(f"differing buckets {bad}; {hashes_compared} hashes compared, not 10,000 rows")

# Repair: exchange only keys in differing buckets (last-writer-wins is assumed
# here; real stores compare versions or vector clocks per key).
for k in [k for k in x if bucket_of(k) in bad]:
    if y.get(k) != x[k]:
        y[k] = x[k]
assert build_tree(y)[-1][0] == tx[-1][0]               # roots match after repair

def inclusion_proof(levels: list, index: int) -> list:
    proof = []
    for level in levels[:-1]:
        sibling = index ^ 1
        proof.append((sibling < index, level[sibling]))  # (sibling is left?, hash)
        index //= 2
    return proof

def verify(leaf: bytes, proof: list, root: bytes) -> bool:
    acc = leaf
    for sibling_is_left, sib in proof:
        acc = node_hash(sib, acc) if sibling_is_left else node_hash(acc, sib)
    return acc == root

proof = inclusion_proof(tx, 5)
assert len(proof) == 4                                  # log2(16) sibling hashes
assert verify(tx[0][5], proof, tx[-1][0])
assert not verify(leaf_hash(b"forged"), proof, tx[-1][0])
print("inclusion proof of", len(proof), "hashes verified")
```

## Trade-offs
- **Leaf granularity**: more, smaller leaves pinpoint differences precisely
  but make the tree larger to build, hold and exchange; fewer, larger leaves
  are cheap but force syncing many unchanged keys per mismatch. Systems pick
  a fixed depth per range and accept "overstreaming" some unchanged data.
- **Precomputed vs on-demand trees**: keeping trees updated on every write
  makes comparison instant but costs write-path CPU and memory; building them
  during repair (Cassandra builds them in a validation pass over the data)
  costs heavy disk I/O when repair runs, so it is scheduled and throttled.
- **Full vs incremental repair**: re-hashing all data each time is simple
  and catches everything; incremental schemes hash only data written since
  the last repair, which is cheaper but adds bookkeeping that must itself be
  correct.
- **Fanout**: binary trees give the smallest proofs per level; wider trees
  are shallower, so fewer round trips during descent but more hashes per
  level. Batch a whole level per round trip to hide latency.
- **Cryptographic vs fast hashes**: anti-entropy between trusted replicas can
  use a fast non-cryptographic hash and accept rare collisions; anything an
  adversary can influence (proofs, content addresses, transparency logs)
  needs a collision-resistant hash such as SHA-256.

## Gotchas
- Hashing a non-canonical encoding: two replicas with the same rows in a
  different order, encoding or float format get different hashes forever.
  Sort keys and serialise deterministically before hashing
  ([[schema-evolution-and-serialization]]).
- Trees built while writes are still arriving compare two moving targets;
  you will find "differences" that are just in-flight writes. Compare
  snapshots or tolerate and re-check.
- Odd node counts: duplicating the last hash to pad a level (as Bitcoin's
  original Merkle code did) lets two different lists share a root
  (CVE-2012-2459). Use the RFC 6962 split rule or include the leaf count.
- No leaf/interior domain separation: an attacker can present an interior
  node as a leaf and forge inclusion proofs.
- Repair that copies without merge rules resurrects deleted data. Deletes
  must exist as tombstones until every replica has seen them, and tombstones
  must not be purged before repair runs (Cassandra's `gc_grace_seconds` exists
  for this reason).
- Anti-entropy that never runs because it is "expensive": drift accumulates
  silently until a failover serves stale or missing data. Schedule it, track
  last successful repair per range and alert when it is overdue.
- Repair traffic competing with user traffic: throttle streaming, run one
  range at a time and keep it off peak ([[backpressure-and-load-shedding]]).
- Equal roots prove equal bytes, not correct bytes: both replicas can carry
  the same bad write. Repair is not a substitute for backups.

## Related
- [[replication]] - leaderless replicas, quorums, read repair and why they drift.
- [[gossip-and-failure-detection]] - epidemic protocols for membership; anti-entropy is the data-level counterpart.
- [[design-key-value-store]] - Dynamo-style store that uses per-range Merkle trees for repair.
- [[design-file-sync]] - content hashes and chunking to sync only changed files and blocks.
- [[audit-logs-and-temporal-data]] - hash-chained and Merkle-tree tamper-evident logs.
- [[software-supply-chain-security]] - transparency logs for signed artifacts.
- [[cryptography-and-tls]] - hash functions, collision resistance and Certificate Transparency.
- [[backup-and-disaster-recovery]] - verifying copies and restores against the source.

## References
- Ralph C. Merkle, "A Digital Signature Based on a Conventional Encryption Function", CRYPTO 1987.
- Alan Demers, Dan Greene, Carl Hauser et al., "Epidemic Algorithms for Replicated Database Maintenance", PODC 1987 (anti-entropy and rumor mongering).
- Giuseppe DeCandia et al., "Dynamo: Amazon's Highly Available Key-value Store", SOSP 2007, section 4.7 (Merkle trees per key range).
- RFC 6962, *Certificate Transparency*, section 2.1 (Merkle hash trees, audit and consistency proofs): https://www.rfc-editor.org/rfc/rfc6962
- Apache Cassandra documentation, "Repair": https://cassandra.apache.org/doc/latest/cassandra/managing/operating/repair.html
- Scott Chacon and Ben Straub, *Pro Git*, 2nd ed., "Git Internals - Git Objects": https://git-scm.com/book/en/v2/Git-Internals-Git-Objects
- Andrew Tridgell and Paul Mackerras, "The rsync algorithm", ANU technical report TR-CS-96-05, 1996.
- Martin Kleppmann, *Designing Data-Intensive Applications*, ch. 5 (read repair and anti-entropy in leaderless replication).
