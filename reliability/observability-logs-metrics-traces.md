---
title: Observability - logs, metrics, traces
category: reliability
tags: [observability, logging, metrics, tracing, opentelemetry, prometheus, monitoring, alerting]
use_cases:
  - add structured logging, metrics and tracing to a new microservice
  - figure out why requests are slow across several services
  - set up dashboards and alerts that page on user impact instead of CPU noise
  - instrument a Python service with OpenTelemetry and export to a collector
  - stop a metrics bill or Prometheus server from blowing up because of label cardinality
status: draft
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/monitoring-distributed-systems/
  - https://opentelemetry.io/docs/concepts/signals/
  - https://prometheus.io/docs/practices/naming/
  - https://prometheus.io/docs/practices/instrumentation/
  - https://www.w3.org/TR/trace-context/
  - Observability Engineering (Majors, Fong-Jones, Miranda), O'Reilly
---

# Observability - logs, metrics, traces

## Summary
Observability is the ability to ask new questions about a running system from the telemetry it emits, without shipping new code. The three classic signals are logs (discrete events), metrics (aggregated numbers over time) and traces (the causal path of one request across services). Use all three, correlated by a shared request/trace ID, and alert on symptoms users feel rather than on every internal cause.

## Key concepts
- **Logs**: timestamped event records. Best for "what exactly happened to this one request". Emit structured (JSON) logs, never free text you must regex later.
- **Metrics**: numeric time series, cheap to store and query, ideal for dashboards and alerts. Types: counter (monotonic), gauge (up/down), histogram (distribution, gives percentiles).
- **Traces**: a tree of spans per request. Each span has name, start, duration, attributes, parent. Shows where latency lives in a multi-service call.
- **Context propagation**: the trace ID travels in headers (W3C `traceparent`) across HTTP/gRPC/queue hops so spans stitch together.
- **Cardinality**: the number of distinct label/attribute value combinations. Metrics systems store one series per combination; high cardinality is the main cost and outage driver.
- **Golden signals** (Google SRE): latency, traffic, errors, saturation. **RED** (rate, errors, duration) for request-driven services, **USE** (utilization, saturation, errors) for resources.
- **Monitoring vs observability**: monitoring checks known failure modes; observability lets you debug unknown ones using high-dimensional events.
- **OpenTelemetry (OTel)**: vendor-neutral API/SDK/protocol (OTLP) and Collector for all three signals. Instrument once, choose the backend later.

## When to use / scenarios
- Any service in production. The minimum viable set is structured logs with a request ID, RED metrics per endpoint, and a health check.
- Multiple services or async hops: add distributed tracing; without it, latency debugging is guesswork.
- Debugging a latency regression: start at the metric (which endpoint, which percentile), pivot to traces (which span), finish in logs (which error).
- When NOT to over-invest: a single-process script or internal tool does not need a trace backend; logs plus one uptime check is enough. Do not ship every debug log at full volume to a paid backend; sample or filter.

## How it works / example

```
 app (SDK) --OTLP--> OTel Collector --> metrics backend (Prometheus/Mimir)
                          |          --> trace backend   (Tempo/Jaeger)
                          |          --> log backend     (Loki/Elastic)
                          +-- batch, sample, redact, route
```

Minimal Python instrumentation (Flask-style service, OTLP export to a Collector on localhost):

```python
import logging, json, time
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

resource = Resource.create({"service.name": "orders-api", "deployment.environment": "prod"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="localhost:4317", insecure=True)))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("orders")
meter = metrics.get_meter("orders")
request_duration = meter.create_histogram("http.server.duration", unit="s")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span().get_span_context()
        return json.dumps({
            "ts": self.formatTime(record), "level": record.levelname,
            "msg": record.getMessage(),
            "trace_id": format(span.trace_id, "032x") if span.is_valid else None,
        })

log = logging.getLogger("orders")
h = logging.StreamHandler(); h.setFormatter(JsonFormatter()); log.addHandler(h); log.setLevel(logging.INFO)

def handle_order(order_id: str):
    start = time.perf_counter()
    with tracer.start_as_current_span("handle_order") as span:
        span.set_attribute("order.id", order_id)       # fine on a span, NOT as a metric label
        log.info("processing order")                     # carries trace_id for correlation
        ...
    request_duration.record(time.perf_counter() - start, {"route": "/orders", "status": "200"})
```

Practices that matter more than the tooling:
1. Log the trace ID in every line so you can jump from a trace to its logs and back.
2. Name metrics consistently (`<unit>_total` for counters, base units like seconds and bytes).
3. Expose a `/healthz` (liveness) and `/readyz` (readiness) separate from business metrics.
4. Alert on SLO burn rate or user-facing symptoms (see [[slis-slos-error-budgets]]), and use dashboards for the causes.

Prometheus-style alert on a symptom, not a cause:

```yaml
- alert: HighErrorRatio
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m]))
      / sum(rate(http_requests_total[5m])) > 0.02
  for: 10m
  labels: {severity: page}
  annotations:
    summary: "More than 2% of requests failing for 10m"
    runbook: "https://wiki.example.com/runbooks/high-error-ratio"
```

## Trade-offs
- **Logs vs metrics for the same fact**: logs are rich but costly to store and query at volume; metrics are cheap but lose detail. Count with metrics, explain with logs.
- **Trace sampling**: head sampling (decide at the start) is cheap but may drop the interesting slow/error traces; tail sampling (decide after the trace completes, in the Collector) keeps errors and outliers but needs memory and sticky routing.
- **Self-hosted vs SaaS**: self-hosting Prometheus/Loki/Tempo costs engineering time; SaaS costs money that scales with volume and cardinality. Budget either way.
- **Auto-instrumentation vs manual spans**: auto gets you HTTP/DB spans in minutes; add manual spans around business operations where the interesting time is spent.
- **Histogram buckets**: more buckets give better percentile accuracy but more series; choose buckets around your SLO threshold.

## Gotchas
- Putting user IDs, request IDs, emails or full URLs in metric labels creates unbounded series and takes Prometheus down. Put high-cardinality values in spans and logs only.
- Averages hide tail latency; use histograms and look at p95/p99. Percentiles cannot be averaged across instances; aggregate histogram buckets instead.
- Logging PII, tokens or full request bodies is a security and compliance incident waiting to happen; redact in the app or Collector.
- Unstructured multi-line stack traces split into separate log events; keep the stack inside one JSON field.
- Clock skew between hosts makes log ordering misleading; trust span parent/child structure and monotonic durations (see [[time-clocks-and-ordering]]).
- Alerting on CPU > 80% pages people for things that do not hurt users, and teaches them to ignore pages. Every page should be actionable and urgent.
- Dashboards nobody looks at and alerts nobody owns are noise. Review them after incidents.
- Missing context propagation through message queues breaks traces at the async boundary; inject trace headers into message metadata.
- Instrumentation itself can add latency or fail; export asynchronously with batching and never let telemetry errors crash the request path.

## Related
- [[slis-slos-error-budgets]] - turns metrics into reliability targets and sensible alerts.
- [[incident-response-and-postmortems]] - observability data is what responders use during an incident.
- [[resilience-patterns]] - circuit breaker state, retries and timeouts should all emit metrics.
- [[failure-modes-and-fallacies]] - the failure classes that telemetry must make visible.
- [[performance-and-load-testing]] - load tests are only useful when you can see saturation and latency.
- [[capacity-planning-and-autoscaling]] - utilization and saturation metrics drive scaling decisions.

## References
- Google SRE Book, ch. 6 "Monitoring Distributed Systems": https://sre.google/sre-book/monitoring-distributed-systems/
- OpenTelemetry signals and concepts: https://opentelemetry.io/docs/concepts/signals/
- Prometheus naming and instrumentation practices: https://prometheus.io/docs/practices/naming/
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- Majors, Fong-Jones, Miranda, Observability Engineering (O'Reilly).
