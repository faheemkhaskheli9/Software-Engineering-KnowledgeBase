---
title: Scenario chooser - what approach for X
category: scenarios
tags: [chooser, decision-guide, index, problem-to-topic, router]
use_cases:
  - "I have a concrete engineering problem and do not know which topic to read"
  - "which approach or pattern should I use for this requirement"
  - "map a project requirement to the right knowledge-base files"
  - "start a system design or architecture decision and find the relevant building blocks"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://www.oreilly.com/library/view/fundamentals-of-software/9781492043447/
  - https://sre.google/sre-book/table-of-contents/
  - https://www.oreilly.com/library/view/system-design-interview/9781736049112/
---

# Scenario chooser - what approach for X

## Summary
A router from concrete problems and requirements to the topic files that answer them. Find the row closest to your situation, read the linked topics in order, and apply them. For the big cross-cutting decisions there are dedicated guides: [[choosing-a-database]], [[choosing-communication-style]], [[scaling-from-zero-to-millions]], [[choosing-an-auth-approach]], [[choosing-a-caching-strategy]], [[background-jobs-and-queues]], [[choosing-a-multi-tenancy-model]], [[migrating-monolith-to-services]], [[choosing-realtime-updates]], and [[choosing-file-and-media-storage]].

## Key concepts
- Match on the **problem**, not on a technology name. Requirements (latency, consistency, volume, team size) decide the approach.
- Most rows list 2-4 topics: the first is the main answer, the rest are what you will trip over next.
- If two rows apply, start with the one about **correctness or data loss**, then performance, then cost.
- Default to the simplest option that meets stated numbers; get numbers with [[back-of-envelope-estimation]].

## When to use / scenarios
Use this file as the first stop for any "how should we..." question. For "design system X" go to [[system-design-interview-framework]] and check the case studies table below. If nothing fits, use the closest row and say so.

## How it works / example
Read the tables by category. Each row: situation, then topics to read.

### Architecture and structure
| Situation | Read |
|---|---|
| New product, small team, unsure about boundaries | [[monolith-vs-microservices]], [[layered-hexagonal-clean-architecture]] |
| Business rules are complex, language differs per team | [[domain-driven-design]], [[coupling-cohesion-and-design-principles]] |
| Business logic tangled with framework and DB, tests are slow | [[layered-hexagonal-clean-architecture]], [[unit-testing-and-test-doubles]], [[solid-principles]] |
| One action must trigger many independent side effects | [[event-driven-architecture]], [[message-queues-and-streams]], [[idempotency-and-exactly-once]] |
| Need full audit trail or separate read/write shapes | [[cqrs-and-event-sourcing]], [[event-driven-architecture]] |
| Spiky or low traffic, tiny ops team | [[serverless-architecture]], [[twelve-factor-app]] |
| Make a service portable and cloud-ready | [[twelve-factor-app]], [[containers-and-docker]], [[kubernetes-basics]] |
| Choose how services talk | [[choosing-communication-style]], [[rest-api-design]], [[grpc-and-protobuf]] |
| Split an existing monolith into services incrementally | [[migrating-monolith-to-services]], [[monolith-vs-microservices]], [[distributed-transactions-and-sagas]] |
| Slow work (emails, reports, media) should leave the request path | [[background-jobs-and-queues]], [[message-queues-and-streams]], [[idempotency-and-exactly-once]] |
| Many customers share one SaaS, data must stay isolated | [[choosing-a-multi-tenancy-model]], [[authorization-models]], [[partitioning-and-sharding]] |

### Data
| Situation | Read |
|---|---|
| Pick a datastore | [[choosing-a-database]], [[sql-vs-nosql]], [[data-modeling-and-schema-design]] |
| Queries are slow | [[database-indexing]], [[orm-and-n-plus-one]], [[caching-strategies]] |
| Concurrent updates corrupt data, double bookings, lost updates | [[transactions-and-isolation-levels]], [[idempotency-and-exactly-once]] |
| Change a schema with zero downtime | [[schema-migrations]], [[deployment-strategies]] |
| Analytics and reporting on large data | [[data-warehousing-and-olap]], [[batch-and-stream-processing]] |
| Process events or logs continuously | [[batch-and-stream-processing]], [[message-queues-and-streams]] |
| Full-text or relevance search | [[search-systems]], [[sql-vs-nosql]] |
| Store images, videos, backups | [[blob-object-storage]], [[cdn-and-edge]] |
| User uploads: validate, process, serve public or private files | [[choosing-file-and-media-storage]], [[blob-object-storage]], [[cdn-and-edge]] |

### APIs
| Situation | Read |
|---|---|
| Public HTTP API for third parties | [[rest-api-design]], [[api-versioning-and-evolution]], [[pagination-filtering-sorting]] |
| Internal service-to-service, strict contracts, streaming | [[grpc-and-protobuf]], [[integration-and-contract-testing]] |
| Many clients with different data needs | [[graphql]], [[rest-api-design]] |
| Notify customers' systems about events | [[webhooks]], [[idempotency-and-exactly-once]] |
| Evolving an API without breaking clients | [[api-versioning-and-evolution]] |
| Large result sets and listing endpoints | [[pagination-filtering-sorting]] |
| One entry point for auth, routing, throttling | [[api-gateway-and-service-mesh]], [[rate-limiting]] |

### Scaling and performance
| Situation | Read |
|---|---|
| Growing from one server to millions of users | [[scaling-from-zero-to-millions]] |
| Distribute traffic across servers | [[load-balancing]], [[consistent-hashing]] |
| Reads dominate and the DB is the bottleneck | [[caching-strategies]], [[replication]], [[database-indexing]] |
| Single DB cannot hold the data or write rate | [[partitioning-and-sharding]], [[consistent-hashing]] |
| Global users, static assets, latency | [[cdn-and-edge]], [[caching-strategies]] |
| Absorb bursts, smooth load | [[message-queues-and-streams]], [[rate-limiting]], [[capacity-planning-and-autoscaling]] |
| Where and how to cache (HTTP, CDN, in-process, Redis) | [[choosing-a-caching-strategy]], [[caching-strategies]], [[cdn-and-edge]] |
| Live updates, chat, presence | [[realtime-websockets-sse]], [[design-chat-system]] |
| Polling vs SSE vs WebSockets for live updates | [[choosing-realtime-updates]], [[realtime-websockets-sse]] |
| Need ids that are unique across machines | [[unique-id-generation]] |
| Estimate size, QPS, storage | [[back-of-envelope-estimation]] |
| Code is slow or memory-hungry | [[big-o-complexity]], [[memory-and-performance]], [[concurrency-and-parallelism]] |

### Distributed systems and reliability
| Situation | Read |
|---|---|
| Choose consistency vs availability | [[cap-and-pacelc]], [[consistency-models]] |
| Replicas disagree, stale reads | [[replication]], [[consistency-models]], [[time-clocks-and-ordering]] |
| Multi-service business transaction | [[distributed-transactions-and-sagas]], [[idempotency-and-exactly-once]] |
| Leader election, locks, agreement | [[consensus-raft-paxos]], [[time-clocks-and-ordering]] |
| Dependency is slow or down, cascading failure | [[resilience-patterns]], [[failure-modes-and-fallacies]] |
| Retries produce duplicates | [[idempotency-and-exactly-once]], [[resilience-patterns]] |
| Know when the system is unhealthy | [[observability-logs-metrics-traces]], [[slis-slos-error-budgets]] |
| Ship safely and roll back | [[deployment-strategies]], [[ci-cd-pipelines]] |
| Run containers in production | [[containers-and-docker]], [[kubernetes-basics]], [[infrastructure-as-code]] |
| Outage happened | [[incident-response-and-postmortems]], [[observability-logs-metrics-traces]] |
| How many servers will we need | [[capacity-planning-and-autoscaling]], [[back-of-envelope-estimation]] |

### Security
| Situation | Read |
|---|---|
| Review a web app for vulnerabilities | [[owasp-top-10]], [[threat-modeling]] |
| Pick an auth approach (sessions, JWT, OIDC/SSO, API keys, mTLS) | [[choosing-an-auth-approach]], [[authentication-and-sessions]], [[oauth2-and-oidc]] |
| Login, sessions, passwords, MFA | [[authentication-and-sessions]], [[cryptography-and-tls]] |
| Login with Google, API access delegation | [[oauth2-and-oidc]] |
| Who can do what (roles, ownership, tenants) | [[authorization-models]] |
| API keys and credentials management | [[secrets-management]] |
| New feature touching sensitive data | [[threat-modeling]], [[cryptography-and-tls]] |

### Testing and practices
| Situation | Read |
|---|---|
| What tests should we write | [[testing-strategy-and-pyramid]], [[unit-testing-and-test-doubles]] |
| Services break each other | [[integration-and-contract-testing]] |
| Hard-to-specify logic, parsers, invariants | [[property-based-and-fuzz-testing]] |
| Will it handle launch day | [[performance-and-load-testing]], [[capacity-planning-and-autoscaling]] |
| Requirements unclear, want executable specs | [[tdd-and-bdd]] |
| Messy code, hard to change | [[refactoring-and-code-smells]], [[clean-code-and-naming]], [[technical-debt-management]] |
| Team branching and release flow | [[git-workflows-and-branching]], [[ci-cd-pipelines]] |
| Improve review quality | [[code-review]] |
| Record why we chose X | [[architecture-decision-records]], [[documentation-practices]] |
| Planning and estimating work | [[estimation-and-planning]], [[agile-scrum-kanban]] |
| Choose error handling approach | [[error-handling-strategies]] |

### Case studies (design system X)
| Design | Read |
|---|---|
| Short links | [[design-url-shortener]] |
| Messaging app | [[design-chat-system]] |
| Social timeline | [[design-news-feed]] |
| Push/email/SMS | [[design-notification-system]] |
| Search-engine crawler | [[design-web-crawler]] |
| YouTube/Netflix style | [[design-video-streaming]] |
| Uber/Lyft style | [[design-ride-sharing]] |
| Payments and ledgers | [[design-payment-system]] |
| Distributed KV store | [[design-key-value-store]] |
| Several users edit one document at once (Google Docs style) | [[design-collaborative-editor]] |
| Files appear on all of a user's devices (Dropbox style) | [[design-file-sync]] |
| Run delayed, recurring or cron jobs reliably | [[design-job-scheduler]] |
| Collect metrics and logs from every service, dashboards, alerts | [[design-metrics-logging-pipeline]] |
| Chat answers grounded in private documents (LLM + retrieval) | [[design-rag-chat]] |
| Shared quota service for an API fleet | [[design-rate-limiter]] |
| Suggestions as the user types (typeahead) | [[design-search-autocomplete]] |
| Sell limited seats under contention without double booking | [[design-ticket-booking]] |
| Any new design | [[system-design-interview-framework]] |

## Trade-offs
- Tables compress nuance; read the linked topic's "When NOT" section before committing.
- Some rows are symptoms with several causes (e.g. "slow"): measure first ([[observability-logs-metrics-traces]]).
- Reading breadth vs depth: for a design review, read the main topic fully and skim the rest.

## Gotchas
- Choosing the technology first ("we will use Kafka") then hunting for a problem. Start from the requirement row.
- Skipping the estimation step. Many "scale" rows are moot at your real numbers.
- Using the case studies as templates rather than as worked examples of the trade-offs.
- Treating this table as complete; combine rows when a requirement has several facets.

## Related
- [[scaling-from-zero-to-millions]] - ordered growth path across many of these rows.
- [[choosing-a-database]] - the data decision in detail.
- [[choosing-communication-style]] - the interaction-style decision in detail.
- [[choosing-an-auth-approach]], [[choosing-a-caching-strategy]], [[background-jobs-and-queues]], [[choosing-a-multi-tenancy-model]], [[migrating-monolith-to-services]], [[choosing-realtime-updates]], [[choosing-file-and-media-storage]] - further problem-to-approach guides.
- [[system-design-interview-framework]] - structured method for open-ended design.
- [[monolith-vs-microservices]] - the first architecture decision most projects face.
- [[owasp-top-10]] - the security baseline that applies to every row.
- See also (AI KB): [AI scenario chooser](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/scenarios/scenario-chooser.md) - the same router for LLM and ML features (RAG, agents, model choice, serving, evals).

## References
- Martin Kleppmann, *Designing Data-Intensive Applications*.
- Mark Richards and Neal Ford, *Fundamentals of Software Architecture*.
- Betsy Beyer et al., *Site Reliability Engineering* (sre.google).
- Alex Xu, *System Design Interview*.
