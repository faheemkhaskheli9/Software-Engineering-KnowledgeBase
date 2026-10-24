---
title: Secrets management
category: security
tags: [secrets, vault, kms, env-vars, rotation, credentials, secret-scanning]
use_cases:
  - "stop committing API keys and database passwords to git"
  - "store and rotate database credentials for a Kubernetes deployment"
  - "choose between environment variables, a cloud secret manager and HashiCorp Vault"
  - "respond to a leaked credential in a public repository"
  - "give CI/CD jobs cloud access without long-lived keys"
status: stable
last_verified: 2026-10-10
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
  - https://developer.hashicorp.com/vault/docs
  - https://12factor.net/config
  - https://docs.github.com/en/code-security/secret-scanning
  - https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect
---

# Secrets management

## Summary
Secrets are credentials that grant access: API keys, DB passwords, signing
keys, tokens, certificates. Managing them means keeping them out of source
control and images, delivering them to workloads at runtime with least
privilege, rotating them, and being able to revoke and audit. The strongest
move is to need fewer long-lived secrets at all.

## Key concepts
- **Separate config from code:** twelve-factor's config rule keeps all
  config, credentials included, out of the code and in the environment. Have
  the platform fill those variables (or mounted files) from a dedicated secret
  store rather than from checked-in files.
- **Secret stores:** cloud managers (AWS Secrets Manager, GCP Secret Manager,
  Azure Key Vault), HashiCorp Vault / OpenBao, Kubernetes Secrets (base64, not
  encryption, unless encryption at rest or an external store is configured),
  encrypted-in-git tools (SOPS, sealed-secrets).
- **Envelope encryption:** a KMS-held key encrypts per-secret data keys; the
  KMS key never leaves the HSM-backed service.
- **Dynamic / short-lived credentials:** Vault database engine or cloud IAM
  issue per-workload credentials with a TTL, so a leak expires itself.
- **Workload identity:** pods/VMs/CI authenticate with an identity (IAM role,
  Kubernetes service account, GitHub OIDC) instead of a stored key.
- **Rotation, revocation, audit:** every secret has an owner, a rotation
  procedure, and access logs.

## When to use / scenarios
- Any app with a DB, third-party API or signing key: use a managed store from
  day one; it is cheap.
- Local development: a git-ignored `.env` with dev-only credentials; never
  copy production values to laptops.
- CI/CD: OIDC federation to the cloud provider rather than stored access keys.
- Highly regulated or multi-cloud estates: Vault with dynamic secrets.
- Not appropriate: secrets in image layers, `docker build --build-arg`,
  config maps, wiki pages, chat, or client-side bundles (anything shipped to a
  browser or mobile app is public).

## How it works / example

Load at start-up from the environment (injected by the platform from the
secret store), fail fast, never log:

```python fragment
import os, sys

def require(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing required secret: {name}")   # name only, never the value
    return v

DB_PASSWORD = require("DB_PASSWORD")
```

Fetching from AWS Secrets Manager at runtime with the instance role (no static
key; `pip install boto3`):

```python
import boto3, json

def get_secret(secret_id: str) -> dict:
    client = boto3.client("secretsmanager")      # credentials come from the IAM role
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
```

Prevent leaks before they land: run a scanner in a pre-commit hook and in CI
(gitleaks, trufflehog, GitHub secret scanning with push protection):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4          # example tag: pin the latest gitleaks release
    hooks: [{id: gitleaks}]
```

Leak response runbook (in order):
1. **Revoke/rotate first.** Assume the secret is already abused.
2. Check provider logs for use between leak and revocation.
3. Remove from history only afterwards (`git filter-repo`); rewriting history
   does not un-leak a public secret, forks and caches persist.
4. Add a scanner rule or test so the same path cannot recur.
5. Write a short postmortem (see incident-response-and-postmortems).

## Trade-offs
- **Env vars vs mounted files vs API fetch:** env vars are universal but leak
  via `/proc`, crash dumps and child processes; files with tight permissions
  or direct API fetch avoid that at the cost of plumbing.
- **Managed service vs Vault:** managed is low-ops and IAM-integrated; Vault
  offers dynamic secrets and portability but you operate (and unseal) it.
- **Rotation frequency:** frequent rotation shrinks exposure but breaks apps
  that cache the credential; support two active versions during rollover.
- **Encrypted-in-git (SOPS):** great GitOps ergonomics and review; key
  management of the SOPS key becomes the new root secret.

## Gotchas
- A deleted commit is still in clones, forks and CI caches. Rotate, always.
- A `.env` committed once "just for testing" is a common way secrets leak;
  add it to `.gitignore` before creating it.
- Kubernetes Secrets are only base64; enable encryption at rest and restrict
  RBAC on `get secrets`.
- Printing config on startup, debug endpoints, error trackers and APM spans
  frequently capture secrets. Scrub them.
- Shared secrets used by many services cannot be rotated safely or attributed;
  prefer one credential per workload.
- Terraform state holds secret values in plaintext; encrypt and restrict the
  backend.
- Secrets in URLs (query strings) end up in access logs.
- A "break glass" secret with no audit trail defeats the whole system.

## Related
- [[twelve-factor-app]] - config strictly separated from code.
- [[infrastructure-as-code]] - keep secrets out of IaC source and state.
- [[ci-cd-pipelines]] - OIDC federation and scoped pipeline credentials.
- [[kubernetes-basics]] - Secret objects, RBAC, external secret operators.
- [[cryptography-and-tls]] - KMS, key hierarchies, certificate handling.
- [[incident-response-and-postmortems]] - the leaked-credential runbook.
- [[configuration-management]] - the non-secret rest of config: layering, validation and rollout.

## References
- OWASP Secrets Management Cheat Sheet.
- HashiCorp Vault documentation.
- GitHub secret scanning and push protection docs.
- The Twelve-Factor App, factor III Config.
