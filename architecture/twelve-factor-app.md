---
title: The twelve-factor app
category: architecture
tags: [twelve-factor, cloud-native, config, stateless, logging, deployment, paas]
use_cases:
  - "make a web service portable and easy to deploy to containers or a PaaS"
  - "decide where configuration, secrets and logs should live"
  - "our app stores sessions and uploads on local disk and breaks when we add a second instance"
  - "checklist for making a service cloud-ready and horizontally scalable"
status: draft
last_verified: 2026-10-10
sources:
  - https://12factor.net/
  - https://www.oreilly.com/library/view/beyond-the-twelve-factor/9781492042631/
  - https://docs.docker.com/build/building/best-practices/
  - https://kubernetes.io/docs/concepts/configuration/
---

# The twelve-factor app

## Summary
Twelve-factor is a methodology (from Heroku engineers) for building services that deploy cleanly to cloud platforms, scale horizontally, and minimise divergence between dev and production. Its factors are mostly about separating code, config and state: one codebase, explicit dependencies, config in the environment, stateless processes, logs as streams. It remains the baseline contract for container and Kubernetes workloads.

## Key concepts
The twelve factors, with the practical meaning:

1. **Codebase**: one repo per app, many deploys (dev, staging, prod) from the same code.
2. **Dependencies**: declare and isolate them (lock files, virtualenv, container image). Never rely on system packages being present.
3. **Config**: store anything that varies per deploy (DB URL, credentials, feature flags) in environment variables, not in code or per-env config files in the repo.
4. **Backing services**: treat DB, cache, queue, SMTP as attached resources addressed by URL; swapping one needs only a config change.
5. **Build, release, run**: strictly separate stages. A build produces an immutable artifact; a release = build + config; the run stage just starts it. Release IDs enable rollback.
6. **Processes**: stateless and share-nothing. Persist anything durable in a backing service. No sticky sessions, no local-disk state.
7. **Port binding**: the app is self-contained and exports HTTP by binding a port, rather than relying on an injected server.
8. **Concurrency**: scale out via the process model (more web workers, more worker processes), with different process types per workload.
9. **Disposability**: fast startup, graceful shutdown on SIGTERM, robust against sudden death (jobs are re-queueable, idempotent).
10. **Dev/prod parity**: keep gaps small in time (deploy often), people (developers deploy), and tools (same DB engine locally, not SQLite vs Postgres).
11. **Logs**: write unbuffered event streams to stdout; the platform routes and stores them.
12. **Admin processes**: run one-off tasks (migrations, consoles) as processes from the same release, not ad hoc on a server.

Commonly cited extensions ("beyond twelve-factor"): API-first, telemetry/observability, authentication and authorization as concerns, health endpoints.

## When to use / scenarios
- Any service going to containers, Kubernetes ([[kubernetes-basics]]), a PaaS, or serverless ([[serverless-architecture]]).
- Moving from a pet-server deployment to repeatable releases ([[ci-cd-pipelines]], [[deployment-strategies]]).
- Review checklist when an app "works on one instance only".

Where it fits poorly: stateful systems (databases, brokers) have their own operational model; desktop and embedded software; batch jobs that legitimately keep large local scratch (the spirit still applies: ephemeral and reproducible).

## How it works / example
```
 one repo --build--> immutable image --+ config (env) = release v42
                                       |
          +----------------------------+------------------+
          v                            v                  v
      web x N (stateless)         worker x M         one-off: migrate
          |                            |
          +--> Postgres (URL)  +--> Redis (URL)  +--> object storage
   logs: stdout --> platform --> log store
```

A small config module and graceful shutdown in Python:

```python
import logging, os, signal, sys, time

class Config:
    """All deploy-specific values come from the environment; fail fast if missing."""
    def __init__(self, env=os.environ):
        self.database_url = self._req(env, "DATABASE_URL")
        self.port = int(env.get("PORT", "8000"))
        self.log_level = env.get("LOG_LEVEL", "INFO")
        self.debug = env.get("DEBUG", "0") == "1"
    @staticmethod
    def _req(env, key):
        if key not in env:
            raise RuntimeError(f"missing required env var {key}")
        return env[key]

logging.basicConfig(stream=sys.stdout, level="INFO",
                    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
log = logging.getLogger("app")

_shutdown = False
def _on_term(signum, frame):
    global _shutdown
    _shutdown = True                         # stop accepting work, finish in-flight, exit

def main():
    cfg = Config()
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    log.info("starting port=%s", cfg.port)
    while not _shutdown:
        time.sleep(0.2)                      # serve requests / poll queue
    log.info("shutting down cleanly")

if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgres://localhost/dev")
    # main() would loop until SIGTERM; assert config parsing here instead
    assert Config({"DATABASE_URL": "x"}).port == 8000
```

Test of "stateless": start two instances behind a load balancer ([[load-balancing]]) and run your suite against it; anything that fails (sessions, uploads, in-memory caches used as truth) was hidden state.

## Trade-offs
- **Env vars vs config files/secret stores:** env vars are simple and language-agnostic but are flat strings, visible to child processes and sometimes in crash dumps. For secrets prefer mounted files or a manager ([[secrets-management]]); for complex structured config, a mounted file path given by env var is fine.
- **Strict statelessness vs performance:** local caches are fine as optimisations if loss is harmless; they just cannot be the source of truth.
- **Logs to stdout vs structured agents:** stdout is portable; richer pipelines (OpenTelemetry) layer on top ([[observability-logs-metrics-traces]]).
- **Port binding and TLS:** a reverse proxy or ingress still terminates TLS in practice.
- **Strict parity vs convenience:** Docker Compose gets you close to prod for dependencies.

## Gotchas
- **Config groups per environment in code** (`settings_prod.py`) leaks deploy knowledge into the build; rebuilding per environment breaks "build once, promote".
- **Secrets in the image or repo.** Layers keep them forever.
- **Sticky sessions** hide state in the load balancer; use signed cookies/tokens or a shared session store ([[authentication-and-sessions]]).
- **Writing logs to files** inside containers fills the disk and loses them at restart.
- **Slow startup / ignoring SIGTERM** breaks rolling deploys and autoscaling; Kubernetes sends SIGTERM then SIGKILL after the grace period.
- **Running migrations at app start** with many replicas races; run them as a one-off admin process ([[schema-migrations]]).
- **Unbounded in-memory queues** are state; they vanish on restart.

## Related
- [[containers-and-docker]] - the image is the build artifact of factor 5.
- [[kubernetes-basics]] - runs twelve-factor processes with config maps and probes.
- [[serverless-architecture]] - applies the same stateless principles at function level.
- [[ci-cd-pipelines]] - build, release, run separation in practice.
- [[secrets-management]] - safer homes for the sensitive part of config.
- [[observability-logs-metrics-traces]] - what to do with the log streams.

## References
- Adam Wiggins, "The Twelve-Factor App", 12factor.net.
- Kevin Hoffman, *Beyond the Twelve-Factor App*, O'Reilly.
- Docker and Kubernetes official documentation on configuration.
