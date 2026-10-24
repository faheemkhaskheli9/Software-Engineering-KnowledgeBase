---
title: CI/CD pipelines
category: reliability
tags: [ci, cd, pipeline, github-actions, automation, build, release, trunk-based-development, supply-chain]
use_cases:
  - set up a CI pipeline that runs tests, lint and builds on every pull request
  - add continuous delivery so merges to main deploy to staging automatically
  - speed up a slow pipeline that takes 40 minutes
  - build a container image once and promote the same artifact through environments
  - stop deploy credentials and secrets from leaking through CI
status: draft
last_verified: 2026-10-10
sources:
  - https://docs.github.com/en/actions
  - https://martinfowler.com/articles/continuousIntegration.html
  - https://trunkbaseddevelopment.com/
  - https://slsa.dev/
  - Continuous Delivery (Humble, Farley), Addison-Wesley
  - Accelerate (Forsgren, Humble, Kim), IT Revolution
---

# CI/CD pipelines

## Summary
Continuous integration merges and verifies small changes frequently with automated build and test; continuous delivery keeps every green main-branch commit deployable, and continuous deployment ships it to production automatically. A good pipeline is fast, deterministic and builds one immutable artifact that is promoted unchanged through environments.

## Key concepts
- **CI**: every push/PR triggers build, unit tests, lint, static analysis. The goal is fast feedback and an always-green main branch.
- **Continuous delivery vs deployment**: delivery = deployable at any time with a manual release button; deployment = automatic release of every passing change.
- **Build once, deploy many**: build the artifact (container image, wheel) once, tag with the commit SHA, and promote the same bytes dev -> staging -> prod. Environment differences come from config (see [[twelve-factor-app]]).
- **Pipeline stages**: checkout -> restore cache -> lint/typecheck -> unit tests -> build -> integration tests -> scan -> publish artifact -> deploy -> smoke test.
- **Trunk-based development**: short-lived branches (hours to a day), merge to main often, use feature flags for unfinished work (see [[git-workflows-and-branching]]).
- **Quality gates**: required checks, code review and branch protection block merges that fail.
- **Pipeline as code**: pipeline definitions live in the repo, are reviewed and versioned.
- **DORA metrics**: deployment frequency, lead time for changes, change failure rate, time to restore. Measure them to see if the pipeline helps.
- **Software supply chain**: pinned dependencies, lockfiles, SBOMs, signed artifacts and provenance (SLSA) so you can trust what you ship.

## When to use / scenarios
- Any project with more than one contributor or any production deployment: automate from the start; even a 20-line workflow pays off.
- Monorepos or many services: path filters and caching so only affected parts build.
- Compliance or audit needs: pipeline records who approved what and which commit is running.
- When NOT to over-build: a solo hobby script does not need staged environments and approval gates; a test + lint workflow is enough.

## How it works / example

```
PR opened -> [lint | unit tests | typecheck] parallel -> build image -> integration tests
merge to main -> build + push image:SHA -> deploy staging -> smoke tests -> (approval) -> deploy prod -> verify
```

GitHub Actions workflow for a Python service (test on PR, build and push on main):

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: pytest -q --maxfail=1

  image:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write          # OIDC to cloud, no long-lived keys
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

Pin third-party actions to a commit SHA for high-trust pipelines; major-version tags can move.

Deploy step idea: update the image tag in a Git repo and let an agent reconcile (GitOps, see [[infrastructure-as-code]]), or run `kubectl set image` / a Helm upgrade with the SHA tag, then wait for `kubectl rollout status` and run a smoke test; fail the job (and roll back) if it does not pass.

Speeding up a slow pipeline, in order of payoff:
1. Run independent jobs in parallel; split the test suite across runners.
2. Cache dependencies and Docker layers (order Dockerfile steps from least to most changing; see [[containers-and-docker]]).
3. Run fast checks first so cheap failures end the run early.
4. Test only what changed in monorepos; run the full suite on main/nightly.
5. Fix or quarantine flaky tests; retries that hide flakiness only slow everyone.

## Trade-offs
- **Speed vs coverage**: fast PR checks (minutes) with slower nightly suites vs everything on every PR. Developers route around a 40-minute pipeline.
- **Hosted vs self-hosted runners**: hosted is zero-maintenance; self-hosted gives control, caching and private network access but is a security and ops burden.
- **Continuous deployment vs gated release**: automatic prod deploys need strong tests, flags and canaries (see [[deployment-strategies]]); regulated or low-confidence teams keep an approval gate.
- **Monorepo vs polyrepo pipelines**: monorepo needs change detection; polyrepo duplicates pipeline config (use shared templates).
- **Ephemeral vs persistent environments**: per-PR preview environments catch integration problems but cost money and need cleanup.

## Gotchas
- Secrets in CI logs or available to PRs from forks. Never expose secrets to untrusted code; prefer short-lived OIDC credentials over stored cloud keys (see [[secrets-management]]).
- Rebuilding the artifact per environment means what you tested is not what you shipped.
- Floating dependencies (`latest`, unpinned ranges) make builds non-reproducible and open supply-chain risk; use lockfiles and renovate/dependabot-style updates.
- Flaky tests erode trust until people ignore red builds. Track and fix them; fail on new flakes.
- A long-lived branch plus "CI" that only runs on main is not CI.
- Pipeline permissions default too wide; set least-privilege tokens per job.
- Cache poisoning and stale caches produce "works only on CI" bugs; key caches on lockfile hashes.
- Manual production steps outside the pipeline (hotfix by SSH) create drift; route emergencies through a fast path in the same pipeline.
- Database migrations in the deploy step need ordering and backward compatibility (see [[schema-migrations]]).

## Related
- [[deployment-strategies]] - what the CD half actually does with the artifact.
- [[git-workflows-and-branching]] - trunk-based development is what makes CI meaningful.
- [[testing-strategy-and-pyramid]] - which tests belong at which pipeline stage.
- [[containers-and-docker]] - the artifact most pipelines build.
- [[secrets-management]] - handling credentials the pipeline needs.
- [[infrastructure-as-code]] - infrastructure changes should flow through a pipeline as well.
- [[software-supply-chain-security]] - pinning, hash checking, SBOMs, SLSA provenance and signing for what the pipeline builds.
- [[static-analysis-and-type-checking]] - linters, type checkers and SAST as pipeline gates with baselines.
- [[monorepo-vs-polyrepo]] - affected-only builds, remote caching and per-path ownership.

## References
- Martin Fowler, Continuous Integration: https://martinfowler.com/articles/continuousIntegration.html
- GitHub Actions documentation: https://docs.github.com/en/actions
- Trunk Based Development: https://trunkbaseddevelopment.com/
- SLSA supply-chain framework: https://slsa.dev/
- Humble and Farley, Continuous Delivery; Forsgren, Humble, Kim, Accelerate.
