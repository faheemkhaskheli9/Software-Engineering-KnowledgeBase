---
title: Threat modeling
category: security
tags: [threat-modeling, stride, dfd, attack-trees, risk, secure-design, trust-boundaries]
use_cases:
  - "run a security design review for a new service before building it"
  - "identify what could go wrong with our file upload feature"
  - "prioritise which security risks to fix first"
  - "document trust boundaries and data flows for a compliance audit"
  - "add a lightweight threat-model step to our design docs"
status: draft
last_verified: 2026-10-10
sources:
  - https://owasp.org/www-community/Threat_Modeling
  - https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html
  - https://www.threatmodelingmanifesto.org/
  - https://shostack.org/books/threat-modeling-book
  - https://attack.mitre.org/
---

# Threat modeling

## Summary
Threat modeling is structured thinking about what can go wrong in a system
before (and while) it is built, so security work targets real risks and is
cheap to act on. Shostack frames it as four questions: what are we working on,
what can go wrong, what are we going to do about it, did we do a good job.
It is the main practice behind OWASP Top 10 A04 (Insecure Design).

## Key concepts
- **Assets:** what an attacker wants (data, money, availability, reputation).
- **Data flow diagram (DFD):** external entities, processes, data stores, data
  flows, and **trust boundaries** (where privilege or ownership changes).
  Threats concentrate where flows cross a boundary.
- **STRIDE** (per element): Spoofing, Tampering, Repudiation, Information
  disclosure, Denial of service, Elevation of privilege. Each maps to a
  property violated: authenticity, integrity, non-repudiation, confidentiality,
  availability, authorization.
- **Other methods:** attack trees (goal decomposed into attacker steps),
  PASTA (risk-centric), LINDDUN (privacy), MITRE ATT&CK (known adversary
  techniques for detection and red-team planning).
- **Risk ranking:** likelihood x impact, or DREAD-like scoring (DREAD is
  criticised as subjective; a simple high/medium/low plus rationale works).
- **Mitigation choices:** eliminate, mitigate, transfer, accept (with named
  owner and reason).

## When to use / scenarios
- New system or major feature that handles auth, money, personal data, file
  upload, third-party integrations, or new network exposure.
- A design doc stage: cheapest moment to change the architecture.
- After an incident or when entering a regulated market.
- Skip the formal process for tiny, low-risk changes; use a 5-minute
  checklist ("new input? new secret? new outbound call? new data class?").
- Not a replacement for testing or scanning; it finds design flaws they cannot.

## How it works / example

A 60-90 minute session with developers, an architect and someone security-minded:

1. Draw the DFD on a whiteboard (keep to one level, 5-15 elements).
2. Mark trust boundaries and list assets.
3. Walk each element and each boundary-crossing flow with STRIDE.
4. Record threats, rate them, choose mitigations, file tickets.
5. Re-review when the design changes.

```
[Browser] --HTTPS--> [API gateway] --> [App service] --> [(Postgres)]
    ^ trust boundary 1 (internet)  ^ boundary 2 (VPC)       |
                                     [App service] --> [S3 bucket for uploads]
```

Threat register entry (keep it in the repo next to the design doc):

```yaml
- id: T-07
  element: "upload flow: Browser -> App service"
  stride: Tampering / Elevation of privilege
  threat: "Attacker uploads an HTML/SVG with script and it is served from our origin (stored XSS)"
  likelihood: medium
  impact: high
  mitigation:
    - "Serve user content from a separate domain with Content-Disposition attachment"
    - "Validate type by content sniffing, not extension; size limits"
    - "CSP on the app origin"
  status: ticketed (SEC-212)
  owner: team-files
```

Minimal automation: a pytest that asserts each threat has an owner and status
keeps the register from rotting.

```python
import yaml, pathlib

def test_threat_register_complete():
    items = yaml.safe_load(pathlib.Path("threats.yaml").read_text())
    for t in items:
        assert t["owner"] and t["status"] and t["mitigation"], t["id"]
```

Abuse cases complement user stories: "As an attacker, I replay a captured
password-reset link" becomes an acceptance test.

## Trade-offs
- **Depth vs frequency:** exhaustive models go stale; lightweight models done
  per feature stay current. Prefer frequent and small.
- **Tool-driven (Threat Dragon, IriusRisk, pytm) vs whiteboard:** tools give
  traceability and diffs; whiteboards give better conversation. Many teams
  whiteboard first, then capture in a tool or YAML.
- **Attacker-centric vs asset-centric vs software-centric:** attackers find
  realistic paths, assets keep focus on business impact, software-centric
  (STRIDE on DFD) is the easiest to teach and repeat.
- **Security team led vs developer led:** developers know the system; security
  brings adversarial thinking. Pair them.

## Gotchas
- Producing a document nobody acts on. Every accepted threat needs a ticket or
  a signed-off acceptance.
- Modeling only the happy-path architecture and ignoring operations: CI/CD,
  admin consoles, backups, support tooling, and third-party dependencies are
  frequent attack paths.
- Stopping at "use HTTPS". Name the specific threat and the specific control.
- Treating insiders and compromised dependencies as out of scope by default.
- Over-trusting internal networks; model them as hostile (zero-trust framing).
- Scoring theatre: debating 6.4 vs 6.7 instead of deciding mitigations.
- Not revisiting after a design change or an incident.

## Related
- [[owasp-top-10]] - A04 Insecure Design is what threat modeling addresses.
- [[authorization-models]] - elevation-of-privilege threats map to authZ design.
- [[architecture-decision-records]] - record the security trade-offs chosen.
- [[system-design-interview-framework]] - add a security pass to any design.
- [[failure-modes-and-fallacies]] - the availability side of "what can go wrong".
- [[incident-response-and-postmortems]] - incidents feed the next model.
- See also (AI KB): [AI security, privacy and compliance](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/ai-security-privacy-compliance.md) - threats specific to LLM features (prompt injection, data leakage, model supply chain).

## References
- Adam Shostack, Threat Modeling: Designing for Security (Wiley, 2014).
- Threat Modeling Manifesto, https://www.threatmodelingmanifesto.org/
- OWASP Threat Modeling Cheat Sheet.
- MITRE ATT&CK, https://attack.mitre.org/
