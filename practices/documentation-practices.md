---
title: Documentation practices
category: practices
tags: [documentation, readme, runbook, diataxis, docs-as-code, api-docs, onboarding, diagrams]
use_cases:
  - "write a README and onboarding guide so a new engineer can run the service on day one"
  - "organise documentation so people can find tutorials, how-tos, reference and explanations"
  - "create runbooks for on-call so incidents do not depend on tribal knowledge"
  - "keep docs from going stale by treating them like code"
  - "document an HTTP API and architecture with diagrams that stay current"
status: draft
last_verified: 2026-10-10
sources:
  - https://diataxis.fr/
  - https://www.writethedocs.org/guide/
  - https://c4model.com/
  - https://developers.google.com/tech-writing
  - https://www.openapis.org/
  - "Docs for Developers (Bhatti et al.), 2021"
---

# Documentation practices

## Summary
Good documentation lets someone other than the author use, operate and change
the system without asking. The practical approach is to document by *reader
need* (learning, doing, looking up, understanding), keep docs in the repo and
reviewed like code, generate what can be generated, and delete what has gone
stale. A small amount of accurate documentation beats a large wiki nobody trusts.

## Key concepts
- **Diataxis framework** splits docs into four types by purpose:
  tutorials (learning-oriented), how-to guides (task-oriented), reference
  (information-oriented), explanation (understanding-oriented). Mixing them in
  one page is the commonest cause of unusable docs.
- **Docs as code:** Markdown/reStructuredText in the repo, built in CI, reviewed
  in pull requests (see [[code-review]]), versioned with the code they describe.
- **Single source of truth:** generate reference from code or spec (OpenAPI,
  docstrings, protobuf, CLI `--help`) so it cannot drift.
- **Audience first:** a new teammate, an on-call engineer at 3am, an API
  consumer and an executive need different docs.
- **Documentation of decisions** belongs in [[architecture-decision-records]];
  of operations in runbooks; of structure in diagrams (C4 model levels:
  context, containers, components, code).
- **Freshness ownership:** every doc has an owner and a place where changes to
  the code prompt changes to the doc (PR template checkbox, CODEOWNERS).
- **Comments explain *why*,** names and types explain *what* (see
  [[clean-code-and-naming]]).

## When to use / scenarios
- **Open source or shared library:** README, quick start, API reference,
  changelog, contribution guide, examples that are tested.
- **Internal service:** README (what/why/run/test/deploy), architecture overview,
  ADRs, runbook with alerts mapped to actions, ownership and contact info.
- **Public API:** reference generated from an OpenAPI/gRPC spec plus guides for
  auth, pagination, errors, rate limits and versioning (see [[rest-api-design]],
  [[api-versioning-and-evolution]]).
- **On-call readiness:** runbooks linked from each alert (see
  [[observability-logs-metrics-traces]]).
- **Avoid** documenting what the code already says well, or duplicating the
  same facts across wikis, slides and READMEs.
- **Avoid** big-bang documentation projects; add docs as a part of the change
  that needs them.

## How it works / example

Minimal README skeleton (answers the first-day questions in order):

```markdown
# order-service
One sentence: what it does and who owns it (#team-orders, on-call rota link).

## Quick start
    make setup && make test && make run      # works on a clean machine

## Architecture in 60 seconds
Diagram + 5 bullets: inputs, outputs, datastores, dependencies, critical flows.

## Common tasks
Run migrations, add an endpoint, rotate a secret, deploy, roll back.

## Operations
Dashboards, alerts, runbook links, SLOs (see slis-slos-error-budgets).

## Decisions
docs/adr/ index.
```

Diataxis mapping:

```
             learning        working
practical    TUTORIAL        HOW-TO GUIDE      "Build your first webhook consumer" / "Rotate API keys"
theoretical  EXPLANATION     REFERENCE         "Why we use event sourcing" / "Endpoint & error code list"
```

Runbook entry format (one per alert):

```markdown
## HighOrderLatency (p99 > 800ms for 10 min)
Impact: checkout slow, revenue risk.
First checks: 1) dashboard link  2) recent deploys  3) DB connections saturation
Mitigations: roll back last deploy (command) / scale workers (command) / enable degraded mode flag
Escalate: if not mitigated in 30 min -> database on-call
Related incidents: postmortem links
```

Docs-as-code pipeline sketch (CI):

```yaml
docs:
  steps:
    - lint markdown and prose (markdownlint, vale)
    - check links (lychee) and that code samples execute (doctest / pytest --doctest-glob)
    - build site (mkdocs / docusaurus / sphinx)
    - publish on merge to main
```

Executable examples cannot rot silently:

```python
def parse_price(s: str) -> int:
    """Return price in cents.

    >>> parse_price("12.50")
    1250
    """
    whole, _, frac = s.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])

if __name__ == "__main__":
    import doctest; doctest.testmod()
```

Diagrams: keep them text-based (Mermaid, PlantUML, Structurizr DSL) so they diff
and live in the repo; use C4 levels and label every arrow with protocol or intent.
Always state what the diagram is (context, sequence, deployment) and the date or version.

API docs: publish the OpenAPI/proto file as the contract, render reference from
it, and add hand-written guides for concepts the spec cannot express. Contract
tests keep spec and behaviour aligned (see [[integration-and-contract-testing]]).

## Trade-offs
- **Wiki vs repo docs.** Wikis are friendly to non-engineers and fast to edit;
  repo docs stay in sync and are reviewable. Many teams keep technical docs in
  the repo and process/product docs in a wiki.
- **Generated vs hand-written.** Generated reference is accurate but dry;
  hand-written guides explain intent but rot. Use both with clear separation.
- **Comprehensive vs concise.** More text means more maintenance and more lies;
  prefer short, linked, owned pages.
- **Diagram fidelity.** Detailed diagrams go stale first; high-level context and
  container diagrams last longest.
- **Writing now vs after the feature ships.** Writing first (design doc, README)
  clarifies thinking; writing after is cheaper but often skipped.

## Gotchas
- Docs that do not run: quick starts that fail on a clean machine destroy
  trust. Test the quick start in CI or have each new hire fix it.
- Stale docs are worse than none; delete or mark as obsolete and date pages.
- Documenting in chat or meetings only. Decisions and fixes made in Slack vanish.
- Screenshots and long shell sessions in docs age badly; prefer text and
  commands, and link to the source of truth.
- No search or structure: a flat folder of 300 pages. Maintain an index and
  navigation by reader goal.
- Writing for yourself: avoid unexplained acronyms, assume no context, define
  terms once in a glossary.
- Secrets or internal hostnames pasted into docs (see [[secrets-management]]).
- Treating the change log as release notes: changelogs list changes, release
  notes tell users what matters and what to do.

## Related
- [[architecture-decision-records]] - the "why" record that complements how-to docs
- [[code-review]] - docs changes ride along in the same PR as the code
- [[clean-code-and-naming]] - self-documenting code reduces needed prose
- [[rest-api-design]] - what API reference documentation must describe
- [[observability-logs-metrics-traces]] - runbooks link alerts to dashboards
- [[incident-response-and-postmortems]] - postmortems and runbooks feed each other
- [[git-workflows-and-branching]] - commit messages and PR descriptions are documentation too

## References
- Diataxis documentation framework: https://diataxis.fr/
- Write the Docs, documentation guide: https://www.writethedocs.org/guide/
- C4 model: https://c4model.com/
- Google Technical Writing courses: https://developers.google.com/tech-writing
- OpenAPI Initiative: https://www.openapis.org/
