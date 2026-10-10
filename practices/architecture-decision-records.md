---
title: Architecture decision records (ADRs)
category: practices
tags: [adr, decisions, documentation, architecture, governance, mads]
use_cases:
  - "record why we picked Postgres over DynamoDB so new hires stop re-litigating it"
  - "introduce a lightweight design-decision process in a team without heavy architecture review"
  - "write down a decision that we may need to reverse or supersede later"
  - "document trade-offs for a build-vs-buy or framework choice in the repo"
  - "audit why the system looks the way it does after the original authors left"
status: draft
last_verified: 2026-10-10
sources:
  - https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
  - https://adr.github.io/
  - https://github.com/joelparkerhenderson/architecture-decision-record
  - https://adr.github.io/madr/
  - https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html
---

# Architecture decision records (ADRs)

## Summary
An ADR is a short, immutable document capturing one significant architectural
decision: the context, the options considered, the choice made, and its
consequences. Stored with the code, ADRs preserve the *why* that code and
diagrams cannot, so future engineers can tell a deliberate constraint from an
accident and know when a decision is safe to revisit.

## Key concepts
- **Architecturally significant decision:** one that is costly to reverse or
  affects structure, quality attributes (latency, security, cost), dependencies,
  interfaces or construction techniques. Not every choice deserves an ADR.
- **One decision per record**, numbered sequentially (`0007-use-postgres.md`).
- **Immutable once accepted.** You do not edit history; you write a new ADR that
  *supersedes* the old one and link both ways.
- **Status lifecycle:** proposed -> accepted -> (deprecated | superseded by ADR-N).
  Rejected ADRs are worth keeping: they document what was *not* done and why.
- **Context first:** forces, constraints and requirements at decision time.
  The same choice can be wrong later when the forces change.
- **Consequences include the negative ones.** An ADR without a downside is
  marketing, not a record.
- **Lives in the repo** (`docs/adr/`), reviewed through pull requests (see
  [[code-review]]), so decisions get the same history and discussion as code.

## When to use / scenarios
- Choosing a database, message broker, framework, cloud provider, auth
  approach, service boundary or API style (see [[monolith-vs-microservices]],
  [[sql-vs-nosql]]).
- Deviating from a standard or adopting an exception ("we allow direct DB
  access from service X because...").
- Decisions people keep asking about in chat ("why don't we use X?").
- Cross-team decisions where a record helps alignment before implementation.
- **Skip** for reversible, local choices (variable names, an internal helper
  library) and for anything a linter or formatter already decides.
- **Avoid** turning ADRs into mandatory design-by-committee approval. They
  record decisions; who decides is a separate governance question. Heavy
  formats lead teams to stop writing them.

## How it works / example

Workflow:

```
need a significant decision
  -> copy template, number it, status: proposed, open PR
  -> discuss options in PR comments (time-box, e.g. one week)
  -> owner decides; status: accepted; merge
  -> later change of mind: new ADR "supersedes 0007"; old one marked superseded
```

Nygard-style template (the original, minimal):

```markdown
# 7. Use PostgreSQL for the orders service

Date: 2026-10-10
Status: Accepted (supersedes none)

## Context
Orders need multi-row transactions and ad-hoc reporting. Team has Postgres
experience. Expected volume is well within a single primary (see estimates in
the design doc). Alternatives considered: DynamoDB, MongoDB.

## Decision
We will use PostgreSQL (managed) as the system of record for orders.

## Consequences
+ ACID transactions, rich queries, mature tooling.
+ Fewer moving parts to operate.
- Horizontal write scaling needs sharding or a migration later.
- Schema changes need discipline (see schema-migrations).
```

MADR adds explicit option comparison, which many teams prefer:

```markdown
## Considered Options
* PostgreSQL
* DynamoDB
* MongoDB
## Decision Outcome
Chosen option: "PostgreSQL", because transactional integrity is required and ...
### Consequences
* Good, because ...
* Bad, because ...
## Pros and Cons of the Options
### DynamoDB
* Good, because near-unlimited horizontal scale
* Bad, because ad-hoc queries and multi-item transactions are awkward
```

Repo layout and a tiny helper to create the next numbered record:

```
docs/adr/
  0001-record-architecture-decisions.md
  0002-use-python-and-fastapi.md
  0007-use-postgres-for-orders.md
  README.md              # index: number, title, status
```

```python
import pathlib, re, sys, datetime
d = pathlib.Path("docs/adr"); d.mkdir(parents=True, exist_ok=True)
n = 1 + max([int(m.group(1)) for p in d.glob("*.md")
             if (m := re.match(r"(\d+)-", p.name))] or [0])
slug = re.sub(r"[^a-z0-9]+", "-", " ".join(sys.argv[1:]).lower()).strip("-")
path = d / f"{n:04d}-{slug}.md"
path.write_text(f"# {n}. {' '.join(sys.argv[1:])}\n\nDate: {datetime.date.today()}\n"
                "Status: Proposed\n\n## Context\n\n## Decision\n\n## Consequences\n")
print(path)
```

Good ADR checklist: states the problem in 3-5 sentences; lists real
alternatives (including "do nothing"); names the decision in active voice
("We will..."); lists both upsides and downsides; says what would make us
revisit it (a trigger such as "if write QPS exceeds one primary").

## Trade-offs
- **Heavyweight (MADR with scoring) vs minimal (Nygard).** More structure helps
  contentious decisions; for routine ones a half-page is enough.
- **ADR in repo vs wiki.** Repo keeps decisions versioned beside the code and
  reviewed; wikis are easier for non-engineers but rot and detach from changes.
- **Per-service vs central ADR log.** Per-repo ADRs stay close to the code;
  a central log (or an index) helps cross-cutting decisions. Many orgs do both.
- **Write before vs after deciding.** Before shapes the decision through
  review; after is cheaper but loses the options discussion. Prefer before for
  anything expensive.
- **Immutable vs editable.** Immutability gives a trustworthy timeline but
  needs supersede chains and an index to stay navigable.

## Gotchas
- Writing ADRs retroactively for decisions nobody remembers produces fiction;
  mark them "retroactive" and record only what is known.
- Not recording the rejected options removes the main value, since people will
  propose the same alternatives again.
- Letting the status rot: a superseded ADR still marked "accepted" misleads.
  Maintain the index or generate it in CI.
- ADRs that restate the code ("we use a repository class") instead of the
  reasoning.
- Tools and formats matter less than the habit; do not block on adopting
  adr-tools or Log4brains before writing the first one.
- Decisions made in meetings but never captured. Make "is this ADR-worthy?" a
  standing question in design discussions and in [[code-review]].
- Link to evidence (benchmarks, spike results, cost estimates) rather than pasting
  it; label any numbers as assumptions if they are projections.

## Related
- [[documentation-practices]] - where ADRs fit alongside READMEs, runbooks and diagrams
- [[technical-debt-management]] - deliberate debt decisions deserve an ADR with a repayment trigger
- [[monolith-vs-microservices]] - a classic ADR-worthy decision
- [[sql-vs-nosql]] - another high-cost-to-reverse choice commonly recorded
- [[system-design-interview-framework]] - trade-off articulation uses the same context/options/decision shape
- [[code-review]] - ADRs are proposed and debated as pull requests

## References
- Michael Nygard, "Documenting Architecture Decisions" (2011): https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- ADR GitHub organisation (tools, templates): https://adr.github.io/
- MADR, Markdown Architectural Decision Records: https://adr.github.io/madr/
- Joel Parker Henderson, ADR examples and templates: https://github.com/joelparkerhenderson/architecture-decision-record
- AWS Prescriptive Guidance, ADR process: https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html
