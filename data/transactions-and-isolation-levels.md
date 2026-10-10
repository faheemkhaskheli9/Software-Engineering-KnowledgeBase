---
title: Transactions and isolation levels
category: data
tags: [acid, transactions, isolation, mvcc, locking, serializable, postgres, deadlock]
use_cases:
  - "transfer money between two accounts without losing or duplicating funds"
  - "prevent two concurrent requests from overselling the last item in stock"
  - "understand which anomalies read committed vs repeatable read allow"
  - "fix deadlocks or serialization failures in a busy service"
status: draft
last_verified: 2026-10-10
sources:
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 7"
  - https://www.postgresql.org/docs/current/transaction-iso.html
  - https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html
  - https://jepsen.io/consistency
---

# Transactions and isolation levels

## Summary
A transaction groups several operations so they succeed or fail together (atomicity) and, while running, appear isolated from concurrent work. Isolation levels define which concurrency anomalies you tolerate in exchange for throughput. Most production bugs come from assuming a stronger level than the database default provides.

## Key concepts
- **ACID**: Atomicity (all or nothing), Consistency (invariants hold, partly the app's job), Isolation (concurrent transactions do not interfere), Durability (committed data survives crashes via WAL).
- **MVCC**: readers see a snapshot, writers create new row versions, so readers do not block writers (Postgres, InnoDB, Oracle).
- **Anomalies**: dirty read, non-repeatable read, phantom read, lost update, write skew.
- **Isolation levels (SQL standard)**: Read Uncommitted, Read Committed, Repeatable Read, Serializable. Actual behaviour differs per engine.
- **Postgres**: Read Committed is the default; Repeatable Read is snapshot isolation (no phantoms, but write skew possible); Serializable uses SSI and may abort with `40001`.
- **MySQL InnoDB**: default Repeatable Read, with gap locks; plain reads use the snapshot, `SELECT ... FOR UPDATE` reads the latest.
- **Pessimistic locking**: `SELECT ... FOR UPDATE` blocks conflicting writers. **Optimistic**: version column, retry on conflict.
- **Savepoints**, **two-phase commit** across databases (see [[distributed-transactions-and-sagas]]).

## When to use / scenarios
- Any multi-statement change that must be all-or-nothing: always wrap in one transaction.
- Read-modify-write of a counter, balance or inventory: needs an atomic update, a row lock, or optimistic version check; Read Committed alone loses updates.
- Invariants spanning multiple rows ("at least one doctor on call", "no overlapping bookings"): write skew; use Serializable, a constraint (exclusion constraint), or lock a parent row.
- Reports needing a consistent view of many tables: Repeatable Read or a read-only snapshot transaction.
- Do NOT hold transactions open across user think time or remote calls: they pin old row versions and locks. Do NOT use distributed transactions when a saga plus idempotency suffices.
- Crossing service or database boundaries: transactions end at the database; use the outbox pattern and [[idempotency-and-exactly-once]].

## How it works / example
Anomaly table (what each level permits; engine specifics noted above):
```
                 dirty  non-rep  phantom  lost-update  write-skew
READ COMMITTED    no     yes      yes      yes*         yes
REPEATABLE READ   no     no       no**     no (PG)      yes
SERIALIZABLE      no     no       no       no           no
 * avoided if you use atomic UPDATE; ** per snapshot semantics in PG
```

Lost update and its fixes:
```sql
-- BAD (two sessions both read 5, both write 4)
SELECT stock FROM items WHERE id = 7;      -- app computes stock - 1
UPDATE items SET stock = 4 WHERE id = 7;

-- Fix 1: atomic update with guard
UPDATE items SET stock = stock - 1 WHERE id = 7 AND stock > 0;   -- check rowcount == 1

-- Fix 2: pessimistic lock
BEGIN;
SELECT stock FROM items WHERE id = 7 FOR UPDATE;
UPDATE items SET stock = stock - 1 WHERE id = 7;
COMMIT;

-- Fix 3: optimistic version
UPDATE items SET stock = stock - 1, version = version + 1
WHERE id = 7 AND version = 12;   -- 0 rows => someone else won, retry
```

Write skew guard with an exclusion constraint (Postgres):
```sql
CREATE EXTENSION btree_gist;
ALTER TABLE bookings ADD CONSTRAINT no_overlap
  EXCLUDE USING gist (room_id WITH =, tstzrange(starts_at, ends_at) WITH &&);
```

Retry loop for serializable work (Python, psycopg 3):
```python
import psycopg
from psycopg import errors

def run_tx(conn, fn, retries=5):
    for _ in range(retries):
        try:
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                return fn(conn)
        except (errors.SerializationFailure, errors.DeadlockDetected):
            continue
    raise RuntimeError("transaction kept conflicting")
```

## Trade-offs
- **Stronger isolation vs throughput**: Serializable costs aborts and retries under contention; Read Committed is cheap but needs explicit locks for read-modify-write.
- **Pessimistic vs optimistic**: pessimistic suits high contention on few rows; optimistic suits low contention and avoids holding locks.
- **Constraints vs application checks**: database constraints are race-free; app-level "check then insert" is not.
- **Long vs short transactions**: short transactions reduce lock waits and bloat but may require splitting logic into idempotent steps.
- **Single DB transaction vs saga**: ACID is simpler but bounded to one database.

## Gotchas
- "ACID" claims vary: MongoDB, MySQL MyISAM, and some distributed stores offer weaker guarantees; read the docs.
- Checking existence then inserting is a race; use `UNIQUE` plus `INSERT ... ON CONFLICT`.
- Deadlocks: two transactions lock rows in different order. Fix by consistent lock ordering and keeping transactions short; always retry on deadlock errors.
- Autocommit means each statement is its own transaction; an ORM session may open a transaction you did not expect, or none at all.
- `SELECT ... FOR UPDATE` on a range in InnoDB takes gap locks and can block unrelated inserts.
- Catching an exception inside a transaction in Postgres leaves it aborted until rollback or savepoint.
- Read replicas lag; a transaction that reads from a replica after writing to the primary can miss its own write (see [[replication]]).
- Do not call external APIs or send emails inside a transaction: the commit may fail after the side effect.

## Related
- [[distributed-transactions-and-sagas]] - when one transaction cannot span the work
- [[consistency-models]] - isolation levels are the single-node cousin of these models
- [[idempotency-and-exactly-once]] - safe retries after conflicts and failures
- [[database-indexing]] - indexes shape which rows are locked
- [[replication]] - replica lag and read-your-writes

## References
- Kleppmann, Designing Data-Intensive Applications, chapter 7 (Transactions).
- PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- MySQL InnoDB isolation levels: https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html
- Jepsen consistency map: https://jepsen.io/consistency
