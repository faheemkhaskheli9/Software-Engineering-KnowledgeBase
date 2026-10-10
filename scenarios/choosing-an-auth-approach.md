---
title: Choosing an auth approach
category: scenarios
tags: [authentication, authorization, sessions, jwt, oauth2, oidc, sso, passkeys, mtls, api-keys, decision-guide]
use_cases:
  - "how should users log in to our new web app: passwords, social login, or an identity provider"
  - "choose between server-side sessions and JWTs for a SPA or mobile app"
  - "add SSO for enterprise customers"
  - "authenticate service-to-service calls and third-party API clients"
  - "decide where authorization checks live once users are logged in"
status: draft
last_verified: 2026-10-10
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
  - https://pages.nist.gov/800-63-3/sp800-63b.html
  - https://www.rfc-editor.org/rfc/rfc9700
  - https://openid.net/specs/openid-connect-core-1_0.html
  - https://oauth.net/2/browser-based-apps/
  - https://www.w3.org/TR/webauthn-2/
---

# Choosing an auth approach

## Summary
Split the question in three: who is the caller (a person in a browser, a mobile app, another service, a third-party developer), who proves their identity (you, or an identity provider), and how the proof travels on each request (session cookie, access token, API key, client certificate). Default for a first-party web app is a server-side session in an `HttpOnly` cookie; reach for OIDC as soon as you need SSO or social login, OAuth 2.0 when a third party acts on a user's behalf, and client credentials or mTLS between services. Authorization is a separate decision made on every request after any of these.

## Key concepts
- **Authentication vs authorization.** Proving identity ([[authentication-and-sessions]]) is not deciding permissions ([[authorization-models]]). Keep them as separate layers.
- **Build vs delegate.** Running your own password store means owning hashing, resets, MFA, breach checks and lockout policy. An IdP (hosted or self-hosted) moves that work out of your app.
- **Credential carrier.** Opaque session id (state on the server, instant revocation) vs self-contained token such as a JWT (verifiable without a lookup, hard to revoke before expiry).
- **Caller types.** Browser on your domain, SPA, native/mobile app, CLI or device, backend service, third-party app. Each has a standard flow ([[oauth2-and-oidc]]).
- **Phishing resistance.** WebAuthn/passkeys bind the credential to the origin; passwords plus TOTP do not.
- **Revocation story.** Decide up front how a stolen credential or a fired employee is cut off, and how fast.

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| First-party server-rendered web app, own users | Server-side session in `HttpOnly; Secure; SameSite` cookie, Argon2id passwords, MFA | [[authentication-and-sessions]] |
| SPA on the same site as its API | Same session cookie (plus CSRF defence), or a backend-for-frontend that holds tokens | [[authentication-and-sessions]], [[oauth2-and-oidc]] |
| Mobile or native app calling your API | Authorization Code + PKCE against your IdP, short-lived access token + refresh token | [[oauth2-and-oidc]] |
| "Sign in with Google/Microsoft", B2B enterprise SSO | OIDC with an IdP; SAML only where customers require it | [[oauth2-and-oidc]] |
| Third-party apps act for your users | OAuth 2.0 authorization server with scopes and consent | [[oauth2-and-oidc]], [[api-versioning-and-evolution]] |
| Server-to-server integrations by customers | API keys (hashed at rest, scoped, rotatable) or OAuth client credentials | [[secrets-management]], [[rate-limiting]] |
| Your own services calling each other | mTLS / workload identity, or client-credentials tokens | [[api-gateway-and-service-mesh]], [[cryptography-and-tls]] |
| CLI or TV device | OAuth device authorization flow | [[oauth2-and-oidc]] |
| Who may do what after login | RBAC first, add ownership/tenant checks, ReBAC for sharing | [[authorization-models]] |
| Several services need the same identity | Validate tokens at the gateway and again (cheaply) in each service | [[api-gateway-and-service-mesh]] |

Decision flow:

```
Who is calling?
  a person
    need SSO, social login, or many apps sharing login? -> OIDC with an IdP
    single first-party web app?                         -> server session cookie (+ MFA / passkeys)
    native/mobile app?                                  -> Auth Code + PKCE, short access + refresh tokens
  a third-party app acting for a user                   -> OAuth 2.0 with scopes and consent
  a customer's server                                   -> scoped API key or client credentials
  one of our services                                   -> mTLS / workload identity or client credentials
Then, on every request: authorization check on the object (role + tenant + ownership)
```

When NOT to: do not issue JWTs to a single monolith just to avoid a session table; do not build an OAuth authorization server unless delegated access is your product; do not accept user sessions for service-to-service calls.

## How it works / example
A typical SaaS layout that combines the rows above:

```
 browser --cookie--> BFF / web app --access token--> API gateway --> services
                        |  (session holds tokens)        | validates JWT (iss, aud, exp, alg)
                        +--OIDC Auth Code + PKCE--> IdP  | per-service: authz on the object
 mobile app --Auth Code + PKCE--> IdP; Bearer token -----+
 partner server --API key / client credentials-----------+ (rate limited per key)
 service A --mTLS--> service B   (no user session involved)
```

Checklist for whichever row you pick:
- Credentials at rest: passwords with Argon2id (or bcrypt/scrypt per OWASP), API keys stored hashed, refresh tokens treated like passwords.
- Transport: TLS everywhere; cookies `Secure`, `HttpOnly`, `SameSite`.
- Session lifecycle: rotate the session id at login, server-side logout, idle and absolute timeouts.
- Token validation: pin algorithms, check `iss`, `aud`, `exp`; keep access tokens short-lived.
- Abuse: rate limit login, reset and token endpoints by account and IP ([[rate-limiting]]).
- Audit: log logins, MFA changes, role changes, impersonation.

## Trade-offs
| Axis | Server session | Self-contained token (JWT) | Delegated IdP (OIDC) |
|---|---|---|---|
| Revocation | Immediate (delete row) | At expiry, unless a denylist adds state | Depends on how your app holds the IdP result |
| Per-request cost | Session store lookup | Signature check, no lookup | Same as the carrier you choose after login |
| Fit | First-party web | APIs, many services, mobile | SSO, social, enterprise, many apps |
| Ops burden | Session store | Key rotation (JWKS) | Vendor cost or running Keycloak-style servers |

- **Hosted vs self-hosted IdP:** hosted removes security-critical operations from your team; self-hosted avoids per-user pricing and keeps data in-house.
- **Tokens in the browser vs BFF:** tokens in JavaScript are exposed to XSS; a backend-for-frontend keeps them server-side behind a session cookie at the cost of an extra hop.
- **Roles in token claims vs live lookup:** claims are fast but stale until expiry; lookups are fresh but cost a query (see [[authorization-models]]).

## Gotchas
- Using an OAuth access token as proof of who the user is; use the OIDC ID token for login.
- Long-lived JWTs with no revocation path; a leaked token stays valid until expiry.
- Storing tokens in `localStorage` when XSS is a realistic risk.
- Checking authorization at the route but not on the object (IDOR/BOLA); see [[owasp-top-10]].
- Forgetting non-HTTP entry points: background jobs, WebSocket subscriptions, webhooks and admin tools need identity and authorization too ([[realtime-websockets-sse]], [[webhooks]]).
- API keys in URLs end up in logs; send them in a header and never log them.
- Account enumeration through different messages on login, signup and reset.
- Adding SSO later to a password-only app is a migration (account linking, duplicate emails); plan the user-identity model early.

## Related
- [[authentication-and-sessions]] - passwords, sessions, MFA, cookie flags.
- [[oauth2-and-oidc]] - flows, PKCE, token validation.
- [[authorization-models]] - RBAC, ABAC, ReBAC once identity is known.
- [[secrets-management]] - signing keys, API keys, client secrets.
- [[choosing-a-multi-tenancy-model]] - tenant context as part of identity.
- [[threat-modeling]] - find spoofing and elevation-of-privilege paths before choosing.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- OWASP Authentication and Session Management cheat sheets.
- NIST SP 800-63B Digital Identity Guidelines.
- RFC 9700, OAuth 2.0 Security Best Current Practice.
- OpenID Connect Core 1.0.
- OAuth 2.0 for Browser-Based Apps (BFF pattern), https://oauth.net/2/browser-based-apps/
- W3C Web Authentication (WebAuthn) Level 2.
