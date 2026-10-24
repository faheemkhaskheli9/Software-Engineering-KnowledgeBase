---
title: Storage engines (B-tree and LSM-tree)
category: data
tags: [storage-engine, b-tree, lsm-tree, wal, fsync, memtable, sstable, compaction, bloom-filter, write-amplification, rocksdb, postgres, sqlite]
use_cases:
  - "choose between a B-tree database and an LSM-tree store for a write-heavy workload"
  - "understand why our database needs a write-ahead log and what fsync settings risk"
  - "tune RocksDB or Cassandra compaction because disk I/O or disk space keeps growing"
  - "explain read, write and space amplification when comparing storage engines"
  - "build a simple durable key-value store and recover it after a crash"
status: draft
last_verified: 2026-10-11
sources:
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 3 'Storage and Retrieval'"
  - "O'Neil, Cheng, Gawlick, O'Neil, The Log-Structured Merge-Tree (LSM-Tree), Acta Informatica 33 (1996) https://www.cs.umb.edu/~poneil/lsmtree.pdf"
  - https://github.com/facebook/rocksdb/wiki/Compaction
  - https://github.com/facebook/rocksdb/wiki/Leveled-Compaction
  - https://github.com/facebook/rocksdb/wiki/RocksDB-Bloom-Filter
  - https://github.com/facebook/rocksdb/wiki/Write-Stalls
  - https://www.postgresql.org/docs/current/wal-intro.html
  - https://www.postgresql.org/docs/current/wal-reliability.html
  - https://www.sqlite.org/wal.html
---

# Storage engines (B-tree and LSM-tree)

## Summary
A storage engine is the part of a database that lays bytes out on disk and finds them again. The two dominant designs are the
B-tree, which updates fixed-size pages in place (Postgres, MySQL InnoDB, SQLite), and the log-structured merge tree (LSM), which
buffers writes in memory and appends immutable sorted files that are merged in the background (RocksDB, LevelDB, Cassandra,
ScyllaDB). Both rely on a write-ahead log for crash safety. The choice is a trade between write cost, read cost and disk space,
usually framed as write, read and space amplification.

## Key concepts
- **Page**: the unit a B-tree reads and writes. Postgres writes 8 KB pages; a page holds sorted keys and child pointers (inner
  pages) or keys and rows/row pointers (leaf pages). An insert into a full page splits it into two and updates the parent.
- **Write-ahead log (WAL)**: every change is appended to a sequential log and flushed to stable storage before the data pages
  change. After a crash, the log is replayed (redo / roll-forward) to restore committed changes. Only the log must be flushed at
  commit, and one fsync can commit many concurrent transactions (group commit).
- **fsync**: the call that asks the OS and device to make written data durable. Durability is only as good as the storage stack's
  honesty about flushes (volatile drive caches, SSDs that ignore flush commands).
- **Torn page**: a power failure in the middle of a multi-sector page write leaves a half-old, half-new page. Postgres guards with
  full-page images in the WAL (`full_page_writes`).
- **Memtable**: the LSM in-memory sorted buffer (often a skip list) that receives writes after the WAL append.
- **SSTable (sorted string table)**: an immutable on-disk file of key-sorted records with a block index and usually a Bloom filter.
  A full memtable is flushed as a new SSTable.
- **Sorted run**: a set of SSTables that together hold one non-overlapping sorted key range. Reads must consult every run that might
  hold the key, newest first.
- **Compaction**: background merge of runs that discards overwritten values and deleted keys (tombstones) once safe.
  - **Leveled**: L1 and below each hold one sorted run split into non-overlapping files; each level is a size multiple of the
    previous. Minimises space amplification at the cost of read and write amplification.
  - **Size-tiered (RocksDB "universal")**: merges runs of similar size into bigger runs. Minimises write amplification at the cost
    of read and space amplification.
- **Amplification**: write amplification = bytes written to disk per byte written by the application; read amplification = disk
  reads (or files probed) per lookup; space amplification = bytes on disk per byte of live data.
- **Bloom filter**: a compact probabilistic set per SSTable. "Definitely absent" is always right, "maybe present" can be wrong, so
  point lookups skip most files that lack the key. Whole-key filters do not help range scans.

## When to use / scenarios
- **B-tree engine (the default relational choice)**: read-heavy or mixed OLTP, many secondary indexes, range scans, predictable read
  latency, transactions with row locking. Postgres, MySQL and SQLite all fit here; most applications never need to look further
  ([[database-indexing]], [[transactions-and-isolation-levels]]).
- **LSM engine**: sustained high write or ingest rates (event logs, metrics, time series, messaging, key-value stores), data larger
  than memory with mostly recent-key reads, or SSDs where you want sequential writes. Usually reached via Cassandra, ScyllaDB,
  RocksDB-backed systems or a key-value store ([[sql-vs-nosql]], [[design-key-value-store]]).
- Signals for LSM: write throughput is the bottleneck on a B-tree, random page writes dominate I/O, or the data is append-mostly.
- Do NOT pick LSM for a read-latency-sensitive workload with heavy point lookups of cold keys and frequent updates of the same keys
  unless you are prepared to tune compaction; and do not choose an engine at all when a managed database already fits.
- Do NOT write your own engine for production. Implementing one (like the example below) is worth doing to understand recovery.

## How it works / example
Write and read paths:

```
B-tree write:  WAL append -> fsync WAL at commit -> modify page in buffer cache -> page written back later (checkpoint)
B-tree read:   root page -> inner pages -> leaf page (O(log n) page reads, cached hot pages)

LSM write:     WAL append (fsync per policy) -> memtable insert -> ack
               memtable full -> flush to new SSTable (L0) -> background compaction L0 -> L1 -> ... -> Ln
LSM read:      memtable -> immutable memtables -> each SSTable/level newest to oldest
               (Bloom filter says absent? skip file : index -> block -> key); first hit wins; tombstone means deleted
```

A toy LSM store: memtable dict, WAL as a list of records, flush to sorted runs, merge compaction, newest-first reads, and crash
recovery by replaying the WAL.

```python
import bisect

TOMBSTONE = object()

class ToyLSM:
    def __init__(self, memtable_limit=3, wal=None, runs=None):
        self.limit = memtable_limit
        self.wal = wal if wal is not None else []    # stands in for an fsynced append-only file
        self.runs = runs if runs is not None else [] # each run: sorted list of (key, value); newest last
        self.memtable = {}
        for key, value in self.wal:                  # recovery: replay the log into a fresh memtable
            self.memtable[key] = value

    def put(self, key, value):
        self.wal.append((key, value))                # 1. log first (durability)
        self.memtable[key] = value                   # 2. then apply in memory
        if len(self.memtable) >= self.limit:
            self.flush()

    def delete(self, key):
        self.put(key, TOMBSTONE)                     # deletes are writes of a tombstone

    def flush(self):
        self.runs.append(sorted(self.memtable.items()))  # immutable sorted run (an SSTable)
        self.memtable = {}
        self.wal.clear()                             # log no longer needed once the run is durable

    def get(self, key):
        if key in self.memtable:
            v = self.memtable[key]
            return None if v is TOMBSTONE else v
        for run in reversed(self.runs):              # newest run first; first hit wins
            i = bisect.bisect_left(run, (key,))
            if i < len(run) and run[i][0] == key:
                v = run[i][1]
                return None if v is TOMBSTONE else v
        return None

    def compact(self):
        merged = {}
        for run in self.runs:                        # oldest to newest, so newer values overwrite
            merged.update(run)
        # ponytail: full merge into one run; real engines merge level by level and keep
        # tombstones until no older run can still hold the key
        self.runs = [sorted((k, v) for k, v in merged.items() if v is not TOMBSTONE)]

db = ToyLSM()
for i in range(7):
    db.put(f"k{i}", i)
db.put("k1", "new")
db.delete("k2")
assert len(db.runs) == 3 and db.get("k1") == "new" and db.get("k2") is None and db.get("k5") == 5

before = sum(len(r) for r in db.runs)
db.compact()
assert len(db.runs) == 1 and sum(len(r) for r in db.runs) < before   # stale versions dropped
assert db.get("k1") == "new" and db.get("k2") is None and db.get("k0") == 0

# Crash: memtable is lost, but WAL and flushed runs survive on "disk"
db.put("k9", 9)
assert db.memtable and db.wal
recovered = ToyLSM(wal=db.wal, runs=db.runs)
assert recovered.get("k9") == 9 and recovered.get("k1") == "new"
print("toy LSM ok")
```

SQLite and Postgres expose the same WAL idea as configuration:

```sql
-- SQLite: commit by appending to the WAL file; readers do not block the writer
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;     -- NORMAL skips the per-commit WAL sync: faster, but a power loss can roll back recent commits

-- Postgres: keep these on unless you accept losing committed transactions or torn pages
SHOW synchronous_commit;     -- on
SHOW full_page_writes;       -- on
```

## Trade-offs
- **Write vs read cost**: LSM turns random writes into sequential appends and background merges; B-trees pay a random page write
  per change but find a key in one root-to-leaf descent. LSM reads may probe several runs (read amplification), softened by Bloom
  filters and block caches.
- **Leveled vs size-tiered compaction**: leveled keeps space amplification low and reads cheaper, but rewrites data more often (per
  level, worst case about the level fanout). Tiered writes each byte about once per level but holds several overlapping runs and
  needs large transient free space during a big merge. RocksDB's universal default `max_size_amplification_percent` of 200 means a
  100-byte database may need up to 300 bytes of storage.
- **Predictability**: B-tree latency is steadier; LSM latency can spike when compaction falls behind or competes for disk bandwidth.
- **Space**: B-trees leave free space in pages and fragment after splits; LSM compresses immutable files well but temporarily stores
  multiple versions and tombstones.
- **Durability vs commit latency**: fsync on every commit is safe and slow; group commit, `synchronous=NORMAL` or async commit trade a
  window of recent commits for throughput. Decide per data class.
- **Bloom filter memory vs false positives**: RocksDB's default of about 10 bits per key gives roughly a 1% false positive rate;
  more bits cost memory, fewer cost wasted reads.

## Gotchas
- Trusting fsync on hardware that lies: volatile drive or controller caches and SSDs that ignore flushes lose "committed" data on
  power loss. Test with `pg_test_fsync` or similar and use power-loss-protected storage.
- Disabling `full_page_writes` or WAL sync to speed up a benchmark, then shipping the setting.
- Compaction debt: if ingest outpaces compaction, L0 files pile up, reads slow down, and engines throttle or stall writes. Watch
  pending compaction bytes and L0 file counts.
- Running an LSM disk near full: size-tiered compaction needs room for the output before it can delete the inputs.
- Tombstones are not free: range deletes or delete-heavy queues leave tombstones that every read must skip until compaction drops
  them; in replicated stores they must outlive repair or deleted data comes back ([[design-key-value-store]]).
- Random keys (UUIDv4) in a B-tree clustered index scatter writes across pages; time-ordered keys keep inserts at the right edge
  ([[unique-id-generation]]).
- Bloom filters only help point lookups; range scans still visit every overlapping run.
- SQLite WAL mode allows only one writer at a time; the WAL grows until a checkpoint (about 1000 pages by default), and a
  long-lived reader can prevent checkpoints from completing.

## Related
- [[database-indexing]] - B-tree indexes from the query side; this topic is the engine underneath
- [[transactions-and-isolation-levels]] - WAL is how committed transactions stay durable
- [[sql-vs-nosql]] - most NoSQL wide-column and KV stores are LSM-based
- [[design-key-value-store]] - worked design that uses an LSM engine per node
- [[replication]] - many databases ship their WAL to replicas
- [[data-warehousing-and-olap]] - columnar storage, the analytical counterpart to row-oriented engines
- [[distributed-locks-and-leader-election]] - fencing and leases for the coordination layer above storage
- [[probabilistic-data-structures]] - how the per-SSTable Bloom filters are sized and why they never give false negatives.

## References
- Kleppmann, *Designing Data-Intensive Applications*, ch. 3 "Storage and Retrieval" (hash indexes, SSTables, LSM-trees, B-trees).
- O'Neil et al., "The Log-Structured Merge-Tree (LSM-Tree)", Acta Informatica 1996: https://www.cs.umb.edu/~poneil/lsmtree.pdf
- RocksDB wiki, Compaction: https://github.com/facebook/rocksdb/wiki/Compaction
- RocksDB wiki, Leveled Compaction: https://github.com/facebook/rocksdb/wiki/Leveled-Compaction
- RocksDB wiki, Bloom Filter: https://github.com/facebook/rocksdb/wiki/RocksDB-Bloom-Filter
- RocksDB wiki, Write Stalls: https://github.com/facebook/rocksdb/wiki/Write-Stalls
- PostgreSQL, Write-Ahead Logging: https://www.postgresql.org/docs/current/wal-intro.html
- PostgreSQL, Reliability (write caches, torn pages): https://www.postgresql.org/docs/current/wal-reliability.html
- SQLite, Write-Ahead Logging: https://www.sqlite.org/wal.html
