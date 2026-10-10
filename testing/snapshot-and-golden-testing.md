---
title: Snapshot and golden-file testing
category: testing
tags: [snapshot-testing, golden-files, approval-testing, characterization-tests, regression-testing, syrupy, jest-snapshots]
use_cases:
  - "lock down the current output of legacy code before refactoring it"
  - "test a report, invoice PDF text, HTML email or CLI output without hand-writing every assertion"
  - "detect unintended changes in a generated config, SQL or serialized API response"
  - "review output changes in a pull request as a readable diff"
  - "stop a snapshot suite from becoming a rubber stamp that everyone regenerates"
status: draft
last_verified: 2026-10-10
sources:
  - "Working Effectively with Legacy Code, Michael Feathers (characterization tests)"
  - "Jest snapshot testing docs - https://jestjs.io/docs/snapshot-testing"
  - "syrupy, pytest snapshot plugin - https://github.com/syrupy-project/syrupy"
  - "ApprovalTests - https://approvaltests.com/"
  - "Go testing package and the testdata directory convention - https://pkg.go.dev/cmd/go"
---

# Snapshot and golden-file testing

## Summary
A snapshot (golden-file, approval) test runs code, serializes its output, and compares it to a stored reference that a human approved earlier. Any difference fails the test and shows a diff; if the change is intended, the reference is updated and reviewed like code. It is the fastest way to cover large or complex outputs and to pin legacy behavior before refactoring, and the easiest kind of test to turn into a rubber stamp.

## Key concepts
- **Golden file / snapshot:** the stored expected output, committed next to the tests (`testdata/`, `__snapshots__/`).
- **Approval testing:** the workflow of reviewing a "received" output and approving it to become the "approved" one (ApprovalTests, Llewellyn Falco).
- **Characterization test (Feathers):** a test that records what the code currently does, right or wrong, so a refactor can prove it changed nothing.
- **Update mode:** a flag or env var (`--snapshot-update`, `jest -u`, `UPDATE_GOLDEN=1`) that rewrites references instead of comparing.
- **Scrubbing / normalization:** replacing nondeterministic parts (timestamps, UUIDs, absolute paths, memory addresses, dict ordering) with stable placeholders before comparing.
- **Inline vs file snapshots:** inline snapshots live in the test source; file snapshots live in separate files and suit large outputs.
- **Diff quality:** stable, human-readable serialization (pretty JSON with sorted keys, one item per line) makes review possible.

## When to use / scenarios
- Outputs that are large and structured: rendered templates, emails, reports, CLI help text, generated code, compiler or linter output, serialized API responses.
- Legacy code with no tests, before refactoring: characterize first, then change structure.
- Visual or document regressions (screenshots, PDFs) with specialized tools that diff images or extracted text.
- NOT for logic with a few clear expected values; an explicit assertion documents intent better ([[unit-testing-and-test-doubles]]).
- NOT for output dominated by nondeterminism that cannot be scrubbed, or that legitimately changes on every release (snapshots then just get regenerated).
- NOT as a substitute for verifying correctness: a snapshot proves "unchanged", not "right". Review the first snapshot as carefully as hand-written expectations.

## How it works / example

Workflow:

```
first run / update mode:  output -> scrub -> write golden file -> human reviews the file in the PR
normal run:               output -> scrub -> compare with golden file
                          equal   -> pass
                          differs -> fail with a unified diff; fix the code, or update + review
```

A minimal golden-file helper with scrubbing, stdlib only (runs in a temp directory):

```python
import difflib
import json
import os
import re
import tempfile
from pathlib import Path

def scrub(text):
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?", "<TIMESTAMP>", text)
    return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<UUID>", text)

def assert_golden(name, value, golden_dir, update=False):
    actual = scrub(json.dumps(value, indent=2, sort_keys=True)) + "\n"   # stable serialization
    path = Path(golden_dir) / f"{name}.golden.json"
    if update or not path.exists():
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True),
                                            "golden", "actual"))
        raise AssertionError(f"{name} changed:\n{diff}")

def render_invoice(total, created):
    return {"id": "3f2b8c1e-9a4d-4e2f-8b7a-1c2d3e4f5a6b", "created": created,
            "lines": [{"sku": "A1", "qty": 2}], "total": total}

with tempfile.TemporaryDirectory() as d:
    update = os.environ.get("UPDATE_GOLDEN") == "1"
    assert_golden("invoice", render_invoice(20, "2026-01-01T10:00:00Z"), d, update)  # records
    assert_golden("invoice", render_invoice(20, "2026-05-09T08:30:00Z"), d)          # timestamp scrubbed: passes
    try:
        assert_golden("invoice", render_invoice(25, "2026-05-09T08:30:00Z"), d)      # real change
    except AssertionError as e:
        print(e)                                  # diff shows: -  "total": 20 / +  "total": 25
```

With pytest, the `syrupy` plugin provides a `snapshot` fixture (`assert result == snapshot`) and `--snapshot-update`; Jest has `toMatchSnapshot()` and `-u`. Check each tool's docs for current flags.

## Trade-offs
- **Coverage per line of test vs intent:** one snapshot covers a lot of output cheaply, but does not say which parts matter; explicit assertions say exactly what is required.
- **Broad vs targeted snapshots:** snapshotting a whole page catches everything and fails on every unrelated change; snapshotting the relevant fragment fails less often and gets reviewed more carefully.
- **File vs inline:** files handle big outputs and binary formats; inline keeps small expectations next to the test for easy reading.
- **Strict vs normalized comparison:** strict catches every change including whitespace; normalization reduces noise but can hide meaningful differences if too aggressive.
- **Characterization vs specification:** characterization tests pin current (possibly buggy) behavior; replace them with intent-revealing tests once the refactor is done.

## Gotchas
- "Update all snapshots" without reading the diff turns the suite into a rubber stamp; require snapshot diffs to be reviewed in PRs like code.
- Unscrubbed timestamps, random IDs, absolute paths, locale formatting, and unordered sets/dicts make snapshots fail on every run or machine.
- Line endings: a golden file checked out with CRLF on Windows fails against LF output; write with explicit newlines and set `.gitattributes`.
- Obsolete snapshots accumulate when tests are renamed or deleted; use the tool's "unused snapshot" check.
- Huge snapshots nobody reads hide regressions in plain sight.
- Snapshotting floating-point output without rounding fails across platforms.
- Snapshot tests that pass on first run (because they wrote the file) prove nothing in CI; make CI fail when a golden file is missing instead of creating it.

## Related
- [[testing-strategy-and-pyramid]] - where output-level regression tests fit
- [[refactoring-and-code-smells]] - characterization tests as a safety net for refactors
- [[unit-testing-and-test-doubles]] - explicit assertions when expectations are small
- [[integration-and-contract-testing]] - contract tests for API shapes instead of raw response snapshots
- [[test-data-management]] - stable fixtures make outputs reproducible
- [[flaky-tests]] - nondeterministic output is a common source of flakiness
- [[mutation-testing]] - why auto-regenerated snapshots give false confidence

## References
- Feathers, "Working Effectively with Legacy Code", characterization tests
- Jest docs, "Snapshot Testing"
- syrupy (pytest) documentation
- ApprovalTests project
- Go `cmd/go` docs, the `testdata` directory convention used for golden files
