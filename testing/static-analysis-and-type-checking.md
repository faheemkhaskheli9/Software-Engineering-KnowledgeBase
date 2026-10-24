---
title: Static analysis, linting and type checking
category: testing
tags: [static-analysis, linting, type-checking, mypy, pyright, ruff, sast, semgrep, codeql, pre-commit, gradual-typing]
use_cases:
  - "catch bugs such as None handling, typos and wrong argument types before tests or code review"
  - "add a linter and type checker to a large legacy codebase without fixing thousands of warnings first"
  - "write a custom lint rule that bans a dangerous pattern across the codebase"
  - "decide which static checks run in pre-commit, which in CI and which block a merge"
  - "add security static analysis (SAST) to the pipeline without drowning the team in false positives"
status: draft
last_verified: 2026-10-24
sources:
  - https://abseil.io/resources/swe-book/html/ch20.html
  - https://doi.org/10.1145/3188720
  - https://doi.org/10.1145/1646353.1646374
  - https://peps.python.org/pep-0484/
  - https://mypy.readthedocs.io/en/stable/
  - https://docs.astral.sh/ruff/
  - https://docs.python.org/3/library/ast.html
  - https://semgrep.dev/docs/
  - https://codeql.github.com/docs/
  - https://pre-commit.com/
---

# Static analysis, linting and type checking

## Summary
Static analysis examines source code without running it to find bugs, style
violations, security issues and type errors. It ranges from formatters and
linters (fast, local, pattern-based) through type checkers (whole-program
reasoning about values) to security-focused SAST tools that track data from
untrusted sources to dangerous sinks. It complements tests: a test checks the
paths you thought of, a static check rejects a class of mistake on every path,
including code no test executes.

## Key concepts
- **Formatter**: rewrites code into one canonical layout (black, `ruff format`,
  gofmt, Prettier). Removes style debate; not a correctness tool.
- **Linter**: syntax-tree or token rules for likely bugs and smells (unused
  variable, mutable default argument, bare `except`, shadowed builtin). Ruff,
  pylint, flake8, ESLint, golangci-lint.
- **Type checker**: verifies that values flow only into places that accept
  them. Python uses *gradual typing* (PEP 484): annotations are optional and
  unannotated code is treated as `Any`, so strictness can be raised module by
  module. mypy and pyright are the common checkers.
- **SAST and dataflow analysis**: rules that follow data from a source
  (request parameter) to a sink (SQL string, shell command, template) through
  assignments and calls. Semgrep (pattern rules, optional taint mode) and CodeQL
  (queries over a code database) are examples; they feed [[owasp-top-10]]
  reviews.
- **Soundness vs precision**: no analysis is both complete and free of false
  positives for every program. Practical tools accept some false negatives to
  keep false positives low. Google's experience (Sadowski et al.) is that
  developers ignore tools whose findings they do not trust.
- **Baseline and ratchet**: record existing findings once and fail only on new
  ones, then reduce the baseline over time. This is how a check is adopted on a
  large legacy codebase.
- **Where checks run**: in the editor (instant), pre-commit hooks (seconds),
  CI on every change (the enforcing gate), and code review bots that comment on
  the diff only.
- **Suppressions**: inline ignores (`# noqa: B006`, `# type: ignore[arg-type]`)
  with a code and ideally a reason; a blanket ignore hides future findings too.

## When to use / scenarios
- Every codebase: a formatter and a linter with a small, agreed rule set,
  enforced in CI, from day one ([[ci-cd-pipelines]]).
- Python or TypeScript code shared by several people or living for years:
  add a type checker; annotate public interfaces first, since types on
  signatures are machine-checked documentation ([[library-api-design]]).
- A recurring bug class shows up in postmortems or reviews (a forbidden API, a
  missing `await`, string-built SQL): encode it as a custom rule so it cannot
  come back.
- Security-sensitive code: add SAST alongside dependency and secret scanning
  ([[software-supply-chain-security]], [[secrets-management]]).
- Architectural rules (no imports from another module's internals) are also
  static checks ([[modular-monolith]]).
- When NOT to rely on it: behaviour, business rules, performance and
  integration with real systems still need tests
  ([[testing-strategy-and-pyramid]]). Do not switch on every available rule at
  once; noisy rules train people to ignore or suppress all findings.

## How it works / example
Most linters parse the file into an abstract syntax tree and visit nodes. A
custom rule with the standard-library `ast` module that flags two classic
Python bugs, mutable default arguments and bare `except:`, and supports a
baseline so only new findings fail:

```python
import ast

RULES = {
    "B001": "mutable default argument (shared between calls)",
    "B002": "bare except also catches KeyboardInterrupt and SystemExit",
}

class Checker(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename, self.findings = filename, []

    def report(self, node, code):
        self.findings.append((self.filename, node.lineno, code))

    def visit_FunctionDef(self, node):
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.report(default, "B001")
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.report(node, "B002")
        self.generic_visit(node)

def lint(filename, source):
    checker = Checker(filename)
    checker.visit(ast.parse(source, filename))
    lines = source.splitlines()
    # honour inline suppressions such as "# noqa: B001"
    return [f for f in checker.findings if f"noqa: {f[2]}" not in lines[f[1] - 1]]

legacy = '''
def add_item(item, bucket=[]):
    bucket.append(item)
    return bucket

def load(path):
    try:
        return open(path).read()
    except:
        return None
'''
changed = legacy + '''
def tags(names, seen={}):
    return seen

def cfg(opts=[]):  # noqa: B001 - read-only sentinel, never mutated
    return opts
'''

baseline = set(lint("app.py", legacy))                # recorded once, committed
assert {code for _, _, code in baseline} == {"B001", "B002"}

new = [f for f in lint("app.py", changed) if f not in baseline]
for filename, line, code in new:
    print(f"{filename}:{line}: {code} {RULES[code]}")
assert [code for _, _, code in new] == ["B001"]        # only the new `seen={}` fails
```

A baseline keyed by line number breaks when lines move; real tools key it by
rule, file and a fingerprint of the code. The same checks exist off the shelf
(Ruff's `B006` and `E722`), so a custom rule is worth it only for
project-specific patterns.

Type checking catches what a linter cannot, for example an `Optional` value
used without a check:

```python fragment
def find_user(user_id: int) -> "User | None": ...

def greet(user_id: int) -> str:
    user = find_user(user_id)
    return "Hello " + user.name     # mypy: Item "None" of "User | None" has no attribute "name"
```

A typical layered setup:

```
editor           : formatter on save, linter and type checker inline
pre-commit hook  : formatter, linter (changed files only, seconds)
CI on every PR   : linter, type checker (whole project), SAST, dependency audit
                   new findings fail the build; baseline shrinks over time
```

## Trade-offs
- **Strict vs gradual adoption**: full strictness from the start gives the most
  value on new code; on existing code start with lenient settings and per-module
  overrides, then tighten the modules people change most.
- **Fast pattern rules vs deep dataflow analysis**: pattern linters run in
  milliseconds and are easy to explain; taint and whole-program analysis find
  injection paths across functions but are slower and noisier, so they often
  run in CI only or nightly.
- **Pre-commit vs CI enforcement**: hooks give the fastest feedback but can be
  skipped and slow down commits; CI is authoritative. Use both with the same
  configuration and pinned tool versions.
- **Off-the-shelf vs custom rules**: maintained rules are free and well tested;
  custom rules encode your own past incidents but need tests and an owner.
- **Blocking vs advisory findings**: blocking keeps the main branch clean;
  advisory rules can be trialled to measure false-positive rates before they
  block anyone.

## Gotchas
- Turning on a new check across the whole repository and failing every build
  on thousands of old findings; people add a blanket ignore and the check never
  recovers. Use a baseline.
- Unpinned tool versions: a linter release adds rules or changes inference and
  CI breaks on unrelated changes. Pin versions and upgrade deliberately.
- `Any` leaks: one unannotated function or untyped library makes everything
  downstream unchecked while the type checker reports success. Track type
  coverage or enable warnings for implicit `Any` on important modules.
- `# type: ignore` and `# noqa` without codes hide new, unrelated errors on the
  same line.
- Treating a clean SAST run as "secure": tools miss logic flaws, authorization
  bugs and anything outside their rules ([[threat-modeling]] still applies).
- Checking only changed lines lets a change break an untouched caller; type
  checking needs the whole program even when linting can be diff-scoped.
- Different configurations in editor, hook and CI produce "passes locally,
  fails in CI"; keep one config file in the repository.

## Related
- [[testing-strategy-and-pyramid]] - static checks are the cheapest layer under the test pyramid.
- [[ci-cd-pipelines]] - where checks become an enforced gate.
- [[clean-code-and-naming]] - formatter and linter replace style debates.
- [[code-review]] - push mechanical findings to tools so reviewers focus on design.
- [[refactoring-and-code-smells]] - linters and complexity checks point at smells.
- [[owasp-top-10]] - SAST rules map to injection and other web vulnerability classes.
- [[software-supply-chain-security]] - dependency and artifact checks that sit beside SAST.
- [[modular-monolith]] - import rules as a static architecture check.
- [[mutation-testing]] - the dynamic counterpart for judging test quality.

## References
- Titus Winters, Tom Manshreck and Hyrum Wright (eds.), *Software Engineering at Google*, O'Reilly, 2020, ch. 20 "Static Analysis": https://abseil.io/resources/swe-book/html/ch20.html
- Caitlin Sadowski et al., "Lessons from Building Static Analysis Tools at Google", *Communications of the ACM* 61(4), 2018: https://doi.org/10.1145/3188720
- Al Bessey et al., "A Few Billion Lines of Code Later: Using Static Analysis to Find Bugs in the Real World", *Communications of the ACM* 53(2), 2010: https://doi.org/10.1145/1646353.1646374
- PEP 484, Type Hints: https://peps.python.org/pep-0484/
- mypy documentation: https://mypy.readthedocs.io/en/stable/
- Ruff documentation: https://docs.astral.sh/ruff/
- Python `ast` module: https://docs.python.org/3/library/ast.html
- Semgrep documentation: https://semgrep.dev/docs/
- CodeQL documentation: https://codeql.github.com/docs/
- pre-commit: https://pre-commit.com/
