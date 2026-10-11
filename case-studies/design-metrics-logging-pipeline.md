---
title: Design a metrics and logging pipeline
category: case-studies
tags: [metrics, logging, monitoring, alerting, time-series, prometheus, opentelemetry, kafka, cardinality, case-study]
use_cases:
  - "design a Datadog or Prometheus style system that collects metrics from thousands of hosts and alerts on them"
  - "build a central log pipeline that ingests, indexes and retains application logs at high volume"
  - "keep ingest working when one service suddenly emits ten times more logs or a new high-cardinality label"
  - "store time series cheaply with downsampling and tiered retention"
  - "practice the metrics monitoring and alerting system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 2 (Alex Xu, Sahn Lam), 'Metrics Monitoring and Alerting System' chapter"
  - "Pelkonen et al., 'Gorilla: A Fast, Scalable, In-Memory Time Series Database', VLDB 2015"
  - https://prometheus.io/docs/introduction/overview/
  - https://prometheus.io/docs/practices/naming/
  - https://opentelemetry.io/docs/collector/
  - https://grafana.com/docs/loki/latest/
  - https://sre.google/sre-book/monitoring-distributed-systems/
---

# Design a metrics and logging pipeline

## Summary
An observability platform collects **metrics** (numeric time series), **logs**
(timestamped events) and often traces from every host and service, ships them
through a buffered pipeline, stores them in purpose-built stores, and serves
dashboards, queries and alerts. Metrics and logs share the ingest shape (agent
-> buffer -> processors -> storage) but differ in storage: metrics compress into
time-series blocks keyed by series, logs go to cheap object storage with a
small index. The hard parts are cardinality, bursty volume, cost of retention,
and keeping alerting alive when the pipeline itself is struggling.

## Key concepts
- **Series** = metric name + a set of labels (`http_requests_total{service="api",status="500"}`). Every distinct label combination is a new series; **cardinality** (number of series) drives memory and cost, not sample count. Prometheus' naming guidance warns against unbounded label values like user IDs.
- **Push vs pull**: Prometheus scrapes targets (pull); agents like the OpenTelemetry Collector or StatsD receive pushes. Pull makes "is the target up" free; push suits short-lived jobs and firewalled hosts.
- **Time-series compression**: delta-of-delta timestamps and XOR-encoded float values (Gorilla paper) shrink samples to a few bytes each.
- **Downsampling / rollups**: keep raw resolution for days, 1-minute and 1-hour aggregates for months.
- **Logs**: index only labels/metadata and keep the bodies compressed in object storage (Loki's approach), or index full text (Elasticsearch/OpenSearch) at higher cost.
- **Alerting** evaluates rules over recent data on a fixed interval and routes, dedupes and silences notifications ([[slis-slos-error-budgets]]).

## When to use / scenarios
- Building or choosing an internal monitoring platform for many services.
- Sizing and structuring a log pipeline before a vendor bill or a self-hosted cluster gets out of hand.
- Most teams should run a managed service or an established open-source stack (Prometheus/Mimir/Thanos, Loki, OpenSearch) and design only the pipeline and conventions; building a TSDB is rarely justified.
- For product analytics (clicks, funnels) use an event pipeline into a warehouse instead ([[data-warehousing-and-olap]]).

## How it works / example

### 1. Requirements
Functional:
- Collect host and application metrics (counters, gauges, histograms) and logs from all services.
- Query: dashboards over time ranges, ad-hoc label filtering, log search by service/time/text.
- Alert rules with notification routing (pager, chat, email), dedupe and silencing.
- Retention: raw metrics 15 days, rollups 1 year; logs 30 days hot, longer in archive (assumed policy).

Non-functional:
- Ingest must not lose data during bursts; small loss is tolerable for debug logs, not for alert-driving metrics.
- Alert evaluation delay of tens of seconds at most; dashboards a few seconds for recent data.
- The platform must stay up when the systems it monitors are failing (that is when it is needed).
- Cost scales roughly linearly with volume, with levers to cut it.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 5,000 hosts x 1,000 active series each = 5 M series, scraped every 15 s -> about 330,000 samples/s.
- At a few bytes per compressed sample (Gorilla-style), 330k x 86,400 s x ~2 bytes -> tens of GB/day of raw metric storage; series index and replication add to it.
- Logs: assume 5,000 hosts x 50 lines/s x 300 bytes -> 75 MB/s, about 6.5 TB/day raw; with compression assumed around 10x (measure it) -> under 1 TB/day in object storage.
- The log figure dominates cost; the metric figure dominates memory (active series held in RAM for the head block).

### 3. API
```
ingest:  OTLP (gRPC/HTTP) from agents/collectors;  Prometheus remote_write;  scrape /metrics
query:   GET /api/v1/query_range?query=rate(http_requests_total{status="500"}[5m])&start=&end=&step=
         GET /api/v1/logs?selector={service="api"}&contains=timeout&start=&end=&limit=
alerts:  rules as code in git, e.g. "error ratio > 2% for 5m -> page team-api"
```

### 4. Data model
```
metrics:
  series index: series_id <- hash(name + sorted labels); inverted index label=value -> [series_id]
  chunks: (series_id, time block) -> compressed (ts, value) samples
  blocks partitioned by time (e.g. 2 h), compacted and moved to object storage
logs:
  stream = label set {service, env, host}; chunk = compressed lines for one stream and time range
  index: labels + time -> chunk ids (small);  bodies in object storage
```

### 5. High-level architecture
```
 hosts/services: app (OTel SDK) -> local agent/collector (batch, retry, drop debug if needed)
                                         |
                                         v
                              Kafka (buffer, partitioned by series/stream hash)
                         /                 |                        \
   metrics ingesters (head block in RAM,   log ingesters (chunk +     stream jobs: rollups,
   WAL, flush blocks)                       index, flush)             derived metrics from logs
        |                                         |
   object storage (blocks, chunks) <------------- +
        ^
   query frontends (split by time, cache results) <- dashboards, ad-hoc queries
   rule evaluator / alert manager (reads recent data directly from ingesters)
```
The Kafka buffer absorbs bursts and lets ingesters restart without dropping
data ([[message-queues-and-streams]], [[batch-and-stream-processing]]).

### 6. Deep dive A: aggregation and the cardinality guard
Agents pre-aggregate before sending, and the pipeline enforces a per-tenant
series limit so one bad deploy that puts a request ID in a label cannot take
the cluster down.

```python
from collections import defaultdict

class Aggregator:
    """Roll raw points into 60 s buckets per series; reject new series past a per-tenant limit."""
    def __init__(self, max_series_per_tenant):
        self.max_series = max_series_per_tenant
        self.series = defaultdict(set)          # tenant -> set of series keys
        self.buckets = {}                       # (series, minute) -> [count, sum, min, max]
        self.rejected = 0

    def add(self, tenant, name, labels, ts, value):
        key = (tenant, name, tuple(sorted(labels.items())))
        known = self.series[tenant]
        if key not in known:
            if len(known) >= self.max_series:
                self.rejected += 1              # count it and expose as a metric; do not crash
                return False
            known.add(key)
        b = self.buckets.setdefault((key, int(ts // 60)), [0, 0.0, value, value])
        b[0] += 1; b[1] += value; b[2] = min(b[2], value); b[3] = max(b[3], value)
        return True

agg = Aggregator(max_series_per_tenant=2)
for t, v in [(0, 10), (30, 30), (61, 5)]:
    agg.add("acme", "latency_ms", {"route": "/a"}, t, v)
agg.add("acme", "latency_ms", {"route": "/b"}, 5, 7)
assert not agg.add("acme", "latency_ms", {"route": "/c", "user": "u123"}, 5, 1)  # over the limit
key = ("acme", "latency_ms", (("route", "/a"),))
assert agg.buckets[(key, 0)] == [2, 40.0, 10, 30]   # count, sum, min, max for minute 0
assert agg.buckets[(key, 1)] == [1, 5.0, 5, 5]
assert agg.rejected == 1
```

Count + sum + min + max per bucket keeps averages and extremes exact across
merges; percentiles cannot be merged from averages, so ship histograms
(bucket counts) and compute quantiles at query time.

### 7. Deep dive B: storage and retention
- Metrics ingesters keep the latest block (e.g. two hours) in memory with a write-ahead log for crash recovery, then flush immutable compressed blocks to object storage; compactors merge and downsample old blocks ([[blob-object-storage]]).
- Replicate each series to 3 ingesters (hash ring, [[consistent-hashing]]) and dedupe at query time, so one ingester loss loses no recent data.
- Logs: index labels only and grep compressed chunks at query time (cheap ingest, slower search), or full-text index (fast search, several times the storage and CPU). Choose by how logs are actually queried.
- Tiered retention: hot (SSD, days), warm (object storage, weeks), archive (cold object tier, months/years, restore on demand).

### 8. Deep dive C: alerting that survives incidents
- Rule evaluators read recent data from ingesters directly, not through the long-term store, so a backlog in compaction does not delay alerts.
- Run the alerting path (evaluator + alert manager) redundantly and, ideally, outside the failure domain it watches; add a "dead man's switch" alert that fires if the pipeline stops sending a heartbeat.
- Alert on symptoms (error ratio, latency SLO burn) rather than every cause; the Google SRE monitoring chapter makes this case ([[slis-slos-error-budgets]]).
- Dedupe and group notifications (one page per incident, not per host), with silences for maintenance.

### 9. Scaling and failure handling
- **Bursts**: agents batch and retry with backoff, the Kafka buffer absorbs spikes; under sustained overload drop debug logs first, then sample, never alert-driving metrics ([[resilience-patterns]]).
- **Hot tenant / hot partition**: per-tenant ingest rate and series limits ([[rate-limiting]]), partition by series hash rather than by tenant.
- **Query of death**: a query over a year of high-cardinality data; enforce limits on series touched and time range, split queries by time and cache results.
- **Ingester restart**: replay WAL and Kafka offsets; replication covers the gap.
- **Monitoring the monitor**: ingest lag, dropped samples/lines, active series per tenant, query latency, alert evaluation delay.
- **Privacy**: logs collect secrets and personal data by accident; redact at the agent and restrict access ([[secrets-management]]).

## Trade-offs
- Pull vs push collection: pull gives up-detection and central control of rate; push handles ephemeral jobs and NAT.
- Label-only log indexing (cheap) vs full-text indexing (fast arbitrary search).
- Raw retention vs downsampling: rollups cut cost but lose spikes shorter than the rollup interval.
- Pre-aggregation at the agent saves bandwidth but loses the ability to re-slice raw data later.
- Managed vendor (fast to adopt, cost grows with volume) vs self-hosted (engineering time, cheaper at scale).

## Gotchas
- User IDs, request IDs, full URLs or error messages as metric labels: cardinality explodes.
- Averaging percentiles across hosts: the result is not a percentile.
- Logging at debug level in production by default; the bill arrives before anyone reads the logs.
- Alerts that depend on the same cluster/region that is down.
- Counter resets after restarts mistaken for drops; use `rate()`-style functions that handle resets.
- Clock skew on hosts producing out-of-order or future samples; decide the accepted window ([[time-clocks-and-ordering]]).

## Related
- [[observability-logs-metrics-traces]] - what to emit and why; this case study is the backend that receives it
- [[slis-slos-error-budgets]] - alert rules built on SLOs
- [[message-queues-and-streams]] - Kafka as the ingest buffer
- [[batch-and-stream-processing]] - rollups and derived metrics
- [[blob-object-storage]] - long-term block and chunk storage
- [[time-series-databases]] - TSDB internals: chunks, Gorilla compression, retention
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Alex Xu and Sahn Lam, *System Design Interview Vol. 2*, "Metrics Monitoring and Alerting System"
- Pelkonen et al., "Gorilla: A Fast, Scalable, In-Memory Time Series Database", VLDB 2015: https://www.vldb.org/pvldb/vol8/p1816-teller.pdf
- Prometheus overview: https://prometheus.io/docs/introduction/overview/
- Prometheus metric and label naming: https://prometheus.io/docs/practices/naming/
- OpenTelemetry Collector: https://opentelemetry.io/docs/collector/
- Grafana Loki documentation: https://grafana.com/docs/loki/latest/
- Google SRE book, "Monitoring Distributed Systems": https://sre.google/sre-book/monitoring-distributed-systems/
