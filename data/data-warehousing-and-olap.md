---
title: Data warehousing and OLAP
category: data
tags: [olap, data-warehouse, star-schema, columnar, etl, elt, dbt, bigquery, snowflake, lakehouse]
use_cases:
  - "build a reporting database so analytics queries do not slow down production"
  - "design a star schema for sales and customer dashboards"
  - "choose between BigQuery, Snowflake, Redshift, ClickHouse or Postgres for analytics"
  - "load operational data into a warehouse and keep history of changes"
status: draft
last_verified: 2026-10-10
sources:
  - "Ralph Kimball, Margy Ross, The Data Warehouse Toolkit, 3rd ed. (Wiley, 2013)"
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 3"
  - https://docs.getdbt.com/
  - https://clickhouse.com/docs
---

# Data warehousing and OLAP

## Summary
OLTP databases serve many small transactional reads and writes; OLAP systems serve fewer, heavy analytical queries that scan and aggregate large volumes. A data warehouse is a separate, read-optimised store (usually columnar) fed from operational sources and modelled for analysis, so reporting never competes with the production workload.

## Key concepts
- **OLTP vs OLAP**: row-oriented point lookups and updates vs column-oriented scans and aggregates over millions of rows.
- **Columnar storage**: stores each column contiguously; queries read only needed columns, compress well, and vectorise (Parquet, ORC, BigQuery, Snowflake, Redshift, ClickHouse, DuckDB).
- **Star schema**: one central **fact** table (events/measures: order lines, clicks) surrounded by **dimension** tables (customer, product, date). Snowflake schema normalises dimensions further.
- **Grain**: what one fact row represents ("one order line"). Decide this first; never mix grains.
- **Slowly changing dimensions (SCD)**: Type 1 overwrite, Type 2 new row with validity dates (keeps history), Type 3 previous-value column.
- **ETL vs ELT**: transform before loading vs load raw and transform inside the warehouse (dbt, SQL). ELT is the modern default.
- **Layers**: raw/bronze, cleaned/silver, modelled marts/gold.
- **Lake / lakehouse**: files in object storage (see [[blob-object-storage]]) with table formats (Iceberg, Delta, Hudi) giving ACID and schema over cheap storage.
- **Cubes, materialised views, pre-aggregates**: trade storage for query speed.

## When to use / scenarios
- Dashboards or BI queries scanning months of data that would hurt the production database.
- Joining data from several systems (app DB, CRM, payments, event tracking) into one analytic model.
- Need history that production overwrites (SCD2) or long retention of events.
- Small scale (a few GB to low hundreds of GB): a Postgres read replica or DuckDB/Parquet may be enough; do not buy a cluster first.
- Sub-second dashboards over huge event streams: ClickHouse, Druid, Pinot, or pre-aggregation from a stream (see [[batch-and-stream-processing]]).
- Do NOT run heavy analytics on the primary OLTP database; do NOT use the warehouse as the serving store for user-facing transactional features.
- Ad hoc ML feature building also benefits from the same modelled data.

## How it works / example
```
 App DB ----CDC/extract----\
 Event tracking -----------> raw layer -> staging (clean/dedupe) -> marts (star schemas) -> BI / ML
 SaaS exports (CRM/payments)/                     (dbt SQL models, tests, scheduling)
```

Star schema for sales:
```sql
CREATE TABLE dim_date (
  date_key int PRIMARY KEY, full_date date, year int, month int, weekday text, is_holiday boolean
);
CREATE TABLE dim_product (
  product_key bigint PRIMARY KEY, sku text, name text, category text
);
CREATE TABLE dim_customer (            -- SCD Type 2
  customer_key bigint PRIMARY KEY, customer_id bigint, segment text, country text,
  valid_from date, valid_to date, is_current boolean
);
CREATE TABLE fact_sales (              -- grain: one order line
  date_key int REFERENCES dim_date, product_key bigint REFERENCES dim_product,
  customer_key bigint REFERENCES dim_customer,
  order_id bigint, qty int, revenue_cents bigint
);

SELECT d.year, d.month, p.category, sum(f.revenue_cents)/100.0 AS revenue
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
JOIN dim_product p ON p.product_key = f.product_key
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
```

SCD2 load in SQL (close the old row, insert the new one):
```sql
UPDATE dim_customer c SET valid_to = current_date, is_current = false
FROM staging_customer s
WHERE c.customer_id = s.customer_id AND c.is_current AND (c.segment, c.country) <> (s.segment, s.country);

INSERT INTO dim_customer (customer_key, customer_id, segment, country, valid_from, valid_to, is_current)
SELECT nextval('customer_key_seq'), s.customer_id, s.segment, s.country, current_date, DATE '9999-12-31', true
FROM staging_customer s
LEFT JOIN dim_customer c ON c.customer_id = s.customer_id AND c.is_current
WHERE c.customer_id IS NULL;   -- new, or just closed above
```

A dbt model is just a SELECT in a file (`models/marts/fct_sales.sql`) with tests like `unique`, `not_null`, `relationships` declared in YAML; dbt builds a dependency graph and materialises tables or views.

## Trade-offs
- **Warehouse vs lakehouse**: warehouses are simple and fast to adopt; lakehouses give openness and cheap storage but more engineering.
- **Star schema vs wide denormalised tables**: stars are flexible and consistent; one big table is simplest and fast in columnar engines but duplicates dimension logic.
- **ETL vs ELT**: ELT keeps raw data for reprocessing and uses warehouse compute; ETL can cut volume or protect PII before landing.
- **Freshness vs cost**: hourly or daily loads are cheap; streaming loads cost more and complicate correctness.
- **Managed (BigQuery/Snowflake) vs self-run (ClickHouse)**: managed is elastic with usage-based cost surprises; self-run is cheaper at steady scale but needs operations.
- **Pre-aggregation vs raw queries**: aggregates speed dashboards but fix the questions you can answer.

## Gotchas
- Warehouses are not enforcing: primary and foreign keys are often informational only, so duplicates arrive silently. Add tests (dbt tests, row-count checks).
- Mixed grain in a fact table gives double counting when summing.
- Timezones and "late-arriving facts" (events before their dimension row exists) need explicit handling.
- Unbounded `SELECT *` over a columnar warehouse can be expensive on pay-per-scan engines; partition and cluster by date and filter columns.
- Dashboards hitting the warehouse directly can run up cost; cache or materialise.
- Source system schema changes break pipelines; monitor with contracts and alerts.
- PII in the raw layer needs the same access control and deletion handling (GDPR erasure) as production.
- Treat metric definitions ("active user", "revenue") as code in one place; two dashboards with different definitions destroy trust.

## Related
- [[batch-and-stream-processing]] - the pipelines that load and transform warehouse data
- [[data-modeling-and-schema-design]] - transactional modelling, the contrast to dimensional modelling
- [[sql-vs-nosql]] - OLTP engine choice that feeds the warehouse
- [[blob-object-storage]] - underlying storage for lakes and Parquet files
- [[partitioning-and-sharding]] - warehouse tables are partitioned and clustered for scan pruning
- [[probabilistic-data-structures]] - HyperLogLog behind approximate distinct counts.
- [[data-quality-and-data-contracts]] - checks and contracts that keep wrong numbers out of published tables.

## References
- Kimball and Ross, The Data Warehouse Toolkit, 3rd ed.
- Kleppmann, Designing Data-Intensive Applications, chapter 3 (column-oriented storage).
- dbt documentation: https://docs.getdbt.com/
- ClickHouse documentation: https://clickhouse.com/docs
