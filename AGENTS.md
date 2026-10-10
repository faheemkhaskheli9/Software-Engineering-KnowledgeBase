# Instructions for AI agents (Claude Code, Codex, Cursor, Copilot, ...)

This repo is a reference knowledge base on software engineering and system
design: fundamentals, design principles, architecture, distributed systems,
data, APIs, reliability/DevOps, security, testing, engineering practices, and
worked system-design case studies.

## Consulting it

1. Read `INDEX.md`. Match your task against the **Tags** and **Use when** columns.
2. Read the **full** matched file(s), not just the index row. Follow `[[links]]`
   in the `## Related` section when they apply.
3. For "which approach/architecture/database for X?" start in
   `scenarios/scenario-chooser.md`, which maps problems to topic files.
4. For "design system X" start with `system-design/system-design-interview-framework.md`
   and check `case-studies/` for a close match.
5. Volatile facts (tool versions, cloud limits, prices) are only as fresh as
   the file's `last_verified` date. Check the cited source before relying on one.
6. Mention which file(s) informed your work.

Quick search without reading the index: `grep -ril "<keyword>" --include=*.md .`

Open improvement tasks for this base are GitHub issues labelled `kb-improvement`:
`gh issue list --label kb-improvement`.

## Adding or editing a topic

1. Copy `_template.md` into the right category folder. One topic per file,
   kebab-case filename.
2. Fill in every section. Code must be minimal and runnable (Python unless the
   topic is language-specific).
3. Cite sources (books, papers, official docs). Set `last_verified` to today.
   Do not invent numbers, benchmarks or limits; leave them out instead.
4. Link a new topic from at least one existing topic's `## Related`, or agents
   following links never reach it.
5. Run `python build_index.py` (stdlib only). It regenerates `INDEX.md`, fails
   on missing frontmatter or a broken `[[link]]`, and warns on orphan topics.
6. Use LF line endings and UTF-8.

## Categories

| Folder | Holds |
|---|---|
| `fundamentals/` | Complexity, data structures, algorithm patterns, concurrency, networking, performance |
| `design/` | SOLID, coupling/cohesion, design patterns, refactoring, clean code, error handling |
| `architecture/` | Monolith vs microservices, layered/hexagonal, DDD, event-driven, CQRS, serverless, 12-factor |
| `system-design/` | Building blocks: load balancing, caching, CDN, queues, rate limiting, search, estimation |
| `distributed-systems/` | CAP, consistency, replication, sharding, consensus, sagas, idempotency, clocks |
| `data/` | SQL vs NoSQL, indexing, transactions, modeling, migrations, batch/stream, OLAP |
| `apis/` | REST, gRPC, GraphQL, versioning, pagination, webhooks |
| `reliability/` | Observability, SLOs, resilience patterns, deployment, CI/CD, containers, k8s, IaC, incidents |
| `security/` | OWASP, authN/sessions, OAuth2/OIDC, authZ, secrets, threat modeling, crypto/TLS |
| `testing/` | Strategy, unit/doubles, integration/contract, TDD, property-based, load testing |
| `practices/` | Git workflows, code review, ADRs, tech debt, estimation, docs, SDLC |
| `case-studies/` | Worked designs: URL shortener, chat, feed, payments, ... |
| `scenarios/` | Problem -> recommended approach, linking the files above |
