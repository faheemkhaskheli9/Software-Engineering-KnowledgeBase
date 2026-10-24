---
title: Browser security - same-origin policy, CORS, CSP and security headers
category: security
tags: [same-origin-policy, cors, csp, content-security-policy, hsts, security-headers, xss, clickjacking, samesite, frame-ancestors]
use_cases:
  - "configure CORS so a single-page app on another origin can call our API with cookies"
  - "browser says blocked by CORS policy: No Access-Control-Allow-Origin header"
  - "add a Content Security Policy to limit the damage of XSS"
  - "choose the baseline HTTP security headers for a web app"
  - "stop our pages being framed by other sites (clickjacking)"
status: draft
last_verified: 2026-10-24
sources:
  - https://fetch.spec.whatwg.org/
  - https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS
  - https://www.w3.org/TR/CSP3/
  - https://web.dev/articles/strict-csp
  - https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
  - https://www.rfc-editor.org/rfc/rfc6797
  - https://www.rfc-editor.org/rfc/rfc6454
---

# Browser security - same-origin policy, CORS, CSP and security headers

## Summary
Browsers run code from many sites side by side, so they enforce the
same-origin policy: script from one origin cannot read responses or DOM from
another. CORS is the server's way to selectively relax that for reads by
other origins; it is not an authentication or CSRF control. Content Security
Policy and the other security response headers (HSTS, `X-Content-Type-Options`,
`frame-ancestors`, `Referrer-Policy`, cookie attributes) are defence in depth
that limits what injected script, framing and downgrade attacks can do. They
complement, never replace, output encoding and server-side authorization.

## Key concepts
- **Origin** = scheme + host + port (RFC 6454). `https://app.example.com` and
  `https://api.example.com` are different origins; they are the same *site*
  (same registrable domain), which matters for `SameSite` cookies.
- **Same-origin policy**: cross-origin *sending* is mostly allowed (links,
  form posts, `<img>`, `<script>`), cross-origin *reading* by script is not.
  That asymmetry is why CSRF exists and why CORS does not stop it.
- **CORS** (Fetch standard): the browser adds `Origin`; the server answers
  with `Access-Control-Allow-Origin` (one origin or `*`) and, for cookies,
  `Access-Control-Allow-Credentials: true`, which cannot be combined with
  `*`. Requests with non-simple methods, headers or content types first send
  an `OPTIONS` *preflight* with `Access-Control-Request-Method/-Headers`;
  `Access-Control-Max-Age` lets the browser cache the answer.
- **`Vary: Origin`** is required when the allowed origin is echoed per
  request, or caches serve one origin's CORS answer to another.
- **CSP**: a response header listing where scripts, styles, frames and
  connections may come from. A *strict* CSP uses a per-response random nonce
  (or hashes) plus `'strict-dynamic'` instead of host allowlists, and sets
  `object-src 'none'` and `base-uri 'none'`. `Content-Security-Policy-Report-Only`
  reports violations without blocking, for rollout.
- **Clickjacking**: `frame-ancestors` in CSP (or the older
  `X-Frame-Options: DENY`) controls who may frame your pages.
- **HSTS** (RFC 6797): `Strict-Transport-Security: max-age=...;
  includeSubDomains` makes the browser use HTTPS only for that host, so
  SSL-stripping downgrades fail after the first visit; the preload list
  covers the first visit too.
- **Other baseline headers** (OWASP HTTP Headers Cheat Sheet):
  `X-Content-Type-Options: nosniff`, a `Referrer-Policy` such as
  `strict-origin-when-cross-origin`, `Permissions-Policy` to disable unused
  features, and cookies with `Secure`, `HttpOnly` and `SameSite`. The old
  `X-XSS-Protection` filter is deprecated; do not rely on it.

## When to use / scenarios
- An SPA, mobile web view or partner site on another origin calls your API:
  configure CORS with an explicit origin allowlist. Same-origin deployment
  (serve the API under the app's origin through a gateway or CDN path) avoids
  CORS entirely ([[api-gateway-and-service-mesh]], [[cdn-and-edge]]).
- Any app that renders user-controlled content: add a strict CSP as the
  second line of defence against XSS ([[owasp-top-10]]).
- Every HTML response: HSTS, `nosniff`, `frame-ancestors`, `Referrer-Policy`,
  secure cookie attributes; set them centrally in middleware or at the edge.
- Pure JSON APIs used only by servers do not need CORS headers; browsers are
  the only enforcers. Omit CORS rather than adding `*` "just in case".
- When NOT to lean on these: CORS does not protect an API from non-browser
  clients, and CSP does not fix an injection bug. Authorization still runs on
  every request ([[authorization-models]]); CSRF still needs SameSite cookies
  or tokens ([[authentication-and-sessions]]).

## How it works / example

```
browser (origin https://app.example.com)            api.example.com
  OPTIONS /orders  Origin: https://app.example.com
                   Access-Control-Request-Method: DELETE  ----->
  <----- 204  Access-Control-Allow-Origin: https://app.example.com
              Access-Control-Allow-Methods: GET, POST, DELETE
              Access-Control-Allow-Credentials: true   Vary: Origin
  DELETE /orders/7 (with cookies)                           ----->
  <----- 200 + same Allow-Origin/Credentials -> script may read the body
```

A framework-free policy layer: CORS decisions from an allowlist, a per-request
nonce CSP, and the baseline headers.

```python
import secrets

ALLOWED_ORIGINS = {"https://app.example.com", "https://admin.example.com"}
ALLOWED_METHODS = {"GET", "POST", "DELETE"}
ALLOWED_HEADERS = {"content-type", "authorization"}

def cors_headers(method, req_headers):
    """Return CORS response headers, or {} to let the browser block the read."""
    origin = req_headers.get("origin")
    if origin not in ALLOWED_ORIGINS:          # exact match, never substring/regex
        return {"Vary": "Origin"}
    h = {"Access-Control-Allow-Origin": origin,
         "Access-Control-Allow-Credentials": "true",
         "Vary": "Origin"}
    if method == "OPTIONS":                    # preflight
        want_method = req_headers.get("access-control-request-method", "")
        want_headers = {x.strip().lower() for x in
                        req_headers.get("access-control-request-headers", "").split(",") if x.strip()}
        if want_method not in ALLOWED_METHODS or not want_headers <= ALLOWED_HEADERS:
            return {"Vary": "Origin"}
        h["Access-Control-Allow-Methods"] = ", ".join(sorted(ALLOWED_METHODS))
        h["Access-Control-Allow-Headers"] = ", ".join(sorted(ALLOWED_HEADERS))
        h["Access-Control-Max-Age"] = "600"
    return h

def security_headers():
    nonce = secrets.token_urlsafe(16)          # new nonce on every response
    csp = "; ".join([
        f"script-src 'nonce-{nonce}' 'strict-dynamic'",
        "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
    ])
    return nonce, {
        "Content-Security-Policy": csp,
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }

# Allowed origin with cookies: echoed origin, never "*".
h = cors_headers("GET", {"origin": "https://app.example.com"})
assert h["Access-Control-Allow-Origin"] == "https://app.example.com"
assert h["Vary"] == "Origin"

# Lookalike origins get nothing, so the browser hides the response.
for evil in ("https://app.example.com.evil.test", "null", "http://app.example.com"):
    assert "Access-Control-Allow-Origin" not in cors_headers("GET", {"origin": evil})

# Preflight: allowed method and headers pass, unknown header is refused.
ok = cors_headers("OPTIONS", {"origin": "https://app.example.com",
                              "access-control-request-method": "DELETE",
                              "access-control-request-headers": "Content-Type"})
assert "DELETE" in ok["Access-Control-Allow-Methods"]
bad = cors_headers("OPTIONS", {"origin": "https://app.example.com",
                               "access-control-request-method": "DELETE",
                               "access-control-request-headers": "X-Debug"})
assert "Access-Control-Allow-Methods" not in bad

n1, h1 = security_headers()
n2, _ = security_headers()
assert n1 != n2 and f"'nonce-{n1}'" in h1["Content-Security-Policy"]
html = f'<script nonce="{n1}" src="/app.js"></script>'   # only nonced scripts run
print(h1["Content-Security-Policy"])
```

## Trade-offs
- **Same origin vs CORS**: routing the API under the app's origin removes
  preflights and CORS mistakes but couples deployment and routing; separate
  origins keep services independent at the cost of preflight round trips
  (reduce with `Access-Control-Max-Age`).
- **Credentialed vs token CORS**: cookies with `Allow-Credentials` keep tokens
  out of JavaScript but require CSRF defences; bearer tokens in a header
  avoid CSRF but are readable by any injected script.
- **Strict nonce CSP vs allowlist CSP**: nonces resist bypasses through
  allowed hosts (JSONP endpoints, open CDNs) but need server-rendered nonces
  and break inline event handlers; allowlists suit static hosting but are
  often bypassable.
- **HSTS scope**: `includeSubDomains` and preload protect every subdomain but
  break any subdomain still served over plain HTTP, and preload removal is
  slow; start with a short `max-age` and raise it.
- **Report-only first vs enforce now**: report-only finds breakage safely but
  protects nothing until switched to enforcing.

## Gotchas
- Reflecting any `Origin` back with `Allow-Credentials: true`: every website
  can now read authenticated responses. Match an exact allowlist.
- Allowlist checks with `endswith`, substring or unanchored regex accept
  `app.example.com.evil.test` or `evilexample.com`.
- Allowing `Origin: null`: sandboxed iframes and `file:` pages send it, so an
  attacker can produce it on demand.
- Thinking CORS blocks the request: simple cross-origin POSTs still reach the
  server and change state; only reading the response is blocked. Use
  `SameSite` cookies or CSRF tokens.
- Missing `Vary: Origin` on cached responses: a CDN serves one origin's CORS
  headers to everyone ([[caching-strategies]]).
- Error responses (401, 500, gateway errors) without CORS headers show up in
  the browser as a CORS failure, hiding the real error.
- A static or reused CSP nonce is no protection; generate one per response
  and never cache the HTML with its nonce at a shared cache.
- `unsafe-inline` in `script-src` without a nonce or hash cancels most of
  CSP's XSS protection.
- Security headers set in the app but stripped or overridden by a proxy or
  CDN; verify the headers clients actually receive.

## Related
- [[owasp-top-10]] - injection and XSS, which CSP mitigates but does not fix.
- [[authentication-and-sessions]] - cookie attributes, SameSite and CSRF defences.
- [[oauth2-and-oidc]] - browser-based token flows that run into CORS and storage choices.
- [[cryptography-and-tls]] - TLS that HSTS forces every request onto.
- [[api-gateway-and-service-mesh]] - setting CORS and headers centrally at the edge.
- [[cdn-and-edge]] - caching with `Vary: Origin` and adding headers at the edge.
- [[threat-modeling]] - deciding which browser-side threats apply.

## References
- WHATWG Fetch Standard (CORS protocol, preflight, credentials): https://fetch.spec.whatwg.org/
- MDN, "Cross-Origin Resource Sharing (CORS)": https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS
- W3C, Content Security Policy Level 3: https://www.w3.org/TR/CSP3/
- web.dev, "Mitigate cross-site scripting (XSS) with a strict Content Security Policy": https://web.dev/articles/strict-csp
- OWASP HTTP Headers Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
- RFC 6797, HTTP Strict Transport Security: https://www.rfc-editor.org/rfc/rfc6797
- RFC 6454, The Web Origin Concept: https://www.rfc-editor.org/rfc/rfc6454
