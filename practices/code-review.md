---
title: Code review
category: practices
tags: [code-review, pull-request, quality, collaboration, feedback, checklist]
use_cases:
  - "set up a code review process for a team that currently merges without review"
  - "make our pull request reviews faster without lowering quality"
  - "write a review checklist for backend changes touching the database and APIs"
  - "teach juniors how to give and receive review feedback"
  - "decide what to automate in review versus what humans should look at"
status: draft
last_verified: 2026-10-10
sources:
  - https://google.github.io/eng-practices/review/
  - https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/
  - https://www.microsoft.com/en-us/research/publication/expectations-outcomes-and-challenges-of-modern-code-review/
  - "Software Engineering at Google (Winters, Manshreck, Wright), 2020, ch. 9"
---

# Code review

## Summary
Code review is a second engineer examining a change before it lands, to catch
defects, keep the design coherent, spread knowledge and maintain shared
standards. Its value depends on small changes, fast turnaround and a clear
division of labour between automated checks and human judgment.

## Key concepts
- **Purpose ranking:** research on modern code review (Bacchelli and Bird,
  Microsoft) found that knowledge transfer, shared ownership and design
  improvement matter as much as finding bugs. Do not sell it as a bug filter only.
- **Author's duty:** make the change reviewable: small, one concern, a
  description explaining *why*, tests included, self-reviewed first.
- **Reviewer's duty:** check design, correctness, tests, readability,
  security and operational impact; approve when the change improves the code
  base, even if not how you would write it (Google's standard).
- **Review latency** is the key throughput metric. A day of waiting per round
  blocks the author and encourages giant batched PRs.
- **Blocking vs non-blocking comments:** label `nit:` (take it or leave it),
  `question:`, `suggestion:`, and `must-fix`.
- **Automate the boring:** formatting, lint, type-check, tests, dependency and
  secret scanning belong in CI (see [[ci-cd-pipelines]]), never in human comments.
- **Code owners:** path-based required reviewers for sensitive areas
  (auth, payments, infra).

## When to use / scenarios
- Every change to a shared main branch, scaled by risk: a typo fix needs a
  glance; a schema migration or auth change needs a domain expert.
- **Pair or mob programming** can replace asynchronous review for some work, if
  a second person genuinely saw all the code.
- **Solo projects / prototypes:** self-review the diff before merging; skip the ceremony.
- **Avoid** using review as the primary quality gate. If most review comments
  are style, add a formatter. If most are missing tests, change the definition
  of done. If reviewers rediscover design problems late, add design review
  or [[architecture-decision-records]] earlier.

## How it works / example

Lifecycle:

```
author: small branch -> self-review diff -> CI green -> open PR (context, risks, test plan)
   -> reviewers (1-2, owners for sensitive paths) comment within target SLA
   -> author responds / pushes fixups -> approve -> merge (see git-workflows-and-branching)
```

PR description template:

```
## What and why
One paragraph: the problem, not a restatement of the diff.
## How
Key design choice; alternatives rejected.
## Risk / rollout
Migrations? Flags? Backwards compat? How to roll back?
## Testing
What was tested and how (unit/integration/manual). Screenshots for UI.
```

Reviewer checklist (backend example):

```
Design     Does it fit the existing architecture? Is the abstraction justified?
Correctness Edge cases: null/empty, concurrency, retries, time zones, overflow.
Data       Migration safe and reversible? Indexes for new queries? N+1?
API        Backwards compatible? Errors and status codes consistent?
Security   Input validation, authZ checks, secrets, injection, PII in logs?
Tests      Fail without the change? Cover the sad paths, not only the happy one?
Operability Logs/metrics/traces added? Timeouts, retries, idempotency?
Readability Names, comments explain why, no dead code, no surprise side effects.
```

Comment styles that work:

```
Weak:   "This is wrong."
Better: "nit: prefer `retry_count` over `rc` for readability."
Better: "question: what happens if `items` is empty here? Looks like we index [0]."
Better: "must-fix: this query runs per row (N+1). Could we batch via IN (...)? See orm-and-n-plus-one."
```

Small automation that enforces a size nudge (Python, runs in CI):

```python fragment
import subprocess, sys
base = "origin/main"
stat = subprocess.check_output(["git", "diff", "--shortstat", base]).decode()
# e.g. " 12 files changed, 340 insertions(+), 20 deletions(-)"
nums = [int(t) for t in stat.replace(",", " ").split() if t.isdigit()]
changed = sum(nums[1:])            # insertions + deletions
if changed > 800:
    print(f"warning: {changed} changed lines; consider splitting this PR")
sys.exit(0)  # warn, do not block
```

Targets worth agreeing on (team assumptions, tune to your context): first
response within one working day, most PRs under a few hundred changed lines,
no PR open for more than a few days.

## Trade-offs
- **Strict (always 2 approvals) vs light (1 approval, post-merge review).**
  Strict suits high-risk code; light keeps flow for low-risk. Use CODEOWNERS to
  vary by path.
- **Synchronous (pairing, walkthrough call) vs asynchronous.** Sync resolves
  disputes fast and teaches; async scales across time zones and leaves a record.
- **Stacked small PRs vs one large PR.** Stacks review better but need tooling
  and discipline about merge order.
- **Human vs AI-assisted review.** Automated reviewers catch style, obvious
  bugs and missing tests cheaply; they do not replace judgment on design,
  product fit or domain risk. Treat their output as a first pass.
- **Blocking on nits** improves consistency but slows delivery; push nits to linters.

## Gotchas
- Rubber-stamping huge diffs ("LGTM") gives false assurance; reviewer quality
  drops sharply as diff size grows.
- Review comments read colder than intended. Ask questions, assume good faith,
  praise good work, and move to a call if a thread passes three rounds.
- Reviewers who only review style miss the expensive problems: wrong abstraction,
  missing failure handling, data-migration hazards.
- Authors who force-push after review comments make it hard to see what changed;
  push fixup commits during review, squash at merge.
- Bottlenecking on one senior reviewer: rotate, document standards, and use
  reviews as mentoring so more people can approve.
- Approving something you did not understand. "I do not follow this" is a valid
  review outcome and often means the code needs comments or simplification.
- Security-sensitive changes need a threat-minded reviewer (see [[owasp-top-10]]).
- Measuring reviewers by comment count rewards noise.

## Related
- [[git-workflows-and-branching]] - PR size, branch protection and merge strategy
- [[ci-cd-pipelines]] - automate everything mechanical before humans look
- [[clean-code-and-naming]] - shared readability standard reviewers apply
- [[refactoring-and-code-smells]] - vocabulary for review feedback on design
- [[testing-strategy-and-pyramid]] - what tests a reviewer should expect to see
- [[documentation-practices]] - PR descriptions and comments as lasting documentation
- [[orm-and-n-plus-one]] - a frequent review catch in data-access code

## References
- Google Engineering Practices, "The Standard of Code Review": https://google.github.io/eng-practices/review/
- Bacchelli and Bird, "Expectations, Outcomes, and Challenges of Modern Code Review" (ICSE 2013): https://www.microsoft.com/en-us/research/publication/expectations-outcomes-and-challenges-of-modern-code-review/
- Winters, Manshreck, Wright, *Software Engineering at Google* (2020), ch. 9 "Code Review"
- SmartBear, best practices for peer code review: https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/
