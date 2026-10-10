---
title: Property-based and fuzz testing
category: testing
tags: [property-based-testing, hypothesis, fuzzing, shrinking, invariants, stateful-testing, atheris]
use_cases:
  - "test a parser or serializer with thousands of generated inputs"
  - "find edge cases our hand-written examples miss"
  - "verify a sorting, pricing or merge function holds invariants"
  - "fuzz a file-format or protocol handler for crashes"
  - "test a stateful component such as a cache or queue against a simple model"
status: draft
last_verified: 2026-10-10
sources:
  - https://hypothesis.readthedocs.io/
  - https://www.cs.tufts.edu/~nr/cs257/archive/john-hughes/quick.pdf
  - https://github.com/google/atheris
  - https://llvm.org/docs/LibFuzzer.html
  - https://fsharpforfunandprofit.com/posts/property-based-testing-2/
---

# Property-based and fuzz testing

## Summary
Property-based testing states a rule that must hold for all inputs (a
*property*) and lets a framework generate hundreds of inputs, then shrinks any
failure to a minimal counterexample. Fuzzing feeds large volumes of random or
mutated (often coverage-guided) input to code to find crashes, hangs and
security bugs. Both find the edge cases you did not think of.

## Key concepts
- **Property:** a general statement: round-trip (`decode(encode(x)) == x`),
  invariant (output sorted, length preserved), idempotence
  (`f(f(x)) == f(x)`), commutativity, "no exception for any input",
  oracle (compare with a slow, obviously correct implementation), metamorphic
  (changing input in a known way changes output predictably).
- **Generators / strategies:** composable descriptions of input spaces
  (`st.integers()`, `st.text()`, `st.lists(...)`, `st.builds(...)`).
- **Shrinking:** on failure, reduce the example to the smallest failing case.
  Hypothesis does this automatically and stores failures in a local example
  database to replay them.
- **Stateful testing:** generate sequences of operations against a system and
  compare it with a simple model (Hypothesis `RuleBasedStateMachine`).
- **Fuzzing:** black-box (random bytes), grammar-based (structured), and
  **coverage-guided** (AFL++, libFuzzer, Atheris for Python, Jazzer for JVM,
  `cargo fuzz`), which evolves inputs that reach new code paths.
- **Sanitizers** (ASan, UBSan) make memory bugs in native code visible while
  fuzzing.

## When to use / scenarios
- Pure functions with clear invariants: sort, merge, diff, money arithmetic,
  rounding, date handling.
- Serialization, parsers, codecs, compression, protocol framing: round-trip
  and "never crashes" properties.
- Anything that accepts untrusted input (image, PDF, JSON, protocol parsers,
  native extensions): fuzz it, ideally in CI for a short budget and
  continuously for longer.
- Refactoring or rewriting: use the old implementation as an oracle.
- Not a replacement for example tests that document intended behaviour; use
  both. Skip when you cannot state any property beyond restating the code.

## How it works / example

Hypothesis (`pip install hypothesis pytest`):

```python
from hypothesis import given, settings, strategies as st, assume, example
import json

# Round-trip property
@given(st.dictionaries(st.text(), st.one_of(st.integers(), st.text(), st.none())))
def test_json_roundtrip(d):
    assert json.loads(json.dumps(d)) == d

# Invariant properties of a function under test
def my_sort(xs):
    return sorted(xs)

@given(st.lists(st.integers()))
def test_sort_properties(xs):
    out = my_sort(xs)
    assert len(out) == len(xs)                         # same length
    assert sorted(out) == out                          # ordered (oracle)
    assert all(a <= b for a, b in zip(out, out[1:]))
    assert my_sort(out) == out                         # idempotent

# Encode/decode with a pinned regression example
def b64_roundtrip(b: bytes) -> bytes:
    import base64
    return base64.b64decode(base64.b64encode(b))

@given(st.binary())
@example(b"")                                         # always run this case
def test_b64(b):
    assert b64_roundtrip(b) == b
```

A real bug-finding style: a buggy `clamp` shrinks to a tiny counterexample.

```python
def clamp(x, lo, hi):
    return max(lo, min(x, hi))      # wrong when lo > hi

@given(st.integers(), st.integers(), st.integers())
def test_clamp_in_range(x, lo, hi):
    assume(lo <= hi)                # document the precondition explicitly
    assert lo <= clamp(x, lo, hi) <= hi
```

Stateful model testing:

```python
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
from hypothesis import strategies as st

class CacheMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.real = MyLRU(capacity=1000)   # system under test (big capacity)
        self.model = {}                    # trivially correct model

    @rule(k=st.integers(), v=st.integers())
    def put(self, k, v):
        self.real.put(k, v); self.model[k] = v

    @rule(k=st.integers())
    def get(self, k):
        assert self.real.get(k) == self.model.get(k)

TestCache = CacheMachine.TestCase
```

Coverage-guided fuzzing with Atheris (`pip install atheris`):

```python fragment
import sys, atheris
with atheris.instrument_imports():
    import mylib                       # code under test

def TestOneInput(data: bytes):
    fdp = atheris.FuzzedDataProvider(data)
    try:
        mylib.parse(fdp.ConsumeUnicodeNoSurrogates(256))
    except mylib.ParseError:
        pass                           # expected rejection is fine; crashes are not

atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
```

Keep a corpus of interesting inputs in the repo and replay it in CI as plain
regression tests.

## Trade-offs
- **Generated breadth vs reproducibility:** randomness finds new bugs but can
  make CI failures look random; rely on Hypothesis' seed printing and example
  database, and pin regressions with `@example`.
- **Run time:** more examples = more coverage and slower runs. Use a CI profile
  with a modest `max_examples` and a long nightly profile.
- **Writing good properties is the hard part:** weak properties pass while the
  code is wrong; oracles and round-trips are strongest.
- **Fuzzing setup cost:** harness, sanitizers and corpus management need
  investment; pays off for parsers and security-critical native code.
- **Strategies too permissive or too narrow:** unconstrained text may spend
  time on irrelevant inputs; over-filtering with `assume` makes the generator
  discard most cases (health check failures).

## Gotchas
- Reimplementing the function inside the test as the "property" proves nothing.
- Floats: NaN, inf and -0.0 are generated by default; decide explicitly with
  `allow_nan=False` etc., and compare with tolerance.
- Nondeterministic or slow code under test breaks shrinking; Hypothesis flags
  flaky tests and deadlines. Fix the code, don't just raise the deadline.
- Don't catch broad exceptions in the harness; you will hide real crashes.
- Fuzzing finds crashes, not logic errors, unless you add assertions.
- Fuzz only code and systems you own, in isolated environments; never point a
  fuzzer at third-party production services.
- Triage every crash; deduplicate by stack trace and keep the minimized input
  as a regression test.

## Related
- [[unit-testing-and-test-doubles]] - example-based tests that properties complement.
- [[testing-strategy-and-pyramid]] - where generated tests fit in the suite.
- [[tdd-and-bdd]] - examples first, then generalise into properties.
- [[owasp-top-10]] - fuzzing targets input-handling weaknesses behind injection and parsing bugs.
- [[algorithm-patterns]] - algorithms with clear invariants are ideal subjects.
- [[error-handling-strategies]] - decide which failures are expected versus bugs.

## References
- Hypothesis documentation, https://hypothesis.readthedocs.io/
- Claessen and Hughes, "QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs" (ICFP 2000).
- Google Atheris, libFuzzer docs, AFL++ project.
- Scott Wlaschin, "Choosing properties for property-based testing".
