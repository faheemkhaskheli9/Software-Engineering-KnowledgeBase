---
title: Error handling strategies
category: design
tags: [error-handling, exceptions, result-type, validation, fail-fast, retries, logging, python]
use_cases:
  - "decide whether a function should raise, return None, or return a result object"
  - "design consistent error responses and codes for an HTTP API"
  - "stop swallowing exceptions and still keep a service running when one request fails"
  - "separate retryable transient failures from permanent ones"
  - "make a batch job report partial failures instead of aborting or hiding them"
status: draft
last_verified: 2026-10-10
sources:
  - "https://docs.python.org/3/tutorial/errors.html"
  - "https://docs.python.org/3/library/exceptions.html"
  - "Release It!, 2nd ed., Michael Nygard"
  - "Code Complete, 2nd ed., Steve McConnell, chapter 8"
  - "https://www.rfc-editor.org/rfc/rfc9457"
---

# Error handling strategies

## Summary
Error handling is deciding, for each failure, who detects it, who can fix it, what the caller sees and what gets recorded. Good strategies fail fast on programmer errors, handle expected failures explicitly at the layer that can act on them, translate errors at boundaries, and never swallow information silently. Consistency matters more than which mechanism you choose.

## Key concepts
- **Kinds of failure:**
  - *Programmer errors / bugs* (None dereference, broken invariant): fail fast, crash the request, alert. Do not "handle".
  - *Expected domain failures* (insufficient funds, validation error, not found): part of the contract; model explicitly.
  - *Transient infrastructure failures* (timeout, connection reset, 503): may be retried.
  - *Permanent infrastructure failures* (bad config, auth rejected): do not retry; surface loudly.
- **Mechanisms:** exceptions (non-local exit, easy to forget to catch), return codes/`None` (easy to ignore), result types (`Ok`/`Err`, explicit but verbose in Python), sentinel/optional values.
- **Fail fast:** validate inputs at the boundary, assert invariants, stop at the first sign of corruption instead of propagating bad data.
- **Catch where you can act:** low layers raise; a higher layer that knows what to do (retry, fallback, user message) catches.
- **Error translation at boundaries:** wrap low-level errors in domain errors (`sqlite3.IntegrityError` becomes `DuplicateEmail`) so internals do not leak; keep the cause via `raise ... from e`.
- **Resource safety:** `with`/`try`/`finally` so cleanup always runs.
- **Idempotent retries with backoff and jitter:** only for transient errors and safe operations; see [[idempotency-and-exactly-once]].
- **Observability:** log once at the point of handling with context, not at every layer; include correlation IDs.
- **User-facing vs developer-facing:** friendly message and stable error code outward, full detail in logs.

## When to use / scenarios
- Library/internal function with a rare failure: raise a specific exception type.
- Frequent, expected "no" answers (lookup misses, parsing user input): return `None`/Optional or a result object so callers must decide.
- HTTP API: map domain errors to status codes and a consistent body (RFC 9457 problem details); see [[rest-api-design]].
- Calling remote services: timeouts, retries with limits, circuit breaker, fallback; see [[resilience-patterns]].
- Batch jobs: collect per-item errors, continue, report a summary, and dead-letter failed items; see [[message-queues-and-streams]].
- NOT: catching `Exception` broadly to "keep things running", or retrying non-idempotent operations blindly.

## How it works / example

Exception hierarchy with translation at the boundary:

```python
class AppError(Exception): ...
class NotFound(AppError): ...
class DuplicateEmail(AppError): ...
class UpstreamUnavailable(AppError): ...

def create_user(repo, email):
    try:
        return repo.insert(email)
    except KeyError as e:                       # low-level detail
        raise DuplicateEmail(email) from e      # keep cause chain
```

Handle where you can act; log once; do not swallow:

```python
import logging
log = logging.getLogger(__name__)

def handler(request):
    try:
        return {"status": 201, "body": create_user(repo, request["email"])}
    except DuplicateEmail:
        return {"status": 409, "body": {"code": "email_taken"}}
    except UpstreamUnavailable:
        return {"status": 503, "body": {"code": "try_later"}}
    except Exception:
        log.exception("unhandled error")        # includes traceback
        return {"status": 500, "body": {"code": "internal"}}
```

Retry only transient errors, with backoff and jitter:

```python
import random, time

def call_with_retry(fn, attempts=4, base=0.2):
    for n in range(attempts):
        try:
            return fn()
        except (TimeoutError, ConnectionError):          # transient only
            if n == attempts - 1:
                raise
            time.sleep(base * 2 ** n * random.uniform(0.5, 1.5))
```

Result object when failure is routine:

```python
from dataclasses import dataclass

@dataclass
class Result:
    value: object = None
    error: str | None = None
    @property
    def ok(self): return self.error is None

def parse_age(s):
    if not s.isdigit():
        return Result(error="not a number")
    return Result(value=int(s))
```

Batch partial failure:

```python
def process_all(items, fn):
    ok, failed = [], []
    for it in items:
        try:
            ok.append(fn(it))
        except Exception as e:                           # boundary of a unit of work
            failed.append((it, repr(e)))
    return ok, failed                                    # caller decides: alert, retry, DLQ
```

Decision flow:

```
Is it a bug (broken invariant)?        -> raise / crash, alert
Is it an expected outcome?             -> model it (specific exception or result)
Is it transient and op idempotent?     -> retry with backoff, deadline
Else                                   -> translate, log once with context, report to caller
```

## Trade-offs
- **Exceptions vs result types:** exceptions keep the happy path clean and propagate automatically but are invisible in signatures; results are explicit and force handling but add boilerplate. In Python, exceptions are idiomatic; use results for high-frequency expected failures.
- **Fail fast vs resilience:** crashing a request on bad data prevents corruption; degraded modes (serve stale cache) preserve availability. Decide per feature.
- **Retry vs fail:** retries hide transient glitches but amplify load during outages; cap attempts and use budgets and circuit breakers.
- **Granular vs coarse exception types:** too many types is ceremony; too few forces string matching. Add a type when a caller needs to react differently.
- **Verbose errors vs security:** detail helps debugging but leaks internals; return stable codes outward and keep traces in logs ([[owasp-top-10]]).

## Gotchas
- `except:` or `except Exception: pass` hides bugs and breaks Ctrl-C/shutdown handling; never silently swallow.
- Logging and re-raising at every layer duplicates logs; log where handled.
- Losing the cause: use `raise NewError(...) from e`, not a bare new exception.
- Returning `None` for both "not found" and "error" makes them indistinguishable.
- Cleanup missed on error paths; use context managers.
- Retrying non-idempotent calls (charging a card twice); use idempotency keys.
- Timeouts missing on remote calls turn failures into hangs.
- Catching errors too early hides them from the layer that could decide properly.
- Error messages containing secrets or PII ending up in logs.
- Inconsistent error formats across endpoints force clients to special-case each.

## Related
- [[resilience-patterns]] - timeouts, retries, circuit breakers and fallbacks across service calls
- [[idempotency-and-exactly-once]] - making retries safe
- [[clean-code-and-naming]] - consistent return/raise conventions
- [[rest-api-design]] - mapping errors to HTTP status codes and bodies
- [[observability-logs-metrics-traces]] - logging and alerting on errors usefully
- [[failure-modes-and-fallacies]] - the failures you are guarding against in distributed systems

## References
- Python docs: errors and exceptions tutorial; built-in exceptions
- Nygard, "Release It!", 2nd ed.
- McConnell, "Code Complete", 2nd ed., ch. 8 (defensive programming)
- RFC 9457, Problem Details for HTTP APIs: https://www.rfc-editor.org/rfc/rfc9457
