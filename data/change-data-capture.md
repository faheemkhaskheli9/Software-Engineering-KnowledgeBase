---
title: Change data capture (CDC)
category: data
tags: [cdc, change-data-capture, debezium, logical-replication, binlog, wal, outbox, kafka-connect, data-sync]
use_cases:
  - "keep a search index or cache in sync with the primary database without dual writes"
  - "stream every insert, update and delete from Postgres or MySQL into Kafka"
  - "feed a data warehouse continuously instead of nightly full exports"
  - "publish domain events reliably from an outbox table"
  - "replicate a monolith's table into a new service's database during a migration"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://debezium.io/documentation/reference/stable/index.html
  - https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
  - https://www.postgresql.org/docs/current/logicaldecoding.html
  - https://www.postgresql.org/docs/current/logical-replication.html
  - https://dev.mysql.com/doc/refman/8.4/en/binary-log.html
---

# Change data capture (CDC)

## Summary
Change data capture turns the committed changes of a database (inserts,
updates, deletes) into an ordered stream that other systems consume: search
indexes, caches, warehouses, other services. Log-based CDC reads the
database's own replication log (Postgres WAL via logical decoding, MySQL
binlog), so it sees every committed change, including deletes, without
touching application code. It replaces fragile dual writes, where the
application writes to the database and to a second system and the two drift
apart when one write fails.

## Key concepts
- **System of record and derived data**: the database is the source of truth;
  everything fed by CDC is a derived view that can be rebuilt from a snapshot
  plus the stream (Kleppmann, DDIA ch. 11 "Databases and Streams").
- **Capture methods**:
  - *Log-based*: read the transaction log. Captures every committed change
    in commit order, including deletes, with low load on the source. Needs
    database configuration and privileges.
  - *Trigger-based*: database triggers copy each change into a changelog
    table. Works anywhere triggers do; adds write cost to every transaction.
  - *Query-based (polling)*: `SELECT ... WHERE updated_at > :last`. Simple,
    but misses hard deletes, can miss rows when timestamps collide or commit
    out of order, and loses intermediate states.
- **Change event**: key, operation, before and after images, source position
  and timestamp. Debezium events carry `before`, `after`, `source`, `op`
  (`c` create, `u` update, `d` delete, `r` snapshot read) and `ts_ms`.
- **Initial snapshot**: a consistent copy of existing rows, followed by the
  stream from the log position the snapshot corresponds to, with no gap and
  no change applied twice in effect.
- **Offset / position**: the consumer's place in the log (Postgres LSN,
  MySQL binlog file and position or GTID). Stored durably so a restart
  resumes; delivery is usually at-least-once, so consumers must be
  idempotent ([[idempotency-and-exactly-once]]).
- **Replication slot** (Postgres): server-side state that remembers how far a
  logical consumer has read and retains WAL until it confirms.
- **Ordering**: changes to one row arrive in order; ordering across rows or
  tables is only kept if the pipeline keeps one partition per key or table.
  Debezium uses the primary key as the Kafka message key.
- **Tombstone**: after a delete event, a message with the key and a null
  value so a compacted Kafka topic can drop the key.
- **Outbox via CDC**: the application writes an event row to an `outbox`
  table in the same transaction as the state change; CDC publishes it. This
  is the reliable alternative to "commit, then publish"
  ([[distributed-transactions-and-sagas]]).

## When to use / scenarios
- A search index, cache or read model must follow a relational database:
  CDC instead of writing to both from application code.
- Continuous loading of a warehouse or lake ([[data-warehousing-and-olap]]).
- Publishing domain events from a service: outbox table plus CDC.
- Migrating data out of a monolith while both sides run
  ([[migrating-monolith-to-services]]).
- Audit trails and cache invalidation driven by actual commits.
- When NOT to use: the consumer needs business intent ("order cancelled by
  customer") rather than row diffs; publish explicit domain events through an
  outbox instead of exposing internal tables. Low-volume nightly reporting:
  a batch export is simpler. Same-database read scaling: use
  [[replication]] read replicas.

## How it works / example

```
app --tx--> [orders table]      (outbox rows in the same tx)
                 |
           WAL / binlog  --> CDC connector (Debezium) --> topic per table
                 ^                    | offset/LSN          |
           replication slot           v                     v
                                consumers: search index, cache, warehouse
```

A runnable trigger-based CDC with SQLite: triggers append every change to a
changelog with a monotonically increasing sequence number; a consumer applies
the changes to a derived "search index" and stores its offset, so a replay
after a crash is harmless. The last part shows why polling `updated_at`
cannot see deletes.

```python
import json
import sqlite3

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price INTEGER,
                       updated_at INTEGER);
CREATE TABLE changelog (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        op TEXT, id INTEGER, after TEXT);
CREATE TRIGGER p_ins AFTER INSERT ON products BEGIN
  INSERT INTO changelog(op, id, after) VALUES ('c', NEW.id,
    json_object('name', NEW.name, 'price', NEW.price));
END;
CREATE TRIGGER p_upd AFTER UPDATE ON products BEGIN
  INSERT INTO changelog(op, id, after) VALUES ('u', NEW.id,
    json_object('name', NEW.name, 'price', NEW.price));
END;
CREATE TRIGGER p_del AFTER DELETE ON products BEGIN
  INSERT INTO changelog(op, id, after) VALUES ('d', OLD.id, NULL);
END;
""")

def write(sql, *args):
    with db:                       # one transaction: row change + changelog row
        db.execute(sql, args)

write("INSERT INTO products VALUES (1, 'lamp', 30, 1)")
write("INSERT INTO products VALUES (2, 'desk', 200, 1)")
write("UPDATE products SET price = 25, updated_at = 2 WHERE id = 1")
write("DELETE FROM products WHERE id = 2")

class SearchIndexConsumer:
    def __init__(self):
        self.index = {}            # derived view
        self.offset = 0            # stored durably in a real system

    def poll(self, batch=100):
        rows = db.execute("SELECT seq, op, id, after FROM changelog "
                          "WHERE seq > ? ORDER BY seq LIMIT ?",
                          (self.offset, batch)).fetchall()
        for seq, op, key, after in rows:
            if op == "d":
                self.index.pop(key, None)          # delete is idempotent
            else:
                self.index[key] = json.loads(after)  # upsert is idempotent
            self.offset = seq
        return len(rows)

c = SearchIndexConsumer()
c.poll()
assert c.index == {1: {"name": "lamp", "price": 25}}

# Crash before saving the offset: replaying from 0 converges to the same state.
replay = SearchIndexConsumer()
replay.poll()
replay.offset = 0
replay.poll()
assert replay.index == c.index

# Polling on updated_at never sees the deleted row: 'desk' stays in the copy.
copy = {r[0]: r[1] for r in db.execute("SELECT id, name FROM products")}
copy[2] = "desk"                  # what a poller copied before the delete
for rid, name in db.execute("SELECT id, name FROM products WHERE updated_at > 1"):
    copy[rid] = name
assert 2 in copy                  # stale: the delete was invisible to the poller
print("index:", c.index, "offset:", c.offset, "stale poll copy:", copy)
```

In production the same shape comes from log-based CDC: Postgres with
`wal_level = logical` and a publication, or MySQL with row-based binlog,
read by a connector such as Debezium on Kafka Connect, which snapshots
first, then streams from the slot or binlog position and records offsets.

## Trade-offs
- **Log-based vs triggers vs polling**: log-based is complete and cheap for
  the source but ties you to database-specific setup and privileges;
  triggers are portable but slow every write; polling needs nothing special
  and misses deletes and intermediate states.
- **Row-level CDC vs domain events (outbox)**: raw table CDC needs no
  application changes but couples consumers to the internal schema; an
  outbox publishes a deliberate contract at the cost of writing it.
- **Managed vs self-run connectors**: managed CDC services reduce
  operations; self-run Debezium gives control over snapshotting, routing and
  transformations.
- **Per-table vs per-key ordering**: one partition per table keeps total
  order but limits throughput; partitioning by key scales and only keeps
  per-row order.

## Gotchas
- An abandoned Postgres replication slot retains WAL until it is consumed,
  which can fill the disk of the primary. Monitor slot lag and cap retention
  (`max_slot_wal_keep_size`); drop slots of retired consumers.
- Schema changes: a renamed or dropped column breaks consumers that read raw
  row images. Treat captured tables as a public contract, or use an outbox
  ([[schema-migrations]]).
- Update events may lack the full before image unless configured (Postgres
  `REPLICA IDENTITY`, MySQL `binlog_row_image`).
- Large transactions and bulk backfills arrive as a flood of events and can
  lag every consumer; throttle or route them separately.
- Consumers that are not idempotent duplicate side effects after a connector
  restart replays from the last committed offset.
- Assuming cross-table order: an order row and its line items can arrive in
  different partitions in either order.
- Sensitive columns flow everywhere the stream goes; filter or mask them in
  the connector ([[privacy-and-pii-handling]]).

## Related
- [[batch-and-stream-processing]] - what consumes and transforms the change stream.
- [[message-queues-and-streams]] - Kafka topics, partitions and compaction that carry CDC events.
- [[distributed-transactions-and-sagas]] - the outbox pattern CDC publishes from.
- [[event-driven-architecture]] - row changes vs domain events as integration contracts.
- [[replication]] - CDC reuses the database's replication log.
- [[idempotency-and-exactly-once]] - consumers must tolerate replayed changes.
- [[data-warehousing-and-olap]] - continuous loading of analytical stores.
- [[migrating-monolith-to-services]] - CDC to move data while both sides run.
- [[schema-evolution-and-serialization]] - database schema changes become event schema changes downstream.
- [[audit-logs-and-temporal-data]] - CDC as one way to capture every change for an audit trail.
- [[data-quality-and-data-contracts]] - producer-owned contracts for the tables and events CDC exposes.

## References
- Martin Kleppmann, *Designing Data-Intensive Applications* (1st ed., 2017), ch. 11 "Stream Processing", section "Databases and Streams" (change data capture, log compaction).
- Debezium documentation: https://debezium.io/documentation/reference/stable/index.html
- Debezium outbox event router: https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html
- PostgreSQL documentation, "Logical Decoding": https://www.postgresql.org/docs/current/logicaldecoding.html
- PostgreSQL documentation, "Logical Replication": https://www.postgresql.org/docs/current/logical-replication.html
- MySQL 8.4 Reference Manual, "The Binary Log": https://dev.mysql.com/doc/refman/8.4/en/binary-log.html
