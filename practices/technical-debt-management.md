---
title: Technical debt management
category: practices
tags: [technical-debt, refactoring, prioritization, maintainability, roadmap, quality]
use_cases:
  - "convince product management to allocate time to paying down tech debt"
  - "build a prioritised list of tech debt items for our quarterly planning"
  - "decide whether to rewrite a legacy module or refactor it incrementally"
  - "track deliberate shortcuts taken to hit a deadline so they do not become permanent"
  - "measure whether code quality is getting better or worse over time"
status: draft
last_verified: 2026-10-10
sources:
  - https://martinfowler.com/bliki/TechnicalDebt.html
  - https://martinfowler.com/bliki/TechnicalDebtQuadrant.html
  - https://www.ward.c2.com/wiki/WardExplainsDebtMetaphor
  - "Working Effectively with Legacy Code (Michael Feathers), 2004"
  - "Refactoring, 2nd ed. (Martin Fowler), 2018"
  - "Accelerate (Forsgren, Humble, Kim), 2018"
---

# Technical debt management

## Summary
Technical debt is the future cost of past design and implementation shortcuts:
extra effort every time you change the affected code. Like financial debt it is
sometimes a smart loan (ship now, fix later) and sometimes reckless. Managing it
means making it visible, pricing it by the interest it charges, and paying
selectively where it blocks delivery or risks reliability.

## Key concepts
- **Principal vs interest.** Principal is the work to fix it; interest is the
  recurring slowdown or risk while it remains. Debt in code nobody touches costs
  almost nothing; debt in the hottest path costs every sprint.
- **Fowler's quadrant:** deliberate vs inadvertent, reckless vs prudent.
  "We must ship now and will deal with consequences" (prudent, deliberate) is
  legitimate; "we don't have time for design" (reckless, deliberate) and "what's
  layering?" (inadvertent) are not.
- **Ward Cunningham's original metaphor:** debt arises when code no longer
  reflects your *current understanding* of the domain; refactor to catch up.
  It was never an excuse for sloppy code.
- **Kinds:** code (smells), design/architecture (wrong boundaries), test
  (flaky or missing), build/infra (slow CI, manual deploys), documentation,
  dependency (outdated, unsupported libraries), data (bad schema).
- **Hotspot analysis:** crossing code churn (git history) with complexity finds
  where debt hurts. Files changed often *and* complex are the priority.
- **Boy-scout rule:** leave the code slightly better than you found it.
- **Strangler fig:** replace a legacy system incrementally behind a facade rather
  than a big-bang rewrite.

## When to use / scenarios
- Velocity has dropped and simple changes keep touching many files.
- Incidents cluster in the same component, or on-call pain is dominated by one area.
- Before a major feature in a messy area: pay the relevant debt first as part
  of the estimate (see [[estimation-and-planning]]).
- Dependency end-of-life or security advisories force upgrades.
- **Do not** declare a rewrite from frustration. Rewrites routinely lose
  undocumented behaviour and take longer than planned; prefer incremental
  refactoring unless the platform or tech is truly dead-ended.
- **Do not** treat all debt as bad: prototypes, spikes and short-lived code may
  rationally carry it.

## How it works / example

Debt register: one list, each item with enough data to prioritise.

```
id    area        description                      type     interest (cost now)           risk   fix size
TD-12 billing     God class InvoiceService (2k loc) design   every billing change +2 days   high   M
TD-19 ci          Integration tests take 40 min    test     slows each PR, devs batch up   med    S
TD-23 deps        Django 3.2 unsupported           deps     no security patches            high   L
TD-31 reports     Copy-pasted SQL in 14 places     code     bugs fixed in some, not others med    S
```

Prioritisation: score = (interest x frequency of touch) + risk, divided by
fix size; or simply sort by "pain per week" and "blast radius", then pick items
that fit the budget. Keep it crude; precision is fake here.

Finding hotspots with git (churn) plus a complexity tool:

```python
import subprocess, collections
log = subprocess.check_output(
    ["git", "log", "--since=6 months ago", "--name-only", "--pretty=format:"]).decode()
churn = collections.Counter(l for l in log.splitlines() if l.endswith(".py"))
for path, n in churn.most_common(10):
    print(n, path)    # cross-reference with cyclomatic complexity (e.g. radon cc)
```

Ways to fund the paydown (pick one and be consistent):
1. **Continuous allowance:** a fixed share of capacity each sprint (commonly
   10-20%, a team judgment, not a standard).
2. **Attach to features:** include refactoring in the estimate of the feature
   that touches the area ("make the change easy, then make the easy change").
3. **Debt sprints / quarters:** periodic focused cleanup; risks being cancelled
   when deadlines press.
4. **Tech-debt-driven epics** with a business case: "cutting CI from 40 to 10
   minutes saves X engineer-hours per week" (state assumptions).

Marking deliberate shortcuts in code so they are findable and carry their ceiling:

```python
# DEBT(TD-45): global lock; fine below ~50 rps, switch to per-account locks if throughput matters
```

Tracking: link each TODO to a ticket, review the register at quarterly planning,
and report a few trend indicators: lead time for change, change-failure rate
and deployment frequency (DORA metrics), time to onboard a new hire, share of
sprint spent on unplanned work and rework.

Rewrite vs refactor decision sketch:

```
Does the system still meet business needs?  yes -> refactor incrementally (strangler fig)
Are tests/characterisation tests possible?  no  -> write them first (Feathers)
Is the tech/platform unsupported or unfixable? yes -> staged migration, not a freeze-and-rewrite
```

## Trade-offs
- **Pay now vs later.** Paying early reduces compounding interest but delays
  features; defer only when the interest is low or the code is about to die.
- **Incremental vs big-bang rewrite.** Incremental is slower to feel complete
  but keeps shipping; big-bang risks a long stall and parity gaps.
- **Dedicated budget vs opportunistic.** A budget guards against perpetual
  deferral; opportunistic cleanup is cheaper but tends to starve.
- **Quantification vs narrative.** Numbers (hours lost, incident count) persuade
  management but are estimates; pair them with one or two vivid examples.
- **Tool metrics (SonarQube-style "debt hours") vs judgment.** Tools find
  smells cheaply but cannot see business cost; use them as inputs only.

## Gotchas
- Calling every annoyance "debt" dilutes the term; require a stated cost.
- Debt register as graveyard: hundreds of stale tickets. Prune quarterly and
  close what is no longer painful.
- "We'll fix it after the release" without a ticket and owner means never.
- Refactoring without tests is rewriting by hope; add characterisation tests first.
- Mixing refactoring and behaviour change in one commit makes review
  and bisecting hard (see [[code-review]]).
- Upgrading dependencies in one giant leap multiplies breakage; upgrade
  continuously in small steps with automation (Dependabot, Renovate).
- Architecture debt is the costly kind and invisible in code metrics; surface it
  via [[architecture-decision-records]] with revisit triggers.
- Ignoring organisational debt (unclear ownership, missing on-call, absent docs)
  while polishing code.

## Related
- [[refactoring-and-code-smells]] - the techniques used to repay code-level debt
- [[estimation-and-planning]] - include debt work in estimates and capacity
- [[architecture-decision-records]] - record deliberate debt and its repayment trigger
- [[testing-strategy-and-pyramid]] - tests make refactoring safe
- [[incident-response-and-postmortems]] - postmortem action items are a major debt source and funding case
- [[coupling-cohesion-and-design-principles]] - the design properties whose decay creates debt
- [[monolith-vs-microservices]] - migrations here are strangler-fig debt paydowns

## References
- Martin Fowler, "Technical Debt" and "Technical Debt Quadrant": https://martinfowler.com/bliki/TechnicalDebt.html , https://martinfowler.com/bliki/TechnicalDebtQuadrant.html
- Ward Cunningham, "The WyCash Portfolio Management System" / debt metaphor: https://www.ward.c2.com/wiki/WardExplainsDebtMetaphor
- Michael Feathers, *Working Effectively with Legacy Code* (2004)
- Martin Fowler, *Refactoring*, 2nd ed. (2018)
- Forsgren, Humble, Kim, *Accelerate* (2018) for delivery-performance metrics
