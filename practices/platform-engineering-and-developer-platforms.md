---
title: Platform engineering and internal developer platforms
category: practices
tags: [platform-engineering, internal-developer-platform, idp, golden-path, paved-road, developer-portal, service-catalog, backstage, scorecards, self-service, team-topologies]
use_cases:
  - "every team builds its own CI, deploy and monitoring setup and it takes weeks to ship a new service"
  - "decide whether to form a platform team and what it should build first"
  - "create a golden path or service template so new services start with CI, observability and security defaults"
  - "keep a service catalog of owners, on-call, runbooks and dependencies that stays accurate"
  - "measure whether the internal platform actually helps developers"
status: draft
last_verified: 2026-10-24
sources:
  - "Matthew Skelton and Manuel Pais, Team Topologies, IT Revolution, 2019"
  - https://tag-app-delivery.cncf.io/whitepapers/platforms/
  - https://tag-app-delivery.cncf.io/whitepapers/platform-eng-maturity-model/
  - https://backstage.io/docs/overview/what-is-backstage
  - https://backstage.io/docs/features/software-catalog/descriptor-format
  - https://engineering.atspotify.com/2020/08/how-we-use-golden-paths-to-solve-fragmentation-in-our-software-ecosystem
  - https://dora.dev/research/2024/dora-report/
---

# Platform engineering and internal developer platforms

## Summary
Platform engineering is building and running an internal product, the
internal developer platform (IDP), that gives application teams self-service
access to the capabilities every service needs: repositories and CI,
environments, deployment, databases, secrets, observability and security
defaults. The goal is to cut the cognitive load and waiting that come from
every team assembling and operating its own toolchain, while keeping teams
free to leave the paved path when they need to. It succeeds when treated as
a product with users, not as a mandate or a ticket queue.

## Key concepts
- **Platform as a product** (Team Topologies; CNCF Platforms white paper):
  a platform team has users (developers), a roadmap driven by their needs,
  documentation, support and adoption metrics. Adoption is earned, not
  ordered.
- **Cognitive load**: the reason to build a platform. Stream-aligned teams
  should spend their attention on their domain, not on Kubernetes manifests,
  certificate rotation and dashboard wiring.
- **Thinnest viable platform** (Team Topologies): start with the smallest set
  of documented, self-service capabilities that helps; sometimes a wiki page
  with a template and a few scripts. Grow it from demand.
- **Golden path / paved road**: an opinionated, supported way to build and
  run a common kind of component (for example "HTTP service in Python"),
  usually a template that creates the repository with CI, deploy config,
  logging, metrics, health checks and security scanning already wired.
  Spotify describes golden paths as the supported, recommended route, not
  the only one allowed.
- **Self-service with guardrails**: developers provision what they need
  through an API, CLI, portal or pull request without filing a ticket;
  policy (quotas, allowed regions, required tags, security baselines) is
  enforced automatically rather than by review.
- **Interaction modes** (Team Topologies): the platform team works mostly in
  *X-as-a-Service* mode, with time-boxed *collaboration* or *facilitating*
  when a new capability is being shaped with a team.
- **Developer portal and service catalog**: a front end (Backstage is a
  widely used open-source framework, created at Spotify and now a CNCF
  project) that lists every component with its owner, lifecycle, APIs,
  dependencies, docs and links to runbooks and dashboards. Backstage reads
  this from `catalog-info.yaml` files kept in each repository.
- **Scorecards**: automated checks of each catalog entry against standards
  (has an owner and on-call rotation, runbook, SLO, supported runtime
  version, passing security scan). They make gaps visible without manual
  audits.
- **Layers, not one tool**: an IDP is usually glue over existing parts
  (source hosting, CI/CD, infrastructure as code, Kubernetes or a PaaS,
  secret manager, observability stack); the portal is the visible tip.

## When to use / scenarios
- Several teams each spend weeks setting up a new service, and the setups
  differ in ways that cause incidents (missing alerts, no graceful
  shutdown, unpinned images).
- Security or compliance baselines (scanning, SBOMs, encryption, audit
  logging) must apply to every service: bake them into the golden path
  instead of chasing each team ([[software-supply-chain-security]]).
- Nobody can answer "who owns this service and how do I page them" during an
  incident: start with a service catalog ([[incident-response-and-postmortems]]).
- Moving to containers or a new cloud: the platform team absorbs the
  infrastructure complexity once ([[kubernetes-basics]], [[infrastructure-as-code]]).
- When NOT to: one or two teams, or one service; a shared CI template and a
  README beat a platform team. A platform built before there are enough
  common needs becomes an expensive product with no users. Also not a fix
  for unclear ownership or an organisation that will not fund product-style
  support.

## How it works / example

```
 developer --> portal / CLI / PR ("new service from python-http template")
                   |
                   v  scaffolder creates repo with:
       CI pipeline, Dockerfile, deploy manifests, health checks,
       logging + metrics + tracing, dependency and secret scanning,
       catalog-info.yaml (owner, lifecycle, system, on-call)
                   |
                   v
   platform APIs: environments, databases, secrets, DNS, certificates
   (infrastructure as code underneath; policy checks enforce guardrails)
                   |
                   v
   service catalog + scorecards --> gaps shown per team, tracked over time
```

A minimal scaffolder that renders a golden-path template, plus a scorecard
that checks catalog entries against platform standards:

```python
from string import Template

GOLDEN_PATH = {
    "catalog-info.yaml": Template(
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        "metadata:\n"
        "  name: $name\n"
        "  annotations:\n"
        "    pagerduty.com/service-id: $oncall\n"
        "spec:\n"
        "  type: service\n"
        "  lifecycle: experimental\n"
        "  owner: $owner\n"),
    ".ci/pipeline.yaml": Template(
        "steps: [lint, test, sast, dependency-scan, build-image, deploy-canary]\n"),
    "app/health.py": Template(
        "def live():  return 200\n"
        "def ready(): return 200 if dependencies_ok() else 503\n"),
}

def scaffold(name: str, owner: str, oncall: str) -> dict:
    if not name.replace("-", "").isalnum() or name != name.lower():
        raise ValueError("service names are lowercase kebab-case")
    return {path: t.substitute(name=name, owner=owner, oncall=oncall)
            for path, t in GOLDEN_PATH.items()}

files = scaffold("invoice-api", owner="team-billing", oncall="PX1234")
assert "owner: team-billing" in files["catalog-info.yaml"]
print("scaffolded:", sorted(files))

CHECKS = {
    "has owner":        lambda c: bool(c.get("owner")),
    "has on-call":      lambda c: bool(c.get("oncall")),
    "has runbook":      lambda c: bool(c.get("runbook_url")),
    "has SLO":          lambda c: c.get("slo_target") is not None,
    "supported runtime": lambda c: c.get("runtime") in {"python3.12", "python3.13", "python3.14"},
    "scan passing":     lambda c: c.get("last_scan") == "pass",
}

def scorecard(component: dict) -> tuple:
    failed = [name for name, check in CHECKS.items() if not check(component)]
    return round(100 * (len(CHECKS) - len(failed)) / len(CHECKS)), failed

catalog = [
    {"name": "invoice-api", "owner": "team-billing", "oncall": "PX1234",
     "runbook_url": "https://runbooks.example/invoice-api", "slo_target": 0.999,
     "runtime": "python3.13", "last_scan": "pass"},
    {"name": "legacy-reports", "owner": "team-data", "oncall": None,
     "runtime": "python3.8", "last_scan": "fail"},
]
for comp in catalog:
    score, failed = scorecard(comp)
    print(f"{comp['name']:15} {score:3}%  missing: {failed}")
assert scorecard(catalog[0]) == (100, [])
assert "has on-call" in scorecard(catalog[1])[1]
```

The scorecard output is a work list for teams and a roadmap signal for the
platform: if most services fail the same check, the golden path or the
platform is missing something.

## Trade-offs
- **Paved road vs mandate**: an optional, clearly better path keeps teams
  that have real special needs productive, but leaves a long tail of
  bespoke setups; mandating it gives uniformity but turns the platform team
  into a bottleneck and gatekeeper. Most organisations make a few baselines
  mandatory (security, ownership metadata) and the rest attractive.
- **Abstraction height**: a thin layer (templates over raw Kubernetes and
  Terraform) leaks complexity but rarely blocks anyone; a high-level
  abstraction ("give me a service with a database") is easy but fails for
  the cases it did not foresee. Provide an escape hatch to the layer below.
- **Build vs buy vs assemble**: a developer portal framework, a hosted
  portal or a PaaS each trade control against the cost of running and
  customising it. Backstage is flexible but is a software project of its
  own to operate and extend.
- **Template ownership after creation**: a scaffolded repository diverges
  from the template the day it is created. Either keep templates thin and
  push shared logic into versioned libraries, base images and reusable CI
  steps that update centrally, or invest in automated template updates.
- **Central platform team vs federated contributions**: a central team keeps
  quality consistent but cannot know every team's needs; letting application
  teams contribute plugins and templates scales ideas but needs review and
  clear ownership ([[monorepo-vs-polyrepo]]).

## Gotchas
- Building the portal first. A portal over missing or manual capabilities is
  a catalog of tickets. Automate the most painful workflow first, then
  surface it.
- No product management: the platform team builds what it finds interesting
  rather than what developers struggle with. Interview users, watch them
  set up a service, and measure.
- Measuring outputs (number of templates, portal page views) instead of
  outcomes: time to first deploy of a new service, lead time and change
  failure rate ([[ci-cd-pipelines]]), developer survey results, and how much
  of the fleet is on the golden path. DORA's 2024 report studied internal
  platforms and found both benefits and costs, so measure your own effect
  rather than assuming it.
- A catalog maintained by hand goes stale within months. Keep metadata in
  each repository next to the code, validate it in CI, and derive what you
  can (ownership from CODEOWNERS, dependencies from traces).
- Hiding failure details behind the abstraction: when a deploy fails,
  developers need the real error and logs, not "deployment failed".
- Breaking changes to platform APIs and templates without versioning or
  migration help; treat platform interfaces like any public API
  ([[library-api-design]], [[api-versioning-and-evolution]]).
- Renaming the operations team "platform team" while keeping the ticket
  queue. If developers still wait for a human to provision a database, it is
  not self-service.

## Related
- [[ci-cd-pipelines]] - reusable pipelines and DORA metrics the platform provides and measures.
- [[infrastructure-as-code]] - the provisioning layer behind self-service environments.
- [[kubernetes-basics]] - the runtime many platforms abstract for application teams.
- [[monorepo-vs-polyrepo]] - repository layout, shared tooling and ownership across many services.
- [[documentation-practices]] - docs-as-code and discoverable runbooks that a portal surfaces.
- [[software-supply-chain-security]] - security baselines baked into golden paths.
- [[observability-logs-metrics-traces]] - default telemetry every template wires in.
- [[technical-debt-management]] - scorecards as a way to see and schedule platform-wide debt.

## References
- Matthew Skelton and Manuel Pais, *Team Topologies*, IT Revolution, 2019 (platform teams, cognitive load, thinnest viable platform, interaction modes).
- CNCF TAG App Delivery, "Platforms White Paper": https://tag-app-delivery.cncf.io/whitepapers/platforms/
- CNCF TAG App Delivery, "Platform Engineering Maturity Model": https://tag-app-delivery.cncf.io/whitepapers/platform-eng-maturity-model/
- Backstage documentation, "What is Backstage?": https://backstage.io/docs/overview/what-is-backstage
- Backstage documentation, "Descriptor Format of Catalog Entities": https://backstage.io/docs/features/software-catalog/descriptor-format
- Spotify Engineering, "How We Use Golden Paths to Solve Fragmentation in Our Software Ecosystem" (2020): https://engineering.atspotify.com/2020/08/how-we-use-golden-paths-to-solve-fragmentation-in-our-software-ecosystem
- DORA, "Accelerate State of DevOps Report 2024" (platform engineering chapter): https://dora.dev/research/2024/dora-report/
- Nicole Forsgren, Jez Humble, Gene Kim, *Accelerate*, IT Revolution, 2018 (delivery performance metrics).
