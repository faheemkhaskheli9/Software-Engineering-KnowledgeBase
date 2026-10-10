---
title: System design interview framework
category: system-design
tags: [system-design, interview, requirements, architecture, trade-offs, scaling]
use_cases:
  - "design a system like X from a vague one-line prompt and structure the answer"
  - "turn fuzzy product requirements into a high-level architecture with justified components"
  - "review a proposed design and find the missing pieces: bottlenecks, failure modes, data model"
  - "prepare for a system design interview with a repeatable step-by-step approach"
status: draft
last_verified: 2026-10-10
sources:
  - "Alex Xu, System Design Interview - An Insider's Guide (Vol 1 and 2), ch. 3 four-step framework"
  - "Martin Kleppmann, Designing Data-Intensive Applications, O'Reilly 2017"
  - https://github.com/donnemartin/system-design-primer
---

# System design interview framework

## Summary
A repeatable sequence for designing a large system from an ambiguous prompt:
clarify requirements, estimate scale, sketch a high-level design, deep-dive the
hard parts, then discuss bottlenecks and trade-offs. The same sequence works
for real design docs; the interview just compresses it into ~45 minutes. Use it
to avoid the two classic failures: jumping to boxes before knowing the
requirements, and listing technologies with no reasoning.

## Key concepts
- **Functional requirements**: what the system does (post a tweet, shorten a URL). Keep to 3-5 core features.
- **Non-functional requirements**: availability, latency, consistency, durability, scale, cost. These pick the architecture, not the features.
- **Back-of-envelope numbers** size the problem (QPS, storage, bandwidth) and decide whether you need sharding, caching or a CDN. See [[back-of-envelope-estimation]].
- **Read/write ratio** and **access pattern** (point lookup, range scan, fan-out) drive the storage choice.
- **Bottleneck-driven design**: start simple (one server + DB), find the first thing that breaks at the stated scale, fix it, repeat.
- **Trade-off language**: every choice is "X over Y because requirement Z". An unjustified component is noise.

## When to use / scenarios
- Any "design X" prompt: URL shortener, chat, feed, notifications, ride-sharing, payments.
- Writing a design doc / ADR for a new service where requirements are fuzzy.
- Reviewing a colleague's architecture: walk the same steps to find gaps.
- Not for: small apps where one Postgres and one app server is the right answer. Say so out loud; over-design is also a failure.

## How it works / example

The five steps and rough time split for a 45-minute session:

```
1. Requirements & scope        (~5 min)  ask, don't assume
2. Estimation & constraints    (~5 min)  QPS, storage, bandwidth
3. API + data model + HLD      (~10 min) boxes and arrows, end-to-end flow
4. Deep dive on 2-3 components (~15 min) the hard/interesting parts
5. Bottlenecks, failure, wrap  (~5-10 min) SPOFs, scaling, monitoring
```

### Step 1 - clarify (questions to always ask)
- Who are the users, how many (DAU/MAU)? Which features are in scope?
- Read-heavy or write-heavy? Peak vs average traffic?
- Latency target? Is stale data acceptable (consistency vs availability)?
- Durability: can we lose data? Retention period?
- Geography: single region or global? Mobile, web, API clients?

Write the agreed scope on the board. Everything later is checked against it.

### Step 2 - estimate
Compute QPS, peak QPS (commonly 2-10x average, state your assumption), storage
per day/year and bandwidth. Round aggressively; the order of magnitude is the
point. If the numbers say one database handles it, do not design sharding.

### Step 3 - high-level design
Define the API first (3-6 endpoints), then the core entities and which store
holds them, then draw the request path:

```
 client -> DNS -> CDN / LB -> API servers (stateless)
                               |-> cache (read path)
                               |-> primary DB (+ replicas)
                               |-> queue -> workers (async work)
                               |-> object store (blobs)
```

Walk one write and one read through the diagram out loud.

### Step 4 - deep dive
Pick the parts that are specific to this problem, not the generic LB/DB boxes.
Examples: ID generation and collision handling for a shortener; fan-out on
write vs read for a feed; delivery guarantees and ordering for chat; the
idempotency key for payments. Name the data structure or algorithm.

### Step 5 - bottlenecks and wrap-up
- Single points of failure, and how each is removed (replication, failover).
- What happens when a node, a zone or a dependency dies? Degrade gracefully.
- Hot keys / hot partitions, thundering herds.
- Monitoring: the 3-4 metrics you would alert on.
- What you would build in v1 vs defer.

### Trade-off sentence template
"I choose <option> over <alternative> because <requirement>. The cost is
<downside>, which we accept/mitigate by <mitigation>."

Example: "I use async replication to replicas over synchronous because read
latency and write availability matter more than reading our own writes
instantly; we route a user's reads to the primary for a few seconds after they
write."

## Trade-offs
- **Breadth vs depth**: covering every box shallowly scores worse than two components explained well. Let the interviewer steer the deep dive.
- **Simplicity vs future scale**: design for ~10x the stated load, not 1000x; mention what you would change at the next order of magnitude.
- **Consistency vs availability / latency**: pick per feature, not per system (payments strong, feed counts eventual).
- **Build vs buy**: for real projects prefer managed queues/DBs; in interviews, say you would and still explain how they work inside.

## Gotchas
- Starting to draw before asking a single question.
- Using a technology name as a justification ("use Kafka") with no reason tied to a requirement.
- Ignoring the data model; most scaling problems are data-access problems.
- Forgetting failure: no discussion of retries, idempotency, backpressure, or what happens on partial failure.
- Estimation theatre: precise-looking numbers that do not change any decision.
- Treating the prompt as fixed. Pushing back on scope ("we can drop X for v1") is a good signal.

## Related
- [[back-of-envelope-estimation]] - the numbers step in detail.
- [[scaling-from-zero-to-millions]] - the incremental "what breaks first" progression.
- [[load-balancing]] - standard block in nearly every design.
- [[caching-strategies]] - standard read-path block.
- [[design-url-shortener]] - a worked example of this framework.
- [[scenario-chooser]] - map a problem to the right topic files.

## References
- Alex Xu, *System Design Interview* vol 1 and 2 (ByteByteGo).
- Kleppmann, *Designing Data-Intensive Applications* (2017).
- System Design Primer: https://github.com/donnemartin/system-design-primer
