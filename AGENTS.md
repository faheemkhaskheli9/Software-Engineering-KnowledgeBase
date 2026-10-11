# Instructions for AI agents (Claude Code, Codex, Cursor, Copilot, ...)

This repo is a reference knowledge base on software engineering and system
design: fundamentals, design principles, architecture, distributed systems,
data, APIs, reliability/DevOps, security, testing, engineering practices, and
worked system-design case studies.

## Consulting it

1. Read `INDEX.md` (one section per category). Match your task against the
   **Tags** and **Use when** columns. `llms.txt` is a shorter one-line-per-topic
   list; `glossary.md` maps terms to the topic that explains each.
2. Read the **full** matched file(s), not just the index row. Follow `[[links]]`
   in the `## Related` section when they apply.
3. For "which approach/architecture/database for X?" start in
   `scenarios/scenario-chooser.md`, which maps problems to topic files.
4. For "design system X" start with `system-design/system-design-interview-framework.md`
   and check `case-studies/` for a close match.
5. Volatile facts (tool versions, cloud limits, prices) are only as fresh as
   the file's `last_verified` date (the **Verified** column). Check the cited
   source before relying on one.
6. Mention which file(s) informed your work.

Quick search without reading the index: `grep -ril "<keyword>" --include=*.md .`

## Which knowledge base answers what

| Question | Go to |
|---|---|
| Architecture, databases, APIs, scaling, caching, queues, reliability, security, testing, process | this base |
| Which AI model, library or technique; RAG, embeddings and vector DBs, LLM serving, prompt and semantic caching, evals, agents, fine-tuning, prompt injection | [AI Knowledge Base](https://github.com/faheemkhaskheli9/AI-Knowledge-Base) (start at its `INDEX.md` or `scenarios/scenario-chooser.md`) |

An LLM feature usually needs both: the AI KB for the model side, this base
for the system around it. Topics that border AI work end their `## Related`
section with a `See also (AI KB):` line pointing at the matching AI KB file.
Link to the AI KB with plain GitHub URLs, never `[[links]]` (those resolve
only inside this repo).

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
5. Run `python build_index.py` (stdlib only) and commit what it writes. It
   regenerates `INDEX.md` and `llms.txt`, fails on invalid frontmatter
   (`category` must match the folder, `status` must be a value listed below,
   `last_verified` a YYYY-MM-DD date, `sources` and `use_cases` non-empty), a
   missing or thin `_template.md` section (under 15 words, or a `## Related`
   with no `[[links]]`), or a broken `[[link]]` (in topics and
   `glossary.md`), and warns on orphan topics
   and on stale topics: `last_verified` older than 180 days, or 90 days for
   `reliability/` and `security/`. Re-check a stale topic's sources, then bump
   its date. CI fails if the committed `INDEX.md`/`llms.txt` are out of date.
   New terms worth defining go in `glossary.md` as `- **Term** - definition. [[topic]]`.
6. Run `python check_code.py [topic.md ...]` (stdlib only, also in CI). Every
   ` ```python ` block must compile; a topic's blocks are joined and run as one
   script (60 s timeout) unless they import a package that is not installed.
   CI installs `requirements-check.txt` first, so pure-library imports (fastapi,
   sqlalchemy, pytest, hypothesis, ...) run there; add a new one, pinned, if a
   topic needs it. Open a block
   with ` ```python fragment ` when it cannot run on its own (needs a server,
   network, database, git repo, or names defined outside the block); it is
   then only compiled. Prefer a self-contained block that runs.
7. Use LF line endings and UTF-8.
8. Optional, needs network: `python check_links.py [topic.md ...]` lists every
   `sources` URL that does not return 2xx; 403/429 (bot blocking) are warnings.
   It runs weekly in CI (`links` workflow), not on every push.

Before every commit, run the same offline checks CI runs, then commit any
`INDEX.md`/`llms.txt` change it makes:

```sh
python test_build_index.py && python build_index.py && python check_code.py
```

## Status values

- `draft` - the default for a new or changed topic.
- `stable` - all three hold: (1) every URL in `sources` resolves and the
  non-URL sources (books, papers) are real and cited at the right chapter;
  (2) `python check_code.py <file>` passes; (3) someone other than the author
  has read the whole file once and found no wrong claims, numbers or code.
  Promote by changing only the `status:` line.
- `needs-review` - a reader found a likely error, or a stale source; say what
  in the commit or an issue, and fix it before setting `stable` again.

A substantive edit to a `stable` topic (new claims, numbers or code) sets it
back to `draft` until it is reviewed again; fixing a typo or adding a Related
link does not.

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
