---
title: Health checks and graceful shutdown
category: reliability
tags: [health-check, liveness, readiness, startup-probe, graceful-shutdown, sigterm, connection-draining, prestop, kubernetes, load-balancer]
use_cases:
  - "design /livez and /readyz endpoints for a service behind a load balancer or Kubernetes"
  - "deploys cause a burst of 502s or connection resets"
  - "a database blip made every pod fail its health check and restart"
  - "handle SIGTERM so in-flight requests and jobs finish before the process exits"
  - "slow-starting service gets killed by its liveness probe during startup"
status: draft
last_verified: 2026-10-24
sources:
  - https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
  - https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
  - https://aws.amazon.com/builders-library/implementing-health-checks/
  - https://github.com/grpc/grpc/blob/master/doc/health-checking.md
  - https://docs.python.org/3/library/signal.html
  - https://12factor.net/disposability
---

# Health checks and graceful shutdown

## Summary
Health checks tell the platform (load balancer, Kubernetes, service mesh)
whether an instance should receive traffic and whether it should be
restarted; graceful shutdown lets an instance leave without dropping the
requests it already accepted. Together they decide whether deploys,
autoscaling and node drains are invisible to users or show up as error
spikes. The two common mistakes are opposite: checks so shallow that broken
instances stay in rotation, and checks so deep that one dependency outage
takes the whole fleet out.

## Key concepts
- **Liveness** ("is this process stuck beyond repair?"): failing it restarts
  the container. Check only the process itself: the event loop answers, no
  deadlock. Never check dependencies here.
- **Readiness** ("should I get traffic right now?"): failing it removes the
  instance from load balancing without restarting it. Fails during warm-up,
  during shutdown, and when the instance is overloaded or locally broken.
- **Startup** probe (Kubernetes): holds off liveness and readiness until a
  slow-starting app has started, so startup time and steady-state
  sensitivity are tuned separately.
- **Shallow vs deep checks** (AWS Builders' Library): shallow checks test the
  host and process; deep checks also test dependencies. A deep check that
  fails on every instance at once (shared database down) removes all
  capacity; load balancers that *fail open* when all targets are unhealthy
  mitigate this, but do not rely on it.
- **Active vs passive checking**: the platform polls an endpoint (active), or
  the load balancer or mesh ejects instances that return errors on real
  traffic (passive, outlier detection). Passive checks catch gray failures
  an endpoint misses.
- **Termination sequence** (Kubernetes): the pod is marked terminating, its
  `preStop` hook runs, then the container gets SIGTERM; if it is still
  running after `terminationGracePeriodSeconds` (default 30 s, which includes
  the preStop time), it gets SIGKILL. Removal from Service endpoints happens
  in parallel, so traffic can still arrive for a short time after SIGTERM.
- **Graceful shutdown steps**: on SIGTERM, fail readiness; keep serving
  briefly while load balancers notice; stop accepting new connections; let
  in-flight requests finish up to a deadline; stop background consumers and
  return unacked messages; flush logs, metrics and buffers; close pools; exit 0.
- **Disposability** (twelve-factor): processes start fast and shut down
  gracefully on SIGTERM, so they can be started or stopped at any moment.

## When to use / scenarios
- Every long-running service behind a load balancer, orchestrator or mesh:
  separate liveness and readiness endpoints from day one.
- Rolling, blue-green and canary deploys only stay zero-downtime with a
  readiness gate and draining ([[deployment-strategies]]).
- Autoscaling and spot or preemptible capacity, where instances are removed
  frequently ([[capacity-planning-and-autoscaling]]).
- Queue consumers and job workers: shutdown means finishing or releasing the
  current job, not just HTTP draining ([[background-jobs-and-queues]]).
- gRPC services: implement the standard `grpc.health.v1.Health` service so
  load balancers and Kubernetes gRPC probes can use it.
- When NOT to rely on them: health checks are not monitoring. They act on one
  instance; whether users are served is an SLI question
  ([[slis-slos-error-budgets]], [[observability-logs-metrics-traces]]).

## How it works / example

```
SIGTERM ─┬─> readiness = 503 ──> LB/endpoints stop sending (takes a few s)
         ├─> keep serving during drain delay
         ├─> stop accepting; wait for in-flight (<= deadline)
         └─> close pools, flush, exit 0      (before grace period -> SIGKILL)
```

A stdlib HTTP server with liveness and readiness endpoints that drains
in-flight requests on SIGTERM:

```python
import http.server
import json
import os
import signal
import threading
import time
import urllib.error
import urllib.request

class App:
    def __init__(self):
        self.ready = False
        self.inflight = 0
        self.lock = threading.Lock()
        self.stop_requested = threading.Event()

app = App()

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/livez":            # process only, no dependencies
            return self._send(200, {"status": "ok"})
        if self.path == "/readyz":           # warm-up done and not draining
            ok = app.ready and not app.stop_requested.is_set()
            return self._send(200 if ok else 503, {"ready": ok})
        if self.path == "/work":
            with app.lock:
                app.inflight += 1
            try:
                time.sleep(0.3)              # slow request in flight at SIGTERM
                return self._send(200, {"done": True})
            finally:
                with app.lock:
                    app.inflight -= 1
        self._send(404, {})

server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
base = f"http://127.0.0.1:{server.server_address[1]}"
threading.Thread(target=server.serve_forever, daemon=True).start()

# Signal handler only records the request; the main thread does the work.
signal.signal(signal.SIGTERM, lambda signum, frame: app.stop_requested.set())

def status(path):
    try:
        return urllib.request.urlopen(base + path, timeout=2).status
    except urllib.error.HTTPError as e:
        return e.code

assert status("/readyz") == 503              # still warming up
app.ready = True                             # caches loaded, pools opened
assert status("/readyz") == 200 and status("/livez") == 200

results = []
worker = threading.Thread(target=lambda: results.append(status("/work")))
worker.start()
time.sleep(0.05)                             # request is now in flight
os.kill(os.getpid(), signal.SIGTERM)         # what the orchestrator sends

app.stop_requested.wait()
assert status("/readyz") == 503              # 1. fail readiness
assert status("/livez") == 200               #    but do not look dead
time.sleep(0.1)                              # 2. drain delay (seconds in prod)
deadline = time.monotonic() + 5              # 3. wait for in-flight work
while app.inflight and time.monotonic() < deadline:
    time.sleep(0.01)
server.shutdown()                            # 4. stop accepting, close
server.server_close()
worker.join()
assert results == [200], results             # in-flight request completed
print("drained cleanly, inflight =", app.inflight)
```

The matching Kubernetes settings (values are illustrative):

```yaml
spec:
  terminationGracePeriodSeconds: 45     # > drain delay + longest request
  containers:
    - name: api
      startupProbe:   {httpGet: {path: /livez,  port: 8080}, periodSeconds: 2, failureThreshold: 30}
      readinessProbe: {httpGet: {path: /readyz, port: 8080}, periodSeconds: 5}
      livenessProbe:  {httpGet: {path: /livez,  port: 8080}, periodSeconds: 10, failureThreshold: 3}
      lifecycle:
        preStop: {exec: {command: ["sleep", "5"]}}   # let endpoint removal propagate
```

## Trade-offs
- **Shallow vs deep readiness**: shallow keeps capacity during a shared
  dependency outage; deep pulls an instance whose own connection or cache is
  broken. A common middle ground: readiness checks local state (pool can
  hand out a connection, required config loaded) and leaves shared-dependency
  failures to circuit breakers and degraded responses ([[resilience-patterns]]).
- **Probe sensitivity**: short periods and low failure thresholds react fast
  but restart or eject instances on GC pauses and brief overload; slow
  probes leave broken instances in rotation longer.
- **Drain time vs deploy speed**: a long grace period protects long requests
  and streaming connections but slows rollouts and node drains; cap request
  duration so the grace period can stay bounded.
- **Fail open vs fail closed at the load balancer**: sending traffic to all
  targets when all fail their checks avoids a self-inflicted total outage
  from a bad check, at the risk of serving from genuinely broken instances.

## Gotchas
- Liveness probes that check the database: a database blip restarts every
  instance, and the restart storm makes recovery slower.
- No startup probe on a slow-starting app: liveness kills it before it
  finishes booting, forever.
- The app is not PID 1 (shell-form `CMD`, wrapper scripts), so SIGTERM never
  reaches it and every shutdown ends in SIGKILL ([[containers-and-docker]]).
- Exiting immediately on SIGTERM: endpoint removal is asynchronous, so
  requests routed in the next seconds hit a closed port.
- Long-lived connections (WebSockets, gRPC streams, HTTP keep-alive) are not
  drained by stopping the listener; send close frames or GOAWAY and set
  `Connection: close` during drain ([[realtime-websockets-sse]]).
- Health endpoints that are expensive (full queries, auth) and are polled by
  every load balancer node; keep them cheap and cache dependency status.
- Health endpoints exposed publicly and leaking versions or dependency
  details; serve them on an internal port or return minimal bodies.
- Readiness returning 200 before caches are warm or migrations are checked,
  so the first users after a deploy see slow or failed requests.
- Grace period shorter than drain delay plus the longest request: SIGKILL
  cuts requests off anyway.

## Related
- [[kubernetes-basics]] - probes, pod lifecycle and rollout mechanics.
- [[deployment-strategies]] - rolling, blue-green and canary releases depend on readiness and draining.
- [[load-balancing]] - active and passive health checks and outlier ejection at the load balancer.
- [[containers-and-docker]] - PID 1 and signal delivery inside containers.
- [[resilience-patterns]] - circuit breakers and load shedding instead of deep health checks.
- [[twelve-factor-app]] - disposability: fast startup and graceful shutdown.
- [[gossip-and-failure-detection]] - how peer-to-peer clusters detect failed members without a central checker.

## References
- Kubernetes documentation, "Configure Liveness, Readiness and Startup Probes": https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Kubernetes documentation, "Pod Lifecycle" (termination of pods): https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- David Yanacek, "Implementing health checks", Amazon Builders' Library: https://aws.amazon.com/builders-library/implementing-health-checks/
- gRPC Health Checking Protocol: https://github.com/grpc/grpc/blob/master/doc/health-checking.md
- Python documentation, `signal` module (handlers run in the main thread): https://docs.python.org/3/library/signal.html
- The Twelve-Factor App, IX "Disposability": https://12factor.net/disposability
