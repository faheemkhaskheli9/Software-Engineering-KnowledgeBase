---
title: Mutation testing
category: testing
tags: [mutation-testing, mutants, mutation-score, test-quality, mutmut, pitest, stryker, coverage]
use_cases:
  - "find out whether a test suite with high line coverage actually catches bugs"
  - "check that tests for a pricing or permissions module assert the right things"
  - "pick which weak tests to strengthen before a risky refactor"
  - "add mutation testing to CI without making the pipeline take hours"
  - "explain to a team why coverage percentage is not a quality gate"
status: draft
last_verified: 2026-10-10
sources:
  - "Hints on Test Data Selection: Help for the Practicing Programmer, DeMillo, Lipton, Sayward, IEEE Computer, 1978"
  - "An Analysis and Survey of the Development of Mutation Testing, Yue Jia and Mark Harman, IEEE TSE, 2011"
  - "State of Mutation Testing at Google, Petrovic and Ivankovic, ICSE-SEIP 2018"
  - "mutmut docs - https://mutmut.readthedocs.io/"
  - "PIT mutation testing for the JVM - https://pitest.org/"
  - "Stryker Mutator - https://stryker-mutator.io/"
---

# Mutation testing

## Summary
Mutation testing measures how good your tests are by deliberately introducing small bugs (mutants) into the code, such as flipping `<` to `<=` or replacing `+` with `-`, and running the suite against each one. A mutant the tests catch is "killed"; one that passes is "survived" and points at behavior no test checks. It answers the question coverage cannot: not "was this line executed?" but "would a test fail if this line were wrong?"

## Key concepts
- **Mutant:** a copy of the program with one small syntactic change.
- **Mutation operators:** rules that create mutants: relational (`<` to `<=`), arithmetic (`+` to `-`), boolean (`and` to `or`, `not` removed), constant (`0` to `1`), return value replacement, statement deletion.
- **Killed / survived:** killed means at least one test failed; survived means all tests passed with the bug in place.
- **Mutation score:** killed / (total - equivalent). Higher is better; treat it as a signal, not a target.
- **Equivalent mutant:** a change that does not alter behavior (`i < n` vs `i != n` in some loops). It can never be killed; tools cannot always detect them, so humans triage survivors.
- **Competent programmer hypothesis:** real bugs are usually small deviations from correct code (DeMillo et al.).
- **Coupling effect:** tests that catch simple faults tend to catch complex ones too.
- **Timeouts and crashes:** a mutant that causes an infinite loop or crash counts as killed (detected), and tools apply a timeout.
- **Incremental / diff-based mutation:** mutate only changed lines, as Google does in code review (Petrovic and Ivankovic, 2018), to keep cost proportional to the change.
- **Tools:** mutmut and cosmic-ray (Python), PIT (JVM), Stryker (JS/TS, C#, Scala), cargo-mutants (Rust).

## When to use / scenarios
- Core logic where wrong answers are expensive: pricing, billing, authorization, validation, parsers.
- Before a large refactor: survivors show where tests would not protect you ([[refactoring-and-code-smells]]).
- Auditing a suite that reports high coverage but still lets bugs through.
- In CI on changed files or nightly on critical modules; not on every file of a large codebase on every commit.
- NOT useful when the suite is slow or flaky: each mutant reruns tests, so fix speed and flakiness first ([[flaky-tests]]).
- NOT valuable for glue code, generated code or UI layout; exclude them.

## How it works / example

The loop every tool runs:

```
for each mutation point in the code:
    apply one mutant
    run the tests that cover that line (with a timeout)
    tests fail   -> killed  (good)
    tests pass   -> survived (a missing or weak assertion)
report survivors with file, line and the change made
```

A tiny mutation tester built on the stdlib `ast` module, showing why a coverage-complete test can still be weak:

```python
import ast

SOURCE = '''
def shipping_fee(total):
    if total >= 50:
        return 0
    return 5
'''

def weak_tests(fn):                       # 100% line coverage, but misses the boundary
    return fn(100) == 0 and fn(10) == 5

def strong_tests(fn):
    return weak_tests(fn) and fn(50) == 0 and fn(49.99) == 5

SWAPS = {ast.GtE: ast.Gt, ast.Gt: ast.GtE, ast.Lt: ast.LtE, ast.LtE: ast.Lt}

class Mutate(ast.NodeTransformer):
    """Mutate exactly the n-th comparison or constant in the tree."""
    def __init__(self, target):
        self.target, self.seen, self.desc = target, -1, None
    def visit_Compare(self, node):
        self.generic_visit(node)
        op = type(node.ops[0])
        if op in SWAPS:
            self.seen += 1
            if self.seen == self.target:
                node.ops[0] = SWAPS[op]()
                self.desc = f"{op.__name__} -> {SWAPS[op].__name__}"
        return node
    def visit_Constant(self, node):
        if isinstance(node.value, int):
            self.seen += 1
            if self.seen == self.target:
                self.desc = f"{node.value} -> {node.value + 1}"
                return ast.copy_location(ast.Constant(node.value + 1), node)
        return node

def mutants():
    i = 0
    while True:
        m = Mutate(i)
        tree = ast.fix_missing_locations(m.visit(ast.parse(SOURCE)))
        if m.desc is None:
            return
        ns = {}
        exec(compile(tree, "<mutant>", "exec"), ns)
        yield m.desc, ns["shipping_fee"]
        i += 1

for name, tests in [("weak", weak_tests), ("strong", strong_tests)]:
    survived = [d for d, fn in mutants() if tests(fn)]
    total = sum(1 for _ in mutants())
    print(f"{name}: killed {total - len(survived)}/{total}, survivors: {survived}")
```

The weak suite lets `>=` -> `>` and `50` -> `51` survive: nothing checks the boundary at exactly 50. The strong suite kills every mutant.

Running a real tool on a Python project (check the tool's docs for the current CLI and config):

```
pip install mutmut
mutmut run          # mutates code under the configured paths and runs the tests per mutant
mutmut results      # list survivors, then inspect each one and add an assertion or mark it equivalent
```

## Trade-offs
- **Insight vs cost:** each mutant reruns (part of) the suite, so total time scales with mutants times test time. Mitigate with per-line test selection, incremental runs on diffs and parallelism.
- **Score as a gate vs as a guide:** a hard threshold invites tests that kill mutants without asserting meaningful behavior; using survivors in review keeps attention on real gaps.
- **Operator sets:** more operators find more gaps but produce more equivalent and low-value mutants to triage.
- **Mutation vs coverage:** coverage is cheap and shows what is not executed; mutation is expensive and shows what is not verified. Use coverage first, mutation where it matters.
- **Mutation vs property-based tests:** properties ([[property-based-and-fuzz-testing]]) generate inputs; mutation evaluates whether any test notices wrong outputs. They complement each other.

## Gotchas
- Equivalent mutants are not test failures; do not write contorted tests to kill them, mark them as ignored.
- Tests that only check "no exception" or "returns something" kill almost nothing; assert values.
- Flaky tests make mutants look killed at random; quarantine them before measuring.
- Mutating logging, `__repr__` or debug code produces noise; configure exclusions.
- Running the whole suite per mutant is the slow path; make sure the tool maps lines to the tests that cover them.
- Snapshot tests that are regenerated automatically can kill mutants without anyone checking the new output is right ([[snapshot-and-golden-testing]]).
- Long-running or infinite-loop mutants need a timeout; set it relative to normal test time.

## Related
- [[testing-strategy-and-pyramid]] - where mutation testing fits next to coverage and other tiers
- [[unit-testing-and-test-doubles]] - writing the assertions that kill mutants
- [[tdd-and-bdd]] - test-first code tends to score higher because every behavior had a failing test
- [[property-based-and-fuzz-testing]] - complementary: generated inputs vs injected faults
- [[flaky-tests]] - fix nondeterminism before trusting mutation results
- [[ci-cd-pipelines]] - running mutation on diffs or nightly instead of every commit

## References
- DeMillo, Lipton, Sayward, "Hints on Test Data Selection" (1978)
- Jia and Harman, "An Analysis and Survey of the Development of Mutation Testing" (IEEE TSE, 2011)
- Petrovic and Ivankovic, "State of Mutation Testing at Google" (ICSE-SEIP 2018)
- Tool docs: mutmut, PIT, Stryker
