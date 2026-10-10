---
title: SQL vs NoSQL
category: data
tags: [sql, nosql, postgres, mongodb, dynamodb, redis, cassandra, database-choice]
use_cases:
  - "pick a database for a new product with users, orders and reporting"
  - "decide whether to move from Postgres to MongoDB or DynamoDB"
  - "store high-volume time series or event data without a single-node bottleneck"
  - "add a cache or session store next to the main relational database"
status: draft
last_verified: 2026-10-10
sources:
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 2-3"
  - https://www.postgresql.org/docs/current/
  - https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-general-nosql-design.html
  - https://www.mongodb.com/docs/manual/data-modeling/
---

# SQL vs NoSQL

## Summary
"SQL" databases are relational systems with a fixed schema, joins, and ACID transactions. "NoSQL" is an umbrella for key-value, document, wide-column and graph stores that trade some of that for horizontal scale, flexible schema or a specialised access pattern. The default for most applications should be a relational database; reach for NoSQL when a specific access pattern or scale requirement demands it, not for fashion.

## Key concepts
- **Relational**: tables, foreign keys, joins, declarative queries, constraints, multi-row transactions (Postgres, MySQL, SQL Server).
- **Key-value**: get/put by key, extremely fast, no query language beyond the key (Redis, DynamoDB in its simplest use).
- **Document**: JSON-like records queried by fields, nested data denormalised into one document (MongoDB, Firestore, Couchbase).
- **Wide-column**: partition key plus clustering key, writes are cheap, queries must follow the table design (Cassandra, ScyllaDB, Bigtable).
- **Graph**: nodes and edges with traversal queries (Neo4j); useful when relationship depth is the query.
- **Schema-on-write vs schema-on-read**: relational enforces shape at write; document stores push shape enforcement into application code.
- **Query-first modelling**: in most NoSQL stores you design tables from your queries; in SQL you model entities first and add indexes later.
- Modern SQL systems blur the line: Postgres has JSONB, arrays, full-text search; NoSQL systems added transactions (MongoDB multi-document, DynamoDB TransactWriteItems).

## When to use / scenarios
- Use **relational** when: data has relationships, you need ad hoc queries and reporting, integrity constraints matter, requirements are still changing, or dataset fits on one (large) node. This covers the vast majority of products.
- Use **key-value / cache** (Redis) for sessions, rate-limit counters, leaderboards, ephemeral data with TTL.
- Use **document** when the aggregate is read and written as a unit, shape varies per record (CMS content, product catalogs with many attribute sets), and cross-document joins are rare.
- Use **wide-column / Dynamo-style** when write throughput or dataset size exceeds a single node, access patterns are known and few, and you can live with limited secondary indexes (messaging history, IoT telemetry, activity feeds).
- Use **graph** when queries are multi-hop traversals (fraud rings, recommendations, org hierarchies of unknown depth).
- Do NOT pick NoSQL because "it scales": a tuned Postgres with read replicas and partitioning handles very large workloads. Do NOT pick it to avoid designing a schema; the schema moves into code and migrations become data-fixing scripts.
- Polyglot persistence is normal: Postgres as system of record, Redis for cache, a search engine for text, object storage for blobs. Keep one source of truth and derive the rest.

## How it works / example
The same "order with items" modelled both ways.

Relational:
```sql
CREATE TABLE orders (
  id          bigint PRIMARY KEY,
  customer_id bigint NOT NULL REFERENCES customers(id),
  placed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE order_items (
  order_id   bigint NOT NULL REFERENCES orders(id),
  sku        text   NOT NULL,
  qty        int    NOT NULL CHECK (qty > 0),
  unit_price numeric(12,2) NOT NULL,
  PRIMARY KEY (order_id, sku)
);
-- ad hoc question answered without planning ahead:
SELECT sku, sum(qty) FROM order_items
JOIN orders o ON o.id = order_id
WHERE o.placed_at >= now() - interval '7 days'
GROUP BY sku ORDER BY 2 DESC LIMIT 10;
```

Document (MongoDB):
```python fragment
db.orders.insert_one({
    "_id": 1001,
    "customer_id": 42,
    "placed_at": datetime.utcnow(),
    "items": [{"sku": "A1", "qty": 2, "unit_price": 9.5}],
})
# fast: fetch whole order by id. awkward: "top SKUs last week" needs an aggregation pipeline
```

DynamoDB single-table sketch (query-first): partition key `CUSTOMER#42`, sort key `ORDER#2026-10-10#1001`, so "latest orders for customer" is one cheap `Query`. "Top SKUs across all customers" is not possible without a second table or an export to an analytics store.

Decision sketch:
```
need ad hoc queries / joins / constraints?  -> relational
single record by key, huge volume, TTL?     -> key-value
aggregate read/written whole, flexible?     -> document
write-heavy, known queries, multi-node?     -> wide-column
multi-hop relationships?                    -> graph
```

## Trade-offs
- **Flexibility vs enforcement**: schemaless speeds the first prototype, but every reader must handle every historical shape. Relational pays upfront and prevents bad data.
- **Query power vs scale-out**: SQL gives arbitrary queries; Dynamo-style gives predictable latency at any size but only for modelled queries.
- **Joins vs denormalisation**: NoSQL duplicates data to avoid joins, so updates must fix many copies; you own consistency.
- **Consistency**: single-node ACID is simple; distributed stores offer tunable or eventual consistency (see [[cap-and-pacelc]]).
- **Operational cost**: managed Postgres is boring and well understood; a self-run Cassandra cluster is a full-time skill.
- **Hiring and tooling**: SQL knowledge, ORMs, BI tools and migration tools are universal.

## Gotchas
- Migrating off a document store later is painful because there is no enforced schema to map from; budget for data cleansing.
- Multi-document transactions in document stores exist but are slower and often a sign the model should be reshaped.
- DynamoDB hot partitions: a low-cardinality partition key throttles regardless of provisioned capacity.
- Cassandra deletes create tombstones; delete-heavy or queue-like workloads degrade reads.
- "We need to scale" is often an indexing or N+1 problem (see [[database-indexing]], [[orm-and-n-plus-one]]) rather than an engine problem.
- JSONB columns are a good escape hatch, but indexing and constraining them takes explicit work (GIN indexes, CHECK constraints).
- Redis is not a durable primary store by default; know your persistence settings (RDB/AOF) before trusting it.

## Related
- [[choosing-a-database]] - scenario-level decision guide built on this comparison
- [[data-modeling-and-schema-design]] - how to model in either paradigm
- [[database-indexing]] - what makes relational queries fast at scale
- [[cap-and-pacelc]] - consistency trade-offs behind distributed NoSQL
- [[partitioning-and-sharding]] - how both families scale beyond one node

## References
- Kleppmann, Designing Data-Intensive Applications, chapters 2 (data models) and 3 (storage).
- PostgreSQL documentation (JSONB, partitioning): https://www.postgresql.org/docs/current/
- DynamoDB NoSQL design best practices: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-general-nosql-design.html
- MongoDB data modeling: https://www.mongodb.com/docs/manual/data-modeling/
