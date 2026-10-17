---
title: Change data capture (CDC)
category: data
tags: [cdc, change-data-capture, debezium, logical-decoding, wal, binlog, outbox, kafka-connect, replication-slot, derived-data]
use_cases:
  - "keep a search index, cache or warehouse in sync with Postgres without dual writes"
  - "publish domain events reliably from a service that writes to MySQL or Postgres"
  - "stream every row change of a legacy database to new services during a migration"
  - "replace a nightly full export with near-real-time incremental loads"
  - "our Postgres disk filled up because of a replication slot, what went wrong"
status: draft
last_verified: 2026-10-17
sources:
  - https://debezium.io/documentation/reference/stable/connectors/postgresql.html
  - https://debezium.io/documentation/reference/stable/connectors/mysql.html
  - https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
  - https://www.postgresql.org/docs/current/logicaldecoding.html
  - https://www.postgresql.org/docs/current/logical-replication.html
  - https://dev.mysql.com/doc/refman/8.4/en/binary-log.html
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 11 Stream Processing, section Change Data Capture"
---

# Change data capture (CDC)

## Summary
Change data capture turns every committed insert, update and delete in a database into an ordered stream of change events that other systems consume. Log-based CDC reads the database's own replication log (the Postgres write-ahead log, the MySQL binary log), so the application writes only to its database and derived stores (search indexes, caches, warehouses, other services) follow without dual writes. Debezium on Kafka Connect is the common open-source implementation; consumers must handle at-least-once delivery, per-key ordering and schema changes.

## Key concepts
- **Source of truth and derived data**: the database stays the system of record; every downstream copy is rebuildable from a snapshot plus the change stream (Kleppmann, DDIA ch. 11).
- **Capture methods**:
  - *Log-based*: read the replication log. Sees every committed change including deletes, adds little load to the write path, and preserves commit order. Postgres exposes it through **logical decoding** (output plugin such as the built-in `pgoutput`, a **publication** choosing tables, a **replication slot** tracking the consumer's position); MySQL through the **binlog** in `ROW` format.
  - *Trigger-based*: triggers copy each change into an audit table in the same transaction. Works without log access, but adds write cost to every statement.
  - *Query-based polling*: `SELECT ... WHERE updated_at > :last`. Simple, but misses hard deletes and intermediate updates between polls, and depends on every writer setting `updated_at`.
- **Change event**: key, `before` and `after` row images, operation (Debezium uses `c` create, `u` update, `d` delete, `r` read during a snapshot), source position (Postgres LSN, binlog file and position) and commit timestamp.
- **Snapshot then stream**: a new consumer first reads a consistent snapshot of existing rows, then streams changes from the log position at which the snapshot was taken, so nothing falls in the gap.
- **Offset**: the log position a consumer has durably processed. It is committed after the effect is applied, so a crash replays from the last offset: delivery is **at-least-once**.
- **Tombstone**: after a delete, Debezium can emit a second record with the same key and a null value so a log-compacted Kafka topic eventually drops the key.
- **Outbox via CDC**: the service inserts an event row into an `outbox` table in the same transaction as the state change; CDC publishes those rows (Debezium's outbox event router routes them to topics). The log, not application code, does the publishing, so events and state cannot diverge.

## When to use / scenarios
- Search index, cache or read model must follow a relational database within seconds ([[search-systems]], [[caching-strategies]], [[cqrs-and-event-sourcing]]).
- Incremental loads into a warehouse or lake instead of nightly full dumps ([[data-warehousing-and-olap]]).
- Reliable event publishing from a service: outbox table plus CDC ([[event-driven-architecture]], [[distributed-transactions-and-sagas]]).
- Strangler-fig migrations: stream a legacy database's changes into the new service's store while both run ([[migrating-monolith-to-services]]).
- When NOT to use:
  - Consumers need business events ("order placed"), not row diffs: publish intent-level events through an outbox rather than exposing internal tables, which couples every consumer to your schema.
  - One small table read occasionally: query it or poll it.
  - You need cross-service atomic updates: CDC is asynchronous and gives eventual consistency, not a distributed transaction.

## How it works / example

```
 app --tx--> Postgres ---WAL---> logical decoding (slot + publication)
                                   |
                         Debezium connector (Kafka Connect)
                                   |  one topic per table, partitioned by primary key
                                   v
                 Kafka topic  -->  sink: search indexer / cache invalidator / warehouse loader
                                   (idempotent upsert by key, guarded by source position)
```

Postgres prerequisites (from the logical decoding and Debezium docs): `wal_level = logical`, a role with the `REPLICATION` attribute, a publication for the captured tables, and one replication slot per connector. By default (`REPLICA IDENTITY DEFAULT`) update and delete events carry only the primary key as the old row; `ALTER TABLE ... REPLICA IDENTITY FULL` logs the whole old row at the cost of more WAL.

The code below simulates the parts a consumer must get right: a snapshot taken at a log position, streaming from that position with overlap, redelivery after a crash, out-of-order duplicates and deletes. The sink stays correct because it upserts by key and ignores any event whose source position is not newer than the one it already applied.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Change:
    lsn: int            # source log position, increases with commit order
    op: str             # "c" create, "u" update, "d" delete, "r" snapshot read
    key: int
    after: dict | None  # None for deletes

class SourceDB:
    """A table plus its change log, like Postgres rows plus WAL."""
    def __init__(self):
        self.rows, self.log, self.lsn = {}, [], 0

    def write(self, key, row):
        self.lsn += 1
        op = "u" if key in self.rows else "c"
        self.rows[key] = row
        self.log.append(Change(self.lsn, op, key, dict(row)))

    def delete(self, key):
        self.lsn += 1
        del self.rows[key]
        self.log.append(Change(self.lsn, "d", key, None))

    def snapshot(self):
        """Consistent copy of the rows plus the log position it reflects."""
        return self.lsn, [Change(self.lsn, "r", k, dict(v)) for k, v in sorted(self.rows.items())]

    def stream(self, from_lsn):
        return [c for c in self.log if c.lsn > from_lsn]

class Sink:
    """Derived store (search index, cache, read model) fed by CDC."""
    def __init__(self):
        self.docs, self.applied = {}, {}   # key -> doc, key -> last applied lsn

    def apply(self, ch: Change):
        if self.applied.get(ch.key, 0) >= ch.lsn:
            return                          # duplicate or stale: at-least-once makes these normal
        self.applied[ch.key] = ch.lsn       # kept for deletes too, so an old update cannot resurrect the row
        if ch.op == "d":
            self.docs.pop(ch.key, None)
        else:
            self.docs[ch.key] = ch.after

db = SourceDB()
for k in range(1, 6):
    db.write(k, {"name": f"item-{k}", "price": 10 * k})

# 1. Snapshot, while writes keep arriving.
snap_lsn, snapshot = db.snapshot()
db.write(2, {"name": "item-2", "price": 25})
db.delete(4)
db.write(6, {"name": "item-6", "price": 60})

sink = Sink()
for ch in snapshot:
    sink.apply(ch)

# 2. Stream from the snapshot position. Starting a little early (overlap) is harmless.
events = db.stream(snap_lsn - 2)
committed_offset = 0
for i, ch in enumerate(events):
    sink.apply(ch)
    if i == 1:
        committed_offset = ch.lsn           # connector commits its offset, then crashes

# 3. Restart from the committed offset: the tail is delivered again.
for ch in db.stream(committed_offset):
    sink.apply(ch)

# 4. A stale duplicate arrives late (e.g. from a retried producer): ignored.
sink.apply(Change(lsn=1, op="c", key=4, after={"name": "item-4", "price": 40}))

assert sink.docs == db.rows, (sink.docs, db.rows)
assert 4 not in sink.docs and sink.docs[2]["price"] == 25
print(f"sink matches source: {len(sink.docs)} rows, last lsn {db.lsn}")
```

Typical Debezium Postgres connector settings (Kafka Connect JSON); names follow the Debezium connector docs:

```
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "plugin.name": "pgoutput",
  "database.hostname": "db", "database.dbname": "shop",
  "database.user": "cdc", "database.password": "${file:/secrets/cdc.properties:password}",
  "topic.prefix": "shop",
  "table.include.list": "public.orders,public.outbox",
  "slot.name": "debezium_shop",
  "publication.name": "dbz_shop",
  "snapshot.mode": "initial"
}
```

## Trade-offs
- **Log-based vs trigger vs polling**: log-based is the most complete and cheapest for the source, but needs database privileges, configuration and a connector to operate; triggers work everywhere at a write-path cost; polling is trivial but lossy for deletes and fast-changing rows.
- **Row events vs outbox events**: raw table changes need no application code but leak the internal schema to every consumer; outbox events are a deliberate public contract at the cost of writing them.
- **Kafka Connect vs embedded**: Debezium on Kafka Connect gives offsets, scaling and many sinks; Debezium Server or the embedded engine avoid running Kafka when the destination is elsewhere.
- **Full row images vs keys only**: `REPLICA IDENTITY FULL` (Postgres) or `binlog_row_image=FULL` (MySQL) give consumers old values for diffs and filtering, and cost more log volume.
- **Freshness vs load**: CDC lag is usually seconds; a warehouse may still prefer micro-batches of the stream for cost.

## Gotchas
- **Replication slots retain WAL** until the consumer confirms it. A stopped or deleted connector with its slot left behind fills the primary's disk. Monitor slot lag (`pg_replication_slots`), drop unused slots, and consider `max_slot_wal_keep_size` to cap retention (the slot is invalidated instead of the disk filling).
- **No global order**: order holds per key when topics are partitioned by primary key; events across tables or partitions can interleave, and transaction boundaries are not preserved unless you consume Debezium's transaction metadata.
- **DDL is not in the logical stream** in Postgres: schema changes must be coordinated with consumers (expand/contract, a schema registry for Avro/Protobuf/JSON Schema), see [[schema-migrations]].
- **Large unchanged values**: Postgres omits unchanged TOASTed columns from update events unless the replica identity is FULL; Debezium then emits a placeholder value that sinks must not write over the real data.
- **Failover**: a replica promoted to primary must have the slot (or the connector must re-snapshot); check your Postgres version's support for failover slots before relying on it.
- **Re-snapshots** of large tables load the source and re-emit every row; sinks must be idempotent and sized for the burst.
- Hard deletes need tombstones or explicit delete handling downstream, or deleted rows live forever in the index.
- Capturing tables with personal data copies it into Kafka and every sink; apply retention and erasure there too ([[privacy-and-pii-handling]]).

## Related
- [[event-driven-architecture]] - outbox pattern and events as the integration backbone.
- [[message-queues-and-streams]] - Kafka topics, partitions and log compaction that carry change events.
- [[batch-and-stream-processing]] - transforming and joining change streams.
- [[idempotency-and-exactly-once]] - why sinks must deduplicate under at-least-once delivery.
- [[replication]] - the same log, used for database replicas.
- [[search-systems]] - keeping a search index in sync from the source database.
- [[migrating-monolith-to-services]] - CDC to move data while old and new systems both run.
- [[data-warehousing-and-olap]] - incremental loads from operational databases.

## References
- Debezium connector for PostgreSQL: https://debezium.io/documentation/reference/stable/connectors/postgresql.html
- Debezium connector for MySQL: https://debezium.io/documentation/reference/stable/connectors/mysql.html
- Debezium outbox event router: https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
- PostgreSQL documentation, Logical Decoding: https://www.postgresql.org/docs/current/logicaldecoding.html
- PostgreSQL documentation, Logical Replication (publications, replica identity): https://www.postgresql.org/docs/current/logical-replication.html
- MySQL 8.4 Reference Manual, The Binary Log: https://dev.mysql.com/doc/refman/8.4/en/binary-log.html
- Martin Kleppmann, *Designing Data-Intensive Applications*, ch. 11 "Stream Processing", "Change Data Capture".
