---
title: Batch and stream processing
category: data
tags: [batch, streaming, kafka, flink, spark, etl, windowing, watermark, lambda-architecture]
use_cases:
  - "compute daily revenue reports from a large event log"
  - "detect fraud or anomalies within seconds of events arriving"
  - "build a real-time dashboard with per-minute aggregates"
  - "choose between Spark batch jobs and Kafka Streams or Flink"
status: draft
last_verified: 2026-10-10
sources:
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 10-11"
  - https://kafka.apache.org/documentation/streams/
  - https://nightlies.apache.org/flink/flink-docs-stable/
  - https://spark.apache.org/docs/latest/
  - "Tyler Akidau et al., The Dataflow Model, VLDB 2015"
---

# Batch and stream processing

## Summary
Batch processing runs a computation over a bounded, complete dataset on a schedule (nightly report, model training, backfill). Stream processing runs continuously over unbounded events as they arrive, producing results with low latency. Pick by how fresh the result must be and how much complexity (state, ordering, late data) you are willing to own.

## Key concepts
- **Bounded vs unbounded data**: a file or table snapshot vs a never-ending log of events.
- **Event time vs processing time**: when the event happened vs when the system saw it. Correct results use event time.
- **Windows**: tumbling (fixed, non-overlapping), sliding (overlapping), session (gap-based).
- **Watermark**: the system's estimate "no more events older than T will arrive"; closes windows and bounds state. Late events beyond it are dropped or routed to a side output.
- **State and checkpoints**: stream operators keep state (counts, joins) that is snapshotted so a restart resumes without loss.
- **Delivery semantics**: at-most-once, at-least-once, exactly-once (really effectively-once via idempotent sinks or transactions; see [[idempotency-and-exactly-once]]).
- **Log as backbone**: Kafka-style durable, replayable logs let you reprocess history (see [[message-queues-and-streams]]).
- **Architectures**: Lambda (separate batch and speed layers, two code paths) vs Kappa (one streaming path, reprocess by replaying the log). ELT/ETL pipelines orchestrated by Airflow, Dagster, Prefect.

## When to use / scenarios
- **Batch** when: results are needed hourly/daily, correctness over complete data matters, you need big joins or ML training, cost efficiency (spin up, process, tear down). Tools: Spark, dbt over a warehouse, SQL jobs, plain Python with DuckDB for moderate data.
- **Stream** when: latency requirement is seconds or less: fraud checks, alerting, live metrics, CDC propagation, real-time recommendations. Tools: Kafka Streams, Flink, Spark Structured Streaming, Beam, cloud equivalents.
- **Micro-batch** (every minute, via batch tooling) is often enough and far simpler than true streaming.
- Do NOT adopt streaming for a report read once a day. Do NOT write ad hoc consumers with hand-rolled state; use a framework that provides checkpointing and windowing.
- Change data capture (Debezium) turns database writes into a stream to feed search indexes, caches and warehouses without dual writes.

## How it works / example
```
 sources -> [Kafka topic] -> stream job (window, join, aggregate) -> serving store / topic
                |                                                  
                +-> archive to object storage -> batch job (backfill, daily truth) -> warehouse
```

Batch job in Python with DuckDB (bounded input, simple and fast on one machine):
```python fragment
import duckdb
duckdb.sql("""
  COPY (
    SELECT date_trunc('day', ts) AS day, country, sum(amount) AS revenue
    FROM read_parquet('s3://bucket/events/dt=2026-10-09/*.parquet')
    GROUP BY 1, 2
  ) TO 'daily_revenue.parquet' (FORMAT parquet)
""")
```

Stream aggregate in plain Python to show the concepts (tumbling 1-minute window with watermark, using event time):
```python
from collections import defaultdict

WINDOW = 60          # seconds
LATENESS = 30        # allowed lateness
counts = defaultdict(int)   # window_start -> count
watermark = 0

def on_event(event_ts: int):
    global watermark
    window = event_ts - event_ts % WINDOW
    if window + WINDOW + LATENESS <= watermark:
        return "late-dropped"          # or send to a side output
    counts[window] += 1
    watermark = max(watermark, event_ts)   # naive: max seen time
    # emit and evict closed windows
    for w in [w for w in counts if w + WINDOW + LATENESS <= watermark]:
        print("final", w, counts.pop(w))
```

Kafka Streams-style consumer guidance: commit offsets only after the sink write succeeds, and make the sink an upsert keyed by (window, key) so replays overwrite instead of double count.

Enrichment join: stream-table join (events joined against a compacted topic or CDC-fed table) is the common pattern; stream-stream joins require windows and more state.

## Trade-offs
- **Latency vs complexity**: streaming gives seconds-fresh results but adds state management, watermarks, reprocessing and on-call load.
- **Lambda vs Kappa**: Lambda duplicates logic in two code paths that drift; Kappa needs a replayable log and a stream engine strong enough to reprocess history.
- **Exactly-once vs idempotent sinks**: framework "exactly-once" holds inside the system; end-to-end still needs transactional or idempotent writes.
- **Event time vs processing time**: event time is correct but needs watermarks and handles late data; processing time is easy but wrong under delays and replays.
- **Managed vs self-hosted**: Flink/Kafka clusters are real operational work; managed services cost more but save staff time.
- **Cost**: batch can use spot capacity and shut down; streaming jobs run 24/7.

## Gotchas
- Time zones and clock skew on producers corrupt event-time windows; use UTC and validate timestamps.
- Unbounded state growth (keys never expire) kills jobs; set TTLs and window bounds.
- Hot keys: one customer producing most events overloads a single partition; salt keys or pre-aggregate.
- Reprocessing after a bug fix double counts unless sinks are idempotent or outputs are versioned and swapped atomically.
- Schema changes in the stream break consumers; use a schema registry with compatibility rules (Avro/Protobuf).
- Consumer lag is the key health metric; alert on it, not just on errors (see [[observability-logs-metrics-traces]]).
- Small-file problem: writing many tiny Parquet files from streaming hurts later batch reads; compact regularly.
- Late and out-of-order events are normal, not exceptional; decide the policy up front.

## Related
- [[message-queues-and-streams]] - the transport layer streams run on
- [[data-warehousing-and-olap]] - typical destination for batch and stream outputs
- [[idempotency-and-exactly-once]] - making reprocessing and retries safe
- [[event-driven-architecture]] - streams as the backbone of event-driven systems
- [[time-clocks-and-ordering]] - why event time and ordering are hard
- [[change-data-capture]] - turning database commits into a stream these pipelines consume
- [[data-quality-and-data-contracts]] - per-batch checks, quarantine and write-audit-publish

## References
- Kleppmann, Designing Data-Intensive Applications, chapters 10 and 11.
- Akidau et al., The Dataflow Model (VLDB 2015); Akidau, Chernyak, Lax, Streaming Systems (O'Reilly, 2018).
- Kafka Streams docs: https://kafka.apache.org/documentation/streams/
- Apache Flink docs: https://nightlies.apache.org/flink/flink-docs-stable/
- Apache Spark docs: https://spark.apache.org/docs/latest/
