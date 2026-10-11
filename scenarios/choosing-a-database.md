---
title: Choosing a database
category: scenarios
tags: [database, sql, nosql, postgres, key-value, document, wide-column, graph, time-series, decision-guide]
use_cases:
  - "which database should we use for a new product with users, orders and reports"
  - "do we need NoSQL or is Postgres enough"
  - "pick storage for sessions, caches, time series, search, or files"
  - "our current database cannot keep up with writes, what are the options"
status: stable
last_verified: 2026-10-10
sources:
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://www.postgresql.org/docs/current/
  - https://martinfowler.com/articles/nosql-intro.html
  - https://docs.aws.amazon.com/decision-guides/latest/decision-guides/databases-on-aws-how-to-choose.html
---

# Choosing a database

## Summary
Pick the database by access patterns, consistency needs, data shape and scale, in that order, then by team familiarity and operational cost. Default to a relational database (PostgreSQL or MySQL) for the system of record; add specialised stores only for workloads it demonstrably serves poorly (cache, search, analytics, time series, blobs). Polyglot persistence is a cost: every extra datastore is another thing to back up, secure, and keep consistent.

## Key concepts
- **Access patterns drive the choice.** List the top queries and writes: by key, by range, by join, by full text, by graph traversal, aggregate scans.
- **Consistency requirement.** Money, inventory, bookings need ACID transactions ([[transactions-and-isolation-levels]]). Feeds, counters, caches tolerate eventual consistency ([[consistency-models]]).
- **Scale axis.** Dataset size, write rate, read rate, and geographic spread. One well-tuned node covers more than most teams expect.
- **System of record vs derived store.** One source of truth; everything else (cache, index, warehouse) is rebuildable from it.
- **Data model families:** relational, key-value, document, wide-column, graph, time-series, search engine, columnar/OLAP, object storage.
- **Operational maturity.** Managed service vs self-hosting; backup, upgrade, failover, monitoring skills.

## When to use / scenarios
Decision table:

| Need | First choice | Why / read |
|---|---|---|
| General app data, relations, transactions, reporting | Relational (PostgreSQL, MySQL) | Joins, constraints, mature tooling. [[sql-vs-nosql]], [[data-modeling-and-schema-design]] |
| Cache, sessions, rate counters, leaderboards | In-memory KV (Redis, Memcached) | Sub-ms access, TTLs. [[caching-strategies]], [[rate-limiting]] |
| Huge key-based access, simple lookups, predictable latency at scale | Key-value / wide-column (DynamoDB, Cassandra) | Partitioned by key. [[partitioning-and-sharding]], [[design-key-value-store]] |
| Flexible nested documents, varied schema per record | Document (MongoDB, Firestore) or Postgres JSONB | Aggregate-oriented. [[data-modeling-and-schema-design]] |
| Full-text search, relevance, facets | Search engine (Elasticsearch/OpenSearch) or Postgres FTS for small | [[search-systems]] |
| Metrics, IoT, events over time | Time-series DB or partitioned tables | Retention, downsampling. [[observability-logs-metrics-traces]] |
| Highly connected data, path queries | Graph DB, or Postgres recursive CTE if shallow | Only if traversals dominate. |
| Analytics, aggregations over billions of rows | Columnar warehouse (BigQuery, Snowflake, ClickHouse) | [[data-warehousing-and-olap]] |
| Files, images, video, backups | Object storage (S3-compatible) | [[blob-object-storage]] |
| Event log, replayable stream | Log/stream platform (Kafka-like) | [[message-queues-and-streams]], [[cqrs-and-event-sourcing]] |
| Embedding similarity search | Vector extension/index (pgvector or dedicated store) | Start inside Postgres if volume is modest. |

Decision flow:

```
Need multi-row ACID or ad-hoc queries/joins? --yes--> Relational (default)
        |no
Access always by a known key at very high scale? --yes--> KV / wide-column
        |no
Documents read/written as a whole aggregate?     --yes--> Document store (or JSONB)
        |no
Mainly search / time-ordered metrics / graph / analytics --> specialised store
```

When NOT to leave relational: "web scale" without numbers, vague flexibility ("schema-less is faster to develop" - the schema moves into code), or hype. When NOT to stay relational: you can show the workload (write throughput, partitioning need, access shape) exceeds a single node plus replicas and caching.

## How it works / example
Write the requirement as a scorecard before choosing. A tiny helper that forces the questions:

```python
from dataclasses import dataclass

@dataclass
class Workload:
    needs_multi_row_acid: bool
    needs_adhoc_queries: bool
    key_value_access_only: bool
    writes_per_sec: int            # measure / estimate: see back-of-envelope-estimation
    data_tb: float
    full_text_search: bool = False
    analytics_scans: bool = False

def recommend(w: Workload) -> list[str]:
    picks = []
    if w.needs_multi_row_acid or w.needs_adhoc_queries or not w.key_value_access_only:
        picks.append("PostgreSQL (system of record)")
    elif w.key_value_access_only:
        picks.append("Key-value / wide-column (partition key = access key)")
    if w.full_text_search:
        picks.append("Search index (derived from the system of record)")
    if w.analytics_scans:
        picks.append("Warehouse/columnar store fed by batch or CDC")
    if w.writes_per_sec > 10_000 or w.data_tb > 10:   # placeholder thresholds: replace with measured single-node limits
        picks.append("Review: replicas, partitioning or a scale-out store")
    return picks

if __name__ == "__main__":
    print(recommend(Workload(True, True, False, 200, 0.5, full_text_search=True)))
```

Treat the thresholds as prompts to measure, not facts; single-node limits depend on hardware, schema and workload.

Polyglot done safely: one writer for each fact. Write to the system of record, derive others via events or CDC with an outbox ([[event-driven-architecture]]), and design them as rebuildable.

## Trade-offs
- **Relational flexibility vs NoSQL scale-out:** relational gives ad-hoc queries and constraints; key-value gives linear scale for known access paths but makes new queries expensive.
- **Managed vs self-hosted:** managed reduces toil and risk; costs more at volume and limits tuning.
- **One store vs many:** one is simpler to operate and keeps consistency; many fit each workload but add sync, consistency and ops burden.
- **Consistency vs availability and latency across regions:** see [[cap-and-pacelc]].
- **Schema-on-write vs schema-on-read:** enforced schema catches bugs early; flexible schema speeds early iteration but defers cost ([[schema-migrations]]).
- **Familiarity:** a store the team can operate at 3am beats a theoretically better one.

## Gotchas
- Choosing by benchmark blog posts instead of your access patterns and durability settings.
- Using a cache or search index as the system of record.
- DynamoDB/Cassandra-style stores need the access patterns designed up front; changing them later is a migration.
- MongoDB or any store used relationally ends up reimplementing joins and transactions in application code.
- Ignoring operations: backups tested by restore, failover drills, upgrade path, connection limits ([[replication]]).
- Hot partitions from monotonically increasing keys.
- Premature sharding: it makes joins, transactions and migrations harder permanently ([[partitioning-and-sharding]]).
- Lock-in through proprietary query APIs; isolate behind a repository port ([[layered-hexagonal-clean-architecture]]).

## Related
- [[sql-vs-nosql]] - deeper comparison of the families.
- [[data-modeling-and-schema-design]] - model after choosing, per store.
- [[database-indexing]] - make the default choice go further.
- [[scaling-from-zero-to-millions]] - when each store enters the picture.
- [[scenario-chooser]] - other problem-to-topic mappings.
- [[design-key-value-store]] - how scale-out KV stores work inside.
- [[time-series-databases]] - when metrics or IoT data justify a TSDB over partitioned Postgres.
- [[graph-databases]] - when multi-hop traversals justify a graph store over recursive CTEs.
- [[vector-databases-for-engineers]] - pgvector vs a dedicated vector store, filtering and sync.

## References
- Martin Kleppmann, *Designing Data-Intensive Applications* (1st ed., 2017), ch. 2 "Data Models and Query Languages", ch. 3 "Storage and Retrieval", ch. 5-7 (replication, partitioning, transactions).
- PostgreSQL documentation (postgresql.org/docs).
- AWS Decision Guides, "Choosing an AWS database service".
- Martin Fowler and Pramod Sadalage, "Introductory Infodeck to NoSQL Databases" (martinfowler.com, 2012).
