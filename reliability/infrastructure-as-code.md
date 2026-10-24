---
title: Infrastructure as code
category: reliability
tags: [iac, terraform, opentofu, pulumi, gitops, configuration-management, drift, immutable-infrastructure]
use_cases:
  - provision cloud networks, databases and clusters from version-controlled code
  - manage dev, staging and prod environments that stay consistent
  - detect and fix configuration drift after someone changed things in the console
  - set up a safe review and apply workflow for infrastructure changes
  - manage Terraform state and secrets without leaking them
status: draft
last_verified: 2026-10-10
sources:
  - https://developer.hashicorp.com/terraform/docs
  - https://developer.hashicorp.com/terraform/language/state
  - https://opentofu.org/docs/
  - https://www.pulumi.com/docs/
  - https://opengitops.dev/
  - Infrastructure as Code, 2nd ed. (Kief Morris), O'Reilly
---

# Infrastructure as code

## Summary
Infrastructure as code (IaC) defines servers, networks, databases, permissions and clusters in versioned text files that tools apply automatically and repeatably. It replaces click-ops and snowflake machines with reviewable diffs, reproducible environments and a record of who changed what. The central discipline is declarative desired state, a protected state file or API source of truth, and a plan-review-apply workflow run from a pipeline.

## Key concepts
- **Declarative vs imperative**: declarative tools (Terraform/OpenTofu, CloudFormation, Kubernetes manifests) describe the end state and compute the diff; imperative scripts describe steps and are not idempotent unless you make them so. Pulumi and CDK use general-purpose languages to produce a declarative graph.
- **Provider / resource / module**: providers talk to an API; resources are the things created; modules package reusable groups of resources with inputs and outputs.
- **State**: Terraform records the mapping between code and real resources in a state file. It can contain secrets, so store it in a remote backend with locking and encryption.
- **Plan then apply**: the plan shows adds, changes and destroys before anything happens. Review it like a code diff.
- **Idempotency and convergence**: applying twice yields the same result; running the tool brings reality to the declared state.
- **Drift**: real infrastructure diverges from code (manual console edits, auto-modified resources). Detect with scheduled plans.
- **Immutable infrastructure**: replace machines/images instead of patching in place; pairs with containers and golden images (see [[containers-and-docker]]).
- **Configuration management**: Ansible/Chef/Puppet configure the inside of machines; most modern setups shrink this role in favor of containers and managed services.
- **GitOps**: Git is the source of truth; an in-cluster agent (Argo CD, Flux) pulls and reconciles continuously, and drift is auto-corrected.
- **Policy as code**: automated checks (OPA/Conftest, Sentinel, tfsec/checkov-style scanners) block insecure or costly changes in CI.

## When to use / scenarios
- Anything beyond a single hand-built server: repeatable environments, disaster recovery (rebuild a region from code), multiple environments.
- Teams needing audit trails and review of infrastructure changes.
- Kubernetes workloads: manifests/Helm/Kustomize in Git with GitOps (see [[kubernetes-basics]]).
- When NOT to: one-off experiments (but write down what you did), or when a managed PaaS removes the infrastructure you would codify. Do not model every tiny resource as a module on day one.

## How it works / example

```
edit .tf -> PR -> CI: fmt, validate, plan (posted to PR) + policy checks
          -> review + approve -> merge -> pipeline: apply (from a single trusted runner)
          -> state updated (remote, locked)  -> scheduled "plan" detects drift
```

Terraform with remote state and a small module call:

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "acme-tfstate"
    key            = "prod/network.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "acme-tfstate-lock"
    encrypt        = true
  }
}

variable "environment" { type = string }

resource "aws_s3_bucket" "uploads" {
  bucket = "acme-${var.environment}-uploads"
  tags   = { environment = var.environment, owner = "platform" }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "uploads_bucket" { value = aws_s3_bucket.uploads.bucket }
```

The same idea in Pulumi with Python (a real language gives loops, functions and tests):

```python fragment
import pulumi, pulumi_aws as aws

env = pulumi.get_stack()
bucket = aws.s3.Bucket(f"uploads-{env}", tags={"environment": env})
pulumi.export("uploads_bucket", bucket.bucket)
```

Repository layout that scales:

```
infra/
  modules/            # reusable: network, postgres, k8s-cluster
  envs/
    dev/   main.tf  terraform.tfvars
    prod/  main.tf  terraform.tfvars
```

Workflow rules worth enforcing:
1. All changes go through PRs; nobody applies from a laptop to production.
2. Separate state per environment and per blast-radius boundary (network, data, apps), not one giant state.
3. Pin provider and module versions; commit the lock file.
4. Tag resources with owner and environment for cost and incident attribution.
5. Run a scheduled plan and alert on unexpected diffs (drift).
6. Test: `validate`, policy scans, and for modules an ephemeral apply in a sandbox account.

## Trade-offs
- **Terraform/OpenTofu vs Pulumi/CDK**: HCL is constrained and uniform, with a huge provider ecosystem; general-purpose languages offer abstraction and tests but can hide complexity and make diffs harder to reason about.
- **Cloud-native (CloudFormation/Bicep) vs cloud-agnostic**: native tools support new services first and need no state backend; agnostic tools help with multi-cloud and non-cloud resources (DNS, SaaS) but you rarely get true portability.
- **Monolithic state vs many small states**: one state is simple but slow, risky and contention-prone; many states limit blast radius but need explicit cross-state references.
- **Push (pipeline apply) vs pull (GitOps)**: pull gives continuous drift correction and no cluster credentials in CI; push is simpler for non-Kubernetes resources.
- **Modules**: reuse reduces duplication but premature or over-parameterized modules become harder to understand than the raw resources.
- **Import existing infrastructure vs rebuild**: importing preserves running resources but needs care; rebuilding is cleaner when downtime is acceptable.

## Gotchas
- State files contain secrets and are the source of truth. Never commit them; use encrypted remote backends with locking; restrict access.
- A manual console fix during an incident causes drift; the next apply may revert it. Fold the change back into code afterwards.
- Renaming a resource in code looks like destroy-and-create to the tool. Use `moved` blocks or state moves, and read the plan for any "destroy".
- Destroying stateful resources (databases, buckets) by accident: enable deletion protection and `prevent_destroy` lifecycle rules on them.
- Secrets passed as variables end up in state and plan output; fetch from a secrets manager at runtime where possible (see [[secrets-management]]).
- Unpinned providers or modules change behavior under you on the next init.
- Applying from several places concurrently without locking corrupts state.
- Huge plans are not reviewed; split changes so humans can actually read them.
- Dependency cycles and implicit ordering: rely on references between resources, not on sleep scripts.
- IAM and security group changes can lock you out of the very thing managing them; stage them carefully.

## Related
- [[ci-cd-pipelines]] - run plan/apply and policy checks from a pipeline.
- [[kubernetes-basics]] - cluster manifests managed via GitOps.
- [[containers-and-docker]] - immutable images instead of in-place server configuration.
- [[secrets-management]] - keeping credentials out of code and state.
- [[twelve-factor-app]] - config separation that makes environments differ only by variables.
- [[incident-response-and-postmortems]] - drift and risky manual changes are frequent incident causes.
- [[platform-engineering-and-developer-platforms]] - self-service provisioning with guardrails built on IaC modules.

## References
- Terraform documentation and state: https://developer.hashicorp.com/terraform/docs and https://developer.hashicorp.com/terraform/language/state
- OpenTofu documentation: https://opentofu.org/docs/
- Pulumi documentation: https://www.pulumi.com/docs/
- OpenGitOps principles: https://opengitops.dev/
- Kief Morris, Infrastructure as Code, 2nd ed. (O'Reilly).
