"""Self-test for build_index.problems: one bad fixture per validation rule.

Run:  python test_build_index.py   (stdlib only, also in CI)
"""
from build_index import SECTIONS, problems

GOOD = """---
title: Example
category: design
tags: [a]
use_cases:
  - do a thing
status: draft
last_verified: 2026-10-10
sources:
  - https://example.com
---

# Example
""" + "".join(f"\n## {s}\ntext\n" for s in SECTIONS)


def bad(old, new):
    assert old in GOOD, old
    return GOOD.replace(old, new, 1)


CASES = {
    "no frontmatter": GOOD.split("---", 2)[2],
    "missing title": bad("title: Example\n", ""),
    "does not match folder": bad("category: design", "category: apis"),
    "not one of": bad("status: draft", "status: done"),
    "not a YYYY-MM-DD date": bad("last_verified: 2026-10-10", "last_verified: 2026-13-01"),
    "sources is empty": bad("sources:\n  - https://example.com\n", "sources:\n"),
    "use_cases is empty": bad("use_cases:\n  - do a thing\n", "use_cases: []\n"),
    "missing section ## Gotchas": bad("\n## Gotchas\n", "\n## Pitfalls\n"),
}

if __name__ == "__main__":
    assert problems("design/example.md", GOOD) == [], problems("design/example.md", GOOD)
    for expected, text in CASES.items():
        errs = problems("design/example.md", text)
        assert any(expected in e for e in errs), f"{expected!r} not reported, got {errs}"
    print(f"build_index self-test: {len(CASES)} bad fixtures rejected, good fixture accepted")
