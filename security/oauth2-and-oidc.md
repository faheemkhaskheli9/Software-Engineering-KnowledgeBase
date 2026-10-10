---
title: OAuth 2.0 and OpenID Connect
category: security
tags: [oauth2, oidc, pkce, jwt, sso, authorization-code, tokens]
use_cases:
  - "add Sign in with Google to our web app"
  - "let a third-party app access our API on behalf of users"
  - "secure a single-page app or mobile app login with PKCE"
  - "authenticate machine-to-machine calls between our services"
  - "decide how to validate access tokens in our API"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc6749
  - https://www.rfc-editor.org/rfc/rfc7636
  - https://www.rfc-editor.org/rfc/rfc9700
  - https://openid.net/specs/openid-connect-core-1_0.html
  - https://oauth.net/2/
---

# OAuth 2.0 and OpenID Connect

## Summary
OAuth 2.0 is a delegation framework: a user (resource owner) lets a client
application obtain a limited access token for an API without sharing their
password. OpenID Connect (OIDC) is a thin identity layer on top that adds an
ID token and a standard way to learn who logged in. Use OAuth for
"authorise this app to call that API" and OIDC for "log this user in".

## Key concepts
- **Roles:** resource owner (user), client (your app), authorization server
  (issues tokens), resource server (the API).
- **Access token:** short-lived credential for the API; opaque string or JWT.
  **Refresh token:** long-lived, exchanges for new access tokens; protect it
  like a password. **ID token (OIDC):** a signed JWT asserting the user's
  identity to the client; never send it to an API as an access token.
- **Scopes:** coarse permissions requested by the client (`read:invoices`).
- **Grant types in practice:**
  - Authorization Code with **PKCE** (RFC 7636): the default for web, SPA,
    mobile and native apps.
  - Client Credentials: machine-to-machine, no user.
  - Device Authorization: TVs and CLIs.
  - Implicit and Resource Owner Password flows: deprecated; do not use
    (see the OAuth 2.0 Security Best Current Practice, RFC 9700).
- **Discovery:** OIDC providers publish `/.well-known/openid-configuration`
  with endpoints and the JWKS URL for signing keys.

## When to use / scenarios
- Social/enterprise SSO: OIDC with an existing IdP (Google, Entra ID, Okta,
  Keycloak, Auth0). Do not build your own authorization server unless that is
  your product.
- Public API with third-party developers: OAuth 2.0 with scopes and consent.
- Internal services: client credentials, or mTLS/workload identity if all
  parties are yours.
- NOT for plain first-party username/password apps with no SSO need; ordinary
  sessions are simpler (see authentication-and-sessions).

## How it works / example

Authorization Code + PKCE:

```
User/Browser        Client app             Auth server           API
   |  click login      |                        |                  |
   |<--redirect--------|  (code_challenge,state)|                  |
   |--------------authenticate + consent------->|                  |
   |<--redirect back with ?code=...&state=...---|                  |
   |  --> Client       |--POST /token code+code_verifier---------->|
   |                   |<--access_token, id_token, refresh_token---|
   |                   |--Authorization: Bearer access_token------>|
```

PKCE and state generation, plus the token exchange (`pip install requests`):

```python
import base64, hashlib, secrets, requests

def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge

verifier, challenge = pkce_pair()
state = secrets.token_urlsafe(16)          # bind to the user's session, check on return
auth_url = ("https://idp.example/authorize?response_type=code"
            f"&client_id=APP&redirect_uri=https://app.example/cb"
            f"&scope=openid%20profile%20email&state={state}"
            f"&code_challenge={challenge}&code_challenge_method=S256")

def exchange(code):
    r = requests.post("https://idp.example/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://app.example/cb",
        "client_id": "APP", "code_verifier": verifier}, timeout=10)
    r.raise_for_status()
    return r.json()
```

Validating a JWT access token in the API (`pip install pyjwt[crypto]`):

```python
import jwt
jwks = jwt.PyJWKClient("https://idp.example/.well-known/jwks.json")

def verify(token: str) -> dict:
    key = jwks.get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"],   # pin the algorithm
                      audience="https://api.example", issuer="https://idp.example")
```

Then check `scope`/roles claims for the specific operation (authorization).

## Trade-offs
- **JWT vs opaque access tokens:** JWTs validate offline and fast but cannot
  be revoked early; opaque tokens need introspection (RFC 7662) but revoke
  instantly. Short JWT lifetimes (5-15 min) are the usual compromise.
- **Hosted IdP vs self-hosted (Keycloak):** hosted reduces operational and
  security burden; self-hosted gives control and avoids per-user pricing.
- **Backend-for-frontend vs tokens in the browser:** a BFF keeps tokens off
  the SPA and uses an HttpOnly session cookie; more infrastructure, far less
  XSS token-theft exposure.
- **Scopes granularity:** coarse scopes are simple; fine-grained permissions
  belong in your authorization layer, not in the token.

## Gotchas
- Missing or unchecked `state` enables login CSRF; missing PKCE enables code
  interception, even for confidential clients under current BCP.
- Exact-match redirect URIs only. Wildcards and open redirects leak codes.
- Validate `iss`, `aud`, `exp`, signature and pin allowed algorithms. Accept
  ID tokens only for the client that requested them, check `nonce`.
- OAuth alone is not authentication. Using an access token to infer identity
  is the classic confused-deputy bug; use OIDC's ID token.
- Do not put sensitive data in JWT payloads; they are only signed, not
  encrypted.
- Refresh token rotation with reuse detection limits the damage of a leak.
- Do not store tokens in `localStorage` if XSS is a realistic risk.
- Clock skew breaks `exp`/`nbf` checks; allow small leeway.

## Related
- [[authentication-and-sessions]] - local sessions, JWT trade-offs, MFA.
- [[authorization-models]] - turning scopes and claims into permissions.
- [[cryptography-and-tls]] - JWT signature algorithms, JWKS key rotation.
- [[api-gateway-and-service-mesh]] - gateways often validate tokens at the edge.
- [[owasp-top-10]] - A07 and A01 failures around tokens and scopes.

## References
- RFC 6749 (OAuth 2.0), RFC 7636 (PKCE), RFC 9700 (OAuth 2.0 Security BCP).
- OpenID Connect Core 1.0, https://openid.net/specs/openid-connect-core-1_0.html
- RFC 7519 (JWT), RFC 7662 (Token Introspection).
- OAuth 2.1 draft, https://oauth.net/2.1/
