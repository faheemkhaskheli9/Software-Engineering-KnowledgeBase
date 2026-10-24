---
title: OWASP Top 10 (2025 edition)
category: security
tags: [owasp, web-security, injection, access-control, ssrf, supply-chain, appsec]
use_cases:
  - "audit our web app against the OWASP Top 10 before launch"
  - "prevent SQL injection and XSS in a new Flask or Django service"
  - "write a secure-coding checklist for code review"
  - "decide which security controls to prioritise with limited time"
  - "make our webhook fetcher safe against SSRF"
status: stable
last_verified: 2026-10-11
sources:
  - https://top10.owasp.org/2025/en/
  - https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/
  - https://top10.owasp.org/2025/A02_2025-Security_Misconfiguration/
  - https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/
  - https://top10.owasp.org/2025/A04_2025-Cryptographic_Failures/
  - https://top10.owasp.org/2025/A05_2025-Injection/
  - https://top10.owasp.org/2025/A06_2025-Insecure_Design/
  - https://top10.owasp.org/2025/A07_2025-Authentication_Failures/
  - https://top10.owasp.org/2025/A08_2025-Software_or_Data_Integrity_Failures/
  - https://top10.owasp.org/2025/A09_2025-Security_Logging_and_Alerting_Failures/
  - https://top10.owasp.org/2025/A10_2025-Mishandling_of_Exceptional_Conditions/
  - https://cheatsheetseries.owasp.org/
  - https://owasp.org/www-project-application-security-verification-standard/
---

# OWASP Top 10 (2025 edition)

## Summary
The OWASP Top 10 is a consensus awareness list of the most critical web
application security risks. This file describes the **2025 edition**
(https://top10.owasp.org/2025/en/, verified 2026-10-11). Use it as a minimum
checklist and shared vocabulary, not a complete standard; for depth use the
ASVS. Categories are groups of CWEs, not individual bugs.

## Key concepts
- Most categories reduce to a few root rules: never trust input, deny by
  default, use vetted libraries, keep dependencies and builds trustworthy,
  fail safely, log what matters.
- Controls belong in layers: framework defaults, code, configuration,
  infrastructure, pipeline.
- Scanners find injection and misconfiguration well; access-control and design
  flaws need tests, threat modeling and human review.

## The 2025 list and the fix that matters most

| ID | Category | Primary defence |
|---|---|---|
| A01 | Broken Access Control (now includes SSRF) | Deny by default, server-side authZ on every request, object ownership checks, allow-listed outbound targets |
| A02 | Security Misconfiguration | Hardened repeatable config, no default creds, minimal surface, secure headers |
| A03 | Software Supply Chain Failures (new) | Dependency inventory (SBOM), pinned and verified packages, trusted build pipeline |
| A04 | Cryptographic Failures | TLS everywhere, modern password hashing, vetted libraries, key management |
| A05 | Injection (incl. XSS) | Parameterised queries, contextual output encoding, validation, CSP |
| A06 | Insecure Design | Threat modeling, secure design patterns, abuse-case tests |
| A07 | Authentication Failures | MFA, strong hashing, rate limiting, safe session handling |
| A08 | Software or Data Integrity Failures | Signed artifacts, verified updates, no unsafe deserialization |
| A09 | Security Logging and Alerting Failures | Log auth/access events, alert on them, protect log integrity |
| A10 | Mishandling of Exceptional Conditions (new) | Fail closed, handle every error path, no leaky errors, global handlers |

### Changes from 2021
- **New:** A03 Software Supply Chain Failures (broadens 2021's "Vulnerable and
  Outdated Components" to the whole dependency, build and distribution chain)
  and A10 Mishandling of Exceptional Conditions.
- **SSRF** (2021 A10) is merged into A01 Broken Access Control.
- **Security Misconfiguration** moved up to A02; **Injection** dropped from A03
  to A05; **Cryptographic Failures** from A02 to A04; **Insecure Design** from
  A04 to A06.
- Renamed: Authentication Failures (was Identification and Authentication
  Failures); Logging and Alerting (was Logging and Monitoring) to stress that
  logs must trigger action.

## When to use / scenarios
- Pre-launch review of any internet-facing service: walk A01-A10.
- Training and code-review rubrics: every PR touching input, auth, SQL, file
  access, outbound HTTP, error handling or dependencies gets the matching
  category checked.
- Not a substitute for threat modeling, ASVS-level requirements for regulated
  systems, or the OWASP API Security Top 10 (BOLA, mass assignment, etc.).

## How it works / example

### A01 Broken Access Control (and SSRF)
Authenticate is not authorize; ownership belongs in the query.

```python
def get_invoice(conn, current_user_id, invoice_id):
    row = conn.execute(
        "SELECT id, owner_id, total FROM invoices WHERE id = ? AND owner_id = ?",
        (invoice_id, current_user_id),   # ownership is part of the query
    ).fetchone()
    if row is None:
        raise LookupError("not found")   # 404 avoids confirming existence
    return row
```

SSRF guard for a server-side URL fetcher (merged into A01 in 2025):

```python
import ipaddress, socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"https"}

def assert_public_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ALLOWED_SCHEMES or not p.hostname:
        raise ValueError("scheme/host not allowed")
    for info in socket.getaddrinfo(p.hostname, p.port or 443):
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:   # private, loopback, link-local, CGNAT, reserved...
            raise ValueError("internal address blocked")
    # Resolve once and connect to the checked IP, or DNS rebinding bypasses this.
```

### A05 Injection
Never build SQL with string formatting.

```python
def find_user_bad(conn, name):
    return conn.execute(f"SELECT * FROM users WHERE name = '{name}'")  # injectable

def find_user_ok(conn, name):
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchall()
```

XSS is part of this category: rely on auto-escaping templates (Jinja2
autoescape, React JSX), never concatenate user data into HTML or `innerHTML`,
and add a Content-Security-Policy as defence in depth.

### A10 Mishandling of Exceptional Conditions
Fail closed, keep error detail server-side, never swallow errors in security
paths.

```python
import logging
log = logging.getLogger("app")

def is_authorized(user, action, resource) -> bool:
    try:
        return policy_engine.check(user, action, resource)
    except Exception:
        log.exception("authz check failed")   # full detail in logs only
        return False                          # fail closed, never "allow on error"
```

### A03 and A08 in the pipeline
Pin and verify dependencies (`pip install --require-hashes -r requirements.txt`,
lockfiles), scan in CI, build from clean trusted runners, and sign and verify
artifacts. Never `pickle.loads` or `yaml.load` untrusted data; use
`json` / `yaml.safe_load`.

## Trade-offs
- **Allow-list vs deny-list validation:** allow-lists are safer but need
  maintenance; deny-lists get bypassed.
- **Framework defaults vs custom controls:** defaults cover much of the list
  for free; custom code is where the bugs are. Stay on the paved road.
- **Dependency freshness vs stability:** fast patching shrinks A03 exposure but
  risks breakage; pin, test automatically, and update on a cadence.
- **Verbose errors vs debuggability:** return generic client errors, put detail
  in protected logs with correlation IDs.

## Gotchas
- Authentication present, authorization missing: the classic IDOR. Test with
  two users and swap IDs.
- ORMs do not make raw-query escape hatches safe; `text()`/`raw()` with
  f-strings is still injection.
- Client-side validation and hidden form fields are UX, not security.
- SSRF checks on the hostname string rather than the resolved IP, or followed
  through redirects, are bypassable.
- Debug mode, default admin consoles and stack traces in production recur as
  A02/A10 findings.
- "Fail open" on timeouts or exceptions in auth, rate limiting or payment
  checks is a vulnerability, not resilience.
- Logging secrets or full PII creates a new leak; logging without alerting
  (A09) means nobody notices the attack.
- "We pass the Top 10" is a claim about categories, not absence of bugs.

## Related
- [[authentication-and-sessions]] - A07 in depth: password storage, sessions, MFA.
- [[authorization-models]] - A01 in depth: RBAC, ABAC, object-level checks.
- [[cryptography-and-tls]] - A04: what to encrypt, hash and sign, and how.
- [[threat-modeling]] - the practice that addresses A06 Insecure Design.
- [[secrets-management]] - avoids hard-coded credentials feeding A02/A07.
- [[ci-cd-pipelines]] - where A03/A08 controls (scanning, signing) live.
- [[software-supply-chain-security]] - the controls behind A03 Software Supply Chain Failures.
- [[privacy-and-pii-handling]] - minimising, protecting and erasing the personal data a breach exposes.
- [[static-analysis-and-type-checking]] - SAST and taint rules that find injection paths before review.
- See also (AI KB): [Prompt injection](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/prompt-injection.md) - the injection class specific to LLM features, which parameterised queries do not stop.

## References
- OWASP Top 10:2025, https://top10.owasp.org/2025/en/ and the per-category
  pages under https://top10.owasp.org/2025/ (for example
  https://top10.owasp.org/2025/A01_2025-Broken_Access_Control/).
- OWASP Cheat Sheet Series, https://cheatsheetseries.owasp.org/
- OWASP ASVS and OWASP API Security Top 10, https://owasp.org/API-Security/
