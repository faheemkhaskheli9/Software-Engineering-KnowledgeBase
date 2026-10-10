---
title: Serverless architecture
category: architecture
tags: [serverless, faas, lambda, cold-start, event-triggers, managed-services, cost-model]
use_cases:
  - "run spiky or low-traffic backend code without managing servers"
  - "process uploaded files or queue messages with pay-per-use compute"
  - "decide whether Lambda-style functions or containers fit our API workload"
  - "reduce ops burden for a small team by using managed building blocks"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/articles/serverless.html
  - https://docs.aws.amazon.com/lambda/latest/dg/welcome.html
  - https://cloud.google.com/functions/docs/concepts/overview
  - https://learn.microsoft.com/en-us/azure/azure-functions/functions-overview
  - https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html
---

# Serverless architecture

## Summary
Serverless means you run code and use managed services without provisioning or patching servers; the platform scales to demand, including to zero, and bills by use. Two flavors: Functions-as-a-Service (Lambda, Cloud Functions, Azure Functions) triggered by events, and Backend-as-a-Service (managed databases, auth, queues, storage). It trades control and predictability for operational simplicity and elastic cost.

## Key concepts
- **Function**: stateless handler invoked per event (HTTP via gateway, queue message, object upload, schedule, stream record). Each invocation may run on a fresh or reused instance.
- **Cold start**: the extra latency when a new execution environment initializes (runtime start, code load, your init). Warm instances reuse state between invocations.
- **Stateless compute, external state.** Anything durable lives in a database, object store, or queue; in-memory state is only a cache.
- **Concurrency model**: typically one request per instance per time; platforms scale by adding instances, and have concurrency limits and per-account quotas (check provider docs; they change).
- **Execution limits**: maximum duration, memory, payload size, and package size are bounded and provider-specific. Long jobs need other tools (containers, workflow services).
- **Event sources and retries**: async triggers retry on failure, so handlers must be idempotent ([[idempotency-and-exactly-once]]); failed events go to a dead-letter queue.
- **Pay per use**: billed on invocations, duration times memory, plus the managed services around it. Cheap at low or bursty load; can exceed container cost at steady high load.
- **Serverless containers** (Cloud Run, Fargate, Container Apps) bridge the gap: any container image, scale-to-zero or minimal, per-request or per-second billing.

## When to use / scenarios
- Spiky, unpredictable, or low-volume workloads; internal tools; prototypes; scheduled jobs.
- Event glue: image thumbnailing on upload, webhook receivers ([[webhooks]]), ETL triggers, queue consumers ([[message-queues-and-streams]]).
- Small team without ops capacity, where managed services replace self-run infrastructure.
- Fan-out parallel processing of independent items.

When NOT:
- Steady, high, predictable throughput where reserved containers or VMs are cheaper.
- Ultra-low, consistent latency requirements where cold starts hurt (mitigate with provisioned concurrency, or choose containers).
- Long-running, stateful, or connection-heavy workloads (WebSocket servers, large in-memory models) though some platforms now support parts.
- Heavy vendor-neutral portability requirements: triggers, IAM and event formats are proprietary.
- Database connection pressure: thousands of concurrent functions can exhaust a relational DB; use a pooler/proxy or data API.

## How it works / example
```
 client --> API gateway --> [fn: create_order] --> managed DB
                                 | emits event
                                 v
                           queue/topic --> [fn: send_email]
 S3 upload event ----------------------> [fn: make_thumbnail] --> object store
```

A Lambda-style handler with the main practices: init outside the handler, idempotency key, structured logging, partial batch failure reporting.

```python
import json, logging, os

log = logging.getLogger(); log.setLevel(logging.INFO)

# Runs once per cold start; reused across warm invocations.
TABLE = os.environ.get("TABLE", "orders")
_seen: set[str] = set()            # per-instance cache only, NOT a dedup guarantee

def process(body: dict) -> None:
    ...                             # business logic; must itself be idempotent (DB conditional write)

def handler(event, context):
    """SQS-triggered: return failed ids so only those are retried."""
    failures = []
    for rec in event.get("Records", []):
        try:
            body = json.loads(rec["body"])
            process(body)
        except Exception:
            log.exception("failed message_id=%s", rec.get("messageId"))
            failures.append({"itemIdentifier": rec["messageId"]})
    return {"batchItemFailures": failures}

if __name__ == "__main__":
    print(handler({"Records": [{"messageId": "1", "body": json.dumps({"id": 1})},
                               {"messageId": "2", "body": "not json"}]}, None))
```

Design heuristics: small, single-purpose functions; compose with managed workflow (state machines) instead of function-calls-function chains; keep deploy packages small; configure timeouts below the caller's timeout; give each function least-privilege IAM ([[authorization-models]]).

## Trade-offs
- **Ops vs control:** no servers to patch, but little control over runtime, networking, and debugging.
- **Cost:** near-zero idle cost and elastic scaling versus potentially higher unit cost at sustained load. Model it with [[back-of-envelope-estimation]] using provider pricing pages (volatile; verify).
- **Latency:** cold starts are workload and runtime dependent; measure rather than assume. Mitigations: lighter runtimes, smaller packages, provisioned/minimum instances, keeping init lean.
- **Granularity:** many tiny functions increase deployment and observability surface; a "monolithic function" (one function, internal router) simplifies deploys but loses per-route scaling and permissions.
- **Lock-in:** accept it consciously, or isolate with ports/adapters ([[layered-hexagonal-clean-architecture]]) so business logic stays portable.

## Gotchas
- **Retries cause duplicates.** Every async trigger is at-least-once; design for it.
- **Recursive invocation loops** (function writes to the bucket that triggers it) can run up bills. Use prefix filters and budget alarms.
- **Unbounded fan-out** overwhelms downstream databases and third-party APIs; set reserved concurrency limits ([[rate-limiting]]).
- **Local dev and testing** differ from cloud behavior; rely on [[integration-and-contract-testing]] against real services in a sandbox account.
- **Distributed tracing is essential** across functions and queues ([[observability-logs-metrics-traces]]).
- **Hidden costs:** NAT gateways, API gateway requests, log ingestion, and data transfer often dominate the function bill.
- **Timeouts and partial failure** in synchronous chains: avoid function-to-function sync calls.
- **Secrets** belong in a secrets manager, not environment variables checked into IaC ([[secrets-management]]).
- Define infrastructure as code from day one ([[infrastructure-as-code]]); console-clicked serverless apps are unreproducible.

## Related
- [[event-driven-architecture]] - serverless is typically event-triggered.
- [[twelve-factor-app]] - stateless processes and config principles carry over.
- [[monolith-vs-microservices]] - functions as a deployment granularity choice.
- [[infrastructure-as-code]] - how to deploy and version it.
- [[capacity-planning-and-autoscaling]] - concurrency limits and cost modeling.
- [[choosing-communication-style]] - how functions should talk to each other.

## References
- Mike Roberts, "Serverless Architectures" (martinfowler.com).
- AWS Lambda Developer Guide and Serverless Applications Lens (AWS Well-Architected).
- Google Cloud Functions / Cloud Run documentation; Azure Functions documentation.
