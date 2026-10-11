---
title: Data modeling and schema design
category: data
tags: [schema, normalization, denormalization, erd, constraints, keys, soft-delete, postgres]
use_cases:
  - "design the database schema for a new multi-tenant SaaS product"
  - "decide when to denormalize for read performance"
  - "model many-to-many relationships, hierarchies and audit history"
  - "choose primary keys and constraints that keep data correct"
status: draft
last_verified: 2026-10-10
sources:
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 2"
  - "C. J. Date, Database Design and Relational Theory (O'Reilly, 2012)"
  - https://www.postgresql.org/docs/current/ddl-constraints.html
  - https://www.sqlstyle.guide/
---

# Data modeling and schema design

## Summary
Schema design decides what your data can express and what bad states the database refuses to store. Start from the entities and invariants of the domain, normalise to remove accidental duplication, enforce rules with constraints, and denormalise deliberately only where measured read patterns justify it. A good schema is the cheapest correctness tool you have.

## Key concepts
- **Entities and relationships**: one-to-one, one-to-many (foreign key on the "many" side), many-to-many (junction table).
- **Normal forms**: 1NF atomic values; 2NF no partial dependence on part of a composite key; 3NF no non-key attribute depends on another non-key attribute. "Every fact stored once."
- **Keys**: natural (email, ISBN) vs surrogate (bigint identity, UUID). Surrogate PK plus unique constraint on the natural key is the common pattern.
- **Constraints**: `NOT NULL`, `UNIQUE`, `CHECK`, `FOREIGN KEY`, exclusion constraints; they hold regardless of which service writes.
- **Denormalisation**: duplicate or precompute data to avoid joins (counters, snapshots, materialised views).
- **Aggregates (DDD)**: the cluster of rows modified together; boundaries guide table grouping and transaction scope (see [[domain-driven-design]]).
- **Temporal data**: audit tables, effective-dated rows, event logs.

## When to use / scenarios
- Greenfield project: model on paper first (entity list, cardinalities, invariants), then write DDL.
- Multi-tenancy: shared tables with `tenant_id` on every row (simple, use composite keys and row-level security), schema-per-tenant, or database-per-tenant (isolation, heavier ops).
- Hierarchies (categories, org charts): adjacency list (`parent_id` + recursive CTE) is fine for most; materialised path or closure table when reads of subtrees dominate.
- Money: `numeric`/integer minor units, never float. Time: store UTC `timestamptz`; keep the user time zone separately.
- Flexible attributes: JSONB column for genuinely sparse extras, not for core fields you filter and join on.
- Denormalise when a measured hot read repeats the same join/aggregate, and you can keep the copy correct (trigger, same transaction, or rebuildable from source). For analytics use a separate model (see [[data-warehousing-and-olap]]).
- Do NOT skip constraints "because the app validates": multiple writers, scripts and bugs will violate invariants.

## How it works / example
Orders domain with constraints, soft delete, audit and a junction table:

```sql
CREATE TABLE customers (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email      text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE UNIQUE INDEX customers_email_live ON customers (lower(email)) WHERE deleted_at IS NULL;

CREATE TABLE products (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sku         text NOT NULL UNIQUE,
  price_cents integer NOT NULL CHECK (price_cents >= 0)
);

CREATE TABLE orders (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id bigint NOT NULL REFERENCES customers(id),
  status      text   NOT NULL CHECK (status IN ('open','paid','shipped','cancelled')),
  placed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
  order_id    bigint  NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id  bigint  NOT NULL REFERENCES products(id),
  qty         integer NOT NULL CHECK (qty > 0),
  -- snapshot: product price may change later, the order must not
  unit_price_cents integer NOT NULL CHECK (unit_price_cents >= 0),
  PRIMARY KEY (order_id, product_id)
);
```

Notes on the choices: `unit_price_cents` is deliberate denormalisation (historical truth). Orders keep `customer_id` as a foreign key, not a copy of the email. The partial unique index allows re-registering an email after soft delete.

Denormalised counter kept correct in the same transaction:
```sql
BEGIN;
INSERT INTO comments (post_id, body) VALUES (9, 'hi');
UPDATE posts SET comment_count = comment_count + 1 WHERE id = 9;
COMMIT;
```

Tenant isolation with row-level security:
```sql
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON invoices
  USING (tenant_id = current_setting('app.tenant_id')::bigint);
```

## Trade-offs
- **Normalised vs denormalised**: normalised gives one place to update and fewer anomalies; denormalised gives faster reads at the price of sync logic.
- **Natural vs surrogate keys**: natural keys change (emails, names); surrogate keys are stable but need extra unique constraints.
- **UUID vs bigint**: UUIDs are safe to generate anywhere and hard to guess but larger and unordered; bigint identities are compact and ordered (see [[unique-id-generation]]).
- **Soft delete vs hard delete**: soft delete preserves history but pollutes every query and unique constraint; consider an archive table or event log instead.
- **JSONB vs columns**: JSONB is flexible but weaker on constraints, statistics and migrations.
- **Shared schema vs per-tenant**: shared is cheap to operate; per-tenant isolates noisy neighbours and simplifies per-customer export or deletion.

## Gotchas
- Storing lists in a comma-separated column breaks 1NF and makes joins and constraints impossible; use a child table.
- `NULL` semantics: `NULL <> NULL`, unique constraints allow multiple NULLs (in most engines); `NOT IN` with NULLs returns nothing.
- Enum types are hard to alter; a lookup table or `CHECK` is easier to evolve.
- Polymorphic associations (`target_type`, `target_id`) cannot have real foreign keys; prefer separate nullable FKs with a CHECK, or separate tables.
- Over-normalising reference data (a table for every status) adds joins without value; over-denormalising leads to drift.
- Timestamps without time zone and floats for money are classic production bugs.
- Cascading deletes can erase far more than intended; prefer `RESTRICT` unless ownership is truly strict.
- Schema is hard to change once large; plan evolution via [[schema-migrations]] and avoid renames that need coordinated deploys.

## Related
- [[sql-vs-nosql]] - picking the paradigm before modelling
- [[database-indexing]] - indexes follow from the access patterns you model for
- [[schema-migrations]] - evolving the model safely
- [[domain-driven-design]] - aggregates and bounded contexts guide table boundaries
- [[data-warehousing-and-olap]] - star schemas are a different modelling approach for analytics
- [[strings-and-text-encoding]] - column charsets, collations and Unicode normalization of keys

## References
- Kleppmann, Designing Data-Intensive Applications, chapter 2.
- C. J. Date, Database Design and Relational Theory.
- PostgreSQL constraints: https://www.postgresql.org/docs/current/ddl-constraints.html
- SQL style guide: https://www.sqlstyle.guide/
