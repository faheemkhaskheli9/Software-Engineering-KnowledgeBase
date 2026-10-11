"""Self-test for build_index.problems: one bad fixture per validation rule.

Run:  python test_build_index.py   (stdlib only, also in CI)
"""
import tempfile
from pathlib import Path

from build_index import SECTIONS, md_link_errors, problems

FILLER = "One sentence of filler text that is long enough to pass the minimum word count check."
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
""" + "".join(f"\n## {s}\n{FILLER} [[example]]\n" for s in SECTIONS)


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
    "thin section ## Trade-offs": bad(f"## Trade-offs\n{FILLER}", "## Trade-offs\nToo short."),
    "## Related has no [[links]]": bad(f"## Related\n{FILLER} [[example]]", f"## Related\n{FILLER}"),
}

if __name__ == "__main__":
    assert problems("design/example.md", GOOD) == [], problems("design/example.md", GOOD)
    for expected, text in CASES.items():
        errs = problems("design/example.md", text)
        assert any(expected in e for e in errs), f"{expected!r} not reported, got {errs}"
    print(f"build_index self-test: {len(CASES)} bad fixtures rejected, good fixture accepted")

    with tempfile.TemporaryDirectory() as tmp:  # relative Markdown links and anchors
        (Path(tmp) / "data").mkdir()
        (Path(tmp) / "data" / "foo.md").write_text("# Foo\n\n## Write-ahead log (WAL)\n", encoding="utf-8")
        page = Path(tmp) / "README.md"
        ok = "[a](data/foo.md) [b](data/foo.md#write-ahead-log-wal) [c](#top) [d](https://x.org/y.md)"
        assert md_link_errors(page, f"# Top\n{ok}\n") == [], md_link_errors(page, f"# Top\n{ok}\n")
        broken = "[a](data/bar.md) [b](data/foo.md#nope) [c](#missing) `[d](skipped.md)`"
        errs = md_link_errors(page, f"# Top\n{broken}\n")
        assert errs == ["data/bar.md (no such file)", "data/foo.md#nope (no such anchor)",
                        "#missing (no such anchor)"], errs
    print("build_index self-test: broken relative links and anchors rejected")
