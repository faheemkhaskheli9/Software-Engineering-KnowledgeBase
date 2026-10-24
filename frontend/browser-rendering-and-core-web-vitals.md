---
title: Browser rendering and Core Web Vitals
category: frontend
tags: [critical-rendering-path, dom, cssom, render-blocking, async, defer, long-tasks, core-web-vitals, lcp, inp, cls, rum, crux, lighthouse]
use_cases:
  - "find out why our landing page shows a blank screen for seconds before anything renders"
  - "fix a poor INP score where buttons feel laggy after a click"
  - "stop the page jumping around while images and ads load (CLS)"
  - "decide whether to trust Lighthouse lab scores or real-user field data"
  - "set up Core Web Vitals monitoring and alert at the 75th percentile"
status: draft
last_verified: 2026-10-11
sources:
  - https://developer.mozilla.org/en-US/docs/Web/Performance/Guides/Critical_rendering_path
  - https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script
  - https://web.dev/articles/vitals
  - https://web.dev/articles/defining-core-web-vitals-thresholds
  - https://web.dev/articles/lcp
  - https://web.dev/articles/inp
  - https://web.dev/articles/cls
  - https://web.dev/blog/inp-cwv-launch
  - https://web.dev/articles/optimize-long-tasks
  - https://web.dev/articles/lab-and-field-data-differences
---

# Browser rendering and Core Web Vitals

## Summary
A browser turns HTML, CSS and JavaScript into pixels through the critical
rendering path: parse HTML into the DOM, parse CSS into the CSSOM, combine them
into a render tree, compute layout, paint and composite. Anything that blocks
that path (render-blocking CSS, parser-blocking scripts) or occupies the main
thread (long JavaScript tasks) delays what the user sees and how fast the page
reacts. Core Web Vitals are Google's three user-centric metrics for this:
LCP (loading), INP (responsiveness) and CLS (visual stability), judged at the
75th percentile of real page loads.

## Key concepts
- **DOM:** built incrementally as HTML bytes are parsed. A classic `<script>` without `async`/`defer` halts parsing until it is fetched and executed, because it may modify the DOM.
- **CSSOM:** built from all stylesheets. CSS is render-blocking: MDN notes the browser blocks rendering until it has received and processed all the CSS, since later rules can override earlier ones.
- **Render tree:** DOM plus computed styles for visible nodes only; `<head>` and `display: none` subtrees are excluded.
- **Layout (reflow):** computes size and position of every box; depends on viewport width. **Paint** fills pixels; **composite** assembles painted layers (transforms and opacity on their own layer can animate without layout or paint).
- **`async` vs `defer`:** both fetch in parallel with parsing. `async` scripts run as soon as they arrive, in no guaranteed order; `defer` scripts run in document order after parsing, before `DOMContentLoaded`. Module scripts are deferred by default.
- **Main thread and long tasks:** parsing, style, layout, and your JavaScript share one main thread. web.dev defines a long task as any task taking longer than 50 ms; while one runs, input cannot be handled.
- **LCP (Largest Contentful Paint):** render time of the largest image, text block or video visible in the viewport, relative to navigation start.
- **INP (Interaction to Next Paint):** latency from a click, tap or key press until the browser next paints a frame; hover and scroll are not counted. It reports roughly the worst interaction, ignoring one highest interaction per 50. INP replaced FID (First Input Delay) as a Core Web Vital in March 2024.
- **CLS (Cumulative Layout Shift):** each shift scores impact fraction x distance fraction; shifts are grouped into session windows (under 1 s apart, at most 5 s long) and CLS is the worst window. Shifts within 500 ms of a discrete user input are excluded.
- **Field vs lab data:** field data (also called RUM, real user monitoring; Chrome's public dataset is CrUX) comes from real visits on real devices and networks. Lab data (Lighthouse, WebPageTest) comes from a controlled, repeatable load. INP cannot be measured reliably in the lab; Total Blocking Time (TBT) is the lab proxy used to diagnose it.

Thresholds from web.dev, assessed at the 75th percentile of page loads, segmented by mobile and desktop:

| Metric | Good | Needs improvement | Poor |
|---|---|---|---|
| LCP | <= 2500 ms | 2500-4000 ms | > 4000 ms |
| INP | <= 200 ms | 200-500 ms | > 500 ms |
| CLS | <= 0.1 | 0.1-0.25 | > 0.25 |

## When to use / scenarios
- Blank page for a long time, then everything appears at once: look for render-blocking CSS and synchronous scripts in `<head>`; this mostly hurts LCP.
- Clicks feel sluggish, or a menu opens late: long tasks on the main thread (hydration, large event handlers, third-party scripts); this is INP.
- Content jumps when images, ads, embeds or web fonts load: missing reserved space; this is CLS.
- Release gating: track the three metrics from field data at p75 per page template and per device class, and use lab runs in CI to catch regressions before they reach users.
- Not the right tool for API or backend capacity questions; use [[performance-and-load-testing]] and server-side latency SLOs ([[slis-slos-error-budgets]]) there. Core Web Vitals measure the user's page experience, of which server time (TTFB) is only one part.

## How it works / example

```
bytes -> HTML parser -> DOM ----\
            |  (blocked by       +--> render tree -> layout -> paint -> composite
            |   sync <script>)   |
CSS  ----> CSSOM ---------------/   (render waits for all CSS)
```

Script loading choices:

```html
<!-- blocks the parser while it downloads and runs -->
<script src="legacy.js"></script>
<!-- runs whenever it arrives, any order: analytics, independent widgets -->
<script async src="analytics.js"></script>
<!-- runs in order after parsing: application code that needs the DOM -->
<script defer src="app.js"></script>
<!-- modules are deferred by default -->
<script type="module" src="main.js"></script>
```

Classifying field samples the way a dashboard would: take the 75th percentile
of each metric and compare it with the web.dev thresholds. Nearest-rank
percentile here; real tools use their own percentile and aggregation methods.

```python
import math

# (good_max, poor_min) from web.dev; values above poor_min are "poor"
THRESHOLDS = {"LCP": (2500, 4000), "INP": (200, 500), "CLS": (0.1, 0.25)}

def p75(samples):
    ordered = sorted(samples)
    rank = math.ceil(0.75 * len(ordered))      # nearest-rank method
    return ordered[rank - 1]

def classify(metric, samples):
    good_max, poor_min = THRESHOLDS[metric]
    value = p75(samples)
    if value <= good_max:
        return value, "good"
    if value <= poor_min:
        return value, "needs improvement"
    return value, "poor"

# 3 of 4 visits are fast, so p75 is still good even with one slow outlier
assert classify("LCP", [1200, 1800, 2400, 9000]) == (2400, "good")
assert classify("INP", [80, 150, 320, 340]) == (320, "needs improvement")
assert classify("CLS", [0.0, 0.02, 0.3, 0.4]) == (0.3, "poor")
assert classify("LCP", [2500] * 4)[1] == "good"     # boundary is inclusive
print("ok")
```

Breaking up a long task so input can be handled between chunks (browser
JavaScript; `scheduler.yield()` with a `setTimeout` fallback, per web.dev):

```javascript
function yieldToMain() {
  if (globalThis.scheduler?.yield) return scheduler.yield();
  return new Promise(resolve => setTimeout(resolve, 0));
}

async function processAll(items) {
  for (const item of items) {
    process(item);
    await yieldToMain();      // lets pending clicks and paints run
  }
}
```

## Trade-offs
- **Field vs lab:** field data is the truth about users but is noisy, delayed and needs traffic; lab data is immediate and reproducible but runs on one device and network profile and cannot see real interactions. Use lab for debugging and CI, field for goals.
- **Inlining critical CSS vs caching it:** inlining the above-the-fold CSS removes a render-blocking request but is re-sent with every HTML response and cannot be cached separately.
- **Client-side rendering vs server rendering:** a client-rendered shell can show nothing until a large bundle runs (hurting LCP); server rendering paints sooner but hydration can create long tasks that hurt INP.
- **Yielding often vs throughput:** more yields keep the page responsive but add scheduling overhead, so total work takes slightly longer.
- **Third-party scripts:** analytics, ads and chat widgets bring business value and main-thread cost you do not control; load them `async` or after the page is interactive, and budget them ([[web-performance]]).

## Gotchas
- A good Lighthouse score does not mean good INP; the lab never clicks the way users do, and TBT is only a proxy.
- CrUX and most dashboards report p75 over a rolling window, so a fix takes time to show up in field numbers.
- Lazy-loading the hero image delays LCP; only lazy-load images outside the initial viewport.
- Images, iframes and ad slots without `width`/`height` (or `aspect-ratio`) reserve no space and cause layout shifts; so do web fonts swapping in with different metrics and banners inserted above content.
- Animating `top`, `left`, `width` or `height` forces layout every frame; animate `transform` and `opacity` instead.
- Reading layout (`offsetHeight`, `getBoundingClientRect`) right after writing styles forces a synchronous layout; batch reads before writes.
- `async` scripts can execute in the middle of parsing and in any order; never use `async` for scripts that depend on each other.
- FID is retired; dashboards or SLOs still keyed on FID are measuring a metric Chrome tools no longer guarantee.

## Related
- [[web-performance]] - the techniques (bundles, caching, images, preload, budgets) that move these metrics.
- [[accessibility-basics]] - focus management and stable layouts help both a11y and CLS.
- [[performance-and-load-testing]] - percentiles, regression gating and backend-side load testing.
- [[observability-logs-metrics-traces]] - collecting RUM metrics alongside server telemetry.
- [[slis-slos-error-budgets]] - turning p75 LCP/INP/CLS into SLOs.
- [[cdn-and-edge]] - lower TTFB and faster asset delivery feed LCP.
- [[processes-threads-and-io-models]] - event loops and why one busy thread blocks input.
- [[rendering-strategies-csr-ssr-ssg]] - choosing CSR, SSR, SSG, ISR or islands per route, and the hydration cost of each.

## References
- MDN, Critical rendering path: https://developer.mozilla.org/en-US/docs/Web/Performance/Guides/Critical_rendering_path
- MDN, `<script>` element (`async`, `defer`, modules): https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script
- web.dev, Web Vitals: https://web.dev/articles/vitals
- web.dev, How the Core Web Vitals thresholds were defined: https://web.dev/articles/defining-core-web-vitals-thresholds
- web.dev, LCP / INP / CLS metric pages: https://web.dev/articles/lcp, https://web.dev/articles/inp, https://web.dev/articles/cls
- web.dev, INP becomes a Core Web Vital (March 2024): https://web.dev/blog/inp-cwv-launch
- web.dev, Optimize long tasks: https://web.dev/articles/optimize-long-tasks
- web.dev, Why lab and field data can differ: https://web.dev/articles/lab-and-field-data-differences
