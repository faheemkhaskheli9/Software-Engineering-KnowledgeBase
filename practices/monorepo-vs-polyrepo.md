---
title: Monorepo vs polyrepo
category: practices
tags: [monorepo, polyrepo, repository-structure, affected-builds, build-graph, bazel, nx, workspaces, codeowners, sparse-checkout, dependency-management, large-scale-changes]
use_cases:
  - "decide whether a growing set of services and libraries should live in one repository or many"
  - "CI in our monorepo runs every test on every pull request and takes an hour"
  - "a shared library change needs coordinated pull requests across a dozen repositories"
  - "services pin different versions of an internal package and drift apart"
  - "assign ownership and required reviewers per directory in one large repository"
status: draft
last_verified: 2026-10-24
sources:
  - https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/
  - https://abseil.io/resources/swe-book
  - https://monorepo.tools/
  - https://bazel.build/basics/dependencies
  - https://docs.npmjs.com/cli/using-npm/workspaces
  - https://git-scm.com/docs/git-sparse-checkout
  - https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
---

# Monorepo vs polyrepo

## Summary
A monorepo keeps many projects (services, libraries, apps) in one version
control repository with one history; a polyrepo gives each project its own
repository and shares code through versioned packages. The choice is less about
storage than about how changes cross project boundaries: a monorepo makes an
atomic change across producer and all consumers possible and keeps one version
of everything, but needs build tooling that only rebuilds what a change
affects, plus ownership rules per directory. A polyrepo gives strong isolation
and simple per-repo tooling, at the cost of version skew and multi-repo
coordination. Repository layout is independent of deployment: a monorepo can
hold many independently deployed services.

## Key concepts
- **Monorepo**: many projects, one repository, usually one version of each
  internal library at any commit ("one-version rule"). Not the same as a
  monolith ([[monolith-vs-microservices]]).
- **Polyrepo (multi-repo)**: one repository per project; internal code shared
  as published, versioned artifacts (packages, images, generated clients).
- **Build graph**: explicit dependencies between targets (Bazel `BUILD` files,
  Nx/Turborepo project graph, package manager workspaces). It drives which
  targets a change affects and the order to build them.
- **Affected (change-based) builds**: map changed files to owning targets, then
  rebuild and test those plus everything that depends on them, transitively.
- **Remote caching and hermetic builds**: if a target's inputs are unchanged,
  reuse its output from a shared cache instead of rebuilding; correct only when
  builds are hermetic (declared inputs only).
- **Atomic / large-scale change**: one commit updates an API and all its callers;
  at very large scale such changes are split into many independently reviewed
  pieces by tooling (Software Engineering at Google, ch. 22).
- **Version skew and diamond dependencies**: in polyrepos, services pin
  different versions of a shared library; two dependencies needing
  incompatible versions of a third is the diamond problem.
- **Ownership**: `CODEOWNERS` (GitHub, GitLab) maps paths to required reviewers
  so a large repository still has clear owners.
- **Scaling Git**: partial clone, sparse checkout and file-system monitors keep
  clones and status fast when the repository is large.

## When to use / scenarios
- Monorepo signals: several services and libraries changed together often;
  one team or a few closely cooperating teams; shared tooling, linting and
  dependency versions are wanted; frequent cross-cutting refactors; a
  front-end and back-end that share types or generated clients.
- Polyrepo signals: independent teams or companies with separate release
  cycles; open-source components published to outside users; strict access
  separation (contractors, regulated code); very different toolchains with
  little shared code.
- Hybrid is common: one monorepo per product or domain, separate repositories
  for open-source libraries and infrastructure modules.
- When NOT to move to a monorepo: you have no plan for affected-only CI and
  caching (every PR would run everything), or you need hard per-project access
  control that your Git host cannot enforce per path.

## How it works / example
Typical monorepo layout:

```
repo/
  apps/web/            (front-end, depends on libs/ui, libs/api-client)
  services/orders/     (deploys alone, depends on libs/db, libs/auth)
  services/billing/    (deploys alone, depends on libs/db)
  libs/{ui,api-client,db,auth}/
  tools/               (lint, codegen, release scripts)
  CODEOWNERS           (services/billing/ @payments-team ...)
```

Change detection: map changed files to projects, add every project that
depends on them, then build in dependency order. This is what Bazel, Nx,
Turborepo and path-filtered CI jobs do in essence.

```python
from graphlib import TopologicalSorter

# project -> projects it depends on
DEPS = {
    "libs/db": set(),
    "libs/auth": set(),
    "libs/ui": set(),
    "libs/api-client": {"libs/auth"},
    "services/orders": {"libs/db", "libs/auth"},
    "services/billing": {"libs/db"},
    "apps/web": {"libs/ui", "libs/api-client"},
}

def owner(path: str) -> str | None:
    """Longest project prefix that contains the file."""
    matches = [p for p in DEPS if path == p or path.startswith(p + "/")]
    return max(matches, key=len) if matches else None

def affected(changed_files: list[str]) -> list[str]:
    dependents = {p: set() for p in DEPS}
    for project, deps in DEPS.items():
        for d in deps:
            dependents[d].add(project)
    todo = {owner(f) for f in changed_files} - {None}
    if any(owner(f) is None for f in changed_files):
        return list(TopologicalSorter(DEPS).static_order())  # root config changed: build all
    seen = set()
    while todo:
        p = todo.pop()
        if p not in seen:
            seen.add(p)
            todo |= dependents[p]
    order = TopologicalSorter({p: DEPS[p] & seen for p in seen})
    return list(order.static_order())                     # dependencies before dependents

# A UI tweak only rebuilds the web app.
assert affected(["libs/ui/button.tsx"]) == ["libs/ui", "apps/web"]

# A database library change hits both services, never the web app.
plan = affected(["libs/db/pool.py"])
assert set(plan) == {"libs/db", "services/orders", "services/billing"}
assert plan[0] == "libs/db"

# An auth change ripples through the generated client to the web app.
plan = affected(["libs/auth/jwt.py"])
assert set(plan) == {"libs/auth", "libs/api-client", "apps/web", "services/orders"}
assert plan.index("libs/api-client") < plan.index("apps/web")

# A root file (lockfile, CI config) has no owner: build everything.
assert len(affected(["package-lock.json"])) == len(DEPS)
print("ok", plan)
```

Ownership per path with GitHub `CODEOWNERS` (last matching rule wins):

```
*                     @platform-team
/services/billing/    @payments-team
/libs/auth/           @security-team @platform-team
```

## Trade-offs
- **Atomic changes vs isolation**: a monorepo lets one pull request change an
  API and every caller with one CI run; a polyrepo isolates failures and
  permissions per repository but turns the same change into a release, bumps
  and many PRs, often over weeks.
- **One version vs independent versions**: the one-version rule removes
  diamond dependencies and drift, but every upgrade must fix all consumers at
  once; independent versions let teams upgrade on their schedule and
  accumulate skew and security debt.
- **Tooling investment**: monorepos need a build graph, affected-only CI,
  remote caching, ownership rules and Git scaling; polyrepos need shared CI
  templates, dependency update bots, internal package publishing and
  cross-repo search.
- **Discoverability vs noise**: everything is searchable and reusable in a
  monorepo, which also makes accidental coupling easy; enforce boundaries with
  visibility rules or import linters ([[modular-monolith]]).
- **Deploys**: either layout can deploy services independently; a monorepo
  must still version API and schema changes, because services do not deploy
  at the same instant ([[api-versioning-and-evolution]]).

## Gotchas
- Moving to a monorepo without affected-only CI: build times grow with every
  project added and everyone waits on everyone's flaky tests.
- Implicit dependencies (a script reading a file in another project, a shared
  root config) are invisible to the build graph; affected detection misses them
  and breakage lands on main. Declare them, or treat root files as "build all".
- Atomic commits do not mean atomic deploys: a commit changing a server and its
  client still rolls out in two steps, so keep wire changes backward compatible.
- One shared lockfile means one bad dependency upgrade can break every project
  at once; run the full suite for lockfile changes.
- Coarse `CODEOWNERS` (one team owns `*`) creates a review bottleneck; very
  fine rules create orphaned paths when teams change.
- Merging repositories without history (copying files) loses blame and
  bisect; import with history (for example `git subtree` or `git filter-repo`
  to move each repo under a subdirectory, then merge).
- Polyrepo "shared library" copies pasted between repositories diverge
  silently; publish it as a versioned package or move it.
- Monorepo access control is coarse on most Git hosts: read access is usually
  all or nothing for the repository.

## Related
- [[git-workflows-and-branching]] - trunk-based development and merge strategy at monorepo scale.
- [[ci-cd-pipelines]] - path filters, caching and affected-only pipelines.
- [[monolith-vs-microservices]] - deployment architecture, a separate decision from repository layout.
- [[modular-monolith]] - boundary checks that also keep a monorepo from tangling.
- [[release-versioning-and-changelogs]] - versioning shared packages in a polyrepo.
- [[software-supply-chain-security]] - lockfiles, pinned dependencies and update bots.
- [[code-review]] - required reviewers and ownership per path.
- [[graph-algorithms]] - topological sort and reachability behind affected builds.

## References
- Rachel Potvin and Josh Levenberg, "Why Google Stores Billions of Lines of Code in a Single Repository", *Communications of the ACM* 59(7), 2016.
- Titus Winters, Tom Manshreck and Hyrum Wright, *Software Engineering at Google* (O'Reilly, 2020), ch. 16 "Version Control and Branch Management", ch. 18 "Build Systems and Build Philosophy", ch. 21 "Dependency Management", ch. 22 "Large-Scale Changes".
- monorepo.tools (overview of monorepo concepts and tools).
- Bazel documentation, "Dependencies".
- npm documentation, "workspaces"; Git documentation, `git-sparse-checkout`.
- GitHub Docs, "About code owners".
