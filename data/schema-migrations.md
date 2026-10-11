---
title: Schema migrations
category: data
tags: [migrations, ddl, zero-downtime, expand-contract, alembic, flyway, postgres, backfill]
use_cases:
  - "rename or drop a column on a live table without downtime"
  - "add a NOT NULL column to a table with hundreds of millions of rows"
  - "set up versioned migrations in CI for a Python or JVM service"
  - "roll out a schema change across several service versions safely"
status: draft
last_verified: 2026-10-10
sources:
  - https://alembic.sqlalchemy.org/en/latest/
  - https://documentation.red-gate.com/flyway
  - https://www.postgresql.org/docs/current/sql-altertable.html
  - "Jez Humble, David Farley, Continuous Delivery (Addison-Wesley, 2010), ch. 12"
---

# Schema migrations

## Summary
A migration is a versioned, repeatable change to the database schema (and sometimes data), stored in source control and applied by tooling in order. The hard part is not writing the DDL but doing it while old and new application versions run against the same database without locking tables or breaking requests. The standard answer is the expand/contract pattern with small, backward-compatible steps.

## Key concepts
- **Versioned migrations**: ordered files (`0042_add_status.sql`) tracked in a `schema_migrations` table; each runs exactly once (Flyway, Alembic, Liquibase, Django, Rails, Prisma, Atlas).
- **Forward-only vs reversible**: down migrations rarely work after data has changed; many teams only roll forward with a fix.
- **Expand/contract (parallel change)**: expand schema to support both old and new, migrate data and code, then contract by removing the old.
- **Lock level of DDL**: some `ALTER TABLE` forms take `ACCESS EXCLUSIVE` and block all reads and writes while waiting for the lock and while running.
- **Backfill**: populating new columns for existing rows, done in batches outside the DDL transaction.
- **Online schema change tools**: gh-ost, pt-online-schema-change (MySQL), pg_repack, pgroll (Postgres).
- **Compatibility window**: during deploys, version N and N+1 of the app run simultaneously (rolling, blue/green, see [[deployment-strategies]]).

## When to use / scenarios
- Always: any schema change in a shared environment goes through a migration tool, never hand-run SQL on production.
- Adding a nullable column or a table: trivial, safe.
- Adding `NOT NULL` or a default to a huge table: split into add nullable, backfill in batches, add constraint as `NOT VALID` then `VALIDATE`.
- Renaming a column: never `ALTER ... RENAME` in one step with a running app; use expand/contract.
- Changing a column type: add a new column, dual-write, backfill, switch reads, drop old.
- Dropping a column or table: only after no deployed code reads or writes it.
- Large data transformations: run as a separate job, not inside a deploy-blocking migration.
- Do NOT edit an already-applied migration; add a new one. Do NOT let the ORM auto-generate and auto-apply on boot in production without review.

## How it works / example
Rename `users.fullname` to `users.display_name` with zero downtime:

```
1. EXPAND   migration: add display_name (nullable). Deploy code that writes both columns, reads old.
2. BACKFILL batch job: UPDATE users SET display_name = fullname WHERE display_name IS NULL (in chunks).
3. SWITCH   deploy code that reads display_name, still writes both.
4. CONTRACT after one more release: stop writing fullname; migration drops fullname.
```

Safe patterns in Postgres:
```sql
-- 1. Avoid long lock waits: fail fast instead of queueing behind a slow transaction
SET lock_timeout = '3s';
SET statement_timeout = '15min';

-- 2. Add column nullable, with no table rewrite
ALTER TABLE orders ADD COLUMN currency text;

-- 3. Backfill in batches from application or script (not one giant UPDATE)
UPDATE orders SET currency = 'USD'
WHERE id IN (SELECT id FROM orders WHERE currency IS NULL ORDER BY id LIMIT 10000);

-- 4. Add constraint without a full-table blocking scan
ALTER TABLE orders ADD CONSTRAINT currency_nn CHECK (currency IS NOT NULL) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT currency_nn;   -- scans, but only a SHARE UPDATE EXCLUSIVE lock

-- 5. Indexes concurrently (cannot run inside a transaction block)
CREATE INDEX CONCURRENTLY orders_currency_idx ON orders (currency);
```

Alembic revision (Python/SQLAlchemy):
```python
"""add currency to orders"""
from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"

def upgrade():
    op.add_column("orders", sa.Column("currency", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("orders", "currency")
```

CI check idea: run all migrations on an empty database, then run the app's test suite; also run migrations against a restored copy of production schema to catch lock and duration problems.

## Trade-offs
- **Speed vs safety**: one-step changes are simple but need downtime or luck; expand/contract takes 3-4 deploys.
- **Reversible vs forward-only**: down scripts give comfort but are often untested; roll-forward fixes are more honest.
- **Tool-managed vs hand-written SQL**: ORM autogeneration is quick but misses data fixes and lock behaviour; hand-written SQL is explicit.
- **Migrate on deploy vs separate step**: running in the app boot path is easy but races with multiple instances and slow migrations delay startup; a dedicated migration job is safer.
- **Online change tools vs native DDL**: gh-ost and similar copy tables, adding operational complexity but avoiding long locks on engines that lack online DDL.

## Gotchas
- A trivial `ALTER TABLE` can wait behind a long-running query, and while it waits every new query queues behind it, causing an outage. Use `lock_timeout` and retry.
- `ADD COLUMN ... DEFAULT` was a table rewrite in old Postgres (before 11) and some other engines; know your version.
- `CREATE INDEX` without `CONCURRENTLY` blocks writes; a failed concurrent build leaves an `INVALID` index you must drop.
- MySQL DDL is non-transactional (implicit commits), so a failed migration can leave a half-applied state.
- Two developers creating the same revision number on different branches; use timestamps or have the tool detect multiple heads.
- Enum value additions, foreign key additions and `NOT NULL` flips all take locks or scan the table; check each in the docs for your engine.
- Dropping a column that a still-running old app version selects causes errors during the deploy window.
- Data migrations that import models from application code break later when the model changes; use raw SQL or frozen snapshots in migrations.
- Seed or reference data changes belong in migrations or idempotent scripts, not manual inserts.

## Related
- [[data-modeling-and-schema-design]] - what you are changing and why constraints matter
- [[deployment-strategies]] - old and new code coexist, dictating compatible steps
- [[ci-cd-pipelines]] - run and test migrations automatically before release
- [[api-versioning-and-evolution]] - the same expand/contract thinking applied to APIs
- [[database-indexing]] - concurrent index builds and their cost
- [[backup-and-disaster-recovery]] - take and verify a restorable backup before a risky migration

## References
- Alembic documentation: https://alembic.sqlalchemy.org/en/latest/
- Flyway documentation: https://documentation.red-gate.com/flyway
- PostgreSQL ALTER TABLE: https://www.postgresql.org/docs/current/sql-altertable.html
- Humble and Farley, Continuous Delivery, chapter on managing data.
