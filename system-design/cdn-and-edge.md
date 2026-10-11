---
title: CDN and edge
category: system-design
tags: [cdn, edge, cache-control, anycast, static-assets, latency, cloudflare, cloudfront]
use_cases:
  - "serve images, video and static assets to a global audience with low latency"
  - "offload traffic from the origin servers and survive traffic spikes"
  - "set correct Cache-Control headers and invalidate assets after a deploy"
  - "run lightweight logic (redirects, auth checks, A/B routing) close to users"
status: draft
last_verified: 2026-10-10
sources:
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching
  - https://www.rfc-editor.org/rfc/rfc9111
  - https://developers.cloudflare.com/cache/
  - https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/
---

# CDN and edge

## Summary
A content delivery network is a globally distributed set of cache servers
(points of presence, PoPs) that serve content from a location near the user and
shield the origin. Edge compute extends this to running small functions at the
PoP. A CDN is typically the cheapest, highest-leverage latency and scale
improvement for any internet-facing product.

## Key concepts
- **Origin**: your servers or object store; the CDN pulls from it on a miss (pull CDN) or you push files to it (push CDN).
- **PoP / edge node**: cache close to users; requests reach it via DNS steering or anycast routing.
- **Cache key**: what identifies an object (URL, selected headers/query/cookies). Over-specific keys kill the hit ratio.
- **Cache-Control**: origin tells CDN and browsers how to cache: `max-age`, `s-maxage` (shared caches only), `public`, `private`, `no-store`, `stale-while-revalidate`, `stale-if-error`, `immutable`.
- **Validation**: `ETag` / `Last-Modified` with conditional requests (`304 Not Modified`).
- **Origin shield / tiered cache**: a middle cache layer collapsing misses from many PoPs into one origin request.
- **Purge / invalidation**: explicit removal of cached objects; slow-ish and sometimes billed.
- **Edge compute**: Cloudflare Workers, CloudFront Functions / Lambda@Edge, Fastly Compute. Short-running, limited runtime and state.

## When to use / scenarios
- Static assets (JS, CSS, images, fonts, video segments, downloads): always.
- Public, cacheable API or HTML responses (catalog pages, docs, news) with `s-maxage` plus stale-while-revalidate.
- Users spread across continents; origin in one region (round trip alone is ~100+ ms cross-continent).
- Traffic spikes or DDoS: CDN absorbs volumetric load, adds WAF and bot controls.
- Streaming video via HLS/DASH segments: see [[design-video-streaming]].
- Not for: per-user private data (unless carefully keyed and `private`), highly dynamic writes, tiny single-region audience where it adds complexity without gain.

## How it works / example

```
 user (Karachi) -> DNS/anycast -> nearest PoP
                                    | hit  -> respond (ms)
                                    | miss -> regional/shield cache
                                                | hit  -> respond, store at PoP
                                                | miss -> origin / object store
                                                          -> store at shield + PoP
```

### Header recipe that works for most web apps
```
# fingerprinted build assets (app.3f9a1c.js): cache forever
Cache-Control: public, max-age=31536000, immutable

# HTML shell: always revalidate, so deploys are picked up
Cache-Control: no-cache            # means "store, but revalidate each time"

# public API response, CDN may keep 60 s and serve stale 5 min while refreshing
Cache-Control: public, max-age=0, s-maxage=60, stale-while-revalidate=300

# anything personalised or sensitive
Cache-Control: private, no-store
```

Fingerprint (content-hash) filenames so you never need to purge assets: a new
deploy produces new URLs, old URLs remain valid for clients still on the old
HTML.

Minimal Python check of what an origin sends (use before blaming the CDN):

```python fragment
import urllib.request

def cache_headers(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as r:
        keep = ("cache-control", "etag", "age", "vary", "cf-cache-status",
                "x-cache", "expires", "last-modified")
        return {k: v for k, v in r.headers.items() if k.lower() in keep}

if __name__ == "__main__":
    print(cache_headers("https://example.com/"))
```

`Age` shows seconds in a shared cache; `X-Cache` / `CF-Cache-Status` shows
HIT/MISS (names are vendor-specific).

### Edge compute uses
Redirects and rewrites, A/B bucketing, geo-based routing, JWT signature check
before reaching origin, image resizing by query param, HTML personalisation
shells. Keep it stateless and fast; state lives in a regional store or an
edge KV with eventual consistency.

## Trade-offs
- **Freshness vs hit ratio**: longer TTL cuts origin load but serves stale content; mitigate with versioned URLs and stale-while-revalidate.
- **Purge vs versioned URLs**: versioning is instant and free; purge is needed only for un-fingerprintable URLs (HTML, API).
- **Cost**: egress is billed per GB, often cheaper than origin cloud egress; requests and edge-compute invocations are billed too.
- **Single CDN vs multi-CDN**: multi-CDN improves resilience and negotiating power at high operational cost.
- **Edge compute vs origin compute**: edge cuts latency but has tight CPU/memory limits and weaker data locality; use it for routing and light transforms, not business logic over your primary DB.

## Gotchas
- `Vary: Cookie` or `Vary: *` (or a Set-Cookie on cacheable responses) fragments or disables caching.
- Caching an error response or a login redirect for everyone; set short TTL for 4xx/5xx or `no-store`.
- Leaking private content: a missing `private`/`Authorization`-aware cache key lets user A see user B's page.
- Query-string noise (`?utm_source=...`) creates many cache keys; normalize or exclude params.
- `no-cache` is not `no-store`; people misuse both.
- Purge propagation is not instant and may be rate-limited; do not build correctness on it.
- Origin must tolerate the shield and PoPs hitting it when a popular object expires; use request collapsing and stale-while-revalidate (see [[caching-strategies]]).
- Large file range requests and partial caching behave differently per vendor; test video and downloads.

## Related
- [[caching-strategies]] - the general theory behind TTLs, invalidation and stampedes.
- [[blob-object-storage]] - the usual origin for images and video.
- [[load-balancing]] - regional balancing behind the edge.
- [[networking-fundamentals]] - DNS, anycast, TCP and TLS handshake costs the CDN removes.
- [[design-video-streaming]] - CDN-centric design.
- [[rate-limiting]] - edge-level limiting and bot protection.
- [[web-performance]] - browser-side caching, cache busting, images and resource hints.

## References
- MDN HTTP caching: https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching
- RFC 9111 HTTP Caching: https://www.rfc-editor.org/rfc/rfc9111
- Cloudflare cache docs: https://developers.cloudflare.com/cache/
- Amazon CloudFront developer guide: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/
