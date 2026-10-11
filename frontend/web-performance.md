---
title: Web performance
category: frontend
tags: [bundle-size, code-splitting, compression, brotli, gzip, cache-control, etag, cache-busting, lazy-loading, responsive-images, avif, webp, preload, preconnect, performance-budget]
use_cases:
  - "our JavaScript bundle is huge and the first load on mobile is slow"
  - "set Cache-Control so returning visitors do not re-download assets after every deploy"
  - "serve smaller images to phones and modern formats to browsers that support them"
  - "speed up loading of fonts and third-party resources with preload and preconnect"
  - "add a performance budget to CI so page weight does not creep up"
status: draft
last_verified: 2026-10-11
sources:
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching
  - https://www.rfc-editor.org/rfc/rfc9111
  - https://www.rfc-editor.org/rfc/rfc9110
  - https://www.rfc-editor.org/rfc/rfc8246
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Compression
  - https://developer.mozilla.org/en-US/docs/Web/Performance/Guides/Lazy_loading
  - https://web.dev/articles/browser-level-image-lazy-loading
  - https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Responsive_images
  - https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Image_types
  - https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/preload
  - https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/preconnect
  - https://web.dev/articles/performance-budgets-101
---

# Web performance

## Summary
Front-end performance work is mostly about sending fewer bytes, sending them
once, and asking for the important ones first. The main levers are smaller
JavaScript (code splitting, removing dependencies), compression, HTTP caching
with content-hashed filenames, right-sized images in modern formats loaded
lazily below the fold, resource hints (`preload`, `preconnect`) for critical
requests, and a performance budget that fails the build when a page gets
heavier. The effect is measured with the Core Web Vitals
([[browser-rendering-and-core-web-vitals]]).

## Key concepts
- **Bundle size and code splitting:** ship the code a route needs, load the rest on demand. MDN lists entry-point splitting and dynamic splitting at `import()` expressions. JavaScript costs download, parse, compile and execute time on the main thread, so bytes of JS hurt more than bytes of images.
- **Compression:** browsers send `Accept-Encoding`, the server picks an algorithm and labels it with `Content-Encoding`; MDN names `gzip` and `br` (Brotli) as the relevant ones. Responses must carry `Vary: Accept-Encoding` so caches keep the variants apart. Do not recompress images, audio or video; they are already compressed.
- **Freshness (`Cache-Control: max-age`):** how long a stored response may be reused without asking the server (RFC 9111).
- **`immutable` (RFC 8246):** the server promises not to change the resource during its freshness lifetime, so clients skip revalidation even on a normal reload.
- **Validation (`ETag` / `If-None-Match`, `304 Not Modified`):** once stale, the client sends the stored ETag; if it still matches, the server answers 304 with no body. RFC 9110 requires the weak comparison function for `If-None-Match`, and a recipient must ignore `If-Modified-Since` when `If-None-Match` is present.
- **`no-cache` vs `no-store`:** `no-cache` allows storing but requires revalidation before every reuse (right for HTML); `no-store` forbids storing at all and also forfeits features like the back/forward cache.
- **Cache busting:** put a content hash in subresource URLs (`app.3f9a1c.js`) and cache them for a long time with `immutable`; the HTML that references them is revalidated each time, so a deploy changes the URLs it points to.
- **Lazy loading:** `loading="lazy"` on `<img>` and `<iframe>` defers off-screen resources until the user scrolls near them.
- **Responsive images:** `srcset` with `w` descriptors plus `sizes` lets the browser pick a file for the slot width and pixel density (resolution switching); `<picture>` with `media` serves different crops (art direction) or different formats with fallbacks.
- **Image formats:** MDN recommends WebP or AVIF for raster images, JPEG as the lossy photo fallback, PNG for lossless screenshots and transparency, and SVG for icons, logos and diagrams.
- **Resource hints:** `preload` fetches a resource needed soon at high priority (needs `as`; fonts also need `crossorigin`); `preconnect` opens DNS+TCP+TLS to a cross-origin host early; `dns-prefetch` does only the DNS step.
- **Performance budget:** a limit the team agrees not to exceed, expressed as quantities (KB of JS, number of requests), milestone timings, or rule-based scores (Lighthouse).

## When to use / scenarios
- Slow first load on mobile with a large JS bundle: analyse the bundle, split by route, lazy-import heavy widgets (editors, charts, maps), drop unused dependencies.
- Returning visitors re-download everything after each deploy: hashed asset filenames with long `max-age` and `immutable`, HTML with `no-cache`.
- Image-heavy pages: responsive `srcset`, AVIF/WebP with fallback, explicit `width`/`height`, lazy-load below the fold, eager (and possibly `fetchpriority="high"`) for the LCP image.
- Fonts or a critical API on another origin: `preload` the font file, `preconnect` to the few most critical third-party origins.
- A team keeps regressing page weight: add a budget check to CI ([[ci-cd-pipelines]]).
- Not first: if the server takes seconds to produce HTML, fix the backend and put a CDN in front ([[cdn-and-edge]], [[caching-strategies]]) before tuning the front end.

## How it works / example

The recipe MDN gives for cache busting:

```http
# /assets/app.3f9a1c.js  (URL changes whenever content changes)
Cache-Control: public, max-age=31536000, immutable

# /index.html  (URL cannot change; always revalidate)
Cache-Control: no-cache
ETag: "AAPuIbAOdvAGEETbgAAAAAAABAAE"
```

Images and hints:

```html
<link rel="preconnect" href="https://cdn.example.com">
<link rel="preload" href="/fonts/body.woff2" as="font" type="font/woff2" crossorigin>

<!-- LCP hero: eager, sized, modern format with fallback -->
<picture>
  <source srcset="hero-800.avif 800w, hero-1600.avif 1600w" type="image/avif">
  <img src="hero-800.jpg" srcset="hero-800.jpg 800w, hero-1600.jpg 1600w"
       sizes="(width <= 800px) 100vw, 800px" width="800" height="450" alt="...">
</picture>

<!-- below the fold -->
<img src="chart.webp" loading="lazy" width="600" height="400" alt="...">
```

A build step that fingerprints assets and picks headers, plus the server side
of an `If-None-Match` check (weak comparison, per RFC 9110):

```python
import hashlib

def hashed_name(filename: str, content: bytes, length: int = 8) -> str:
    stem, dot, ext = filename.rpartition(".")
    digest = hashlib.sha256(content).hexdigest()[:length]
    return f"{stem}.{digest}.{ext}"

def cache_control(path: str) -> str:
    if path.endswith(".html"):
        return "no-cache"                               # revalidate every time
    return "public, max-age=31536000, immutable"        # hashed asset

def etag_for(content: bytes) -> str:
    return '"' + hashlib.sha256(content).hexdigest()[:16] + '"'

def opaque(tag: str) -> str:
    return tag.strip().removeprefix("W/")                # weak comparison ignores W/

def respond(content: bytes, if_none_match: str | None):
    etag = etag_for(content)
    if if_none_match is not None:
        tags = [t for t in if_none_match.split(",") if t.strip()]
        if if_none_match.strip() == "*" or any(opaque(t) == etag for t in tags):
            return 304, {"ETag": etag}, b""
    return 200, {"ETag": etag}, content

v1, v2 = b"console.log(1)", b"console.log(2)"
assert hashed_name("app.js", v1) != hashed_name("app.js", v2)   # new content, new URL
assert hashed_name("app.js", v1) == hashed_name("app.js", v1)   # stable across builds
assert hashed_name("app.js", v1).startswith("app.") and hashed_name("app.js", v1).endswith(".js")
assert cache_control("index.html") == "no-cache"
assert "immutable" in cache_control(hashed_name("app.js", v1))

status, headers, body = respond(v1, None)
assert status == 200 and body == v1
tag = headers["ETag"]
assert respond(v1, tag)[0] == 304                  # unchanged -> 304, no body
assert respond(v1, "W/" + tag)[0] == 304           # weak match also counts
assert respond(v1, '"other", ' + tag)[0] == 304    # any tag in the list
assert respond(v2, tag)[0] == 200                  # changed -> full response
print("ok")
```

A budget check is the same idea applied to build output: sum compressed sizes
per route and fail CI when the total exceeds the agreed limit.

## Trade-offs
- **Many small chunks vs few large ones:** finer splitting sends less unused code but adds requests and can create waterfalls of dependent imports; split at routes and heavy features, not every module.
- **Long `max-age` vs ability to fix mistakes:** a cached-forever asset cannot be recalled; this is safe only when the URL changes with the content. Un-hashed URLs need short TTLs or revalidation.
- **Compression level vs CPU:** higher levels give smaller files at more CPU; precompress static assets at build time at a high level and use a cheaper level for dynamic responses.
- **Preload vs bandwidth contention:** every preload competes with other early requests; preloading things that are not needed soon slows down what is.
- **Modern image formats vs pipeline cost:** AVIF/WebP save bytes but need an encoding step, multiple variants and fallbacks; an image CDN can do this per request at a price.
- **Budgets strict vs advisory:** a failing build stops regressions but blocks releases on noisy measurements; gate on deterministic sizes, report timings as trends.

## Gotchas
- Lazy-loading the LCP image or anything in the initial viewport makes LCP worse; web.dev advises lazy-loading only images outside the initial viewport.
- Missing `width`/`height` on images and iframes causes layout shift (CLS) when they load.
- Hashing on build time or a version number instead of content invalidates every file on each deploy; hash the content.
- `immutable` or a long `max-age` on `index.html` strands users on an old build that points at deleted assets.
- Deleting the previous deploy's hashed assets breaks clients still running the old HTML; keep old assets for a while.
- A font `preload` without `crossorigin` is fetched twice, because the eventual font request is made in anonymous CORS mode.
- Preconnecting to many origins is counterproductive; MDN recommends `preconnect` only for the most critical ones and `dns-prefetch` for the rest.
- Without `Vary: Accept-Encoding`, a shared cache can serve Brotli bytes to a client that did not ask for them.
- ETags that differ per server (inode-based, per-instance) behind a load balancer turn every revalidation into a full 200.
- Responses with no `Cache-Control` are still cached heuristically; always send an explicit policy.

## Related
- [[browser-rendering-and-core-web-vitals]] - the rendering model and the metrics these techniques improve.
- [[cdn-and-edge]] - where these headers are enforced at scale, and the header recipe per content type.
- [[choosing-a-caching-strategy]] - browser and CDN layers within the overall caching decision.
- [[caching-strategies]] - TTLs, invalidation and validation in general.
- [[rest-api-design]] - ETags and conditional requests for API responses.
- [[ci-cd-pipelines]] - where bundle-size budgets run.
- [[internationalization-and-localization]] - per-locale bundles and fonts add to page weight.

## References
- MDN, HTTP caching: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Caching
- RFC 9111, HTTP Caching: https://www.rfc-editor.org/rfc/rfc9111
- RFC 9110, HTTP Semantics, sections 8.8.3 (ETag) and 13.1.2 (If-None-Match): https://www.rfc-editor.org/rfc/rfc9110
- RFC 8246, HTTP Immutable Responses: https://www.rfc-editor.org/rfc/rfc8246
- MDN, Compression in HTTP: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Compression
- MDN, Lazy loading: https://developer.mozilla.org/en-US/docs/Web/Performance/Guides/Lazy_loading
- web.dev, Browser-level image lazy loading: https://web.dev/articles/browser-level-image-lazy-loading
- MDN, Responsive images: https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Responsive_images
- MDN, Image file type and format guide: https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Image_types
- MDN, `rel=preload` and `rel=preconnect`: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/preload, https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/rel/preconnect
- web.dev, Performance budgets 101: https://web.dev/articles/performance-budgets-101
