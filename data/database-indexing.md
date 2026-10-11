---
title: Database indexing
category: data
tags: [index, b-tree, postgres, mysql, query-plan, explain, performance]
use_cases:
  - "a query on a large table is slow and I need to know which index to add"
  - "decide column order for a composite index"
  - "understand why the database ignores my index"
  - "reduce write overhead caused by too many indexes"
status: draft
last_verified: 2026-10-10
sources:
  - https://use-the-index-luke.com/
  - https://www.postgresql.org/docs/current/indexes.html
  - https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 3"
---

# Database indexing

## Summary
An index is a separate, ordered (or hashed) structure that lets the database find rows without scanning the whole table. The standard choice is a B-tree; the art is choosing which columns, in which order, and noticing when an index cannot help. Every index speeds some reads and slows every write, so index for the queries you actually run.

## Key concepts
- **B-tree**: balanced sorted tree; supports equality, range, `ORDER BY`, prefix `LIKE 'abc%'`. Default in Postgres, MySQL InnoDB.
- **Composite index**: sorted by first column, then second within ties. Usable for any leftmost prefix of its columns.
- **Selectivity**: fraction of rows a predicate removes. High selectivity (few matching rows) benefits from an index; low selectivity (boolean flag, 50% of rows) usually does not.
- **Covering index / index-only scan**: the index contains every column the query needs, so the table is never touched. Postgres: `INCLUDE (...)`.
- **Clustered vs heap**: InnoDB stores rows in primary-key order (clustered), secondary indexes store the PK; Postgres keeps an unordered heap and all indexes point to heap locations.
- **Partial index**: indexes only rows matching a predicate (`WHERE deleted_at IS NULL`).
- **Expression index**: indexes a computed value (`lower(email)`).
- Other types: hash (equality only), GIN (arrays, JSONB, full text), GiST/SP-GiST (geometry, ranges), BRIN (huge naturally ordered tables like time series), LSM-tree based engines (Cassandra, RocksDB) trade read cost for write speed.

## When to use / scenarios
- Index columns used in `WHERE`, `JOIN ... ON`, `ORDER BY` of frequent or slow queries; always index foreign key columns that you join or delete by (Postgres does not do this automatically).
- Composite index when queries filter on several columns together: put equality columns first, then the range or sort column.
- Partial index for "active rows only" patterns or a unique constraint over a subset (unique email among non-deleted users).
- Do NOT index: tiny tables, low-selectivity columns by themselves, columns that are rarely queried, or every column "just in case".
- Do NOT rely on an index when the query wraps the column in a function or casts it (see gotchas); fix the query or add an expression index.
- For text search, similarity or JSON containment use GIN or a search engine (see [[search-systems]]), not B-tree.

## How it works / example
Workflow: look at the plan, change one thing, look again.

```sql
CREATE TABLE orders (
  id bigserial PRIMARY KEY, customer_id bigint NOT NULL,
  status text NOT NULL, placed_at timestamptz NOT NULL, total numeric(12,2)
);

-- Slow query: recent open orders for a customer
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, total FROM orders
WHERE customer_id = 42 AND status = 'open'
ORDER BY placed_at DESC LIMIT 20;
-- Seq Scan on orders ... Rows Removed by Filter: millions

-- Equality columns first, then the sort column, so the sort comes free from the index
CREATE INDEX CONCURRENTLY orders_cust_status_placed_idx
  ON orders (customer_id, status, placed_at DESC) INCLUDE (total);
-- Now: Index Only Scan using orders_cust_status_placed_idx, no sort node
```

Leftmost-prefix rule for index `(a, b, c)`:
```
WHERE a = 1                  -> uses index
WHERE a = 1 AND b = 2        -> uses index
WHERE a = 1 AND c = 3        -> uses a only, c filtered after
WHERE b = 2                  -> cannot use efficiently
WHERE a > 1 AND b = 2        -> range on a stops use of b for seeking
```

Partial and expression indexes:
```sql
CREATE UNIQUE INDEX users_email_active ON users (lower(email)) WHERE deleted_at IS NULL;
SELECT * FROM users WHERE lower(email) = 'a@b.com' AND deleted_at IS NULL;
```

Reading a plan: look for Seq Scan on big tables, big gaps between estimated and actual rows (stale statistics, run `ANALYZE`), `Rows Removed by Filter`, sorts spilling to disk, and nested loops with huge outer sets.

## Trade-offs
- **Read speed vs write cost**: each insert/update/delete must maintain every index; heavy-write tables should carry few indexes.
- **Index size vs memory**: indexes compete for cache; a wide composite index that no longer fits in memory loses its benefit.
- **Covering index vs bloat**: `INCLUDE` columns avoid table lookups but enlarge the index.
- **One composite vs several single-column**: databases can combine single-column indexes (bitmap AND) but a purpose-built composite is usually faster.
- **B-tree vs LSM**: LSM engines absorb writes cheaply but reads check multiple levels; pick by workload (see [[sql-vs-nosql]]).

## Gotchas
- Functions on indexed columns defeat the index: `WHERE date(created_at) = ...`, `WHERE lower(email) = ...` without an expression index. Rewrite as a range: `created_at >= d AND created_at < d + 1`.
- Type mismatch (comparing varchar to integer, or MySQL collation differences) forces implicit casts and scans.
- `LIKE '%foo'` (leading wildcard) cannot use a B-tree; use trigram (`pg_trgm`) or full-text.
- `OR` across different columns and `NOT IN`/`<>` often skip indexes.
- Creating an index on a live table locks writes unless you use `CREATE INDEX CONCURRENTLY` (Postgres) or an online DDL tool; failed concurrent builds leave an invalid index to drop.
- Duplicate or redundant indexes: `(a)` is redundant when `(a, b)` exists. Audit with `pg_stat_user_indexes` (unused indexes show `idx_scan = 0`).
- The planner may legitimately choose a seq scan if it reads a large fraction of the table. Do not force it; check statistics first.
- Indexes do not fix N+1 query patterns; reduce query count first (see [[orm-and-n-plus-one]]).
- Random UUID primary keys on clustered engines cause page splits and cache misses; consider time-ordered IDs (see [[unique-id-generation]]).

## Related
- [[orm-and-n-plus-one]] - the other common cause of slow data access
- [[data-modeling-and-schema-design]] - schema shape determines which indexes are possible
- [[transactions-and-isolation-levels]] - indexes interact with locking and gap locks
- [[partitioning-and-sharding]] - when one index on one node is no longer enough
- [[unique-id-generation]] - key choice affects index locality
- [[storage-engines-btree-lsm]] - the B-tree and LSM engines underneath indexes, with WAL and compaction

## References
- Markus Winand, Use The Index, Luke: https://use-the-index-luke.com/
- PostgreSQL indexes chapter: https://www.postgresql.org/docs/current/indexes.html
- MySQL optimization and indexes: https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html
- Kleppmann, Designing Data-Intensive Applications, chapter 3.
