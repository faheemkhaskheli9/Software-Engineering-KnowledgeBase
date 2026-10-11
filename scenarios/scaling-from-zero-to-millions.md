---
title: Scaling from zero to millions of users
category: scenarios
tags: [scaling, growth-path, horizontal-scaling, caching, sharding, bottlenecks, capacity]
use_cases:
  - "our single-server app is getting slow as users grow, what do we do next and in what order"
  - "plan how a web product evolves architecturally from MVP to millions of users"
  - "decide when to add a cache, read replicas, a queue, a CDN, or sharding"
  - "explain the step-by-step scaling story in a system design interview"
status: draft
last_verified: 2026-10-11
sources:
  - https://bytebytego.com/courses/system-design-interview/scale-from-zero-to-millions-of-users
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://sre.google/sre-book/table-of-contents/
  - https://aws.amazon.com/architecture/well-architected/
---

# Scaling from zero to millions of users

## Summary
Scale in stages, each triggered by a measured bottleneck, not in advance. The typical order: single server, split database from app, add load balancer and stateless app tier, add caching and a CDN, add read replicas, move slow work to queues, then shard and go multi-region. Each step buys headroom and costs complexity, so take the cheapest step that fixes the current constraint.

## Key concepts
- **Vertical scaling** (bigger machine) is simple and has a ceiling and a single point of failure. **Horizontal scaling** (more machines) needs stateless services and a way to distribute load.
- **Bottleneck-driven.** Find the saturated resource (CPU, memory, DB connections, disk IO, network, a lock) before changing anything ([[observability-logs-metrics-traces]]).
- **Read vs write.** Reads scale with caches and replicas; writes are the hard part and eventually need partitioning.
- **Stateless tier + stateful tier.** Keep app servers disposable ([[twelve-factor-app]]); concentrate state in a few well-understood stores.
- **Sync vs async.** Anything the user need not wait for moves to a queue.
- **Numbers first.** Estimate QPS, storage and bandwidth ([[back-of-envelope-estimation]]) to know which stage you are actually at.

## When to use / scenarios
Use as the roadmap when asked "how will this scale?" Do not apply stages ahead of need: many products run comfortably on stage 2 or 3. A well-indexed single relational database goes a long way ([[database-indexing]]).

## How it works / example
Stage-by-stage, with trigger, action, and topics:

| Stage | Trigger (symptom) | Action | Read |
|---|---|---|---|
| 0. Single server | MVP | App, DB, files on one box; add monitoring, backups | [[observability-logs-metrics-traces]] |
| 1. Separate DB | App and DB fight for CPU/RAM | Move DB to managed instance; tune queries and indexes | [[database-indexing]], [[orm-and-n-plus-one]] |
| 2. Load balancer + N app servers | CPU-bound app, need redundancy | Stateless app tier behind LB; sessions in shared store/token | [[load-balancing]], [[authentication-and-sessions]] |
| 3. Cache + CDN | DB read load, slow static assets | Cache hot reads; offload static content and media | [[caching-strategies]], [[cdn-and-edge]], [[blob-object-storage]] |
| 4. Read replicas | Reads outgrow primary even with cache | Route reads to replicas, accept lag | [[replication]], [[consistency-models]] |
| 5. Queues and workers | Slow tasks (email, images, reports) hurt latency | Async processing, retries, DLQ | [[message-queues-and-streams]], [[idempotency-and-exactly-once]] |
| 6. Protect and shape | Abuse, bursts, noisy tenants | Rate limits, gateway, backpressure | [[rate-limiting]], [[api-gateway-and-service-mesh]], [[resilience-patterns]] |
| 7. Autoscale | Daily peaks, cost | Scale on metrics, define capacity targets | [[capacity-planning-and-autoscaling]] |
| 8. Shard writes | Single primary write/storage limit | Partition by key; avoid cross-shard transactions | [[partitioning-and-sharding]], [[consistent-hashing]], [[unique-id-generation]] |
| 9. Specialised stores | Search, analytics, feeds | Add search index, warehouse, stream pipeline | [[search-systems]], [[data-warehousing-and-olap]], [[batch-and-stream-processing]] |
| 10. Multi-region | Latency to far users, DR | Regional deployments, replication, failover | [[cap-and-pacelc]], [[failure-modes-and-fallacies]] |

Target shape around stages 3-7:

```
 users --> CDN --> LB --> [app x N] --+--> cache --> DB primary --> replicas
                              |       +--> queue --> [workers]
                              +--> object storage
```

Runnable sketch to reason about the cache step: expected DB load after a cache with a given hit rate.

```python
def db_qps_after_cache(read_qps: float, write_qps: float, hit_rate: float) -> float:
    """Reads that miss go to the DB; writes always do (write-through/invalidate)."""
    assert 0 <= hit_rate <= 1
    return read_qps * (1 - hit_rate) + write_qps

def replicas_needed(db_read_qps: float, per_node_read_qps: float) -> int:
    import math
    return max(1, math.ceil(db_read_qps / per_node_read_qps))

if __name__ == "__main__":
    # Plug in YOUR measured numbers; these are placeholders for the arithmetic only.
    qps = db_qps_after_cache(read_qps=1000, write_qps=50, hit_rate=0.9)
    print(qps, replicas_needed(qps - 50, per_node_read_qps=400))
```

Checklist before each step: what metric proves the need, what is the rollback, what new failure modes appear (stale cache, replica lag, duplicate messages, hot shard).

## Trade-offs
- **Premature scaling vs outage risk:** build for roughly the next order of magnitude, not three ahead. Keep seams (stateless app, queue-friendly jobs, IDs not tied to one DB) cheap to add early.
- **Cache vs replicas:** caches are cheaper and faster but add invalidation bugs; replicas are simpler semantically but add lag and cost.
- **Shard vs scale-up:** modern hardware and managed databases push the sharding point very far; shard when storage or write throughput truly exceeds one node.
- **Microservices as scaling:** they scale teams more than throughput ([[monolith-vs-microservices]]).
- **Managed services vs self-run:** managed shortens the path; watch cost at volume and quotas.

## Gotchas
- Adding app servers when the DB is the bottleneck makes things worse (more connections).
- Cache stampede on a cold or expired hot key; coalesce requests or use jittered TTLs.
- Replica lag causing "I saved but it is not there" bugs; read from primary after writes for that user.
- Sharding key chosen without access patterns: hot partitions and cross-shard joins.
- Autoscaling that reacts slower than the spike; keep headroom and warm capacity.
- Retries amplify overload (retry storms); add jitter and budgets ([[resilience-patterns]]).
- Load testing only the happy path; test with realistic data volume ([[performance-and-load-testing]]).
- Forgetting to scale the humans: on-call, runbooks, SLOs ([[slis-slos-error-budgets]]).

## Related
- [[scenario-chooser]] - map other specific problems to topics.
- [[choosing-a-database]] - where state lives at each stage.
- [[system-design-interview-framework]] - turn this roadmap into an interview answer.
- [[back-of-envelope-estimation]] - decide which stage numbers justify.
- [[caching-strategies]] - the highest-leverage early step.
- [[partitioning-and-sharding]] - the late, costly step.

## References
- Alex Xu, *System Design Interview - An Insider's Guide* (Volume 1), ch. 1 "Scale From Zero To Millions Of Users".
- Martin Kleppmann, *Designing Data-Intensive Applications*, 1st ed., Part II "Distributed Data" (ch. 5-9).
- Google SRE book, ch. 19 "Load Balancing at the Frontend", ch. 20 "Load Balancing in the Datacenter", ch. 21 "Handling Overload", ch. 22 "Addressing Cascading Failures".
- AWS Well-Architected Framework, performance efficiency pillar.
