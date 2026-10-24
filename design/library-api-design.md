---
title: API design for libraries
category: design
tags: [library-design, public-api, backwards-compatibility, semver, deprecation, hyrums-law, ergonomics, keyword-only-arguments]
use_cases:
  - "design the public interface of an internal SDK or shared Python package"
  - "change a function signature without breaking every caller"
  - "decide what to export from a package and what to keep private"
  - "deprecate and remove an old function safely"
  - "review a library PR for API usability and compatibility risks"
status: draft
last_verified: 2026-10-10
sources:
  - "How to Design a Good API and Why it Matters, Joshua Bloch, 2006 (talk, Google Tech Talks / OOPSLA companion)"
  - "Effective Java, 3rd ed., Joshua Bloch"
  - "Practical API Design: Confessions of a Java Framework Architect, Jaroslav Tulach"
  - "Semantic Versioning 2.0.0 - https://semver.org/"
  - "PEP 387, Backwards Compatibility Policy - https://peps.python.org/pep-0387/"
  - "PEP 8, Public and internal interfaces - https://peps.python.org/pep-0008/"
  - "Hyrum's Law - https://www.hyrumslaw.com/"
  - "Python warnings docs - https://docs.python.org/3/library/warnings.html"
---

# API design for libraries

## Summary
A library's public API is a promise: once others depend on it, every name, parameter, default, exception and observable behavior is hard to change. Good library APIs are small, hard to misuse, consistent, and evolvable: they expose the minimum, make common cases short and dangerous cases explicit, and change through additive releases and announced deprecations under semantic versioning. This note is about in-process APIs (packages, SDKs, modules); network APIs are in [[rest-api-design]].

## Key concepts
- **Public surface:** everything a caller can reach and reasonably rely on: exported names, signatures, return types, exceptions, side effects, performance characteristics.
- **Hyrum's Law:** with enough users, every observable behavior of your system will be depended on by somebody, documented or not.
- **Minimal surface (Bloch):** "When in doubt, leave it out." You can add later; you can rarely remove.
- **Hard to misuse:** the easiest way to call it should be the correct way. Use types, enums and keyword-only arguments instead of positional booleans and magic strings.
- **Principle of least astonishment:** names and behavior match what a reader of the call site expects; consistent with the language's conventions (Python: PEP 8 naming, context managers, iterators, exceptions).
- **Explicit public/private boundary:** in Python, leading underscore for internals, `__all__` for exports, a documented list of supported modules (PEP 8 "Public and internal interfaces").
- **Semantic versioning:** MAJOR for incompatible changes, MINOR for backwards-compatible additions, PATCH for backwards-compatible fixes (semver.org). Only meaningful if the public API is defined.
- **Deprecation cycle:** announce (docs + `DeprecationWarning`), keep working for at least one release window, then remove in a major version. PEP 387 describes CPython's own policy.
- **Additive evolution:** new optional keyword parameters with safe defaults, new functions, new classes. Removing, renaming or reordering is breaking.
- **Error contract:** documented exception types are part of the API; raise your own exception hierarchy rooted at one base class so callers can catch broadly or narrowly.

## When to use / scenarios
- Starting a shared package used by other teams: decide the public modules and names up front, document them, keep the rest underscored.
- A function grew `def f(x, a=True, b=False, c=None, d=3)`: switch new and optional parameters to keyword-only (`*,`), group related options into a small config object.
- A behavior change is needed: add a new function or a flag defaulting to the old behavior, deprecate the old path, flip the default in the next major.
- Users depend on an internal module: either promote it to public with a contract, or provide a public alternative before hiding it.
- NOT the same discipline for application-internal code with one consumer you control; there you refactor freely ([[refactoring-and-code-smells]]).

## How it works / example

Hard-to-misuse signature: keyword-only options, an enum instead of a magic string, a narrow return type.

```python
from enum import Enum

class Compression(Enum):
    NONE = "none"
    GZIP = "gzip"

class ExportError(Exception):
    """Base class for all errors raised by this library."""

def export_rows(rows, path, *, compression=Compression.NONE, overwrite=False):
    """Write rows to path. Options are keyword-only, so call sites stay readable."""
    if not isinstance(compression, Compression):
        raise TypeError("compression must be a Compression")
    return len(rows)

assert export_rows([1, 2], "out.csv", overwrite=True) == 2
try:
    export_rows([1], "out.csv", True)            # positional boolean rejected
except TypeError:
    print("positional flag rejected")
```

Deprecating a name without breaking callers:

```python
import warnings

def fetch_items(limit=100):
    return list(range(limit))

def get_items(limit=100):
    """Deprecated alias for fetch_items, to be removed in 3.0."""
    warnings.warn("get_items() is deprecated; use fetch_items()",
                  DeprecationWarning, stacklevel=2)   # points at the caller's line
    return fetch_items(limit)

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    assert get_items(3) == [0, 1, 2]
assert caught and issubclass(caught[0].category, DeprecationWarning)
print("deprecation warned:", caught[0].message)
```

Declaring the public surface of a package (in `mylib/__init__.py`):

```
from ._export import export_rows, Compression, ExportError
__all__ = ["export_rows", "Compression", "ExportError"]   # everything else is internal
```

Change classification:

```
Safe (MINOR):    new function, new optional keyword param with old-behavior default,
                 new exception subclass of an existing documented one
Breaking (MAJOR): remove/rename anything public, reorder positional params, change a default,
                 raise a new unrelated exception type, change return type or units
```

## Trade-offs
- **Small surface vs convenience:** fewer functions are easier to keep stable; convenience helpers make the common case pleasant but each one is a permanent promise. Add helpers when usage shows the need.
- **Flexibility vs simplicity:** many parameters cover every case but make the API hard to learn; a simple default path plus an advanced lower-level API serves both audiences.
- **Strict validation vs leniency:** validating inputs early gives clear errors; accepting anything makes later tightening a breaking change (Hyrum's Law).
- **Rich types vs plain data:** returning your own classes allows evolution (add attributes); returning tuples or dicts is simpler but freezes the shape.
- **Fast iteration (0.x) vs stability (1.0+):** semver treats 0.x as unstable; staying there forever signals that callers should pin exact versions.
- **Exceptions vs result values:** exceptions are idiomatic in Python; a result type suits languages and APIs where failure is common and expected ([[error-handling-strategies]]).

## Gotchas
- Positional boolean parameters (`send(msg, True, False)`) are unreadable at the call site and impossible to reorder later.
- Mutable default arguments (`def f(items=[])`) share state across calls.
- Leaking third-party types in signatures (returning a `requests.Response`) makes their breaking changes yours.
- Changing a default value is a breaking change even though the signature looks the same.
- `DeprecationWarning` is hidden by default outside `__main__` and test runners; also document deprecations in the changelog.
- Global configuration (`mylib.settings.timeout = 5`) couples all callers in a process; prefer per-instance configuration.
- Returning `None` on error in some paths and raising in others forces callers to handle both.
- Re-exporting everything with `from .x import *` makes internals public by accident.
- Undocumented performance (a call that was O(1) becomes a network call) breaks callers just as surely as a signature change.

## Related
- [[rest-api-design]] - the same principles for network APIs
- [[api-versioning-and-evolution]] - versioning and deprecation for remote APIs
- [[release-versioning-and-changelogs]] - SemVer bumps, pre-release ordering and changelogs
- [[clean-code-and-naming]] - naming that makes call sites read well
- [[coupling-cohesion-and-design-principles]] - information hiding is what a small public surface buys
- [[error-handling-strategies]] - designing an exception hierarchy callers can rely on
- [[dependency-injection]] - letting callers supply clients and clocks instead of hard-wiring them

## References
- Bloch, "How to Design a Good API and Why it Matters" (2006) and "Effective Java", 3rd ed.
- Tulach, "Practical API Design"
- Semantic Versioning 2.0.0
- PEP 387 (backwards compatibility policy); PEP 8 (public and internal interfaces)
- Hyrum's Law (hyrumslaw.com); also discussed in "Software Engineering at Google", ch. 1
- Python docs: warnings, enum, keyword-only parameters
