---
title: Incident response and postmortems
category: reliability
tags: [incident-response, on-call, postmortem, sre, severity, runbooks, mttr, blameless]
use_cases:
  - set up an on-call rotation and an incident process for a small team
  - run a live production incident without chaos
  - write a blameless postmortem with useful action items
  - define severity levels and escalation rules
  - reduce time to detect and time to restore for outages
status: draft
last_verified: 2026-10-10
sources:
  - https://sre.google/sre-book/managing-incidents/
  - https://sre.google/sre-book/postmortem-culture/
  - https://sre.google/sre-book/being-on-call/
  - https://response.pagerduty.com/
  - https://www.atlassian.com/incident-management
---

# Incident response and postmortems

## Summary
Incident response is a rehearsed process for detecting, coordinating, mitigating and communicating during a production problem; the postmortem is the blameless written review afterwards that turns the failure into lasting fixes. Good teams optimize for fast mitigation (restore service first, find root cause second) and treat each incident as a source of system improvements rather than people to blame.

## Key concepts
- **Incident**: an unplanned event degrading or threatening the service beyond agreed levels (usually tied to an SLO, see [[slis-slos-error-budgets]]).
- **Severity levels**: a small scale (SEV1 critical/major outage, SEV2 significant degradation, SEV3 minor) that determines who is paged, who communicates, and how fast. Define by user impact, not by cause.
- **Roles**: Incident Commander (IC) coordinates and decides; Operations/Tech lead does the hands-on work; Communications lead updates stakeholders and status page; Scribe records the timeline. In a small team one person may hold several, but the IC should not also debug.
- **Mitigate before diagnosing**: roll back, fail over, disable a feature flag, add capacity, shed load. Understanding comes after service is restored.
- **Runbook / playbook**: documented steps for known alerts, linked from the alert itself.
- **Blameless culture**: assume people acted sensibly with the information they had; ask what let the failure happen, not who caused it.
- **Metrics**: MTTD (detect), MTTA (acknowledge), MTTR (restore). Use them as trends, not targets to game.
- **Contributing factors vs root cause**: complex failures have several; a single "root cause" is usually a simplification.
- **Action items**: tracked, owned, prioritized fixes with due dates; the point of the whole exercise.

## When to use / scenarios
- Before you need it: any service with on-call and customers. Even a two-person team benefits from severity definitions, a shared channel and a timeline doc.
- During a page: follow the lifecycle below.
- After SEV1/SEV2, any customer-visible data loss or security event, any near miss that consumed significant error budget, or any incident with surprising behavior: write a postmortem.
- When NOT to: do not write full postmortems for every trivial alert; fix noisy alerts instead (an alert that fires without needing action is a bug).

## How it works / example

Lifecycle:

```
detect (alert/customer) -> triage + declare severity -> assign IC
  -> mitigate (rollback / failover / flag off / scale) -> communicate on a cadence
  -> resolve + confirm via SLI -> postmortem within days -> action items tracked to done
```

Incident channel kickoff template (paste in chat):

```
INCIDENT: checkout errors elevated        SEV: 2        Started: 14:07 UTC
IC: @alice   Ops: @bob   Comms: @carol   Scribe: @dave
Impact: ~8% of checkout requests failing with 502
Current hypothesis: last deploy (orders-api 1.8.2) at 14:02
Next update: 14:30 UTC (every 30 min)
Doc: <link to timeline doc>
```

Triage questions that usually find the cause fast:
1. What changed recently (deploy, config, flag, infra, traffic, dependency, certificate expiry)? Most incidents are changes.
2. Which signal moved first and what do latency, errors, saturation show (see [[observability-logs-metrics-traces]])?
3. Is it all users or a slice (region, tenant, version, device)?
4. Can we undo the most recent change right now? If yes, do it.

Postmortem template:

```markdown
# Postmortem: <title>   (date, authors, status, severity)
## Summary            2-3 sentences: what broke, who was affected, how long.
## Impact             Users/requests affected, SLO budget consumed, revenue/data effect.
## Timeline (UTC)     Detection, escalation, key decisions, mitigation, resolution. Facts only.
## Root cause and contributing factors
## What went well / what went poorly / where we got lucky
## Detection and response analysis   Why did/didn't alerts fire? How long did each phase take?
## Action items       | action | type (prevent/detect/mitigate) | owner | priority | due | ticket |
## Lessons learned
```

Writing guidance: describe systems and decisions, never "X forgot to"; ask "why did the system allow this"; five whys is a prompt for questions, not a formula. Prefer action items that change the system (automated check, guardrail, safer default, better alert) over "be more careful" or "add documentation". Review the draft in a meeting, publish widely, and track the items.

On-call health basics:
- Rotation of enough people (a common guideline is at least 5-8 for sustainable 24x7), follow-the-sun if multi-region, clear handoff notes.
- Pages must be actionable and urgent; everything else is a ticket. Review pages per shift and delete or tune noise.
- Compensate and protect time off after rough shifts.
- Game days / chaos experiments rehearse the process and validate runbooks before real incidents.

## Trade-offs
- **Speed vs coordination**: heavy process slows a tiny team; no process makes a large incident chaotic. Scale roles with severity.
- **Rollback-first vs debug-in-place**: rollback restores fast but destroys evidence of a live fault; capture logs, heap or traces first when cheap, then roll back.
- **Public status transparency vs risk**: early honest status updates build trust; vague or late ones erode it. Prefer a regular cadence even with "no change".
- **Postmortem depth vs frequency**: deep reviews for the big ones, short blameless notes for smaller ones.
- **Follow-the-sun vs single on-call region**: better sleep and response vs handoff and ownership complexity.
- **Pager for everything vs SLO-based paging**: SLO-based reduces noise but requires good SLIs.

## Gotchas
- Everyone debugging, nobody coordinating. Name an IC immediately and let them delegate.
- Silent investigation: stakeholders pinging engineers for status. The comms role exists to absorb that.
- Blame disguised as process ("human error" as root cause). Humans err; systems should make the error hard or harmless.
- Postmortems with action items that never get done teach everyone the ritual is theater; review open items regularly.
- Fixing the symptom: restoring service and closing the incident without asking why detection was late or why a safeguard was missing.
- Changing many things at once during mitigation obscures what actually helped. Make one change at a time and note it in the timeline.
- Alert fatigue: unowned noisy alerts cause real pages to be ignored.
- Single points of knowledge: only one person understands a system. Rotate responsibility and keep runbooks current.
- Incident tooling that depends on the failing system (chat, wiki, VPN, status page hosted on the same cloud) is unavailable exactly when needed; keep an out-of-band path.
- Security incidents need extra handling (evidence preservation, legal, disclosure timelines); involve the right people early.

## Related
- [[slis-slos-error-budgets]] - severity and paging should key off SLO impact.
- [[observability-logs-metrics-traces]] - the data responders rely on to triage.
- [[deployment-strategies]] - fast rollback and flags are the main mitigation tools.
- [[resilience-patterns]] - preventing localized failures from cascading.
- [[failure-modes-and-fallacies]] - taxonomy of how distributed systems fail.
- [[documentation-practices]] - runbooks and postmortem archives.

## References
- Google SRE Book, ch. 14 "Managing Incidents", ch. 15 "Postmortem Culture", ch. 11 "Being On-Call": https://sre.google/sre-book/managing-incidents/ and https://sre.google/sre-book/postmortem-culture/ and https://sre.google/sre-book/being-on-call/
- PagerDuty Incident Response documentation: https://response.pagerduty.com/
- Atlassian incident management handbook: https://www.atlassian.com/incident-management
