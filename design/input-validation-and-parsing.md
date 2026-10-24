---
title: Input validation and parsing at trust boundaries
category: design
tags: [input-validation, parse-dont-validate, allowlist, trust-boundary, mass-assignment, redos, canonicalization, path-traversal, json, unicode-normalization, domain-types]
use_cases:
  - "validate API request bodies so bad data is rejected at the edge instead of failing deep in the service"
  - "stop clients from setting fields like is_admin or price through mass assignment"
  - "replace scattered if-checks with typed domain values that cannot hold invalid data"
  - "accept file names or paths from users without allowing directory traversal"
  - "return every validation error in one response instead of one per request"
  - "review regexes used for validation for catastrophic backtracking"
status: draft
last_verified: 2026-10-24
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html
  - https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/
  - https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS
  - https://cwe.mitre.org/data/definitions/20.html
  - https://www.rfc-editor.org/rfc/rfc8259
  - https://www.rfc-editor.org/rfc/rfc9457
  - https://unicode.org/reports/tr15/
  - https://docs.python.org/3/library/json.html
---

# Input validation and parsing at trust boundaries

## Summary
Every value that crosses a trust boundary (HTTP request, message from another
team, file upload, CLI argument, environment, database row written by another
system) can be malformed or hostile. Validate it once, at the boundary, by
*parsing* it into types that can only hold valid values, and let the rest of
the code rely on those types. This turns a class of crashes, corrupt data and
security bugs into a clear 400/422 response at the edge. Validation reduces
attack surface but does not replace context-specific defences such as
parameterized queries and output encoding.

## Key concepts
- **Trust boundary**: the point where data enters code you control from code
  you do not. Validate there, not in every function, and not only in the
  browser (client-side checks are UX; anyone can call the API directly).
- **Parse, don't validate** (Alexis King): a validator returns `True/False` and
  the caller keeps the raw value; a parser returns a new, more precise type
  (`EmailAddress`, `Quantity`, `NonEmptyList`) or fails. Downstream code then
  cannot forget the check, because it only accepts the parsed type.
- **Syntactic vs semantic validation** (OWASP): syntax is shape (an integer, an
  ISO date, at most 254 characters); semantics is meaning in context (start
  date before end date, the product exists, the user may order it). Do syntax
  first and cheaply; semantic checks often need the database or domain rules.
- **Allowlist over denylist**: define what is allowed (character classes,
  enums, ranges, formats) instead of trying to list every bad input.
  Denylists of "dangerous characters" are always incomplete.
- **Limits first**: cap body size, string length, array length, nesting depth
  and number ranges before expensive work. Unbounded input is a denial of
  service.
- **Canonicalize, then validate**: decode, normalize (Unicode NFC/NFKC,
  resolved file paths) and only then check; checking first and normalizing
  later lets `..%2f` or lookalike characters slip past.
- **Unknown fields**: reject or ignore unexpected keys explicitly. Binding a
  request body straight onto a model lets clients set `role`, `price` or
  `owner_id` (mass assignment; OWASP calls the fix an allowlist of bindable
  fields or a separate input DTO).
- **Error reporting**: collect all field errors and return them together with
  a stable machine-readable format (RFC 9457 problem details); 400 for
  unparseable bodies, 422 Unprocessable Content is common for well-formed but
  invalid values. Do not echo raw hostile input into HTML error pages.
- **ReDoS**: regexes with nested or overlapping quantifiers (`(a+)+$`,
  `(\w+\s?)*$`) can take exponential time on crafted input in backtracking
  engines. Keep validation regexes simple, anchor them, bound input length
  first, or use a linear-time engine (RE2-style).

## When to use / scenarios
- Any public or partner-facing API, webhook receiver, form handler or message
  consumer: parse at the handler, pass domain types inward (see
  [[layered-hexagonal-clean-architecture]]).
- Inter-service messages: the producer's schema is a contract, but consumers
  still parse; a bad deploy upstream should fail loudly at the edge, not corrupt
  data (see [[schema-evolution-and-serialization]]).
- Configuration and environment variables: parse at start-up and fail fast,
  instead of discovering a typo in the first request at 3 a.m.
- File names, paths, URLs and redirect targets from users: canonicalize and
  check against an allowed base or allowlist of hosts.
- When NOT to rely on validation alone:
  - SQL, shell and template injection: use parameterized queries, argument
    arrays and context-aware output encoding even for "validated" input (see
    [[owasp-top-10]]).
  - Authorization: a well-formed `order_id` says nothing about whether the
    caller may read that order (see [[authorization-models]]).
  - Free text (names, comments, addresses): restrictive patterns reject real
    people's names; validate length and encoding, then encode on output.

## How it works / example

```
raw bytes --size limit--> strict decode (JSON, UTF-8) --> canonicalize
   --> parse each field into a domain type (collect errors) --> reject unknown fields
   --> semantic checks (DB lookups, cross-field rules) --> domain command
```

A request parser using only the standard library: strict JSON, typed fields,
all errors at once, unknown-field rejection, Unicode normalization, anchored
regexes and safe path handling:

```python
import json
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

MAX_BODY = 16_384

class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__(errors)
        self.errors = errors

def strict_json(raw: bytes) -> dict:
    """Size limit, UTF-8 only, no duplicate keys, no NaN/Infinity."""
    if len(raw) > MAX_BODY:
        raise ValidationError({"body": "too large"})
    def no_dupes(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValidationError({"body": "duplicate keys"})
        return dict(pairs)
    def no_constants(name):
        raise ValidationError({"body": f"{name} not allowed"})
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=no_dupes,
                         parse_constant=no_constants, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError({"body": "invalid JSON"}) from None
    if not isinstance(doc, dict):
        raise ValidationError({"body": "expected an object"})
    return doc

USERNAME = re.compile(r"[a-z0-9_]{3,32}")          # used with fullmatch: no ^/$ pitfalls
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,253}\.[A-Za-z]{2,63}")   # syntax only; confirm by sending mail
CURRENCIES = {"EUR", "GBP", "USD"}

@dataclass(frozen=True)
class CreateOrder:                                   # only this type reaches the domain layer
    username: str
    email: str
    quantity: int
    currency: str

def parse_create_order(raw: bytes) -> CreateOrder:
    doc = strict_json(raw)
    errors: dict[str, str] = {}
    allowed = {"username", "email", "quantity", "currency"}
    for extra in sorted(doc.keys() - allowed):       # mass assignment guard
        errors[extra] = "unknown field"

    username = doc.get("username")
    if isinstance(username, str):
        username = unicodedata.normalize("NFKC", username).lower()   # canonicalize first
    if not (isinstance(username, str) and USERNAME.fullmatch(username)):
        errors["username"] = "3-32 chars of a-z, 0-9, _"

    email = doc.get("email")
    if not (isinstance(email, str) and len(email) <= 254 and EMAIL.fullmatch(email)):
        errors["email"] = "invalid email address"

    qty = doc.get("quantity")
    if type(qty) is not int or not 1 <= qty <= 100:  # bool is a subclass of int
        errors["quantity"] = "integer between 1 and 100"

    currency = doc.get("currency")
    if currency not in CURRENCIES:                   # allowlist
        errors["currency"] = f"one of {sorted(CURRENCIES)}"

    if errors:
        raise ValidationError(errors)
    return CreateOrder(username, email, qty, currency)

def errors_of(raw: bytes) -> dict[str, str]:
    try:
        parse_create_order(raw)
    except ValidationError as e:
        return e.errors
    return {}

ok = parse_create_order(b'{"username": "\xef\xbc\xa1da_99", "email": "ada@example.com", "quantity": 2, "currency": "EUR"}')
assert ok == CreateOrder("ada_99", "ada@example.com", 2, "EUR")    # fullwidth A normalized by NFKC

# All errors at once, including a mass-assignment attempt and bool-as-int.
errs = errors_of(b'{"username": "a", "email": "nope", "quantity": true, "currency": "BTC", "is_admin": true}')
assert set(errs) == {"username", "email", "quantity", "currency", "is_admin"}, errs

assert errors_of(b'{"quantity": 1, "quantity": 99}') == {"body": "duplicate keys"}
assert errors_of(b'{"quantity": NaN}') == {"body": "NaN not allowed"}
assert errors_of(b"[1, 2]") == {"body": "expected an object"}
assert errors_of(b"x" * (MAX_BODY + 1)) == {"body": "too large"}

# Anchoring pitfall: re.match with "$" accepts a trailing newline; fullmatch does not.
assert re.match(r"^[a-z0-9_]{3,32}$", "admin\n") is not None
assert USERNAME.fullmatch("admin\n") is None

# Paths: resolve, then check containment (canonicalize before validating).
def safe_path(base: Path, user_name: str) -> Path:
    candidate = (base / user_name).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValidationError({"path": "outside upload directory"})
    return candidate

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    assert safe_path(base, "report.pdf").parent == base.resolve()
    for evil in ("../../etc/passwd", "/etc/passwd", "a/../../x"):
        try:
            safe_path(base, evil)
            raise AssertionError(evil)
        except ValidationError:
            pass
print("valid:", ok, "| errors:", errs)
```

In larger codebases a schema library (Pydantic, attrs with validators,
marshmallow, JSON Schema validators) generates the same parser from type
annotations or a schema; the principles above (strict mode, forbid extra
fields, limits, all errors at once) are what to configure.

## Trade-offs
- **Strict vs lenient**: strict parsing (reject unknown fields, exact types)
  catches client bugs and attacks early but makes additive changes harder for
  old servers; tolerant readers ignore unknown fields to allow evolution. A
  common split: strict on public writes, tolerant on reading events from your
  own producers (see [[api-versioning-and-evolution]]).
- **Edge-only vs defence in depth**: validating once at the boundary keeps
  the core clean; domain constructors that also enforce invariants
  (value objects) protect against internal callers and are cheap when the type
  is the parser.
- **Schema-driven vs hand-written**: schemas give documentation, client
  generation and consistent errors; hand-written parsers handle complex
  cross-field rules more clearly. Many teams use a schema for shape and code for
  semantics.
- **Normalizing vs preserving input**: NFKC and lowercasing make lookups
  and uniqueness checks safe but change what the user typed; store the
  normalized key for matching and the original for display when it matters.
- **Rich error detail vs information leakage**: per-field messages help
  legitimate clients; do not reveal internals (stack traces, SQL, which
  usernames exist).

## Gotchas
- `isinstance(True, int)` is `True` in Python; booleans pass naive integer
  checks.
- JSON duplicate keys: RFC 8259 says names SHOULD be unique and behaviour
  otherwise is unpredictable; Python keeps the last value by default, and two
  parsers in one request path (gateway and service) can disagree on which wins.
- `float` parsing accepts `NaN` and `Infinity` in Python's `json` module by
  default; they then poison comparisons and sums.
- `re.match(r"^...$")` accepts a trailing newline; use `fullmatch` or `\Z`.
- Validating a URL by string prefix (`startswith("https://good.com")`) is
  bypassed by `https://good.com.evil.net`; parse it and compare the host to an
  allowlist.
- Checking a path before decoding or resolving it misses `%2e%2e/`, symlinks
  and absolute paths; joining an absolute user path discards the base.
- Validating, then reading the raw value again later (time-of-check to
  time-of-use) loses the guarantee; pass the parsed object on.
- Email and name regexes that are "complete" are either wrong or ReDoS-prone;
  check basic shape and confirm by use (send the email).
- Logging rejected input verbatim can inject fake log lines or leak personal
  data; log a truncated, escaped form.
- Coercing types silently (`"12abc"` to `12`, `"false"` to `True`) hides
  client bugs; reject instead of guessing.

## Related
- [[owasp-top-10]] - injection and other weaknesses that validation reduces but does not fix on its own.
- [[error-handling-strategies]] - turning validation failures into expected, typed errors.
- [[rest-api-design]] - status codes and problem-details bodies for invalid requests.
- [[layered-hexagonal-clean-architecture]] - adapters parse at the edge, the core receives domain types.
- [[functional-core-imperative-shell]] - parsers are pure functions that are easy to test.
- [[strings-and-text-encoding]] - Unicode normalization and lookalike characters behind canonicalization.
- [[property-based-and-fuzz-testing]] - fuzz parsers with generated and malformed input.
- [[data-compression]] - decompression bombs: cap decoded size, not only request size.

## References
- OWASP Input Validation Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html
- OWASP Mass Assignment Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html
- Alexis King, "Parse, don't validate" (2019): https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/
- OWASP, Regular expression Denial of Service (ReDoS): https://owasp.org/www-community/attacks/Regular_expression_Denial_of_Service_-_ReDoS
- MITRE CWE-20, Improper Input Validation: https://cwe.mitre.org/data/definitions/20.html
- RFC 8259, The JavaScript Object Notation (JSON) Data Interchange Format (section 4, unique names): https://www.rfc-editor.org/rfc/rfc8259
- RFC 9457, Problem Details for HTTP APIs: https://www.rfc-editor.org/rfc/rfc9457
- Unicode Standard Annex #15, Unicode Normalization Forms: https://unicode.org/reports/tr15/
- Python `json` module (`object_pairs_hook`, `parse_constant`): https://docs.python.org/3/library/json.html
