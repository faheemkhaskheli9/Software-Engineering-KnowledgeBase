---
title: Release versioning and changelogs
category: practices
tags: [semver, calver, conventional-commits, changelog, release-notes, versioning, release-process, pep-440]
use_cases:
  - "decide between semantic versioning and calendar versioning for our product"
  - "generate the next version number and changelog automatically from commits"
  - "write release notes users actually read"
  - "compare and sort version strings correctly, including pre-releases"
status: draft
last_verified: 2026-10-24
sources:
  - https://semver.org/spec/v2.0.0.html
  - https://calver.org/
  - https://www.conventionalcommits.org/en/v1.0.0/
  - https://keepachangelog.com/en/1.1.0/
  - https://packaging.python.org/en/latest/specifications/version-specifiers/
---

# Release versioning and changelogs

## Summary
A version number is a message to users about what changed and whether
upgrading is safe. Semantic versioning (MAJOR.MINOR.PATCH) encodes
compatibility and suits libraries and APIs; calendar versioning encodes when
and suits applications and fast-moving products. Pair either with a
human-written changelog grouped by change type, and automate the bump from
structured commit messages so releases are cheap and consistent.

## Key concepts
- **SemVer 2.0.0**: given a declared public API, increment MAJOR for incompatible changes, MINOR for backwards-compatible features, PATCH for backwards-compatible fixes. Versions `0.y.z` are initial development: anything may change.
- **Pre-release and build metadata**: `1.4.0-rc.1` sorts before `1.4.0`; pre-release identifiers compare dot-separated, numeric parts numerically and below alphanumeric parts. `+build.5` metadata is ignored for precedence.
- **CalVer**: version from the date, e.g. `YYYY.MM.MICRO` (pip `24.2`) or `YY.MM` (Ubuntu `24.04`). Says how old a release is, not whether it breaks you.
- **Conventional Commits 1.0.0**: `type(scope)!: description`. `fix` maps to PATCH, `feat` to MINOR, and `!` or a `BREAKING CHANGE:` footer to MAJOR; other types (`docs`, `chore`, `refactor`) do not trigger a release by themselves.
- **Keep a Changelog**: newest first, an `Unreleased` section, and entries grouped as Added, Changed, Deprecated, Removed, Fixed, Security, each release dated in ISO 8601.
- **Ecosystem rules**: some package managers have their own version grammar (Python's PEP 440, used by pip, writes `1.4.0rc1`); follow it for the packages you publish.

## When to use / scenarios
- Library, SDK or public API that others pin: SemVer, because dependents rely on MAJOR bumps to signal breaks ([[library-api-design]], [[api-versioning-and-evolution]]).
- Continuously deployed service or app with no external compile-time dependents: CalVer or just a build number; compatibility is handled by API versioning, not the app version.
- Team wants releases on every merge: Conventional Commits plus a release tool computes the version and changelog in CI ([[ci-cd-pipelines]]).
- Not a replacement for deprecation notices and migration guides on breaking changes.

## How it works / example
Compute the next SemVer version from commit messages and sort versions with
pre-release precedence:

```python
import re

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
COMMIT = re.compile(r"^(\w+)(?:\([^)]*\))?(!)?: ")

def parse(v):
    m = SEMVER.match(v)
    if not m:
        raise ValueError(f"not semver: {v}")
    major, minor, patch, pre = m.groups()
    return int(major), int(minor), int(patch), pre

def sort_key(v):
    major, minor, patch, pre = parse(v)
    if pre is None:
        return (major, minor, patch, 1, ())  # a release sorts after its pre-releases
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, ids)

def bump(current, commits):
    major, minor, patch, _ = parse(current)
    level = None
    for msg in commits:
        m = COMMIT.match(msg)
        if not m:
            continue
        if m.group(2) or "\nBREAKING CHANGE:" in msg:
            level = "major"
        elif m.group(1) == "feat" and level != "major":
            level = "minor"
        elif m.group(1) == "fix" and level is None:
            level = "patch"
    if level is None:
        return current  # nothing releasable
    if level == "major" and major > 0:  # in 0.y.z a breaking change bumps minor
        return f"{major + 1}.0.0"
    if level in ("major", "minor"):
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"

assert bump("1.4.2", ["fix(api): handle empty body", "docs: typo"]) == "1.4.3"
assert bump("1.4.2", ["feat: add export", "fix: off by one"]) == "1.5.0"
assert bump("1.4.2", ["feat!: drop v1 endpoints"]) == "2.0.0"
assert bump("0.9.1", ["refactor: x\n\nBREAKING CHANGE: config renamed"]) == "0.10.0"
assert bump("1.4.2", ["chore: deps"]) == "1.4.2"

versions = ["1.0.0", "1.0.0-rc.1", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta.11", "1.0.0-beta.2", "0.9.0"]
print(sorted(versions, key=sort_key))
assert sorted(versions, key=sort_key) == [
    "0.9.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
```

The `0.y.z` rule (a breaking change bumps MINOR) is a common release-tool
convention, not part of SemVer, which allows any change before 1.0.0.

Changelog entry in Keep a Changelog form:

```markdown
## [1.5.0] - 2026-10-24
### Added
- CSV export for reports.
### Fixed
- Off-by-one in pagination of `/orders`.
```

## Trade-offs
- **SemVer vs CalVer**: SemVer communicates compatibility but needs a defined public API and discipline; CalVer is effortless and communicates age, but every upgrade needs reading notes.
- **Generated vs written changelog**: generated from commits is complete and free but reads like a log; curated notes are useful to users but cost time. A common middle ground: generate, then edit the highlights.
- **Release per merge vs batched releases**: per merge gives small, easy-to-bisect releases; batches suit products with app-store reviews or customer change windows.

## Gotchas
- Hyrum's law: with enough users, any observable behaviour is depended on, so "just a fix" can break someone; call out behaviour changes even in PATCH releases.
- Sorting versions as strings puts `1.10.0` before `1.9.0`; parse them.
- Marking a breaking change as MINOR erodes trust in the scheme; consumers then pin exactly and stop taking fixes.
- Re-using or moving a published version tag breaks caches and reproducible builds; publish a new version instead.
- Squash merges keep only the PR title, so enforce the commit convention on PR titles.

## Related
- [[library-api-design]] - what counts as the public API that SemVer protects.
- [[api-versioning-and-evolution]] - versioning network APIs, deprecation and sunset headers.
- [[git-workflows-and-branching]] - tags, release branches and trunk-based releases.
- [[ci-cd-pipelines]] - automating the bump, tag and publish steps.
- [[software-supply-chain-security]] - signing and provenance for published releases.

## References
- Semantic Versioning 2.0.0: https://semver.org/spec/v2.0.0.html
- Calendar Versioning: https://calver.org/
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- Keep a Changelog 1.1.0: https://keepachangelog.com/en/1.1.0/
- Python Packaging, Version specifiers (PEP 440): https://packaging.python.org/en/latest/specifications/version-specifiers/
