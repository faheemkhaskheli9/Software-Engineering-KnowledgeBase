---
title: Authentication and sessions
category: security
tags: [authentication, passwords, argon2, sessions, cookies, jwt, mfa, csrf]
use_cases:
  - "add login with email and password to a web app and store passwords safely"
  - "choose between server-side sessions and JWTs for our API"
  - "add TOTP two-factor authentication"
  - "stop credential stuffing and brute-force attacks on the login endpoint"
  - "set cookie flags correctly for a session cookie"
status: stable
last_verified: 2026-10-10
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
  - https://pages.nist.gov/800-63-4/sp800-63b.html
  - https://www.rfc-editor.org/rfc/rfc6238
---

# Authentication and sessions

## Summary
Authentication proves who a caller is; a session carries that proof across
requests. Get three things right: store passwords with a slow memory-hard
hash, keep session identifiers unguessable and revocable, and layer MFA and
rate limiting against credential attacks. Prefer delegating to an identity
provider (see OIDC) over building this yourself when you can.

## Key concepts
- **Password storage:** salted, slow, memory-hard hash. OWASP's current
  preference order is Argon2id, then scrypt, then bcrypt (work factor 10+),
  then PBKDF2 (FIPS contexts). Never SHA-256/MD5 alone, never reversible
  encryption.
- **Session:** server issues an opaque random ID, stores state server-side
  (DB/Redis), sends it in a cookie. Revocation is trivial: delete the row.
- **Stateless token (JWT):** signed claims the client presents. Scales without
  a lookup but cannot be revoked before expiry without extra state.
- **MFA:** something you know plus have/are. TOTP (RFC 6238), WebAuthn/passkeys
  (phishing-resistant). SMS/voice OTP is a "restricted" authenticator in NIST
  SP 800-63B-4: allowed only with a stronger alternative offered.
- **NIST SP 800-63B-4 (2025) guidance:** at least 15 characters for a
  password used alone, no composition rules, check against a blocklist of
  breached and common passwords, no forced periodic rotation (only on evidence
  of compromise), support password managers and paste.

## When to use / scenarios
- Server-rendered or first-party web app: server-side sessions in an
  `HttpOnly` cookie. Default choice.
- Mobile/SPA calling your own API: still consider opaque tokens or sessions;
  use short-lived access tokens (JWT acceptable) plus refresh tokens.
- Third-party or enterprise login, social login: use OIDC, do not handle
  passwords at all.
- Service-to-service: mTLS or OAuth client credentials, not user sessions.
- Do NOT use JWTs "because everyone does" for a monolith with a session store.

## How it works / example

Password hashing with Argon2id (`pip install argon2-cffi`):

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()  # defaults follow current RFC 9106 low-memory profile

def register(password: str) -> str:
    return ph.hash(password)            # salt is generated and embedded

def login(stored_hash: str, password: str) -> bool:
    try:
        ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
    if ph.check_needs_rehash(stored_hash):   # upgrade params transparently
        ...  # re-hash and persist the new value
    return True
```

Session cookie issuance (framework-agnostic):

```python
import secrets

def new_session(store: dict, user_id: int) -> str:
    sid = secrets.token_urlsafe(32)          # 256 bits from the OS CSPRNG
    store[sid] = {"uid": user_id}
    return sid

# Always rotate the id at login (prevents session fixation) and set:
COOKIE_FLAGS = "HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=3600"
```

TOTP verification with the stdlib (`hmac`) shows how little magic there is:

```python
import hmac, hashlib, struct, time, base64

def totp(secret_b32: str, t=None, step=30, digits=6) -> str:
    key = base64.b32decode(secret_b32, casefold=True)
    counter = int((time.time() if t is None else t) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off+4])[0] & 0x7FFFFFFF) % 10**digits
    return str(code).zfill(digits)

# RFC 6238 Appendix B test vector (SHA-1, T=59s, 8 digits):
assert totp(base64.b32encode(b"12345678901234567890").decode(), t=59, digits=8) == "94287082"

# Verify with hmac.compare_digest, accept +/-1 step for clock skew,
# and store the last used step to block replay.
```

Login flow: rate limit by account and IP, generic error ("invalid credentials"),
constant-time compare, verify password, check MFA, regenerate session ID,
log the event.

## Trade-offs
- **Sessions vs JWT:** sessions give instant revocation and small cookies but
  need shared storage; JWTs avoid lookups but need short expiry plus a
  refresh/denylist strategy, which reintroduces state.
- **Cookies vs Authorization header:** cookies get `HttpOnly` protection from
  XSS theft but need CSRF defences; bearer tokens in JS-accessible storage are
  XSS-stealable but CSRF-immune.
- **Lockout vs throttling:** hard lockout enables denial of service against
  victims; progressive delays, CAPTCHA and per-IP limits are friendlier.
- **Argon2 cost:** higher memory/time is safer against offline cracking but
  costs login latency and server RAM. Benchmark on production hardware.

## Gotchas
- Fast hashes (SHA-256, even salted) are crackable at billions per second on
  GPUs; the slowness is the feature.
- Not rotating the session ID at login allows fixation.
- JWT pitfalls: accepting `alg: none` or algorithm confusion (RS256 vs HS256),
  not validating `exp`/`aud`/`iss`, storing them in `localStorage`.
- Account enumeration via different messages or timings on login, signup and
  password reset. Return the same response either way.
- Password reset tokens must be single-use, short-lived, random and stored
  hashed; never email a password.
- `SameSite=Lax` is not a full CSRF defence for state-changing GETs; keep GETs
  safe and add CSRF tokens for cookie-authenticated unsafe methods.
- Logging out must invalidate server-side state, not just delete the cookie.
- Truncating passwords silently (bcrypt's 72-byte limit) is a real bug; use
  Argon2 or pre-hash deliberately.

## Related
- [[oauth2-and-oidc]] - delegate login to an identity provider instead.
- [[authorization-models]] - what an authenticated user may do.
- [[cryptography-and-tls]] - hashing vs encryption, TLS for cookie `Secure`.
- [[rate-limiting]] - throttling login and reset endpoints.
- [[owasp-top-10]] - A07:2025 Authentication Failures.
- [[secrets-management]] - protecting signing keys and pepper values.

## References
- OWASP Authentication, Password Storage and Session Management cheat sheets.
- NIST SP 800-63B-4 Digital Identity Guidelines: Authentication and
  Authenticator Management (August 2025).
- RFC 6238 (TOTP); RFC 9106 (Argon2).
- W3C WebAuthn (latest level), https://www.w3.org/TR/webauthn/
