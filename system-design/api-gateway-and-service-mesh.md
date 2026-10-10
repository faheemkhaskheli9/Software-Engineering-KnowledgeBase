---
title: API gateway and service mesh
category: system-design
tags: [api-gateway, service-mesh, envoy, istio, kong, mtls, sidecar, bff, ingress]
use_cases:
  - "put one entry point in front of several microservices with auth, rate limits and routing"
  - "add mutual TLS, retries and tracing between services without changing application code"
  - "decide whether we need a service mesh or whether a gateway and libraries are enough"
  - "build a backend-for-frontend that aggregates calls for a mobile client"
status: draft
last_verified: 2026-10-10
sources:
  - https://microservices.io/patterns/apigateway.html
  - https://www.envoyproxy.io/docs/envoy/latest/
  - https://istio.io/latest/docs/
  - https://linkerd.io/2/overview/
  - "Sam Newman, Building Microservices, 2nd ed., O'Reilly 2021"
---

# API gateway and service mesh

## Summary
An **API gateway** is the single entry point for external (north-south)
traffic: routing, authentication, rate limiting, TLS termination, request
shaping. A **service mesh** is infrastructure for internal (east-west)
service-to-service traffic: a data plane of sidecar (or node-level) proxies and
a control plane that configures mutual TLS, retries, timeouts, traffic
splitting and telemetry uniformly. They overlap but solve different edges.

## Key concepts
- **Gateway responsibilities**: request routing, protocol translation (REST to gRPC), authN/Z (JWT validation, API keys), rate limiting ([[rate-limiting]]), caching, request/response transformation, WAF, API analytics.
- **Backend for Frontend (BFF)**: a gateway-like service per client type (web, mobile) that aggregates and shapes data for that client.
- **Ingress controller**: Kubernetes component exposing services via HTTP routing; the Gateway API is its successor spec ([[kubernetes-basics]]).
- **Data plane**: proxies (Envoy, Linkerd2-proxy) handling the actual traffic.
- **Control plane**: pushes policy/config and certificates to proxies (Istio's istiod, Linkerd control plane).
- **Sidecar vs ambient/node proxy**: sidecar per pod gives isolation but costs memory/CPU and latency; Istio ambient mode and eBPF approaches (Cilium) reduce that.
- **Mesh features**: mTLS with automatic cert rotation, service discovery, load balancing with outlier detection, retries/timeouts/circuit breaking, canary traffic splitting, distributed tracing and golden-signal metrics.

## When to use / scenarios
- Many services behind one public API: need uniform auth, rate limits, versioned routes.
- Multiple client types with different payload needs: BFF.
- Zero-trust requirement: encrypt and authenticate every internal hop (mTLS) and enforce which service may call which.
- Polyglot services where you cannot put resilience and telemetry in one shared library.
- Progressive delivery: weighted routing for canaries ([[deployment-strategies]]).
- Not for: a monolith or a handful of services. A mesh adds real operational cost; start with a gateway and resilience libraries, adopt a mesh when consistency across many teams/languages justifies it.

## How it works / example

```
 internet -> CDN/WAF -> [ API GATEWAY ] --JWT check, rate limit, route-->
                              |
              +---------------+------------------+
              v                                  v
        +-----------+  mTLS via proxies   +-----------+
        | svc A     |<------------------->| svc B     |
        | [app][prx]|                     | [prx][app]|
        +-----------+                     +-----------+
                 \  control plane (certs, routes, policy)  /
```

Declarative gateway route (Kubernetes Gateway API style, illustrative):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: orders }
spec:
  parentRefs: [{ name: public-gw }]
  rules:
    - matches: [{ path: { type: PathPrefix, value: /v1/orders } }]
      backendRefs:
        - { name: orders-v1, port: 80, weight: 90 }
        - { name: orders-v2, port: 80, weight: 10 }   # canary
```

Istio-style mesh policy requiring mTLS and limiting callers (illustrative):

```yaml
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata: { name: default, namespace: shop }
spec: { mtls: { mode: STRICT } }
```

A tiny BFF aggregation, runnable idea (parallel calls, partial failure tolerated):

```python
import asyncio

async def fetch(name, delay, fail=False):
    await asyncio.sleep(delay)
    if fail:
        raise RuntimeError(name)
    return {name: "ok"}

async def home_screen():
    results = await asyncio.gather(
        fetch("profile", 0.05), fetch("orders", 0.08),
        fetch("recommendations", 0.1, fail=True), return_exceptions=True)
    page = {}
    for r in results:
        if isinstance(r, dict):
            page.update(r)       # degrade gracefully: skip failed widget
    return page

if __name__ == "__main__":
    print(asyncio.run(home_screen()))
```

## Trade-offs
- **Gateway as chokepoint**: central policy is convenient but it is a latency hop and a failure domain; keep it stateless, scale horizontally, avoid business logic in it.
- **Mesh vs libraries**: libraries (Resilience4j, gRPC interceptors) are lighter and testable in-process but need per-language effort; mesh is language-agnostic but adds proxies, debugging complexity, and control-plane upgrades.
- **Sidecar overhead**: extra hop and resource use per pod; ambient/eBPF modes trade isolation for cost.
- **One gateway vs BFF per client**: BFFs avoid the lowest-common-denominator API but multiply services to maintain.
- **Managed gateway** (AWS API Gateway, Azure APIM, Apigee) vs self-hosted (Kong, Envoy, nginx, Traefik): managed is quicker with per-request pricing and vendor limits; self-hosted gives control and ops work.

## Gotchas
- Putting orchestration and business rules in the gateway; it becomes an unowned monolith. Keep it to cross-cutting concerns and thin aggregation.
- Stacked retries: client, gateway, and mesh each retry, multiplying load 3x3x3 during an incident. Set retry budgets at one layer ([[resilience-patterns]]).
- Timeouts must shrink along the call chain (client > gateway > service > dependency) or work continues after the caller gave up.
- Double authentication/authorization or trusting internal traffic blindly; validate tokens at the edge and still authorize in the service ([[authorization-models]]).
- Mesh certificate or control-plane outages can break all traffic; know the fail-open/closed behaviour and rehearse upgrades.
- Header propagation: tracing needs services to forward trace headers or the mesh cannot stitch spans ([[observability-logs-metrics-traces]]).
- Gateway request-size limits and timeouts can silently cut uploads and long polls; check defaults.

## Related
- [[rate-limiting]] - a core gateway feature.
- [[load-balancing]] - gateway and mesh both perform L7 balancing.
- [[monolith-vs-microservices]] - the decision that creates the need for these.
- [[resilience-patterns]] - retries, timeouts, circuit breakers that meshes can enforce.
- [[kubernetes-basics]] - ingress, Gateway API and sidecar deployment context.
- [[oauth2-and-oidc]] - token validation at the gateway.
- See also (AI KB): [LLM gateways and routing](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/llm-gateways-and-routing.md) - a gateway in front of LLM providers: routing, fallback, keys and spend limits.

## References
- microservices.io API gateway pattern: https://microservices.io/patterns/apigateway.html
- Envoy docs: https://www.envoyproxy.io/docs/envoy/latest/
- Istio docs: https://istio.io/latest/docs/
- Linkerd overview: https://linkerd.io/2/overview/
- Sam Newman, *Building Microservices* (2nd ed.).
