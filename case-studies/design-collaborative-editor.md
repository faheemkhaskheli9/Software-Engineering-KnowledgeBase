---
title: Design a collaborative editor (Google Docs-like)
category: case-studies
tags: [collaborative-editing, google-docs, operational-transformation, crdt, realtime, presence, offline, conflict-resolution, case-study]
use_cases:
  - "design Google Docs or Notion style real-time co-editing where several users type in one document"
  - "merge concurrent edits so every client converges to the same text without locking"
  - "choose between operational transformation and CRDTs for a collaborative feature"
  - "support offline editing that merges cleanly when the user reconnects"
  - "show live cursors and presence of other editors"
status: draft
last_verified: 2026-10-10
sources:
  - "Ellis and Gibbs, 'Concurrency Control in Groupware Systems', SIGMOD 1989"
  - "Shapiro, Preguica, Baquero, Zawirski, 'Conflict-free Replicated Data Types', SSS 2011"
  - https://www.inkandswitch.com/local-first/
  - https://www.figma.com/blog/how-figmas-multiplayer-technology-works/
  - https://docs.yjs.dev/
  - https://automerge.org/docs/hello/
---

# Design a collaborative editor (Google Docs-like)

## Summary
Several users edit the same document at once, each seeing their own typing
instantly and everyone else's within a fraction of a second, and all copies
must converge to the same content without anyone's edits being lost. Edits
are applied optimistically on the client and exchanged as small operations;
a merge algorithm makes concurrent operations commute. The two families are
**operational transformation** (OT, a server orders operations and transforms
concurrent ones against each other, the classic Google Docs approach) and
**CRDTs** (operations carry unique IDs so any replica can merge in any order,
used by Yjs and Automerge). The rest of the system is a realtime session
service, an operation log with snapshots, and presence.

## Key concepts
- **Optimistic local apply**: the client applies its own edit immediately and sends the operation; the network never blocks typing.
- **Convergence**: after all operations are delivered, every replica has identical state, regardless of delivery order.
- **Intention preservation**: an insert lands where the user meant it, even after concurrent edits shifted positions.
- **OT**: transform `op_a` against concurrent `op_b` (shift positions) so applying them in either order gives the same result. Simplest with a central server that assigns a total order (revision numbers).
- **CRDT for text**: each character has a unique, ordered ID (e.g. site ID + counter); inserts reference neighbours by ID, deletes leave tombstones. No central ordering needed, which suits peer-to-peer and offline-first ([[consistency-models]]).
- **Presence** (cursors, selections, who is here) is ephemeral, lossy state sent on the same channel but never persisted.

## When to use / scenarios
- Documents, spreadsheets, whiteboards, design tools, code editors with live share.
- Offline-first apps that sync later (notes, field data): CRDTs fit naturally; see the Ink and Switch local-first essay.
- If users rarely edit the same thing at the same time, simpler is fine: per-field last-writer-wins, or locking a section while someone edits it. Figma's post explains why they used server-authoritative last-writer-wins per property rather than full OT for a design canvas.
- Whole-file sync with conflict copies is enough for binary files ([[design-file-sync]]).

## How it works / example

### 1. Requirements
Functional:
- Rich text editing by many concurrent users per document (assume up to ~50 active editors; huge audiences are viewers).
- See others' edits and cursors live; comments and suggestions (out of scope for v1).
- Version history: view and restore earlier versions.
- Offline editing for a while, merged on reconnect.
- Sharing with view/comment/edit permissions.

Non-functional:
- Local keystroke latency near zero; remote edits visible within a few hundred ms.
- Strong eventual consistency: all replicas converge; no acknowledged edit is lost.
- Durable: the operation log is persisted before acknowledging.
- Scale to many documents; most are idle at any time.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 5 M concurrently open documents, 10% actively edited, 1 op/s per active editor averaged after client batching -> about 500,000-1 M ops/s across the fleet, each tiny (tens of bytes).
- Per document the rate is low (tens of ops/s even with 50 editors), so a single owner process per document is affordable; total throughput scales by spreading documents across servers.
- Op log growth: 1 M ops/s x ~50 bytes -> 4 TB/day before compaction; snapshots plus truncating or compressing old ops keep it bounded.

### 3. API
Over a WebSocket per open document ([[realtime-websockets-sse]]):
```
-> {"type":"join","doc":"d1","since_rev":120}
<- {"type":"snapshot","rev":120,"content":...} or {"type":"ops","from_rev":121,"ops":[...]}
-> {"type":"op","base_rev":125,"client_seq":7,"op":{"ins":"X","pos":42}}
<- {"type":"ack","client_seq":7,"rev":126}
<- {"type":"op","rev":127,"author":"u2","op":{...}}
-> {"type":"presence","cursor":42,"selection":[40,45]}      (ephemeral, not stored)
HTTP: GET /docs/{id}/versions, POST /docs/{id}:restore, sharing via the permissions service
```

### 4. Data model
```
documents(doc_id, owner_id, title, latest_rev, snapshot_rev, created_at)
ops(doc_id, rev, author_id, client_id, client_seq, op_blob, ts)   PK (doc_id, rev)
     UNIQUE (doc_id, client_id, client_seq)                        -- dedupe client retries
snapshots(doc_id, rev, content_blob)                               -- every N ops; in object storage
acl(doc_id, principal, role)
```
Loading a document = latest snapshot + ops after it. Partition by `doc_id`
([[partitioning-and-sharding]]).

### 5. High-level architecture
```
 clients <==WebSocket==> LB --route by doc_id--> session servers (one owner per active doc)
                                                   | in-memory doc state, transform/merge
                                                   | append op -> ops store (durable) -> ack
                                                   | broadcast to other clients of the doc
 doc router: doc_id -> owner server (consistent hashing / lease in a coordination store)
 snapshotter (async): ops -> snapshot every N ops -> object storage
 presence: relayed by session server only, never stored
 permissions, history and search services over HTTP
```
One owner per active document gives a single place to assign revision numbers
(a total order), which is what makes OT simple. See [[consistent-hashing]],
[[load-balancing]].

### 6. Deep dive A: OT for concurrent inserts
The core of OT is a transform function. This minimal version handles inserts
only; ties at the same position are broken by site ID so both sides choose the
same order. Real implementations add deletes, formatting and composition of
operation sequences.

```python
from itertools import product

def apply(doc, op):
    pos, text, _site = op
    return doc[:pos] + text + doc[pos:]

def transform(op, against):
    """Rewrite `op` so it applies after `against` (both made on the same base)."""
    pos, text, site = op
    a_pos, a_text, a_site = against
    if a_pos < pos or (a_pos == pos and a_site < site):
        pos += len(a_text)
    return (pos, text, site)

base = "abc"
a = (1, "X", 1)                                   # site 1 inserts X at 1
b = (1, "Y", 2)                                   # site 2 concurrently inserts Y at 1
at_site_1 = apply(apply(base, a), transform(b, a))
at_site_2 = apply(apply(base, b), transform(a, b))
assert at_site_1 == at_site_2 == "aXYbc"

for pa, pb in product(range(len(base) + 1), repeat=2):   # converge for every position pair
    a, b = (pa, "XX", 1), (pb, "Y", 2)
    assert apply(apply(base, a), transform(b, a)) == apply(apply(base, b), transform(a, b))
```

With a central server: a client sends `op` with `base_rev`; the server
transforms it against every op committed since `base_rev`, assigns the next
revision, persists, acks and broadcasts. The client, meanwhile, transforms
incoming ops against its own unacknowledged ones (the Jupiter/Google Wave
style client-server protocol). That keeps transform cases to two parties
instead of N.

### 7. Deep dive B: CRDT alternative and offline
- A sequence CRDT (RGA, YATA in Yjs, Automerge's text type) gives each inserted character a unique ID and inserts "after ID x". Concurrent inserts after the same ID are ordered deterministically by ID, so merge is commutative and needs no server ordering.
- This makes offline and peer-to-peer editing natural: replicas exchange missing ops (or state vectors) whenever they connect.
- Costs: metadata per character and tombstones for deletes; libraries compress heavily, but documents with long histories still grow and need garbage collection, which is hard when some replica may be offline.
- A server is still useful with CRDTs: it relays, persists, enforces permissions and serves snapshots, but it does not need to transform.

### 8. Deep dive C: persistence, history and permissions
- Ack only after the op is durable in the ops store; a crashed session server loses nothing, and clients resend unacked ops (deduped by `(client_id, client_seq)`, [[idempotency-and-exactly-once]]).
- Snapshots every N ops bound load time; version history is a list of named snapshots plus the op log in between.
- Permissions are checked on join and on every op (a user can lose edit rights mid-session); view-only clients receive ops but cannot send them ([[authorization-models]]).
- Undo is per user: invert the user's own op and transform it against everything after it, not "revert to previous revision".

### 9. Scaling and failure handling
- **Owner failover**: the doc router's lease expires, a new server loads snapshot + ops and becomes owner; clients reconnect and resend from their last acked revision ([[consensus-raft-paxos]] for the lease store).
- **Split brain**: two servers both think they own a doc and assign conflicting revisions; the ops store's `PK (doc_id, rev)` rejects the second writer (a fence).
- **Large audiences**: broadcast to thousands of viewers through a pub/sub fan-out tier instead of the owner process ([[message-queues-and-streams]]).
- **Slow clients**: bounded send buffers; a lagging client is told to resync from a snapshot.
- **Monitoring**: op round-trip latency, transform/merge errors, reconnect rate, divergence checks (periodic content hash compare between server and clients).

## Trade-offs
- OT: compact ops and simple server-ordered model, but needs a central ordering point and transform functions are notoriously hard to get right for rich text.
- CRDT: no central ordering, great for offline and P2P, but per-character metadata and tombstone growth; mature libraries (Yjs, Automerge) make it practical.
- Fine-grained ops (every keystroke) feel live but cost more messages; batching every few tens of ms is the usual compromise.
- Last-writer-wins per property is far simpler and fine for structured data (canvases, forms) where concurrent edits to the same property are rare.

## Gotchas
- Sending whole-document state on every change: bandwidth and merge conflicts both explode.
- Transforming against ops in the wrong order or skipping the client-side transform of in-flight ops causes silent divergence; add content hash checks.
- Ordering by client wall-clock time ([[time-clocks-and-ordering]]).
- Cursor positions are indexes too: transform them like inserts, or cursors jump.
- Unicode: positions in UTF-16 code units (browsers) vs code points (server) disagree for emoji.
- Treating presence like data: persisting cursor moves floods the op log.

## Related
- [[realtime-websockets-sse]] - the transport for ops and presence
- [[consistency-models]] - strong eventual consistency and convergence
- [[time-clocks-and-ordering]] - logical ordering instead of wall clocks
- [[design-chat-system]] - similar session, fan-out and resync mechanics
- [[design-file-sync]] - whole-file sync with conflicted copies, the coarse-grained alternative
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Ellis and Gibbs, "Concurrency Control in Groupware Systems", SIGMOD 1989 (original OT)
- Shapiro et al., "Conflict-free Replicated Data Types", SSS 2011
- Kleppmann, Wiggins, van Hardenberg, McGranaghan, "Local-first software" (Ink and Switch, 2019): https://www.inkandswitch.com/local-first/
- Figma, "How Figma's multiplayer technology works": https://www.figma.com/blog/how-figmas-multiplayer-technology-works/
- Yjs documentation: https://docs.yjs.dev/
- Automerge documentation: https://automerge.org/docs/hello/
