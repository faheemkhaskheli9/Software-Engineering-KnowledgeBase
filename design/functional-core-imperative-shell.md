---
title: Functional core, imperative shell
category: design
tags: [functional-core, imperative-shell, pure-functions, side-effects, impureim-sandwich, testability, immutability, boundaries]
use_cases:
  - "make business rules testable without mocks, databases or network"
  - "refactor a function that mixes SQL queries, HTTP calls and decision logic"
  - "structure a CLI, job or request handler so most code is pure"
  - "reduce the number of mocks in a test suite"
  - "design a billing or pricing engine whose results must be reproducible"
status: draft
last_verified: 2026-10-10
sources:
  - "Boundaries, Gary Bernhardt, talk, 2012 - https://www.destroyallsoftware.com/talks/boundaries"
  - "Functional Core, Imperative Shell, Gary Bernhardt, Destroy All Software screencast, 2012"
  - "Impureim sandwich, Mark Seemann, 2020 - https://blog.ploeh.dk/2020/03/02/impureim-sandwich/"
  - "Architecture Patterns with Python, Harry Percival and Bob Gregory - https://www.cosmicpython.com/"
  - "Out of the Tar Pit, Ben Moseley and Peter Marks, 2006"
---

# Functional core, imperative shell

## Summary
Split a program into a pure core that makes all the decisions from plain values, and a thin imperative shell that gathers inputs (DB, network, clock, files), calls the core, and carries out its results. The core is tested with ordinary values and no doubles; the shell is so small and straight-line that a few integration tests cover it. Seemann calls the per-request shape an "impureim sandwich": impure read, pure decide, impure write.

## Key concepts
- **Pure function:** output depends only on inputs; no I/O, no mutation of shared state, no clock or randomness. Same input, same output.
- **Functional core:** the domain logic as pure functions over immutable or locally owned values. Contains the branches and the bugs.
- **Imperative shell:** the code that talks to the world. Has few branches; mostly sequencing.
- **Values as the boundary:** the core takes and returns data (dataclasses, dicts, tuples), not connections or clients (Bernhardt, "Boundaries").
- **Decisions as data:** instead of performing side effects, the core returns a description of what should happen (commands, events, a list of emails to send) and the shell executes it.
- **Impureim sandwich:** read (impure) -> compute (pure) -> write (impure). Works when the inputs can be fetched up front.
- **Relation to hexagonal architecture:** hexagonal keeps I/O behind ports but the domain may still call them; FCIS goes further and keeps I/O out of the domain entirely ([[layered-hexagonal-clean-architecture]]).
- **Accidental vs essential state:** "Out of the Tar Pit" argues most complexity comes from mutable state and control flow; pushing state to the edges is the remedy.

## When to use / scenarios
- Pricing, billing, eligibility, scheduling, validation and diffing logic: the core is naturally a function of data.
- Batch jobs and CLIs: load everything, compute a plan, apply it. Bonus: a `--dry-run` is just printing the plan.
- Request handlers: fetch the aggregate, decide, persist the result and emit events.
- Tests full of mocks asserting call order: a sign the logic should move into a pure function.
- NOT a fit when the decision needs data that depends on earlier I/O results in a loop (paginating until a condition, interactive protocols). Then interleave, or return "need more data" from the core and let the shell loop.
- NOT a fit when the input set is too large to load up front; stream through the core in chunks instead.

## How it works / example

Before: decisions tangled with I/O, so testing needs a fake DB, mailer and clock.

```
def renew_subscriptions(db, mailer):
    for sub in db.query("SELECT ... WHERE active"):
        if sub.expires < datetime.now() and sub.auto_renew:
            db.execute("UPDATE ...")
            mailer.send(sub.email, "renewed")
        elif sub.expires < datetime.now():
            mailer.send(sub.email, "expired")
```

After: a pure core that returns decisions, and a shell that executes them.

```python
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class Sub:
    id: int
    email: str
    expires: date
    auto_renew: bool

@dataclass(frozen=True)
class Renew:
    sub_id: int
    new_expiry: date

@dataclass(frozen=True)
class Email:
    to: str
    template: str

def plan_renewals(subs, today):                   # functional core: pure, no I/O
    actions = []
    for s in subs:
        if s.expires >= today:
            continue
        if s.auto_renew:
            actions.append(Renew(s.id, today + timedelta(days=365)))
            actions.append(Email(s.email, "renewed"))
        else:
            actions.append(Email(s.email, "expired"))
    return actions

def run(repo, mailer, today):                     # imperative shell: read, decide, write
    actions = plan_renewals(repo.active_subs(), today)
    for a in actions:
        if isinstance(a, Renew):
            repo.set_expiry(a.sub_id, a.new_expiry)
        else:
            mailer.send(a.to, a.template)
    return actions

# The core is tested with plain values: no mocks
today = date(2026, 3, 1)
subs = [Sub(1, "a@x", date(2026, 2, 1), True),
        Sub(2, "b@x", date(2026, 2, 1), False),
        Sub(3, "c@x", date(2026, 4, 1), True)]
assert plan_renewals(subs, today) == [
    Renew(1, date(2027, 3, 1)), Email("a@x", "renewed"), Email("b@x", "expired")]
print("core ok")
```

Shape:

```
        +----------------- imperative shell -----------------+
input ->| read DB / API / clock  ->  core(values) -> decisions |-> write DB / send / log
        +------------------------------------------------------+
                         core: pure, most branches, most tests
```

## Trade-offs
- **Testability vs up-front loading:** the core needs its inputs as values, which can mean loading more data than an interleaved version would.
- **Decisions-as-data vs direct calls:** returning commands adds small types and a dispatcher in the shell, but makes logic inspectable, loggable and dry-runnable.
- **Pure core vs ORM-rich domain:** active-record models that lazy-load on attribute access put I/O inside the core; FCIS works better with plain data loaded explicitly ([[orm-and-n-plus-one]]).
- **Shell testing:** the shell has few branches, so a handful of integration tests suffice; logic creeping into the shell erodes the benefit.
- **Performance:** immutable values and copying can cost allocations in hot loops; local mutation inside a function is still pure from the outside.

## Gotchas
- Reading `datetime.now()`, `random`, environment variables or config inside the core makes it impure; pass them in as values.
- Logging from the core is a side effect; return information and log in the shell, or accept logging as a pragmatic exception.
- A core that takes a repository object "just to read" is not pure; pass the data.
- Exceptions for expected outcomes (not found, rejected) hide decisions; return them as values ([[error-handling-strategies]]).
- Mutable inputs: if the core mutates a list it was given, the shell sees changed state. Use frozen dataclasses or copy.
- The shell growing `if` statements means a decision leaked out of the core; move it back.

## Related
- [[layered-hexagonal-clean-architecture]] - the architecture-scale cousin: ports, adapters and a dependency rule
- [[dependency-injection]] - the alternative way to handle dependencies when I/O must stay interleaved
- [[unit-testing-and-test-doubles]] - FCIS removes most of the need for doubles
- [[error-handling-strategies]] - results as values instead of exceptions
- [[refactoring-and-code-smells]] - extracting pure functions from tangled code
- [[cqrs-and-event-sourcing]] - commands and events as returned decisions

## References
- Bernhardt, "Boundaries" (talk, 2012) and "Functional Core, Imperative Shell" (Destroy All Software, 2012)
- Seemann, "Impureim sandwich" (blog.ploeh.dk, 2020)
- Percival and Gregory, "Architecture Patterns with Python"
- Moseley and Marks, "Out of the Tar Pit" (2006)
