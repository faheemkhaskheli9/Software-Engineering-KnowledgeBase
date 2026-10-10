---
title: Containers and Docker
category: reliability
tags: [docker, containers, dockerfile, images, multi-stage-build, compose, oci, container-security]
use_cases:
  - containerize a Python web service with a small, secure, cache-friendly image
  - run an app plus its database locally with docker compose
  - shrink a 1 GB image and speed up rebuilds
  - make containers run as non-root with proper signal handling and healthchecks
  - understand what a container actually is versus a virtual machine
status: draft
last_verified: 2026-10-10
sources:
  - https://docs.docker.com/build/building/best-practices/
  - https://docs.docker.com/build/building/multi-stage/
  - https://docs.docker.com/compose/
  - https://opencontainers.org/
  - https://docs.docker.com/engine/security/
---

# Containers and Docker

## Summary
A container is a regular Linux process isolated with namespaces and limited with cgroups, started from an immutable layered image that bundles the app and its userspace dependencies. Docker (and any OCI-compatible tooling) turns that into a portable build-ship-run unit, giving identical behavior across laptop, CI and production. The craft is in writing small, reproducible, least-privilege images.

## Key concepts
- **Image vs container**: an image is a read-only stack of layers; a container is a running instance with a thin writable layer. Containers are disposable.
- **Namespaces and cgroups**: namespaces isolate what a process sees (pid, net, mount, user); cgroups limit what it uses (CPU, memory). Containers share the host kernel, unlike VMs.
- **Layers and cache**: each Dockerfile instruction makes a layer; unchanged leading layers are reused. Order steps from least to most frequently changing.
- **Registry and tags**: images are pushed/pulled by name:tag. Tags are mutable; the digest (`@sha256:...`) is immutable.
- **Multi-stage builds**: compile or install in a fat builder stage, copy only artifacts into a slim runtime stage.
- **PID 1 and signals**: the container's main process receives SIGTERM on stop; it must handle it (or use an init like `tini`) to shut down gracefully.
- **Volumes vs bind mounts vs tmpfs**: persistent data lives in volumes, not the container layer.
- **Compose**: declarative multi-container setup for local dev and simple single-host deployments.
- **OCI**: open standards for image and runtime formats, so images run under containerd, Podman and Kubernetes (see [[kubernetes-basics]]).

## When to use / scenarios
- Reproducible environments across dev, CI and prod; one artifact per service (see [[ci-cd-pipelines]]).
- Packaging services for Kubernetes or a managed container platform.
- Local integration setups: app + Postgres + Redis via Compose.
- Isolating dependencies of conflicting versions on one host.
- When NOT to: stateful databases in production without a clear storage/backup story (managed DB is often saner), workloads needing a different kernel or strong isolation from untrusted tenants (use VMs or sandboxed runtimes such as gVisor/Firecracker), and GUI desktop apps.

## How it works / example

Production-quality multi-stage Dockerfile for a Python app:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src/ ./src/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Notes on that file:
- Dependencies copy and install before source code, so code edits do not invalidate the dependency layer.
- Exec-form `CMD [...]` makes the app PID 1 so it receives SIGTERM; shell form wraps it in `sh -c` and swallows signals.
- Non-root `USER` limits damage from a compromise.
- Keep a `.dockerignore` (`.git`, `.venv`, `__pycache__`, `*.env`, tests data) so the build context is small and secrets stay out.

Compose for local development:

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://app:app@db:5432/app
    depends_on:
      db: {condition: service_healthy}
  db:
    image: postgres:16
    environment: {POSTGRES_USER: app, POSTGRES_PASSWORD: app, POSTGRES_DB: app}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      retries: 10
volumes:
  pgdata:
```

Useful commands: `docker build -t app:dev .`, `docker run --rm -p 8000:8000 app:dev`, `docker logs -f <c>`, `docker exec -it <c> sh`, `docker image ls`, `docker history app:dev` (see layer sizes).

Hardening checklist: pin base images by version (digest for strict reproducibility), scan images for vulnerabilities in CI, run read-only root filesystem where possible (`--read-only`), drop capabilities (`--cap-drop ALL`), never bake secrets into layers, and rebuild regularly to pick up base image patches.

## Trade-offs
- **Base image**: `slim` Debian is a safe default; Alpine is small but uses musl, which can break wheels and subtly change behavior; distroless is minimal and harder to debug (no shell); full images are convenient but large with a bigger attack surface.
- **One process per container vs several**: one process per container is cleaner for scaling and restarts; supervisors inside a container are for legacy cases.
- **Tags**: `:latest` is convenient and non-reproducible; commit-SHA tags and digests are reproducible.
- **Compose vs Kubernetes**: Compose is great on one host and in dev; once you need rolling updates, self-healing and multi-node scheduling, move to an orchestrator.
- **Image size vs build speed vs debuggability**: tiny images pull fast but are harder to debug; use ephemeral debug containers rather than shipping tools in prod.

## Gotchas
- Data written to the container filesystem disappears when the container is replaced. Use volumes or external storage.
- A secret copied in one layer and "deleted" in a later one still exists in the earlier layer. Use BuildKit secret mounts (`RUN --mount=type=secret`).
- Running as root is the default; many images and hosts treat that as a finding.
- Missing memory limits let one container OOM the host; with limits, apps unaware of cgroups (some JVM/runtime settings) may size heaps wrongly. Check how your runtime reads container limits.
- `localhost` inside a container is the container, not the host; services reach each other by Compose service name or cluster DNS.
- `depends_on` without health conditions only orders start, not readiness.
- Logs belong on stdout/stderr, not files inside the container (see [[twelve-factor-app]] and [[observability-logs-metrics-traces]]).
- Unbounded log drivers fill disks; configure rotation.
- `COPY . .` before dependency install busts the cache on every edit.
- Time zone, locale and CA certificates are often missing in minimal images, causing odd TLS or date bugs.

## Related
- [[kubernetes-basics]] - orchestrating containers across machines.
- [[ci-cd-pipelines]] - building, scanning and publishing images.
- [[twelve-factor-app]] - config via env, logs to stdout, stateless processes: the container-friendly app model.
- [[secrets-management]] - how to get secrets into containers without baking them in.
- [[infrastructure-as-code]] - provisioning the hosts and registries containers run on.
- [[memory-and-performance]] - understanding memory limits and process behavior inside cgroups.

## References
- Docker build best practices: https://docs.docker.com/build/building/best-practices/
- Docker multi-stage builds: https://docs.docker.com/build/building/multi-stage/
- Docker Compose documentation: https://docs.docker.com/compose/
- Docker engine security: https://docs.docker.com/engine/security/
- Open Container Initiative: https://opencontainers.org/
