---
title: Application configuration and dynamic config
category: reliability
tags: [configuration, config, dynamic-config, config-validation, hot-reload, last-known-good, configmap, layered-config, config-as-code, staged-rollout]
use_cases:
  - "decide what belongs in code, deploy-time config, runtime (dynamic) config and secrets"
  - "a bad config push took down every instance at once"
  - "load typed, validated settings from defaults, files and environment variables and fail fast on startup"
  - "change timeouts, limits or allowlists at runtime without a redeploy, safely"
  - "updated a Kubernetes ConfigMap but pods still use the old values"
status: draft
last_verified: 2026-10-24
sources:
  - https://12factor.net/config
  - https://sre.google/workbook/configuration-design/
  - https://kubernetes.io/docs/concepts/configuration/configmap/
  - https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html
  - "Chunqiang Tang et al., Holistic Configuration Management at Facebook, SOSP 2015"
---

# Application configuration and dynamic config

## Summary
Configuration is every value that changes behaviour without changing code:
endpoints, timeouts, pool sizes, limits, allowlists, feature toggles. It is
also one of the most common causes of outages, because a config change can
reach the whole fleet faster than a code deploy and usually skips the tests
and review code gets. Treat config as code: typed and validated, versioned
and reviewed, rolled out gradually with automatic rollback, and loaded so
that a bad value is rejected instead of taking a service down.

## Key concepts
- **Kinds of configuration** and where each lives:
  - *Build-time constants* that never differ per environment: code.
  - *Deploy-time config* that differs per environment (database URL, region,
    pool size): environment variables or a mounted file, read at startup
    ([[twelve-factor-app]]).
  - *Runtime (dynamic) config* that operators change while running (rate
    limits, timeouts, kill switches, blocklists): a config service or
    watched file, applied without restart.
  - *Feature flags*: dynamic config evaluated per request or user, with
    targeting ([[feature-flags]]).
  - *Secrets*: credentials; same loading path, but stored and audited in a
    secret manager and never logged ([[secrets-management]]).
- **Layering and precedence**: defaults in code < config file < environment
  < command-line or explicit override. Make the order explicit and print the
  effective config (with secrets redacted) at startup.
- **Schema and validation**: parse into typed objects at load time; check
  types, ranges and cross-field rules (`min_pool <= max_pool`). Unknown keys
  are errors, so typos do not silently fall back to defaults
  ([[input-validation-and-parsing]]).
- **Fail fast at startup, fail safe at runtime**: an invalid config at boot
  should stop the process before it takes traffic; an invalid dynamic update
  should be rejected and the **last-known-good** config kept.
- **Config as code**: config lives in version control, changes go through
  review and CI validation, and every running version is identifiable
  (version or hash exported as a metric and logged).
- **Staged rollout**: push a config change to a canary set, watch health
  signals, then widen, exactly like a code deploy; roll back automatically on
  alarms ([[deployment-strategies]]). Facebook's Configerator and AWS
  AppConfig both build in validation and staged deployment for this reason.
- **Immutable snapshots**: readers take one consistent snapshot per request
  or operation, so a reload mid-request cannot mix old and new values.
- **Propagation semantics** (Kubernetes): a ConfigMap mounted as a volume is
  updated in the pod eventually after a change; values injected as
  environment variables, and volumes mounted with `subPath`, are not updated
  until the pod restarts. Immutable ConfigMaps never change; you create a new
  one and roll the Deployment.

## When to use / scenarios
- Any service: start with typed, validated, layered deploy-time config and a
  redacted startup dump.
- Operators need to change limits, timeouts or blocklists during an incident
  without a deploy: add dynamic config with validation and last-known-good.
- Many services share settings (endpoints, quotas): a central config repo or
  service with per-service schemas, rather than copies drifting apart.
- Multi-tenant products with per-tenant limits: config keyed by tenant with
  defaults, not one column per setting.
- When NOT to make it configurable: values that never change in practice,
  or whose change needs code changes anyway. Every knob is a test-matrix
  dimension and an outage path; YAGNI applies to configuration too.

## How it works / example

```
 repo (reviewed, CI-validated)      config service / ConfigMap
 defaults.py  config/prod.yaml ──>  version 42 ──> canary hosts ──> all hosts
                                          │             │ alarm?
 env vars (deploy-time) ──┐               │             └─> roll back to 41
                          v               v
               process: load -> parse -> validate -> immutable snapshot
                                   invalid? keep last-known-good, alert
```

Typed, layered loading with fail-fast validation and secret redaction, plus a
dynamic holder that rejects bad updates and keeps the last good snapshot:

```python
import dataclasses
import threading
from dataclasses import dataclass, field, fields

class Secret(str):
    def __repr__(self):
        return "Secret('***')"

@dataclass(frozen=True)
class Settings:
    database_url: Secret
    pool_min: int = 2
    pool_max: int = 10
    request_timeout_s: float = 2.0
    allowed_origins: tuple = ()
    version: str = field(default="0", compare=False)

    def __post_init__(self):
        if not 1 <= self.pool_min <= self.pool_max <= 200:
            raise ValueError(f"need 1 <= pool_min <= pool_max <= 200,"
                             f" got {self.pool_min}..{self.pool_max}")
        if not 0 < self.request_timeout_s <= 30:
            raise ValueError("request_timeout_s must be in (0, 30]")

def _coerce(f, raw):
    if not isinstance(raw, str):
        return raw
    if f.type in (int, "int"):
        return int(raw)
    if f.type in (float, "float"):
        return float(raw)
    if f.type in (tuple, "tuple"):
        return tuple(s.strip() for s in raw.split(",") if s.strip())
    if f.type in (Secret, "Secret"):
        return Secret(raw)
    return raw

def load(*layers, env=None, prefix="APP_"):
    """Later layers win; env vars (APP_POOL_MAX=...) win over all files."""
    known = {f.name: f for f in fields(Settings)}
    merged = {}
    for layer in layers:
        unknown = set(layer) - set(known)
        if unknown:                                   # typos must not pass
            raise KeyError(f"unknown config keys: {sorted(unknown)}")
        merged.update(layer)
    for key, value in (env or {}).items():
        if key.startswith(prefix) and key[len(prefix):].lower() in known:
            merged[key[len(prefix):].lower()] = value
    return Settings(**{k: _coerce(known[k], v) for k, v in merged.items()})

defaults = {"pool_max": 10}
prod_file = {"pool_max": 50, "allowed_origins": ("https://app.example.com",)}
env = {"APP_DATABASE_URL": "postgres://app:hunter2@db/app",
       "APP_REQUEST_TIMEOUT_S": "1.5", "PATH": "/usr/bin"}

cfg = load(defaults, prod_file, env=env)
assert cfg.pool_max == 50 and cfg.request_timeout_s == 1.5
assert "hunter2" not in repr(cfg)                 # safe to log at startup
print("effective config:", cfg)

for bad in ({"pool_max": 0}, {"pool_mx": 20}):    # out of range, typo
    try:
        load(defaults, bad, env=env)
        raise AssertionError("bad config accepted")
    except (ValueError, KeyError) as e:
        print("startup refused:", e)

class DynamicConfig:
    """Validate before swap; keep last-known-good; readers get snapshots."""
    def __init__(self, initial):
        self._current, self._lock = initial, threading.Lock()
        self.rejected = 0

    def snapshot(self):
        return self._current            # one immutable object per request

    def apply(self, changes, version):
        with self._lock:
            try:
                candidate = dataclasses.replace(self._current, version=version,
                                                **changes)
            except (TypeError, ValueError) as e:
                self.rejected += 1      # alert on this metric
                return False, str(e)
            self._current = candidate
            return True, version

live = DynamicConfig(dataclasses.replace(cfg, version="41"))
request_view = live.snapshot()
assert live.apply({"request_timeout_s": 0.8}, "42") == (True, "42")
ok, why = live.apply({"request_timeout_s": 300}, "43")    # fat-fingered push
assert not ok and live.snapshot().version == "42"         # last-known-good
assert request_view.request_timeout_s == 1.5              # in-flight unaffected
assert live.snapshot().request_timeout_s == 0.8 and live.rejected == 1
print("running version", live.snapshot().version, "- rejected:", why)
```

## Trade-offs
- **Static (restart to change) vs dynamic**: static config is simple,
  reproducible and rolled out with the deploy machinery you already trust;
  dynamic config enables fast mitigation but is a second, faster deploy path
  that needs its own validation, staging and audit.
- **Environment variables vs files vs config service**: env vars are
  universal but flat strings, visible to child processes and only read at
  start; files hold structure and can be watched; a config service adds
  versioning, targeting and push at the cost of a runtime dependency (cache
  the last good copy locally so its outage does not stop startup).
- **Central vs per-service config**: central repos make cross-service changes
  atomic and reviewable; per-service config keeps ownership local but drifts.
- **Flexibility vs safety**: generic expression languages or templating in
  config let operators do anything, including things no test covered. The
  Google SRE workbook recommends minimising the number of knobs users must
  set and keeping config close to the user's intent rather than the
  mechanism.

## Gotchas
- A global config push with no canary: the change that breaks one host
  breaks all of them in seconds. Stage config like code.
- Defaults that silently apply when a key is misspelled. Reject unknown keys.
- Validation only in the service, not in CI: the bad value is found when it
  reaches production. Run the same schema check on every config change.
- Reloading config by mutating shared objects in place: a request sees half
  old, half new values. Swap a whole immutable snapshot.
- Hot reload that re-reads the file, fails to parse and falls back to
  defaults (pool size 2 in production). Keep last-known-good.
- Updating a ConfigMap and expecting env-var consumers to change: they need a
  rollout; hash the config into a pod annotation so a change triggers one.
- Secrets in plain config files or printed in a startup dump; redact by type,
  not by key-name guessing ([[secrets-management]]).
- Config that differs between environments in ways tests never exercise
  (TLS off in staging): parity matters as much for config as for code.
- No record of which config version was live when an incident started:
  export the version as a metric and include it in logs
  ([[observability-logs-metrics-traces]]).
- Temporary emergency overrides that nobody removes: give overrides an owner
  and an expiry, like flags ([[technical-debt-management]]).

## Related
- [[twelve-factor-app]] - deploy-time config in the environment, separate from code.
- [[feature-flags]] - per-request dynamic config with targeting, rollout and kill switches.
- [[secrets-management]] - the sensitive part of config and how to store, rotate and audit it.
- [[deployment-strategies]] - canary and staged rollout apply to config changes too.
- [[input-validation-and-parsing]] - parse-don't-validate applies to config files and env vars.
- [[kubernetes-basics]] - ConfigMaps, Secrets and rollouts that pick up new values.
- [[incident-response-and-postmortems]] - config changes as a frequent trigger and fast mitigation.
- [[infrastructure-as-code]] - versioned, reviewed infrastructure settings and drift detection.

## References
- The Twelve-Factor App, III "Config": https://12factor.net/config
- Google, *The Site Reliability Workbook*, ch. 14 "Configuration Design and Best Practices": https://sre.google/workbook/configuration-design/
- Kubernetes documentation, "ConfigMaps" (mounted ConfigMaps are updated, env vars and subPath mounts are not; immutable ConfigMaps): https://kubernetes.io/docs/concepts/configuration/configmap/
- AWS AppConfig User Guide, "What is AWS AppConfig?" (validators, deployment strategies, rollback on alarm): https://docs.aws.amazon.com/appconfig/latest/userguide/what-is-appconfig.html
- Chunqiang Tang, Thawan Kooburat, Pradeep Venkatachalam et al., "Holistic Configuration Management at Facebook", SOSP 2015.
