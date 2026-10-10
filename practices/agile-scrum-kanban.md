---
title: Agile, Scrum and Kanban
category: practices
tags: [agile, scrum, kanban, sprint, retrospective, wip-limits, lean, sdlc]
use_cases:
  - "choose between Scrum and Kanban for a team doing mixed feature and support work"
  - "set up sprint planning, standups and retrospectives for a new team"
  - "reduce work in progress and cycle time on a team that starts everything and finishes nothing"
  - "explain agile principles to stakeholders used to waterfall"
  - "run a delivery process for an ops or platform team with unpredictable interrupts"
status: draft
last_verified: 2026-10-10
sources:
  - https://agilemanifesto.org/
  - https://www.scrum.org/resources/scrum-guide
  - https://kanban.university/kanban-guide/
  - "Kanban: Successful Evolutionary Change for Your Technology Business (David J. Anderson), 2010"
  - "Accelerate (Forsgren, Humble, Kim), 2018"
  - "The Goal (Eliyahu Goldratt), 1984"
---

# Agile, Scrum and Kanban

## Summary
Agile is a set of values for delivering software in small increments with fast
feedback; Scrum and Kanban are two concrete frameworks for it. Scrum organises
work into fixed-length sprints with defined roles and events. Kanban visualises
a continuous flow and limits work in progress. Choose by the nature of your work:
plannable product increments favour Scrum, interrupt-driven or continuous work favours Kanban.

## Key concepts
- **Agile Manifesto (2001):** individuals and interactions, working software,
  customer collaboration and responding to change are valued over their
  counterparts, which still matter. It is values, not a process.
- **Scrum roles:** Product Owner (value and backlog ordering), Developers
  (build the increment), Scrum Master (helps the team use Scrum well).
- **Scrum events:** Sprint (fixed length of at most one month), Sprint Planning,
  Daily Scrum, Sprint Review, Sprint Retrospective. **Artifacts:** Product
  Backlog, Sprint Backlog, Increment, each with a commitment (Product Goal,
  Sprint Goal, Definition of Done).
- **Definition of Done:** shared quality bar for "finished" (tested, reviewed,
  deployed or deployable, documented as needed).
- **Kanban principles:** visualise work, limit WIP, manage flow, make policies
  explicit, improve collaboratively. Pull, do not push.
- **Flow metrics:** cycle time (start to done), throughput (items per period),
  WIP, work item age. Little's Law: average cycle time = average WIP / throughput.
- **Theory of constraints:** system output is limited by its bottleneck;
  improving anything else does not help.
- **Continuous delivery** (see [[ci-cd-pipelines]]) is the technical enabler
  that makes short iterations meaningful.

## When to use / scenarios
- **Scrum fits:** a product team building features toward goals, wanting a
  regular cadence, stakeholder review and planning rhythm, with work that can
  be sliced to fit an iteration.
- **Kanban fits:** support/ops/SRE teams, maintenance, mixed priorities and
  frequent interrupts, or teams already deploying continuously that find
  sprint boundaries artificial.
- **Scrumban / hybrid:** Kanban board with WIP limits plus a lightweight
  planning and retrospective cadence. Very common in practice.
- **Scaled work (many teams):** keep teams small and autonomous, align via
  shared goals and roadmaps; heavy scaling frameworks add overhead, so adopt
  them only when coordination problems are proven.
- **Avoid** "Agile" as a ritual layer on a waterfall process (fixed scope and
  date with daily standups). Avoid Scrum when priorities change daily and
  sprint commitments are constantly broken; use Kanban.
- Not suited: research with no plannable output (use time-boxed spikes, see
  [[estimation-and-planning]]).

## How it works / example

Scrum sprint (two weeks, an assumption many teams use):

```
Day 1   Sprint Planning: Product Owner proposes goal; team selects backlog items it can finish
Daily   15-min Daily Scrum: progress toward the Sprint Goal, blockers (not a status report)
Mid     Backlog refinement: slice and clarify upcoming items (ongoing, ~10% capacity)
Last    Sprint Review: demo working increment to stakeholders, adapt backlog
Last    Retrospective: what went well, what to change, 1-2 concrete experiments
```

Kanban board with WIP limits:

```
Backlog | Ready(5) | In Progress(3) | In Review(2) | Testing(2) | Done
  ...   |  [A][B]  |   [C][D]       |   [E]        |   [F]      | [G][H]
```
Rule: if In Review is at its limit, you review instead of starting new work.
That is how WIP limits turn queues into swarming and shorten cycle time.

Little's Law in action (Python):

```python
throughput_per_week = 5          # items finished per week (measure it)
wip = 15                          # items in progress right now
avg_cycle_time_weeks = wip / throughput_per_week   # 3.0 weeks
# halving WIP to 7 at the same throughput -> about 1.4 weeks
print(avg_cycle_time_weeks, 7 / throughput_per_week)
```

Working agreements worth writing down: Definition of Done; WIP limits;
review SLA (see [[code-review]]); how urgent interrupts are handled (an
expedite lane limited to one item); on-call rota; how work is sliced
(vertical slices with user value).

Retrospective formats: Start/Stop/Continue; 4Ls (liked, learned, lacked,
longed for); timeline of the sprint. Always leave with at most one to three
owned actions and review them at the next retro.

Metrics worth watching (team-level, never individual): cycle time
distribution (use percentiles, not averages), throughput trend, deployment
frequency, lead time for changes, change failure rate, time to restore (DORA).
Use them to ask questions, not to rank people.

User story shape (INVEST: independent, negotiable, valuable, estimable, small,
testable): "As an account owner I can export my invoices as CSV so that I can
reconcile them in my accounting tool", with acceptance criteria in
Given/When/Then form (see [[tdd-and-bdd]]).

## Trade-offs
- **Scrum cadence vs Kanban flow.** Cadence gives rhythm and forced reflection
  but creates sprint-end crunch and artificial batching; flow minimises delay
  but needs discipline to avoid drifting without regular reflection.
- **Fixed-length sprints vs variable.** Fixed lengths make velocity comparable
  and meetings predictable; shorter sprints give faster feedback and cost more
  ceremony overhead.
- **Commitment vs forecast.** Modern Scrum frames the Sprint Goal as the
  commitment and the selected items as a forecast, reducing blame for slippage.
- **Specialist roles vs cross-functional teams.** Cross-functional teams cut
  handoffs but need broader skills and investment in learning.
- **Process consistency vs team autonomy.** Org-wide standardisation eases
  reporting and moves people; autonomy fits local needs. Standardise the
  interfaces (cadences, definitions, metrics), not the internals.

## Gotchas
- Velocity treated as productivity, leading to inflated points and corner cutting.
- Standup turning into a manager status meeting rather than team coordination.
- Carrying unfinished stories over every sprint: slices are too large or the
  team over-commits; finish before starting.
- No WIP limits on a Kanban board: it becomes a pretty to-do list.
- Skipping retrospectives or never acting on them; the process then stops adapting.
- Product Owner as order-taker with no authority; backlog becomes a request queue.
- Hardening or QA sprints at the end signal missing built-in quality; invest in
  automation (see [[testing-strategy-and-pyramid]]).
- Mistaking ceremonies for agility: if releases still happen quarterly and
  feedback arrives months late, nothing has changed.
- Ignoring technical work: reserve capacity for [[technical-debt-management]]
  and operations.

## Related
- [[estimation-and-planning]] - forecasting, velocity and throughput
- [[ci-cd-pipelines]] - the engineering practice that makes short iterations real
- [[git-workflows-and-branching]] - trunk-based flow matches small increments
- [[technical-debt-management]] - ring-fence capacity for it in every cadence
- [[incident-response-and-postmortems]] - unplanned work and its feedback into planning
- [[tdd-and-bdd]] - acceptance criteria and test-first within stories
- [[slis-slos-error-budgets]] - error budgets arbitrate feature work vs reliability work

## References
- Agile Manifesto: https://agilemanifesto.org/
- The Scrum Guide: https://www.scrum.org/resources/scrum-guide
- The Kanban Guide: https://kanban.university/kanban-guide/
- David J. Anderson, *Kanban* (2010)
- Forsgren, Humble, Kim, *Accelerate* (2018)
- Eliyahu Goldratt, *The Goal* (1984)
