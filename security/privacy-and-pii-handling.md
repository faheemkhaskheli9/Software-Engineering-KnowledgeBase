---
title: Privacy and PII handling
category: security
tags: [privacy, pii, personal-data, gdpr, data-minimisation, pseudonymisation, anonymisation, retention, crypto-shredding, log-redaction]
use_cases:
  - "keep emails, phone numbers and tokens out of application logs"
  - "implement a GDPR 'delete my account' request across databases, backups and event logs"
  - "share user analytics with a data team without exposing who the users are"
  - "decide how long to keep customer records and enforce it automatically"
  - "map where personal data lives before a privacy review"
status: draft
last_verified: 2026-10-11
sources:
  - https://gdpr-info.eu/art-4-gdpr/
  - https://gdpr-info.eu/art-5-gdpr/
  - https://gdpr-info.eu/art-6-gdpr/
  - https://gdpr-info.eu/art-15-gdpr/
  - https://gdpr-info.eu/art-17-gdpr/
  - https://gdpr-info.eu/art-25-gdpr/
  - https://gdpr-info.eu/art-32-gdpr/
  - https://gdpr-info.eu/recitals/no-26/
  - https://eur-lex.europa.eu/eli/reg/2016/679/oj
  - https://csrc.nist.gov/pubs/sp/800/122/final
  - https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
---

# Privacy and PII handling

## Summary
Personal data is any information about an identifiable person, and handling it
well is mostly an engineering problem: collect less, know where it lives,
restrict and encrypt it, keep it out of logs, delete it on schedule and on
request. Laws such as the EU GDPR turn these practices into obligations, and
NIST SP 800-122 gives a security-side guide to protecting PII confidentiality.
This topic is engineering guidance, not legal advice; check obligations with
your privacy or legal team.

## Key concepts
- **Personal data** (GDPR Art. 4(1)): "any information relating to an
  identified or identifiable natural person", directly or indirectly, for
  example by name, identification number, location data or an online
  identifier. IP addresses, device ids and user ids usually count. NIST's term
  is PII.
- **Principles** (GDPR Art. 5): lawfulness, fairness and transparency;
  purpose limitation (collected for specified purposes, not reused in
  incompatible ways); data minimisation ("limited to what is necessary");
  accuracy; storage limitation (kept identifiable no longer than necessary);
  integrity and confidentiality; plus accountability (be able to show
  compliance).
- **Lawful basis** (Art. 6): every processing activity needs one of consent,
  contract, legal obligation, vital interests, public task or legitimate
  interests. Record which one applies per purpose.
- **Data subject rights**: access (Art. 15, a copy of the data and how it is
  used) and erasure (Art. 17, "right to be forgotten", subject to listed
  exceptions), among others. Systems must be able to find and act on all data
  for one person.
- **Pseudonymisation vs anonymisation**: pseudonymised data (Art. 4(5)) can
  only be linked back with additional information kept separately, and is
  still personal data (Recital 26). Truly anonymous data is outside GDPR, but
  real anonymisation is hard: combinations of quasi-identifiers (postcode,
  birth date, gender) often re-identify people.
- **Data protection by design and by default** (Art. 25) and **security of
  processing** (Art. 32, which names pseudonymisation and encryption as
  example measures).
- **Crypto-shredding**: encrypt each person's data with a per-person key; to
  erase, delete the key. Copies in backups, event logs and caches become
  unreadable without rewriting them.
- **Data map / inventory**: which systems hold which personal data fields, for
  what purpose, under which basis, for how long, and who can access them.

## When to use / scenarios
- Any system with user accounts, customers or employees: build the data map,
  logging redaction and retention jobs from the start; retrofitting is far
  more expensive.
- Analytics, ML training or sharing with third parties: pseudonymise or
  aggregate first; use keyed hashing so ids still join across tables.
- Event-sourced systems, append-only logs and long-retention backups where
  deleting one person's rows is impractical: crypto-shredding.
- High-risk processing (health, children, large-scale tracking): a formal data
  protection impact assessment alongside [[threat-modeling]].
- Not a substitute for: access control ([[authorization-models]]) or
  encryption at rest ([[cryptography-and-tls]]); privacy needs those and more.

## How it works / example

A logging filter that redacts common PII before records leave the process,
plus keyed pseudonymisation (HMAC) so analysts can count and join on a stable
id without seeing the email. A plain unkeyed hash of an email is not
pseudonymisation in practice: anyone can hash a list of known emails and match.

```python
import hashlib
import hmac
import io
import logging
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]+=*")

def redact(text: str) -> str:
    text = BEARER.sub("Bearer [REDACTED]", text)
    text = EMAIL.sub("[EMAIL]", text)
    return CARD.sub("[CARD]", text)

class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True

def pseudonym(value: str, key: bytes) -> str:
    """Stable per key; not reversible or linkable without the key (keep it in a KMS)."""
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]

buf = io.StringIO()
log = logging.getLogger("app")
handler = logging.StreamHandler(buf)
handler.addFilter(RedactFilter())
log.addHandler(handler)
log.setLevel(logging.INFO)

log.info("signup %s card %s auth %s", "ana@example.com", "4111 1111 1111 1111", "Bearer eyJhbGciOi.abc")
out = buf.getvalue()
assert "ana@example.com" not in out and "4111" not in out and "eyJ" not in out, out
assert "[EMAIL]" in out and "[CARD]" in out and "[REDACTED]" in out

k1, k2 = b"analytics-key-2026", b"marketing-key-2026"
assert pseudonym("Ana@Example.com", k1) == pseudonym("ana@example.com ", k1)   # joinable
assert pseudonym("ana@example.com", k1) != pseudonym("bob@example.com", k1)
assert pseudonym("ana@example.com", k1) != pseudonym("ana@example.com", k2)    # not linkable across purposes
print(out.strip())
```

Regex redaction is a safety net, not the main control. The main control is
not passing personal data to the logger in the first place: log ids and
event names, and use structured fields with an allow list.

Crypto-shredding in outline:

```
user 42 -> data key K42 (stored in key service, wrapped by a KMS key)
events/backups store AES-GCM(K42, payload)
erasure request: delete K42 -> every copy of user 42's payload is unreadable
```

Erasure request checklist: find the person in the data map's systems
(primary DB, search index, caches, warehouse, object storage, third-party
processors), delete or shred, record what was done and when, and make sure a
later restore from backup re-applies the deletion.

## Trade-offs
- **Minimisation vs future value**: data you never collect cannot leak or need
  deleting; product and analytics teams will want "just in case" fields. Make
  each field earn its purpose.
- **Pseudonymised vs anonymised outputs**: pseudonymised data keeps joins and
  debugging possible but remains regulated; aggregation or anonymisation
  reduces risk and utility.
- **Crypto-shredding vs physical deletion**: shredding handles immutable stores
  and backups, at the cost of a key service on the read path and the risk that
  losing keys loses data unintentionally.
- **Short vs long retention**: short retention reduces exposure and storage;
  legal holds, fraud investigation and financial record rules can require
  longer. Write retention per data category, not one global number.
- **Central redaction vs per-service discipline**: redacting in the log
  pipeline (see [[observability-logs-metrics-traces]]) catches mistakes from all
  services, but data has already left the process by then.

## Gotchas
- Personal data hides in URLs and query strings, exception messages, request
  bodies captured by APM, analytics events, support tickets and test fixtures
  copied from production (see [[test-data-management]]).
- Unkeyed hashes of emails or phone numbers are trivially reversible by
  dictionary; use HMAC with a secret key, or tokenisation.
- "Anonymised" datasets released with quasi-identifiers can be re-identified
  by joining with public data.
- Deleting the row but not the search index, cache, data warehouse copy or
  third-party copy leaves the data in place.
- Restoring a backup brings back deleted users; keep a deletion log and replay
  it after any restore (see [[backup-and-disaster-recovery]]).
- Soft-delete flags are not erasure.
- Access to production data "for debugging" with no audit trail undermines
  every other control; NIST SP 800-122 recommends minimising the use,
  collection and retention of PII and applying safeguards by the PII's
  confidentiality impact level.
- Rules differ by jurisdiction and sector (GDPR, CCPA/CPRA, HIPAA); do not
  assume one law's definitions hold elsewhere.

## Related
- [[observability-logs-metrics-traces]] - redaction in the telemetry pipeline.
- [[cryptography-and-tls]] - field-level and envelope encryption, key management.
- [[secrets-management]] - tokens and keys are not PII but leak through the same logs.
- [[threat-modeling]] - privacy threats belong in the same model.
- [[authorization-models]] - least-privilege access to personal data.
- [[owasp-top-10]] - logging and data exposure failures.
- [[cqrs-and-event-sourcing]] - immutable event logs make erasure hard; crypto-shredding helps.
- [[backup-and-disaster-recovery]] - erasure and retention inside backups.
- [[audit-logs-and-temporal-data]] - audit and history tables that copy personal data need retention and redaction too.
- See also (AI KB): [AI security, privacy and compliance](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/ai-security-privacy-compliance.md) - personal data in prompts, training data and LLM logs.

## References
- Regulation (EU) 2016/679 (GDPR), EUR-Lex: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- GDPR Art. 4 (definitions), Art. 5 (principles), Art. 6 (lawfulness), Art. 15 (access), Art. 17 (erasure), Art. 25 (by design and default), Art. 32 (security), Recital 26: https://gdpr-info.eu/
- NIST SP 800-122, Guide to Protecting the Confidentiality of Personally Identifiable Information (PII), 2010: https://csrc.nist.gov/pubs/sp/800/122/final
- OWASP Logging Cheat Sheet (data to exclude from logs): https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- Python documentation, hmac: https://docs.python.org/3/library/hmac.html
