---
title: Load balancing
category: system-design
tags: [load-balancer, l4, l7, nginx, haproxy, health-checks, high-availability]
use_cases:
  - "spread traffic across several stateless app servers and survive a server failure"
  - "choose between L4 and L7 load balancing for a new service"
  - "route requests by path or header to different backend services"
  - "pick a balancing algorithm for long-lived connections or uneven request cost"
status: draft
last_verified: 2026-10-10
sources:
  - https://nginx.org/en/docs/http/load_balancing.html
  - https://www.haproxy.com/documentation/
  - "Michael Mitzenmacher, The Power of Two Choices in Randomized Load Balancing, IEEE TPDS 2001"
  - "Betsy Beyer et al., Site Reliability Engineering (Google), ch. 'Load Balancing in the Datacenter'"
---

# Load balancing

## Summary
A load balancer (LB) distributes incoming requests across a pool of backends,
removes failed backends via health checks, and gives clients a single stable
address. It is the standard way to scale stateless services horizontally and to
get availability without clients knowing about individual servers.

## Key concepts
- **L4 (transport) balancing**: decides per TCP/UDP connection using IP/port; fast, protocol-agnostic, no HTTP awareness (e.g. AWS NLB, HAProxy tcp mode, LVS).
- **L7 (application) balancing**: parses HTTP/gRPC; can route by host/path/header/cookie, terminate TLS, retry, compress, rewrite (e.g. nginx, Envoy, HAProxy http mode, AWS ALB).
- **Algorithms**: round robin, weighted round robin, least connections, least response time, IP/consistent hash, random with power-of-two-choices.
- **Health checks**: active (LB probes `/healthz`) and passive (eject on errors/timeouts). Separate liveness from readiness.
- **Session affinity (sticky sessions)**: pin a client to a backend via cookie or IP hash; usually a smell, prefer externalizing state.
- **Redundancy of the LB itself**: active-passive (VRRP/keepalived, floating IP) or active-active (DNS, anycast, cloud-managed).
- **Connection draining**: finish in-flight requests before removing a backend on deploy.

## When to use / scenarios
- More than one app server, or any zero-downtime deploy (rolling/blue-green).
- Need path-based routing to several services behind one hostname (L7), or raw TCP (databases, MQTT, game servers) (L4).
- TLS termination and WAF at the edge in one place.
- Global traffic: add DNS / GeoDNS / anycast above regional LBs (see [[cdn-and-edge]]).
- Not needed: single instance with a managed platform that already fronts it; client-side balancing (gRPC/Envoy/service mesh) can replace a central LB for east-west traffic, see [[api-gateway-and-service-mesh]].

## How it works / example

```
            clients
               |
          DNS / anycast
               |
        +------v------+      health checks
        |  LB (active)| <--------------------+
        +--+---+---+--+                      |
           |   |   |                         |
        +--v+ +v-+ +v--+                     |
        |A1 | |A2| |A3 | stateless app  -----+
        +---+ +--+ +---+
```

Minimal nginx upstream (L7) with passive health and least connections:

```nginx
upstream app {
    least_conn;
    server 10.0.0.11:8000 max_fails=3 fail_timeout=10s;
    server 10.0.0.12:8000 max_fails=3 fail_timeout=10s;
    server 10.0.0.13:8000 backup;
    keepalive 32;
}
server {
    listen 443 ssl;
    location /api/ { proxy_pass http://app; proxy_next_upstream error timeout http_502; }
}
```

Runnable toy of the power-of-two-choices algorithm (pick 2 random backends,
send to the less loaded one; avoids the herd behaviour of "global least
loaded" while staying near-optimal):

```python
import random

class P2C:
    def __init__(self, backends):
        self.load = {b: 0 for b in backends}

    def acquire(self):
        a, b = random.sample(list(self.load), 2)
        pick = a if self.load[a] <= self.load[b] else b
        self.load[pick] += 1
        return pick

    def release(self, backend):
        self.load[backend] -= 1

if __name__ == "__main__":
    lb = P2C(["a", "b", "c", "d"])
    for _ in range(1000):
        lb.acquire()
    print(lb.load)   # roughly even
```

### Choosing an algorithm
| Situation | Algorithm |
|---|---|
| Uniform, short requests | round robin |
| Heterogeneous servers | weighted round robin |
| Variable request cost, long connections (websockets, uploads) | least connections or P2C |
| Cache locality per key (shard-aware caches) | consistent hash on key (see [[consistent-hashing]]) |
| Need stickiness without cookies | source IP hash (breaks behind NAT) |

## Trade-offs
- **L4 vs L7**: L4 is cheaper and faster and carries any protocol; L7 gives routing, retries, observability, and header-based canaries at CPU cost.
- **Hardware vs software vs cloud-managed**: managed LBs remove ops burden but limit tuning and cost per LCU/GB; nginx/HAProxy/Envoy give control.
- **Central LB vs client-side**: central is simple; client-side (gRPC, service mesh) removes a hop and a bottleneck but spreads complexity to every client.
- **Stickiness vs statelessness**: stickiness hides a session-state problem and skews load; use shared session store (Redis) or signed tokens instead.
- **Aggressive vs lenient health checks**: fast eviction limits errors but flaps under GC pauses; add hysteresis (N failures to eject, M successes to return).

## Gotchas
- The LB is a SPOF unless it is itself redundant.
- Retrying non-idempotent requests (POST) across backends causes double writes; only retry when safe or with idempotency keys ([[idempotency-and-exactly-once]]).
- Health check that only tests the process, not dependencies, keeps a broken node in rotation; one that tests the DB can take the whole fleet out when the DB blips. Prefer shallow readiness plus circuit breaking.
- Idle timeout mismatch: LB idle timeout shorter than keep-alive of backend causes sporadic 502s. Keep the backend timeout longer than the LB's.
- Forwarded client IP is lost behind a proxy; use `X-Forwarded-For` / PROXY protocol and trust it only from the LB.
- Long-lived connections (websockets) unbalance over time after scale-out; rebalance or cap connection age. See [[realtime-websockets-sse]].
- Thundering herd of new instances at deploy; use slow start/warm-up.

## Related
- [[consistent-hashing]] - hash-based routing that tolerates pool changes.
- [[api-gateway-and-service-mesh]] - L7 routing, auth and client-side balancing.
- [[resilience-patterns]] - retries, timeouts and circuit breakers around backends.
- [[deployment-strategies]] - rolling, blue-green and canary via the LB.
- [[networking-fundamentals]] - TCP/HTTP basics behind L4 vs L7.
- [[cdn-and-edge]] - global distribution in front of regional LBs.
- [[health-checks-and-graceful-shutdown]] - what instance health endpoints should check and how instances leave rotation.

## References
- nginx upstream module: https://nginx.org/en/docs/http/load_balancing.html
- HAProxy docs: https://www.haproxy.com/documentation/
- Mitzenmacher, "The Power of Two Choices in Randomized Load Balancing" (2001).
- Google SRE book, "Load Balancing in the Datacenter".
