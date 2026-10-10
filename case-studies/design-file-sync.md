---
title: Design a file sync service (Dropbox-like)
category: case-studies
tags: [file-sync, dropbox, google-drive, chunking, content-defined-chunking, deduplication, conflict-resolution, block-storage, case-study]
use_cases:
  - "design a Dropbox or Google Drive style service that syncs files across a user's devices"
  - "upload only the changed parts of large files and deduplicate identical blocks"
  - "detect and resolve conflicting edits made offline on two devices"
  - "notify devices of remote changes quickly without constant polling"
  - "practice the file storage and sync system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 15 'Design Google Drive'"
  - https://dropbox.tech/infrastructure/rewriting-the-heart-of-our-sync-engine
  - https://dropbox.tech/infrastructure/streaming-file-synchronization
  - https://rsync.samba.org/tech_report/
  - "Muthitacharoen, Chen, Mazieres, 'A Low-bandwidth Network File System', SOSP 2001"
  - https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
---

# Design a file sync service (Dropbox-like)

## Summary
Users drop files into a folder on one device and the same tree appears on
their other devices and on the web, with sharing and version history. The
design splits **file bytes** (cut into content-addressed blocks in object
storage) from **metadata** (the file tree, versions and block lists in a
database), and syncs by exchanging metadata changes plus only the blocks the
other side lacks. The hard parts are chunking so small edits upload little,
change notification, and conflicting offline edits.

## Key concepts
- **Block store**: files are split into blocks named by their hash (SHA-256). Identical blocks are stored once (dedup); an upload sends only blocks the server does not have.
- **Content-defined chunking (CDC)**: block boundaries are chosen by a rolling hash over the content (LBFS paper), so inserting bytes near the start shifts only one or two boundaries instead of every fixed-size block after it.
- **Metadata journal**: every change to a namespace (user's tree or shared folder) gets a monotonically increasing sequence number; a device syncs by asking for "changes since cursor N".
- **File version** = ordered list of block hashes + size + modification info. History is cheap because versions share blocks.
- **Conflict**: two devices edit the same file from the same base version; the server accepts the first, the second becomes a "conflicted copy" (Dropbox's documented behaviour) rather than a silent overwrite.
- **Notification**: long-poll or WebSocket tells a device "namespace changed, pull" ([[realtime-websockets-sse]]).

## When to use / scenarios
- Consumer or enterprise file sync and share, backup clients, design-asset sync.
- Syncing large binary artefacts between machines (game assets, datasets).
- For "users upload files, nobody edits them later" (photos, attachments) skip blocks and sync: upload whole objects to object storage with pre-signed URLs ([[blob-object-storage]]).
- For real-time co-editing of a document's content, use a collaborative editor model instead ([[design-collaborative-editor]]); file sync works at whole-file version granularity.

## How it works / example

### 1. Requirements
Functional:
- Upload, download, sync a folder tree across devices; web access.
- Version history and restore; delete with trash.
- Share files/folders with other users (view/edit).
- Offline edits sync when the device reconnects; conflicts are surfaced, never lost.

Non-functional:
- Durability first: never lose a file once the upload is acknowledged.
- Bandwidth efficiency: small edits to large files upload little; identical content uploads once.
- Changes appear on other online devices within seconds.
- Scale to large numbers of users and files, with very large files (multi-GB).

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 50 M users, 10 M daily active, average 10 GB stored -> 500 PB logical; dedup and compression reduce physical storage by an amount you must measure, not assume.
- Assume each DAU changes 20 files/day -> 200 M file versions/day -> about 2,300 metadata writes/s average, peaks higher during work hours.
- Metadata per version (path, block list of e.g. 4 MB blocks, timestamps) about 1 KB plus 32 bytes per block hash -> a few hundred GB/day of metadata: sharded database territory.
- Notification connections: millions of idle long-polls/WebSockets held concurrently.

### 3. API
```
POST /blocks:check     { hashes: [...] }                   -> { missing: [...] }
PUT  /blocks/{sha256}  <bytes>  (or pre-signed URL to object storage)
POST /files:commit     { ns_id, path, base_version, block_list, size, mtime }
                         -> 200 { version, journal_seq }  | 409 { conflict, server_version }
GET  /ns/{id}/changes?cursor=N&limit=     -> { entries: [...], cursor: M, has_more }
GET  /ns/{id}/notify?cursor=N             -> long-poll, returns when cursor is stale
GET  /blocks/{sha256}                     -> bytes (or CDN / pre-signed redirect)
```
Upload is "check, upload missing blocks, commit metadata". Commit is the
atomic step; blocks without a committed version are garbage-collected later.

### 4. Data model
```
namespaces(ns_id, owner_id, type)                 -- user root or shared folder
journal(ns_id, seq, path, file_id, version, op, ts)   PK (ns_id, seq)
files(file_id, ns_id, path, latest_version, is_deleted)
versions(file_id, version, block_list[], size, content_hash, device_id, created_at)
blocks(sha256 PK, size, storage_location, refcount)    -- bytes live in object storage
acl(ns_id, user_id, role)
```
Shard metadata by `ns_id` so one namespace's journal is ordered on one shard
([[partitioning-and-sharding]]). Shared folders are their own namespace and
are mounted into each member's tree, so a share does not copy metadata per user.

### 5. High-level architecture
```
 desktop/mobile client (watcher, local DB of synced state, chunker, block cache)
   |  1. check/upload missing blocks          |  3. long-poll notify
   v                                          v
 block service --> object storage (S3-like, multi-AZ)    notification service
   |                                          ^  publish ns changed
   v  2. commit                               |
 metadata service --> metadata DB (sharded by ns_id, per-ns journal) --> change events (queue)
                                                              |--> search indexing, previews, virus scan
```
See [[blob-object-storage]], [[message-queues-and-streams]], [[sql-vs-nosql]].

### 6. Deep dive A: chunking and dedup
Fixed-size blocks are simple, but an insert near the start of a file shifts
every later block, so everything re-uploads. Content-defined chunking picks
boundaries where a rolling hash of the last few bytes matches a pattern, so
boundaries move with the content.

```python
import hashlib, random

random.seed(7)
GEAR = [random.getrandbits(32) for _ in range(256)]

def chunks(data, mask=(1 << 11) - 1, min_size=512, max_size=16384):
    """Gear-hash content-defined chunking. Average chunk size is roughly mask+1 above min_size."""
    out, start, h = [], 0, 0
    for i, b in enumerate(data):
        h = ((h << 1) + GEAR[b]) & 0xFFFFFFFF
        size = i - start + 1
        if (size >= min_size and (h & mask) == 0) or size >= max_size:
            out.append(data[start:i + 1]); start, h = i + 1, 0
    if start < len(data):
        out.append(data[start:])
    return out

def manifest(data):
    return [hashlib.sha256(c).hexdigest() for c in chunks(data)]

original = random.randbytes(200_000)
edited = original[:1000] + b"INSERTED" + original[1000:]
old, new = manifest(original), manifest(edited)
to_upload = set(new) - set(old)
assert len(old) > 20
assert len(to_upload) <= 2              # only the chunk(s) around the edit change
assert b"".join(chunks(edited)) == edited
```

Real systems use a faster CDC variant (e.g. FastCDC) and larger averages
(megabytes), and compress blocks before upload. rsync's rolling-checksum
algorithm solves the related problem of diffing against a remote copy without
a shared block store.

### 7. Deep dive B: commit, journal and conflicts
1. Client commits `(path, base_version, block_list)`.
2. Metadata service, in one transaction on the namespace's shard: check every block exists, check `files.latest_version == base_version`, insert the new version, append a journal entry with the next `seq` ([[transactions-and-isolation-levels]]).
3. If `latest_version != base_version`, another device committed first: return 409. The client keeps the server version at the path and saves its own as "name (conflicted copy from laptop).ext". Nothing is lost and the user decides.
4. Other devices' notify long-polls return; they call `changes?cursor=` and download missing blocks.

Making commit idempotent (same block list and base for the same client request id) lets the client retry blindly after a timeout ([[idempotency-and-exactly-once]]).

### 8. Deep dive C: the client is half the system
- A local database records the last synced state (path -> version, block list), which lets the client distinguish "I changed it" from "server changed it" from "both changed it".
- File-system watchers miss events and editors save via temp file + rename; periodically rescan and compare hashes.
- Dropbox's "Rewriting the heart of our sync engine" post describes moving to a design that keeps explicit models of local, remote and synced trees, because ad-hoc client logic was a source of bugs.
- Upload large files with resumable multipart uploads so a dropped connection loses one part, not the whole file.

### 9. Scaling and failure handling
- **Durability**: object storage replicated across zones (or erasure-coded); commit only after blocks are durable. Back up metadata separately, since losing the block list loses the file even if the bytes survive.
- **Garbage collection**: decrement block refcounts when versions expire; delete blocks with refcount 0 after a grace period (a concurrent upload may be about to reference them).
- **Hot shared folders**: a folder shared with thousands of users has one journal; notification fan-out goes through the notification tier, not the DB.
- **Downloads**: serve blocks via CDN or pre-signed URLs ([[cdn-and-edge]]).
- **Security**: encrypt at rest, scope pre-signed URLs tightly, check ACLs on every metadata call ([[authorization-models]]). Cross-user dedup can leak "this file exists" to an attacker; many designs dedup per user or per namespace only.
- **Monitoring**: sync lag, commit conflict rate, upload failure rate, GC backlog.

## Trade-offs
- Fixed-size blocks (simple, fast) vs CDC (better dedup for inserts, more CPU on clients).
- Block size: small blocks dedup better and resume faster but multiply metadata; large blocks are the reverse.
- Global dedup saves storage but leaks information across users and complicates deletion; per-user dedup is safer.
- Conflicted copies are honest and lossless but push merging to users; automatic merging only works for formats you understand.
- Long-poll notify is simple and proxy-friendly; WebSocket is lower overhead per message but stateful.

## Gotchas
- Committing metadata before blocks are durable: other devices fetch a file whose bytes do not exist yet.
- Using modification time to detect changes: clocks differ between devices, and some tools preserve mtime; compare hashes.
- Case-insensitive file systems (macOS/Windows defaults) vs case-sensitive ones: `Report.txt` and `report.txt` collide.
- Path length, reserved names and invalid characters differ by OS.
- Renaming a big folder as delete+create of every file instead of one move operation.
- Deleting blocks the moment refcount hits zero races with in-flight uploads.

## Related
- [[blob-object-storage]] - where the block bytes live, multipart and pre-signed uploads
- [[transactions-and-isolation-levels]] - atomic commit and the base-version check
- [[partitioning-and-sharding]] - sharding metadata by namespace
- [[realtime-websockets-sse]] - change notification to devices
- [[design-collaborative-editor]] - content-level co-editing instead of whole-file versions
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 15
- Dropbox, "Rewriting the heart of our sync engine": https://dropbox.tech/infrastructure/rewriting-the-heart-of-our-sync-engine
- Dropbox, "Streaming File Synchronization": https://dropbox.tech/infrastructure/streaming-file-synchronization
- Tridgell and Mackerras, "The rsync algorithm": https://rsync.samba.org/tech_report/
- Muthitacharoen, Chen, Mazieres, "A Low-bandwidth Network File System", SOSP 2001 (content-defined chunking)
- Amazon S3 multipart upload: https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html
