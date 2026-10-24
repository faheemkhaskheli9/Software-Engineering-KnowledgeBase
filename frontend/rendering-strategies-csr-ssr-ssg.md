---
title: Rendering strategies (CSR, SSR, SSG, ISR, streaming, islands)
category: frontend
tags: [rendering, csr, ssr, ssg, isr, hydration, streaming-ssr, islands, spa, mpa, seo, edge-rendering]
use_cases:
  - "choose between a single-page app, server rendering and static generation for a new site"
  - "marketing pages are slow to show content and search engines index an empty shell"
  - "rebuild thousands of static product pages without a full site rebuild on every change"
  - "server-rendered page paints fast but buttons do not respond until hydration finishes"
  - "decide what to render at build time, at request time, at the edge or in the browser"
status: draft
last_verified: 2026-10-24
sources:
  - https://web.dev/articles/rendering-on-the-web
  - https://react.dev/reference/react-dom/client/hydrateRoot
  - https://react.dev/reference/react-dom/server/renderToPipeableStream
  - https://docs.astro.build/en/concepts/islands/
  - https://nextjs.org/docs/pages/building-your-application/data-fetching/incremental-static-regeneration
  - https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics
---

# Rendering strategies (CSR, SSR, SSG, ISR, streaming, islands)

## Summary
A rendering strategy decides where and when a page's HTML is produced: in the
browser after JavaScript runs (client-side rendering, CSR), on a server per
request (server-side rendering, SSR), once at build time (static site
generation, SSG), or at build time with periodic or on-demand regeneration
(incremental static regeneration, ISR). Server-produced HTML usually has to be
made interactive in the browser (hydration), which costs JavaScript and main
thread time. Pick per route by how fresh and personalised the content is, how
much interactivity it needs, and whether first paint and crawlability matter.

## Key concepts
- **CSR (single-page app)**: the server sends a near-empty HTML shell plus a
  bundle; the browser fetches data and builds the DOM. Fast subsequent
  navigation, slow first content, content invisible until JS runs.
- **SSR**: the server renders HTML per request with fresh data; the browser
  shows content immediately, then hydrates. Costs server CPU on every request
  and TTFB depends on the slowest data fetch.
- **SSG**: HTML is rendered at build time and served from a CDN. Fastest and
  cheapest to serve; content is as old as the last build.
- **ISR / on-demand revalidation**: static pages with a revalidation window
  (stale-while-revalidate) or a webhook that regenerates one page when its
  content changes, so large sites need no full rebuild.
- **Hydration**: attaching event handlers and component state to existing
  server HTML (React `hydrateRoot`). Until it finishes, the page looks ready
  but does not respond; mismatches between server and client output cause
  errors or re-rendering.
- **Streaming SSR**: send the HTML shell first and stream slower sections as
  their data arrives (React `renderToPipeableStream` with Suspense), so TTFB
  is not bound to the slowest query.
- **Islands / partial hydration**: ship static HTML and hydrate only the
  interactive components (Astro islands); most of the page sends no JS.
- **Server components / resumability**: frameworks that keep non-interactive
  components server-only, or resume server state without re-executing
  components, to cut hydration cost further.
- **Edge rendering**: SSR in CDN points of presence; lower latency to users,
  but data that lives in one region may make it slower, not faster.
- **Crawlability**: Google can render JavaScript, but rendering may be
  deferred and other crawlers and link-preview bots often do not run it;
  important content and metadata belong in the initial HTML.

## When to use / scenarios
| Route type | Strategy | Why |
|---|---|---|
| Docs, blog, marketing, landing pages | SSG (+ ISR for CMS edits) | Same for every visitor, changes rarely, must be fast and indexable |
| Large catalog (products, listings) | ISR or SSR with CDN caching | Too many pages to rebuild; mostly shared content |
| Personalised, fresh per request (dashboard after login, cart) | SSR, or CSR behind a server-rendered shell | Cannot cache per user at the CDN |
| Highly interactive app (editor, design tool, admin console) | CSR / SPA | Interaction dominates, SEO irrelevant, users stay long |
| Content page with a few widgets | Islands | Static HTML with small interactive parts |
| Slow backend queries on an SSR page | Streaming SSR | Paint shell and fast parts first |

When NOT to: do not SSR a logged-in internal tool just for SEO it does not
need; do not build a public content site as a pure SPA; do not move to edge
rendering when every request needs a round trip to a database in one region.

## How it works / example
Where the work happens for one page view:

```text
CSR:   browser --GET--> CDN (shell.html, app.js) -> run JS -> fetch API -> render DOM   (content late)
SSR:   browser --GET--> server: fetch data, render HTML -> browser paints -> hydrate     (content early)
SSG:   build: fetch data, render HTML -> CDN;  browser --GET--> CDN -> paint -> hydrate  (content early, as of build)
ISR:   like SSG, but a request after the window serves stale HTML and triggers a background re-render
```

A stdlib model of SSG plus ISR-style revalidation: pages are rendered once,
served from a cache, regenerated in the background after the window, and
regenerated immediately when the CMS calls a revalidate hook:

```python
import html
from dataclasses import dataclass

CMS = {"intro": "Hello", "pricing": "From 10 EUR"}   # stand-in for a content API
renders = []                                          # count of render calls

def render(slug: str) -> str:
    renders.append(slug)
    body = html.escape(CMS[slug])                    # escape: content is data
    return f"<!doctype html><title>{slug}</title><main>{body}</main>"

@dataclass
class Entry:
    html: str
    rendered_at: float

class StaticSite:
    def __init__(self, revalidate_s: float):
        self.revalidate_s = revalidate_s
        self.pages: dict[str, Entry] = {}
        self.pending: set[str] = set()               # background regenerations

    def build(self, now: float) -> None:              # SSG: render everything once
        for slug in CMS:
            self.pages[slug] = Entry(render(slug), now)

    def get(self, slug: str, now: float) -> str:
        entry = self.pages.get(slug)
        if entry is None:                             # page created after build
            entry = self.pages[slug] = Entry(render(slug), now)
        elif now - entry.rendered_at >= self.revalidate_s:
            self.pending.add(slug)                    # serve stale, refresh later
        return entry.html

    def run_background(self, now: float) -> None:
        for slug in self.pending:
            self.pages[slug] = Entry(render(slug), now)
        self.pending.clear()

    def revalidate(self, slug: str, now: float) -> None:   # CMS webhook
        self.pages[slug] = Entry(render(slug), now)

site = StaticSite(revalidate_s=60)
site.build(now=0)
assert len(renders) == 2
assert "Hello" in site.get("intro", now=10)          # cached, no render
assert len(renders) == 2

CMS["intro"] = "Hello <again>"
assert "Hello</main>" in site.get("intro", now=70)   # stale served once
site.run_background(now=71)
assert "Hello &lt;again&gt;" in site.get("intro", now=72)

CMS["pricing"] = "From 12 EUR"
site.revalidate("pricing", now=80)                   # on-demand, no waiting
assert "12 EUR" in site.get("pricing", now=81)

CMS["new"] = "Fresh page"
assert "Fresh page" in site.get("new", now=90)       # rendered on first request
print("renders:", renders)
```

Hydration and islands in the HTML (fragment):

```html
<!-- Server HTML is readable before any JS runs -->
<main>
  <article>...static article HTML, no JS...</article>
  <!-- Island: only this component ships and runs JavaScript -->
  <div id="cart-button" data-props='{"sku":"A1"}'><button disabled>Add to cart</button></div>
</main>
<script type="module" src="/islands/cart-button.3f9a.js" async></script>
```

## Trade-offs
- **First paint vs server cost**: SSR and SSG show content early; SSR pays CPU
  per request, SSG pays at build time and CDN-caches the rest.
- **Freshness vs cacheability**: per-request SSR is always fresh but hard to
  cache; SSG/ISR is cacheable but stale within its window. On-demand
  revalidation narrows the gap at the cost of wiring CMS webhooks.
- **Hydration cost vs developer model**: one framework rendering everywhere is
  simple to write but ships the whole component tree to hydrate; islands and
  server components ship less JS but split code into server and client parts.
- **SPA navigation vs MPA simplicity**: SPAs keep state across navigations and
  feel instant after load; multi-page apps are simpler, work without JS and
  get browser history, focus and caching for free.
- **Edge vs region**: edge SSR helps when data is cached or replicated near
  users; with one-region data, render near the data instead.

## Gotchas
- Server HTML that differs from the first client render (dates, random ids,
  `window` checks, locale) causes hydration mismatch errors and visible
  re-rendering.
- A fast-painting SSR page whose hydration is a long task has poor INP:
  users click buttons that do nothing ([[browser-rendering-and-core-web-vitals]]).
- Caching SSR output at a CDN without varying on cookies or auth leaks one
  user's personalised page to others; mark personalised responses
  `Cache-Control: private` ([[cdn-and-edge]]).
- SSG build time grows with page count; past some size you need ISR or
  on-demand generation, not a faster build machine.
- Injecting server data into a `<script>` tag for hydration without escaping
  `</script>` and `<!--` is an XSS hole ([[browser-security-cors-csp-headers]]).
- An SPA served with no server-side routing fallback returns 404 for deep
  links on refresh.
- Per-request data fetches in SSR run on your servers: an N+1 to a backend
  that was hidden in the browser now adds directly to TTFB.

## Related
- [[browser-rendering-and-core-web-vitals]] - how each strategy moves LCP, INP and CLS.
- [[web-performance]] - bundle size, code splitting and caching that decide hydration cost.
- [[cdn-and-edge]] - where static and ISR pages are cached and edge rendering runs.
- [[choosing-a-caching-strategy]] - stale-while-revalidate and invalidation behind ISR.
- [[browser-security-cors-csp-headers]] - CSP nonces and escaping serialized state in server HTML.
- [[accessibility-basics]] - server HTML and real links keep pages usable before and without JS.

## References
- Jason Miller and Addy Osmani, "Rendering on the Web", web.dev.
- React documentation: `hydrateRoot` and `renderToPipeableStream`.
- Astro documentation: "Islands architecture".
- Next.js documentation: "Incremental Static Regeneration (ISR)".
- Google Search Central: "Understand the JavaScript SEO basics".
