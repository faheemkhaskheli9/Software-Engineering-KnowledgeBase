---
title: Estimation and planning
category: practices
tags: [estimation, planning, story-points, roadmap, forecasting, cone-of-uncertainty, capacity]
use_cases:
  - "give a credible delivery date for a project whose scope is still fuzzy"
  - "decide between story points, t-shirt sizes and time estimates for our team"
  - "break a large epic into estimable slices and sequence them to cut risk"
  - "stop our sprints from constantly overcommitting"
  - "forecast release dates using our actual throughput instead of guesses"
status: draft
last_verified: 2026-10-10
sources:
  - "Software Estimation: Demystifying the Black Art (Steve McConnell), 2006"
  - "Actionable Agile Metrics for Predictability (Daniel Vacanti), 2015"
  - https://www.mountaingoatsoftware.com/agile/planning-poker
  - "The Mythical Man-Month (Frederick Brooks), 1975/1995"
  - https://www.scrum.org/resources/scrum-guide
  - "Accelerate (Forsgren, Humble, Kim), 2018"
---

# Estimation and planning

## Summary
Estimation predicts effort or duration under uncertainty; planning turns those
predictions into a sequenced, adjustable commitment. Estimates are ranges with
confidence, not promises. The practical goal is not a precise number but
enough predictability to make decisions, plus early feedback to correct course.

## Key concepts
- **Estimate vs target vs commitment** (McConnell): an estimate is an analysis
  of what is likely; a target is a desired outcome; a commitment is a promise.
  Confusing them causes most estimation conflict.
- **Cone of uncertainty:** early estimates are inherently wide (McConnell cites
  roughly a factor of several at the start). Narrowing requires decisions and
  built work, not more estimating effort.
- **Ranges and confidence:** give best/likely/worst (three-point), or a range
  with a stated confidence, e.g. "6-10 weeks, 80% confidence".
- **Relative sizing:** story points or t-shirt sizes compare items to each other
  and avoid false precision. Velocity is the team's average points per iteration.
- **Throughput forecasting (flow metrics):** count finished items per week and
  use cycle-time percentiles; needs no sizing at all (Kanban, Vacanti).
- **Hofstadter's law / planning fallacy:** work takes longer than expected even
  when you account for the law. Use reference-class data (how long did similar
  work take before?) instead of introspection.
- **Brooks's law:** adding people to a late project makes it later (ramp-up and
  communication overhead).
- **Slicing:** deliver thin vertical slices end to end, not horizontal layers.
- **Buffer:** schedule the aggregate with explicit contingency, not padding every task.

## When to use / scenarios
- **Fixed-date, fixed-scope request (contract, launch event):** estimate ranges,
  find the must-have core, protect the date by flexing scope.
- **Ongoing product team:** velocity or throughput forecasting, re-forecast
  every iteration; skip task-level hour estimates.
- **Discovery/R&D work:** time-box spikes (e.g. 2 days) and estimate afterwards;
  do not estimate unknowns as if they were known.
- **Capacity planning for a quarter:** count people, subtract holidays, on-call,
  support and meeting load, then reserve a share for [[technical-debt-management]]
  and unplanned work.
- **Avoid** estimating at all when decisions do not depend on it (tiny
  tasks, one-person experiments); a #NoEstimates approach based on small, even
  slices and throughput is valid there.
- **Avoid** using velocity to compare teams or evaluate people; it is a private
  planning aid and gets gamed instantly.

## How it works / example

Estimation workflow:

```
1. Clarify scope (what is in/out, definition of done)
2. Break down into slices of roughly comparable size (a few days max)
3. Estimate relatively (planning poker) or count items for throughput
4. Add risk: list unknowns, spike the biggest first
5. Forecast with a range; present assumptions
6. Track actuals, re-forecast each iteration, adjust scope not quality
```

Three-point (PERT) estimate for one item: expected = (optimistic + 4 x likely +
pessimistic) / 6; standard deviation about (pessimistic - optimistic) / 6.
Summing standard deviations in quadrature for independent items gives a
narrower aggregate range than summing worst cases.

Monte Carlo forecast from historical throughput (Python):

```python
import random, statistics
weekly_done = [4, 6, 3, 5, 7, 4, 5, 6]      # items finished per week, your own data
backlog = 40                                 # remaining items
def weeks_to_finish():
    left, w = backlog, 0
    while left > 0:
        left -= random.choice(weekly_done); w += 1
    return w
runs = sorted(weeks_to_finish() for _ in range(10_000))
p50, p85 = runs[len(runs)//2], runs[int(len(runs)*0.85)]
print(f"50% by week {p50}, 85% by week {p85}")   # quote the 85% date for commitments
```

The inputs are your team's real history; the output is a probability statement,
not a promise. Re-run as new weeks of data arrive.

Planning poker with a Fibonacci-like scale (1, 2, 3, 5, 8, 13): everyone reveals
at once to avoid anchoring; large outliers explain their reasoning; anything
13 or above gets split. Calibrate by choosing a reference story the team agrees
is a "3".

Sequencing heuristics:
- Do the riskiest, most uncertain slice first (walking skeleton end to end).
- Deliver the highest value-per-cost items early; leave nice-to-haves last so
  they can be cut.
- Sequence dependencies explicitly; cross-team dependencies get earliest dates.

Release forecast communication template: "Based on 8 weeks of throughput we are
85% confident of finishing the core scope by 14 Dec; the stretch items are
unlikely before January. Largest risks: third-party API access, data migration."

## Trade-offs
- **Story points vs time vs counting items.** Points hide hours but invite
  inflation and conversion arguments; time is concrete but anchored on
  optimism; item-count throughput is cheapest and works when slices are similar.
- **Detailed upfront plan vs rolling-wave planning.** Upfront suits fixed-price
  contracts; rolling wave (detail for the next 1-2 iterations, coarse beyond) suits
  uncertain products.
- **Padding vs explicit buffers vs scope flex.** Hidden padding is consumed by
  Parkinson's law; project-level buffers and cuttable scope are more honest.
- **Individual vs team estimates.** Team estimates average out bias and share
  knowledge but cost meeting time.
- **Accuracy vs effort.** Past a point, extra estimation effort adds no
  accuracy; building and measuring does.

## Gotchas
- Estimates get converted into commitments by the first manager who hears them.
  State the confidence and assumptions every time.
- Estimating only the coding. Include testing, review, deployment, data
  migration, documentation, on-call and meetings.
- Anchoring: the first number spoken wins. Use simultaneous reveal.
- Treating velocity as a target ("raise velocity") makes points inflate; it
  measures nothing then.
- Ignoring unplanned work; if 30% of capacity goes to bugs and support, plan
  for it from your own data.
- Merging the happy-path estimate with the tail risk: the sum of medians is not
  the median of the sum.
- Adding developers late to recover a schedule (Brooks's law).
- Not re-estimating after discovery. When the cone narrows, update stakeholders
  immediately rather than at the deadline.

## Related
- [[agile-scrum-kanban]] - the frameworks that host velocity, sprint planning and flow metrics
- [[technical-debt-management]] - reserve capacity and include refactoring in estimates
- [[back-of-envelope-estimation]] - the same range-and-assumption mindset applied to system capacity
- [[capacity-planning-and-autoscaling]] - resource (not people) capacity planning
- [[architecture-decision-records]] - record decisions that bound scope and risk
- [[incident-response-and-postmortems]] - unplanned work that eats planned capacity

## References
- Steve McConnell, *Software Estimation: Demystifying the Black Art* (2006)
- Daniel Vacanti, *Actionable Agile Metrics for Predictability* (2015)
- Frederick Brooks, *The Mythical Man-Month* (anniversary ed., 1995)
- Mike Cohn, Planning Poker overview: https://www.mountaingoatsoftware.com/agile/planning-poker
- The Scrum Guide: https://www.scrum.org/resources/scrum-guide
