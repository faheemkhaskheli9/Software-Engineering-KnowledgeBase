---
title: Clean code and naming
category: design
tags: [clean-code, naming, readability, functions, comments, formatting, type-hints, maintainability]
use_cases:
  - "make a new teammate able to understand this module in an afternoon"
  - "pick names for functions and variables in a domain-heavy codebase"
  - "decide when a comment is useful versus a sign the code needs rewriting"
  - "set team conventions for function size, parameters and formatting"
  - "review a PR where the logic is right but unreadable"
status: draft
last_verified: 2026-10-10
sources:
  - "Clean Code, Robert C. Martin"
  - "A Philosophy of Software Design, John Ousterhout"
  - "Code Complete, 2nd ed., Steve McConnell"
  - "PEP 8 - https://peps.python.org/pep-0008/"
  - "The Art of Readable Code, Boswell and Foucher"
---

# Clean code and naming

## Summary
Code is read many more times than it is written, so optimize for the next reader. Clean code has intention-revealing names, small focused functions, few surprises, comments that explain why rather than what, and consistent formatting enforced by tools. Naming is the highest-leverage habit: a good name removes the need for a comment and a bad one spreads misunderstanding.

## Key concepts
- **Names reveal intent:** `elapsed_days` not `d`; `is_expired(token)` not `check(token)`. A name should answer what it is, why it exists and how it is used.
- **Use the domain vocabulary:** same word for the same concept everywhere (`customer` vs `client` vs `user` mixed is a bug factory); see ubiquitous language in [[domain-driven-design]].
- **Scope-proportional length:** short names in tiny scopes (`i`, `x` in a 3-line comprehension), descriptive ones for wide scopes.
- **Functions:** do one thing at one level of abstraction; read top-down like a narrative. Few parameters (0-3 is comfortable); avoid boolean flag arguments; avoid output parameters.
- **Command-query separation:** a function either changes state or returns information, not both (with pragmatic exceptions like `pop`).
- **Comments:** explain *why* (constraints, trade-offs, links to specs/issues), not *what*. Stale comments are worse than none. Docstrings document the public contract.
- **Make illegal states unrepresentable:** types, enums and dataclasses over strings and dicts.
- **Early return / guard clauses** to flatten nesting.
- **Consistent formatting:** automated (formatter and linter), not debated in reviews.
- **No surprise side effects:** a function named `get_user` should not create one.
- **Deep modules, small interfaces:** see [[coupling-cohesion-and-design-principles]].

## When to use / scenarios
- Every code review; set the bar as "could a stranger understand this without asking me?"
- Naming a new domain concept: write the name, then a sentence using it aloud. If awkward, rename.
- A function over a screen long, or with sections separated by blank lines and comments: extract functions named after those comments.
- Public library/API: docstrings, type hints and examples matter more than internals.
- NOT dogma: tiny functions everywhere can fragment logic and force jumping between files; Ousterhout's advice is to prefer deep modules over many shallow ones. Don't rename widely used public APIs for taste; see [[api-versioning-and-evolution]].

## How it works / example

Before:

```python
def proc(d, f):
    r = []
    for x in d:
        if x[2] == 1 and not f:
            r.append(x[0] * 1.2)
    return r
```

After: names, types, no magic numbers, no flag argument.

```python
from dataclasses import dataclass

VAT_RATE = 0.20
ACTIVE = 1

@dataclass(frozen=True)
class Product:
    price: float
    status: int

def prices_with_vat(products: list[Product]) -> list[float]:
    return [p.price * (1 + VAT_RATE) for p in products if p.status == ACTIVE]
```

Guard clauses flatten nesting:

```python
def discount(user, cart):
    if user is None:
        return 0
    if not cart.items:
        return 0
    if user.is_vip:
        return cart.total * 0.1
    return 0
```

Comments: what vs why.

```python fragment
x += 1  # increment x                                   <- noise
retry_delay = 2 ** attempt  # vendor rate-limits at 429; back off per their docs (see ticket #482)  <- useful
```

Naming cheat sheet:

```
booleans:       is_/has_/can_/should_ prefix      (is_valid, has_children)
functions:      verbs                             (fetch_orders, parse_header)
classes:        nouns                             (OrderRepository, RetryPolicy)
collections:    plural                            (users, pending_jobs)
units:          include in name when ambiguous    (timeout_seconds, size_bytes)
avoid:          data, info, manager, handler, util, temp, flag, do_stuff
conventions:    PEP 8 snake_case / PascalCase / UPPER_CASE constants
```

Tooling that replaces taste arguments: a formatter (black or ruff format), a linter (ruff), a type checker (mypy or pyright), pre-commit hooks, CI enforcement. Typed signatures serve as machine-checked documentation.

Function-size heuristic: if you need a comment to label a block, extract it; if the name of the extracted function says exactly what the comment said, the comment can go.

## Trade-offs
- **Short functions vs locality:** splitting aids naming and testing but scatters the story; split when the pieces have clear names and contracts.
- **Verbosity vs terseness:** longer names cost horizontal space but save lookups; abbreviations only if universally known in the team (`url`, `id`).
- **Comments vs self-documenting code:** the code cannot say *why* a weird workaround exists; keep those comments.
- **Strict types vs flexibility:** annotations and dataclasses add ceremony upfront and remove whole classes of bugs.
- **Consistency vs local optimum:** following the existing style beats a "better" style used in one corner.
- **Boolean flags vs two functions:** two functions read better; a flag is acceptable for tiny internal helpers.

## Gotchas
- Misleading names (`user_list` that is a dict); names that lie are worse than short names.
- Mixed levels of abstraction in one function (SQL strings next to business rules).
- Noisy commented-out code left "just in case": version control remembers it.
- Over-long parameter lists signal a missing object (see Parameter Object in [[refactoring-and-code-smells]]).
- Negative booleans (`is_not_disabled`) and double negations.
- Mutable default arguments in Python (`def f(x=[])`).
- Docstrings that repeat the signature add nothing; document behavior, errors raised, units and invariants.
- Renaming only in code but not in docs, dashboards, alerts and DB columns leaves inconsistent vocabulary.
- Inconsistent error semantics (some functions return `None`, others raise); see [[error-handling-strategies]].

## Related
- [[refactoring-and-code-smells]] - turning unclear code into clear code safely
- [[error-handling-strategies]] - readable failure paths are part of clean code
- [[coupling-cohesion-and-design-principles]] - structural side of readability
- [[code-review]] - where readability is enforced by humans
- [[documentation-practices]] - docstrings, READMEs and where explanation belongs

## References
- Martin, "Clean Code"
- Ousterhout, "A Philosophy of Software Design"
- McConnell, "Code Complete", 2nd ed.
- PEP 8: https://peps.python.org/pep-0008/
- Boswell and Foucher, "The Art of Readable Code"
