---
title: State machines
category: design
tags: [state-machine, finite-state-machine, fsm, statecharts, transitions, workflow, state-pattern, lifecycle]
use_cases:
  - "model an order, payment or ticket lifecycle so illegal status changes are impossible"
  - "replace a tangle of boolean flags like is_paid, is_shipped, is_cancelled"
  - "implement a protocol parser or connection handler with clear states"
  - "persist workflow state in a database and transition it safely under concurrency"
  - "draw and review the allowed transitions of a feature with product owners"
status: draft
last_verified: 2026-10-10
sources:
  - "Statecharts: A Visual Formalism for Complex Systems, David Harel, Science of Computer Programming, 1987"
  - "Introduction to Automata Theory, Languages, and Computation, Hopcroft, Motwani, Ullman"
  - "Design Patterns, Gamma, Helm, Johnson, Vlissides (State pattern)"
  - "State Chart XML (SCXML), W3C Recommendation, 2015 - https://www.w3.org/TR/scxml/"
  - "Python enum docs - https://docs.python.org/3/library/enum.html"
---

# State machines

## Summary
A finite state machine (FSM) models something that is always in exactly one of a fixed set of states and moves between them only through named transitions triggered by events. Making the states and allowed transitions explicit, usually as a table, turns scattered flag checks into one place that rejects illegal changes, documents the lifecycle, and is easy to test exhaustively. Statecharts extend the idea with nesting and parallel regions for larger systems.

## Key concepts
- **State:** a named condition the entity is in (`PENDING`, `PAID`, `SHIPPED`). Exactly one at a time.
- **Event:** something that happens (`pay`, `ship`, `cancel`, a received byte).
- **Transition:** `(state, event) -> next state`, possibly with a **guard** (condition that must hold) and an **action** (side effect on the way).
- **Transition table:** the full mapping. Any `(state, event)` pair not in the table is illegal.
- **Initial and terminal states:** where the lifecycle starts and states with no outgoing transitions (`DELIVERED`, `CANCELLED`).
- **Mealy vs Moore:** outputs depend on transition (Mealy) or on state (Moore). Matters for protocol and hardware design more than business workflows.
- **Statecharts (Harel, 1987):** hierarchical states (a substate inherits the parent's transitions), orthogonal regions (independent concurrent sub-machines), history states. SCXML is a W3C standard notation.
- **State pattern (GoF):** one class per state with the event methods; the context delegates to the current state object. An OO alternative to a table.
- **Explicit vs implicit state:** implicit state is spread across booleans and nullable timestamps (`paid_at is not None and shipped_at is None`); n booleans allow 2^n combinations, most of them meaningless.
- **Workflow engines:** durable, long-running state machines with timers and retries (Temporal, AWS Step Functions, BPMN engines); see [[distributed-transactions-and-sagas]].

## When to use / scenarios
- Business entities with a lifecycle: orders, payments, subscriptions, tickets, documents in review, KYC checks.
- Several boolean or status flags whose combinations need validation: replace them with one status field and a table.
- Protocol handling, parsers, lexers, UI flows (wizard steps, connection states), game entities.
- Sagas and long-running processes where each step's completion moves the process forward ([[distributed-transactions-and-sagas]]).
- NOT worth it for a two-state toggle with no rules, or a linear sequence with no branching or cancellation.
- Reach for a statechart or workflow engine when the flat machine explodes (many states repeating the same `cancel` and `timeout` transitions) or when state must survive restarts with timers.

## How it works / example

Lifecycle diagram:

```
          pay            ship           deliver
PENDING -------> PAID ---------> SHIPPED --------> DELIVERED
   |               |
   | cancel        | cancel (guard: not yet shipped) / action: refund
   v               v
CANCELLED <--------+
```

Table-driven machine with guards, actions and illegal-transition rejection:

```python
from enum import Enum, auto

class S(Enum):
    PENDING = auto(); PAID = auto(); SHIPPED = auto(); DELIVERED = auto(); CANCELLED = auto()

class IllegalTransition(Exception):
    pass

# (state, event) -> next state. Everything else is illegal.
TRANSITIONS = {
    (S.PENDING, "pay"): S.PAID,
    (S.PENDING, "cancel"): S.CANCELLED,
    (S.PAID, "ship"): S.SHIPPED,
    (S.PAID, "cancel"): S.CANCELLED,
    (S.SHIPPED, "deliver"): S.DELIVERED,
}

class Order:
    def __init__(self):
        self.state = S.PENDING
        self.log = []

    def fire(self, event):
        nxt = TRANSITIONS.get((self.state, event))
        if nxt is None:
            raise IllegalTransition(f"{event} not allowed from {self.state.name}")
        if self.state is S.PAID and nxt is S.CANCELLED:
            self.log.append("refund")            # action on this transition
        self.log.append(f"{self.state.name}->{nxt.name}")
        self.state = nxt

o = Order()
o.fire("pay"); o.fire("cancel")
assert o.state is S.CANCELLED and "refund" in o.log

o = Order()
o.fire("pay"); o.fire("ship")
try:
    o.fire("cancel")
except IllegalTransition as e:
    print(e)                                     # cancel not allowed from SHIPPED

# Exhaustive check: every terminal state really has no way out
terminal = {S.DELIVERED, S.CANCELLED}
assert not any(src in terminal for src, _ in TRANSITIONS)
```

Persisting transitions safely under concurrency: make the database enforce the expected current state.

```
UPDATE orders SET status = 'SHIPPED', version = version + 1
 WHERE id = :id AND status = 'PAID' AND version = :v;
-- 0 rows updated -> someone else transitioned first (or the transition is illegal): reload and decide
```

## Trade-offs
- **Table vs State pattern vs `match`/if-chains:** a table is data you can print, diagram and test exhaustively; the State pattern puts per-state behavior in classes, good when states have rich behavior; if-chains are fine for tiny machines and rot as states grow.
- **Hand-rolled vs library:** a dict and an enum cover most business lifecycles; a library (`transitions` in Python, XState in JS) adds hooks, nesting and diagrams at the cost of a dependency and framework idioms.
- **Flat FSM vs statechart:** flat machines are easy to read until shared transitions repeat across many states; statecharts remove the repetition but are harder to implement and reason about.
- **In-app state vs workflow engine:** in-app is simple and transactional with your data; a workflow engine handles durable timers, retries and long waits but is another system to run.
- **Status column vs event log:** a single status is simple to query; storing transitions as events gives full history and audit ([[cqrs-and-event-sourcing]]).

## Gotchas
- Setting `order.status = "SHIPPED"` directly anywhere in the code bypasses the machine; route all changes through one transition function.
- Read-check-write without a condition in the UPDATE races: two workers both see `PAID` and both ship. Use a conditional update or row lock ([[transactions-and-isolation-levels]]).
- Side effects (charging a card, sending email) inside the transition, before the state is committed, can run twice on retry; use an outbox or idempotency keys ([[idempotency-and-exactly-once]]).
- Adding a state later without updating every consumer that switches on status (reports, UIs, other services) breaks them; treat the state set as part of the contract.
- Storing state names as integers in the DB makes reordering an enum a data corruption bug; store stable strings or explicit values.
- Missing transitions are discovered in production as "stuck" entities; add monitoring for entities sitting in non-terminal states too long.
- Events arriving out of order (a `delivered` webhook before `shipped`) need a policy: reject, buffer, or allow the skip explicitly ([[webhooks]]).

## Related
- [[design-patterns-gof]] - the State pattern as an OO implementation
- [[graph-algorithms]] - a state machine is a directed graph; reachability and cycle checks apply
- [[distributed-transactions-and-sagas]] - sagas as state machines across services
- [[cqrs-and-event-sourcing]] - transitions recorded as events
- [[transactions-and-isolation-levels]] - conditional updates that make transitions atomic
- [[design-payment-system]] - payment lifecycles as the canonical example
- [[property-based-and-fuzz-testing]] - stateful testing of a machine against a model
- [[frontend-state-management]] - reducers and state machines for complex UI flows.

## References
- Harel, "Statecharts: A Visual Formalism for Complex Systems" (1987)
- Hopcroft, Motwani, Ullman, "Introduction to Automata Theory, Languages, and Computation"
- Gamma et al., "Design Patterns" (State)
- W3C, "State Chart XML (SCXML)" Recommendation (2015)
- Python docs: enum
