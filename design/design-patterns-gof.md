---
title: Design patterns (GoF) in practice
category: design
tags: [design-patterns, gof, strategy, factory, observer, decorator, adapter, singleton, command, builder]
use_cases:
  - "swap algorithms (pricing rules, compression, routing) at runtime without if/elif chains"
  - "wrap a third-party SDK so the rest of the code does not depend on it"
  - "add logging, caching or retries around a function without editing it"
  - "notify several components when something happens without hard-wiring them"
  - "build complex objects with many optional parts cleanly"
status: draft
last_verified: 2026-10-10
sources:
  - "Design Patterns: Elements of Reusable Object-Oriented Software, Gamma, Helm, Johnson, Vlissides"
  - "Head First Design Patterns, Freeman and Robson"
  - "https://refactoring.guru/design-patterns"
  - "https://docs.python.org/3/library/functools.html"
---

# Design patterns (GoF) in practice

## Summary
Design patterns are named, reusable solutions to recurring design problems, mostly about reducing coupling and making variation explicit. The 23 GoF patterns come from statically typed OOP; in Python many collapse into first-class functions, decorators and duck typing. Learn the vocabulary for communication, but reach for a pattern only when the problem it solves is present.

## Key concepts
Three families:
- **Creational** (how objects are made): Factory Method, Abstract Factory, Builder, Prototype, Singleton.
- **Structural** (how objects are composed): Adapter, Decorator, Facade, Proxy, Composite, Bridge, Flyweight.
- **Behavioral** (how objects interact): Strategy, Observer, Command, State, Template Method, Iterator, Chain of Responsibility, Mediator, Visitor, Memento.

The ones used constantly:
- **Strategy:** interchangeable algorithm behind one interface.
- **Factory:** centralize which concrete class gets created.
- **Adapter:** translate one interface to another (wrap SDKs, legacy code).
- **Decorator:** add behavior around an object/function with the same interface.
- **Observer / pub-sub:** subject notifies subscribers; decouples producer from consumers.
- **Command:** encapsulate a request as an object (queue, undo, audit, retry).
- **Facade:** a simple front over a complex subsystem.
- **Builder:** step-by-step construction of complex objects.
- **State:** behavior varies with internal state, replacing big conditionals.
- **Singleton:** one instance globally. Mostly an anti-pattern (hidden global state).

## When to use / scenarios

| Problem | Pattern |
|---|---|
| Growing if/elif on a "type" or "mode" | Strategy, or State if it changes over time |
| Need to isolate a vendor SDK | Adapter, behind a domain-owned interface |
| Cross-cutting concern (timing, auth, caching, retry) | Decorator |
| Many listeners to an event | Observer; at system scale, event bus ([[event-driven-architecture]]) |
| Object creation depends on config or input | Factory |
| Constructor with 10 optional args | Builder, or keyword args/dataclass in Python |
| Queue, undo/redo, audit trail of operations | Command |
| Tree structures treated uniformly (file system, UI) | Composite |
| Hide a messy subsystem | Facade |

NOT when: there is one concrete case and no foreseeable second (YAGNI, see [[coupling-cohesion-and-design-principles]]); or when a plain function or dict does the job. Patterns are named after problems, not goals to hit.

## How it works / example

Strategy as plain functions (the Pythonic form):

```python
def flat(price): return price
def black_friday(price): return price * 0.7
def loyalty(price): return price * 0.9

PRICING = {"flat": flat, "bf": black_friday, "loyalty": loyalty}

def checkout(price, rule="flat"):
    return PRICING[rule](price)

assert checkout(100, "bf") == 70
```

Decorator (language feature) for a cross-cutting concern:

```python
import functools, time

def retry(times=3, delay=0.1):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            for attempt in range(times):
                try:
                    return fn(*a, **kw)
                except ConnectionError:
                    if attempt == times - 1:
                        raise
                    time.sleep(delay * 2 ** attempt)
        return wrapper
    return deco

@retry(times=3)
def call_api(): ...
```

Adapter: keep a vendor SDK at the edge.

```python
class VendorSmsClient:                      # third-party, awkward API
    def send_text_message(self, to_number, body_text, opts=None): ...

class Notifier:                             # our interface
    def notify(self, user_phone: str, message: str) -> None: raise NotImplementedError

class SmsNotifier(Notifier):
    def __init__(self, client): self.client = client
    def notify(self, user_phone, message):
        self.client.send_text_message(user_phone, message)
```

Observer:

```python
class EventBus:
    def __init__(self): self._subs = {}
    def subscribe(self, event, fn): self._subs.setdefault(event, []).append(fn)
    def publish(self, event, payload):
        for fn in self._subs.get(event, []):
            fn(payload)

bus = EventBus()
bus.subscribe("order_paid", lambda o: print("send receipt", o))
bus.subscribe("order_paid", lambda o: print("update stock", o))
bus.publish("order_paid", {"id": 1})
```

Command (retryable, queueable unit of work):

```python
from dataclasses import dataclass

@dataclass
class ChargeCard:
    order_id: int
    cents: int
    def execute(self): print("charge", self.order_id, self.cents)
# a worker pops commands from a queue and calls execute(); store them for audit or replay
```

Structure sketch (Strategy):

```
Context ---has-a---> Strategy (interface)
                        ^        ^
                  StrategyA   StrategyB
```

## Trade-offs
- **Indirection vs clarity:** every pattern adds classes and hops. Worth it when it removes duplication or isolates change; not for decoration.
- **Inheritance-based vs function-based:** in Python, prefer functions, closures, decorators and protocols over class hierarchies.
- **Observer coupling:** looser structural coupling but harder-to-trace runtime flow, ordering and error handling between subscribers.
- **Factory vs direct construction:** factories help when creation varies; otherwise a constructor call is clearer.
- **Singleton vs module/DI:** a module-level object or injected instance gives the same single-instance behavior without global-state pitfalls.
- **Pattern vocabulary:** shared names speed up code review but can encourage forcing designs into named shapes.

## Gotchas
- Singleton makes tests order-dependent; inject a single instance instead.
- Decorator stacks: order matters (retry outside vs inside a cache), and forgetting `functools.wraps` loses names and signatures.
- Observer memory leaks: subscribers never unsubscribed stay alive; exceptions in one subscriber can block others if unhandled.
- Visitor and Abstract Factory are heavy in Python and rarely worth it; singledispatch or plain dicts usually suffice.
- Strategy selected by string keys needs validation of unknown keys.
- Over-patterned code ("AbstractSingletonProxyFactoryBean") is a smell; see [[refactoring-and-code-smells]].
- Patterns do not fix a bad domain model; get boundaries right first ([[domain-driven-design]]).

## Related
- [[solid-principles]] - Strategy/Adapter/Factory are the main tools for open/closed and dependency inversion
- [[coupling-cohesion-and-design-principles]] - the goals patterns serve
- [[refactoring-and-code-smells]] - refactoring toward a pattern when a smell appears
- [[event-driven-architecture]] - Observer and Command at system scale
- [[resilience-patterns]] - retry, circuit breaker and bulkhead are decorator/proxy-style patterns
- [[state-machines]] - the State pattern next to table-driven machines and statecharts

## References
- Gamma, Helm, Johnson, Vlissides, "Design Patterns" (1994)
- Freeman and Robson, "Head First Design Patterns"
- Refactoring.Guru catalog: https://refactoring.guru/design-patterns
- Python docs: functools (wraps, singledispatch, lru_cache)
