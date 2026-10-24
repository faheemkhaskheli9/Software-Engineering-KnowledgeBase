---
title: Git workflows and branching
category: practices
tags: [git, branching, trunk-based-development, gitflow, github-flow, merge, rebase, release]
use_cases:
  - "pick a branching strategy for a team of 5-30 engineers shipping a web service continuously"
  - "set up a release process for a mobile app or library with multiple supported versions"
  - "decide between merge commits, squash merges and rebase for our main branch"
  - "stop long-lived feature branches from causing painful merges"
  - "write a commit message and PR convention so the history is usable for bisect and changelogs"
status: draft
last_verified: 2026-10-10
sources:
  - https://trunkbaseddevelopment.com/
  - https://nvie.com/posts/a-successful-git-branching-model/
  - https://docs.github.com/en/get-started/using-github/github-flow
  - https://git-scm.com/book/en/v2
  - https://www.conventionalcommits.org/en/v1.0.0/
  - "Accelerate (Forsgren, Humble, Kim), 2018"
---

# Git workflows and branching

## Summary
A branching workflow is the team agreement on where work happens, how it gets
to the shared mainline, and how releases are cut. The main spectrum runs from
trunk-based development (tiny branches, merge to main daily, feature flags)
to Gitflow (long-lived develop and release branches). Pick the lightest
workflow that matches how you actually release; integration pain grows with
branch lifetime.

## Key concepts
- **Branch lifetime is the cost driver.** Merge conflicts, stale CI results and
  hidden integration bugs scale with how long a branch lives and how far it
  diverges, not with the workflow's name.
- **Trunk-based development (TBD):** everyone commits to `main` (or via
  short-lived branches under about a day or two). Incomplete work hides behind
  feature flags. DORA research (Accelerate) correlates TBD with higher delivery
  performance.
- **GitHub flow:** `main` is always deployable; branch from main, open a PR,
  review, merge, deploy. Effectively TBD with PR-based review.
- **Gitflow:** `main` + `develop` + `feature/*` + `release/*` + `hotfix/*`.
  Designed for versioned, scheduled releases and multiple supported versions.
  Heavy for continuous deployment.
- **Release branches / tags:** cut `release/1.4` from main when you must
  stabilise or patch an old version; otherwise tag commits on main.
- **Merge strategies:** merge commit (preserves branch shape), squash (one
  commit per PR, clean history), rebase-and-merge (linear, keeps each commit).
- **Rebase vs merge when syncing:** rebase *your own unpushed/private* branch
  onto main for a linear history; never rewrite history others have based work on.
- **Conventional Commits:** `feat:`, `fix:`, `feat!:` prefixes enable automated
  changelogs and semantic-version bumps.

## When to use / scenarios
- **Web service / SaaS deployed several times a day:** trunk-based or GitHub
  flow, feature flags for unfinished work, squash merge, CI gate on every PR.
- **Library or app with versioned releases and old versions to patch:** main
  plus `release/x.y` branches, cherry-pick fixes back ("backport"). Full Gitflow
  only if you truly have scheduled multi-week stabilisation.
- **Small team / solo:** commit to main with CI, or tiny branches. Do not
  import process you do not need.
- **Regulated environments needing approvals:** GitHub flow plus protected
  branches, required reviews, signed commits and environment approvals.
- **Avoid Gitflow** when you deploy continuously: `develop` becomes a second,
  lagging trunk and releases become ceremonies.
- **Monorepo at large scale:** TBD with strong CI, code owners and affected-only
  builds; long-lived branches do not survive hundreds of committers.

## How it works / example

```
Trunk-based / GitHub flow
 main  --o--o--o--o--o--o--o--o-->  (always releasable, deploy from here)
          \  /    \   /
           o       o        short-lived branches (hours to 2 days), PR + CI

Gitflow
 main     --o-------------------o--------o-->   tagged releases only
             \                 /        /
 release       \          o--o-         /        stabilise, bug fixes only
                \        /             /
 develop  --o--o--o--o--o--o--o--o--o--o-->      integration branch
              \  /   \     /
 feature        o     o--o                        long-lived features
```

Minimal daily loop (GitHub flow):

```bash
git switch main && git pull --ff-only
git switch -c fix/login-timeout          # branch name: type/short-slug
# ... small commits ...
git fetch origin && git rebase origin/main   # private branch only
git push -u origin fix/login-timeout
# open PR -> CI + review -> squash merge -> delete branch -> deploy
```

Backporting a fix to a release branch:

```bash
git switch release/1.4
git cherry-pick -x <sha-from-main>       # -x records the original commit
```

Feature flag skeleton so unfinished code can merge to main:

```python
def checkout(cart, flags):
    if flags.enabled("new-pricing-engine", user=cart.user_id):
        return new_pricing(cart)
    return legacy_pricing(cart)
```

Branch protection checklist for `main`: require PR, require passing CI,
require at least one approval (see [[code-review]]), block force-push, require
linear history if you squash, enforce CODEOWNERS for sensitive paths.

Commit message format that stays useful for years:

```
fix(auth): refresh token before expiry check

The expiry check ran before refresh, so a token valid for <5s was rejected.
Refresh first, then validate. Adds regression test.

Refs: #482
```
Subject in imperative mood, about 50 chars; body explains *why*, not what.

## Trade-offs
- **Squash vs rebase-merge vs merge commit.** Squash gives a clean, revertable
  unit per PR but loses internal commit granularity; merge commits keep context
  but clutter `git log`; rebase-merge keeps every commit, so every commit must
  build and pass tests (needed for `git bisect`).
- **Feature flags vs long branches.** Flags let you integrate daily but add
  flag debt and combinatorial test states; remove flags promptly (track them
  like [[technical-debt-management]] items).
- **Release branches vs tag-on-main.** Branches support parallel versions but
  double the fix-forward work (backports). If you only ever ship the newest
  version, skip them.
- **Monorepo vs polyrepo** changes the answer: monorepo favours TBD and a single
  version; polyrepo favours per-repo release branches and versioned dependencies.
- **Strict rules vs velocity.** Mandatory two approvals and linear history
  increase safety and friction. Scale the rules with risk, not with habit.

## Gotchas
- `git push --force` on a shared branch destroys teammates' work; use
  `--force-with-lease` and only on your own branch.
- Rebasing a branch that others have pulled forces everyone to repair history.
- Squash-merging a branch, then continuing to work on that same branch, causes
  phantom conflicts (git no longer sees the commits as merged). Branch fresh from main.
- Long-lived `develop` branches in Gitflow drift; hotfixes must be merged to
  both `main` and `develop` or the fix regresses.
- Huge PRs defeat review quality; keep them small (a few hundred changed lines
  is a common rule of thumb, an assumption not a law).
- Committing secrets: removing the file in a later commit does not remove it
  from history. Rotate the secret (see [[secrets-management]]) and treat it as leaked.
- Not deleting merged branches leaves hundreds of stale refs; enable
  auto-delete on merge.
- Large binaries in git bloat clones; use Git LFS or object storage.
- Timestamps and authorship from a misconfigured `user.email` break attribution.
- A flaky CI makes people bypass branch protection; fix flakiness instead of
  granting admin overrides (see [[ci-cd-pipelines]]).

## Related
- [[code-review]] - the PR gate that sits inside every workflow
- [[ci-cd-pipelines]] - automation that makes short-lived branches safe
- [[deployment-strategies]] - feature flags, canaries and releases decouple deploy from release
- [[technical-debt-management]] - stale flags and long branches are debt
- [[testing-strategy-and-pyramid]] - fast tests are what let you merge to trunk daily
- [[agile-scrum-kanban]] - delivery cadence that the branching model should match
- [[release-versioning-and-changelogs]] - version numbers, tags and changelogs for each release
- [[monorepo-vs-polyrepo]] - repository layout that shapes the branching and release answer.

## References
- Trunk Based Development: https://trunkbaseddevelopment.com/
- Vincent Driessen, "A successful Git branching model" (author notes later
  that it is unsuitable for continuous delivery): https://nvie.com/posts/a-successful-git-branching-model/
- GitHub flow: https://docs.github.com/en/get-started/using-github/github-flow
- Pro Git book: https://git-scm.com/book/en/v2
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- Forsgren, Humble, Kim, *Accelerate* (2018)
