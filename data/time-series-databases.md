---
title: Time-series databases
category: data
tags: [time-series, tsdb, metrics, iot, cardinality, compression, gorilla, downsampling, retention, timescaledb, influxdb, prometheus, clickhouse]
use_cases:
  - "store metrics or IoT sensor readings that arrive every few seconds from thousands of devices"
  - "decide between plain Postgres, TimescaleDB, InfluxDB, Prometheus or ClickHouse for time-stamped data"
  - "keep a year of history without paying for raw resolution forever"
  - "find out why a metrics database runs out of memory after someone added a new label"
status: draft
last_verified: 2026-10-11
sources:
  - "Pelkonen et al., 'Gorilla: A Fast, Scalable, In-Memory Time Series Database', VLDB 2015: https://www.vldb.org/pvldb/vol8/p1816-teller.pdf"
  - https://prometheus.io/docs/prometheus/latest/storage/
  - https://www.tigerdata.com/docs/learn/hypertables/understand-hypertables
  - https://www.tigerdata.com/docs/learn/data-lifecycle/data-retention/data-retention-with-continuous-aggregates
  - https://docs.influxdata.com/influxdb/v2/reference/key-concepts/data-elements/
  - https://clickhouse.com/docs/reference/statements/create/table/codec
  - https://www.postgresql.org/docs/current/ddl-partitioning.html
---

# Time-series databases

## Summary
A time-series database (TSDB) stores sequences of `(timestamp, value)` samples
keyed by a series identity, and is built for one workload: a steady stream of
appends of recent data, queries over time ranges, aggregation into buckets, and
deletion of whole old ranges. It wins over a general table through time
partitioning, compression that exploits regular timestamps and slowly changing
values, and built-in downsampling and retention. Below a certain volume a
partitioned Postgres table does the same job with one fewer system to run.

## Key concepts
- **Series** = metric name + tag set (labels). InfluxDB calls the identity a *series key*, "a unique combination of measurement and tag set"; Prometheus uses metric name + labels. Each series holds `(timestamp, value)` samples.
- **Tags vs fields**: tags identify the series and are indexed; values (InfluxDB *fields*) are not indexed. Filter by tags, aggregate values.
- **Cardinality** = number of distinct series. Every new tag value creates a new series with its own index entries and (in Prometheus-style engines) in-memory head state, so memory and index size track cardinality, not sample count. User IDs, request IDs or raw URLs as tags are the classic outage ([[design-metrics-logging-pipeline]]).
- **Append-mostly writes**: samples arrive roughly in time order and are almost never updated; late or out-of-order samples are an exception the engine bounds by a window.
- **Time partitioning / chunks / blocks**: data is split into time ranges. Prometheus groups ingested samples into two-hour blocks protected by a write-ahead log, then compacts them into larger blocks; TimescaleDB hypertables split a Postgres table into chunks by `chunk_time_interval`. Queries touch only the chunks in their range, and retention drops whole chunks.
- **Compression** (Gorilla, VLDB 2015): timestamps are stored as *delta-of-delta*, so a fixed scrape interval costs one `0` bit per sample (about 96% of Facebook's timestamps); values are XORed with the previous value, so an unchanged value costs one bit (about 51% of values). The paper reports 16 bytes per point down to an average of 1.37 bytes. ClickHouse exposes the same ideas as the `DoubleDelta` and `Gorilla` column codecs.
- **Downsampling / rollups**: pre-aggregate raw samples into coarser buckets (1 min, 1 h) and keep those longer than the raw data.
- **Retention**: delete data older than a horizon, per resolution tier. Dropping a partition is cheap; row-by-row `DELETE` is not.

## When to use / scenarios
- Metrics and monitoring, IoT telemetry, financial ticks, application events counted over time: high append rate, queries always bounded by time, old data less valuable than new.
- **Just use Postgres** when volume is modest, you need joins to business tables, or you already run it well: a table partitioned by time (native declarative partitioning or the TimescaleDB extension) with a BRIN or `(series_id, ts)` index covers a lot. Dropping a partition is "far faster than a bulk operation" and avoids the `VACUUM` overhead of a bulk `DELETE` (PostgreSQL docs).
- **TimescaleDB**: you want Postgres SQL, joins and tooling plus automatic chunking, continuous aggregates, retention policies and columnar compression.
- **Prometheus TSDB** (and long-term stores built on its block format): pull-based infrastructure and service metrics with PromQL and alerting; not for per-event or per-user data.
- **InfluxDB**: purpose-built metrics/IoT store with tag/field model and bucket retention.
- **ClickHouse**: high-volume events and logs where you also need ad-hoc analytical SQL; time series is one workload of a columnar OLAP engine ([[data-warehousing-and-olap]]).
- Not a TSDB problem: per-entity current state ("latest reading per device" only) fits a normal table with an upsert; product analytics funnels fit a warehouse.

## How it works / example
Delta-of-delta timestamp encoding with the bit buckets from the Gorilla paper
(section 4.1.1), plus the XOR step for values. Regular intervals collapse to a
single bit per sample; one late sample costs a few bits until the cadence
returns.

```python
import struct

def dod_encode(ts):
    """Timestamps -> (first, first_delta, delta-of-deltas). Needs >= 2 points."""
    assert len(ts) >= 2
    deltas = [b - a for a, b in zip(ts, ts[1:])]
    return ts[0], deltas[0], [b - a for a, b in zip(deltas, deltas[1:])]

def dod_decode(first, first_delta, dods):
    out, delta = [first, first + first_delta], first_delta
    for d in dods:
        delta += d
        out.append(out[-1] + delta)
    return out

def gorilla_bits(d):
    """Bits Gorilla spends on one delta-of-delta (control bits + payload)."""
    if d == 0:
        return 1
    if -63 <= d <= 64:
        return 2 + 7
    if -255 <= d <= 256:
        return 3 + 9
    if -2047 <= d <= 2048:
        return 4 + 12
    return 4 + 32

def xor_prev(a, b):
    as_int = lambda f: struct.unpack(">Q", struct.pack(">d", f))[0]
    return as_int(a) ^ as_int(b)

# scrape every 60 s, one sample 2 s late
ts = [1_700_000_000 + 60 * i for i in range(6)]
ts[3] += 2
first, first_delta, dods = dod_encode(ts)
assert dod_decode(first, first_delta, dods) == ts            # lossless round trip
assert dods == [0, 2, -4, 2]
assert sum(gorilla_bits(d) for d in dods) == 1 + 9 + 9 + 9   # vs 64 bits per raw timestamp

regular = [60 * i for i in range(1000)]
_, _, d = dod_encode(regular)
assert sum(map(gorilla_bits, d)) == len(d)                   # one bit per sample

assert xor_prev(12.0, 12.0) == 0                             # unchanged value -> single '0' bit
x = xor_prev(12.0, 24.0)                                     # the paper's Figure 2 example
leading = 64 - x.bit_length()
trailing = (x & -x).bit_length() - 1
assert (leading, 64 - leading - trailing) == (11, 1)         # 11 leading zeros, 1 meaningful bit
```

The "just Postgres" shape, then the TimescaleDB equivalents:

```sql
-- plain Postgres: one partition per day, dropped for retention
CREATE TABLE readings (
  device_id bigint      NOT NULL,
  ts        timestamptz NOT NULL,
  value     double precision NOT NULL
) PARTITION BY RANGE (ts);
CREATE TABLE readings_2026_10_11 PARTITION OF readings
  FOR VALUES FROM ('2026-10-11') TO ('2026-10-12');
CREATE INDEX ON readings (device_id, ts);
DROP TABLE readings_2026_09_11;            -- retention: no bulk DELETE, no VACUUM debt

-- TimescaleDB (alternative, on a plain non-partitioned table):
-- automatic chunks, a daily rollup, and retention on raw data
CREATE TABLE metrics (device_id bigint NOT NULL, ts timestamptz NOT NULL, value double precision);
SELECT create_hypertable('metrics', by_range('ts'));
CREATE MATERIALIZED VIEW metrics_daily WITH (timescaledb.continuous) AS
  SELECT time_bucket('1 day', ts) AS day, device_id, avg(value), max(value)
  FROM metrics GROUP BY 1, 2;
SELECT add_continuous_aggregate_policy('metrics_daily', '7 days', '1 day', '1 day');
SELECT add_retention_policy('metrics', INTERVAL '30 days');
```

## Trade-offs
- **Postgres (partitioned or TimescaleDB) vs dedicated TSDB**: SQL, joins, transactions and one operational stack vs higher ingest density, native PromQL/Flux-style queries and tighter compression in a specialised engine.
- **Raw retention vs rollups**: rollups cut storage and query time but lose spikes shorter than the bucket and cannot answer new questions about raw data. Keep count, sum, min and max per bucket so averages and extremes stay exact; percentiles need histograms, not averaged percentiles.
- **Chunk size**: small chunks make retention and query pruning fine-grained; many tiny chunks add planning and metadata overhead. Size from your ingest rate and query ranges, and check the engine's own guidance.
- **Cardinality vs query flexibility**: more tags allow finer slicing but multiply series. High-cardinality dimensions belong in logs, traces or an OLAP table, not metric tags.
- **Pull (Prometheus) vs push (InfluxDB, OTel)**: see [[design-metrics-logging-pipeline]].

## Gotchas
- A new tag with unbounded values (user ID, session, full URL, error text) multiplies series count overnight and takes down ingest memory. Enforce per-tenant series limits at ingest.
- Retention dropping raw data can silently delete rollups: TimescaleDB warns that if a continuous aggregate's refresh window overlaps data a retention policy removed, the refresh deletes the aggregated rows too. Keep raw retention longer than the refresh window.
- Row-by-row `DELETE` for retention on a big table causes bloat and long vacuums; drop partitions instead.
- Compression ratios depend on the data: irregular timestamps and noisy floats compress far worse than the 1.37 bytes/point Gorilla reported for Facebook's workload. Measure on your own series.
- Out-of-order and future samples from skewed clocks are rejected or land in odd blocks; define the accepted window ([[time-clocks-and-ordering]]).
- Counters reset on process restart; compute rates with functions that handle resets instead of raw differences.
- Averaging pre-computed percentiles across hosts or buckets does not give a percentile.

## Related
- [[design-metrics-logging-pipeline]] - full monitoring backend built on a TSDB, with a cardinality guard and rollup code
- [[observability-logs-metrics-traces]] - what to emit as metrics vs logs vs traces
- [[database-indexing]] - BRIN and composite `(series, ts)` indexes for the plain-Postgres option
- [[partitioning-and-sharding]] - time partitioning plus series-hash sharding at scale
- [[data-warehousing-and-olap]] - columnar engines such as ClickHouse for analytical event data
- [[batch-and-stream-processing]] - computing rollups in a stream instead of in the database
- [[sql-vs-nosql]] - where TSDBs sit among database families
- [[choosing-a-database]] - decision table that routes metrics and IoT data here
- [[graph-databases]] - another specialised store to justify against plain Postgres
- [[vector-databases-for-engineers]] - another specialised store to justify against plain Postgres

## References
- Pelkonen, Franklin, Teller, Cavallaro, Huang, Meza, Veeraraghavan, "Gorilla: A Fast, Scalable, In-Memory Time Series Database", PVLDB 8(12), 2015, section 4.1: https://www.vldb.org/pvldb/vol8/p1816-teller.pdf
- Prometheus storage (two-hour blocks, WAL, compaction, `--storage.tsdb.retention.time` default 15d): https://prometheus.io/docs/prometheus/latest/storage/
- TimescaleDB (Tiger Data) hypertables: https://www.tigerdata.com/docs/learn/hypertables/understand-hypertables
- TimescaleDB data retention with continuous aggregates: https://www.tigerdata.com/docs/learn/data-lifecycle/data-retention/data-retention-with-continuous-aggregates
- InfluxDB v2 data elements (measurement, tags, fields, series key): https://docs.influxdata.com/influxdb/v2/reference/key-concepts/data-elements/
- ClickHouse column compression codecs (`DoubleDelta`, `Gorilla`): https://clickhouse.com/docs/reference/statements/create/table/codec
- PostgreSQL table partitioning: https://www.postgresql.org/docs/current/ddl-partitioning.html
