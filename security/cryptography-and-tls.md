---
title: Cryptography and TLS
category: security
tags: [cryptography, tls, aes-gcm, hashing, hmac, signatures, certificates, key-management]
use_cases:
  - "encrypt sensitive fields in our database before storing them"
  - "configure TLS correctly for a public API and internal services"
  - "choose between hashing, HMAC, encryption and digital signatures"
  - "verify a webhook signature safely"
  - "decide how to rotate encryption keys"
status: stable
last_verified: 2026-10-10
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html
  - https://www.rfc-editor.org/rfc/rfc8446
  - https://cryptography.io/en/latest/
  - https://csrc.nist.gov/projects/cryptographic-standards-and-guidelines
---

# Cryptography and TLS

## Summary
Applied cryptography for engineers is mostly about choosing the right
primitive, using a vetted library with safe defaults, and managing keys.
TLS protects data in transit; authenticated encryption protects data at rest;
hashes, MACs and signatures provide integrity and authenticity. Never design
your own algorithm or protocol.

## Key concepts
- **Hash (SHA-256/SHA-3):** one-way fingerprint, no key. For passwords use a
  password hash (Argon2id), not a plain hash.
- **MAC / HMAC:** keyed integrity and authenticity between parties sharing a
  secret. Compare with constant-time functions.
- **Symmetric encryption:** use **authenticated encryption (AEAD)**: AES-256-GCM
  or ChaCha20-Poly1305. A unique nonce per key and message is mandatory.
- **Asymmetric:** key exchange (X25519/ECDH), signatures (Ed25519, ECDSA,
  RSA-PSS), RSA-OAEP for encryption when needed. Slower; used to protect or
  authenticate keys and small messages.
- **TLS 1.3 (RFC 8446):** handshake authenticates the server with an X.509
  certificate chain, negotiates ephemeral keys (forward secrecy), then uses
  AEAD. Prefer TLS 1.3, allow 1.2 for compatibility, disable 1.1 and below.
- **Key management:** key hierarchy with a KMS/HSM holding master keys
  (envelope encryption), separate keys per purpose, rotation, access audit.
- **CSPRNG:** use `secrets` / `os.urandom` for anything security-relevant,
  never `random`.

## When to use / scenarios
- All network traffic, including internal: TLS (mTLS for service identity).
- Sensitive columns (PII, tokens): field-level AEAD with envelope keys, in
  addition to disk/database encryption.
- Webhook/message authenticity: HMAC-SHA256 with timestamp.
- Software artifacts and tokens needing public verification: digital
  signatures.
- NOT for: storing passwords with encryption, "encrypting" with base64/XOR,
  custom key-derivation schemes, ECB mode, MD5/SHA-1 for security purposes.

## How it works / example

AEAD encryption with `cryptography` (`pip install cryptography`):

```python
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

key = AESGCM.generate_key(bit_length=256)   # in prod: unwrapped from a KMS data key
aead = AESGCM(key)

def encrypt(plaintext: bytes, context: bytes) -> bytes:
    nonce = os.urandom(12)                    # 96-bit, unique per encryption
    return nonce + aead.encrypt(nonce, plaintext, context)  # context = AAD

def decrypt(blob: bytes, context: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return aead.decrypt(nonce, ct, context)   # raises InvalidTag if tampered
```

Bind the ciphertext to its row via `context` (for example `b"user:42:ssn"`) so
it cannot be copied to another record. Store a key id alongside the blob to
support rotation.

Webhook signature verification with replay protection:

```python
import hmac, hashlib, time

def verify(secret: bytes, body: bytes, ts: str, sig_hex: str, tolerance=300) -> bool:
    if abs(time.time() - int(ts)) > tolerance:
        return False                                       # stale / replay
    expected = hmac.new(secret, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_hex)         # constant time
```

Python client with certificate verification on (the default; never disable):

```python fragment
import ssl, urllib.request
ctx = ssl.create_default_context()
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
urllib.request.urlopen("https://example.com", context=ctx, timeout=10)
```

Server side: terminate TLS at a maintained proxy or load balancer, automate
certificates (ACME/Let's Encrypt), enable HSTS, redirect HTTP to HTTPS, and
test the configuration (for example with SSL Labs or testssl.sh).

## Trade-offs
- **Terminate TLS at the edge vs end-to-end:** edge is simpler and enables
  WAF/caching; end-to-end or mTLS inside the network protects against internal
  adversaries and satisfies stricter compliance.
- **Application-level vs disk/DB encryption:** disk encryption stops lost
  hardware only; app-level protects from DB admins and SQL injection dumps but
  breaks querying (searchable encryption needs blind indexes).
- **RSA vs elliptic curves:** curves give smaller keys and faster operations;
  RSA has the widest legacy support.
- **Short-lived certs vs long-lived:** short is safer and automatable; needs
  solid renewal monitoring.

## Gotchas
- Nonce reuse in AES-GCM is catastrophic: it reveals the XOR of the two
  plaintexts and the authentication subkey, so tags can be forged. Random
  96-bit nonces are fine for a bounded number of messages per key; rotate keys
  or use an AES-GCM-SIV/XChaCha construction for huge volumes.
- `verify=False` or custom `ssl._create_unverified_context` "to fix a cert
  error" silently removes TLS's authentication.
- Comparing MACs with `==` leaks timing.
- Encrypt-then-MAC matters if you ever use non-AEAD modes; just use AEAD.
- Losing the key means losing the data: back up and test recovery of keys.
- Certificate expiry outages are common; monitor expiry and automate renewal.
- Hard-coded keys, IVs or "salts" in source are not cryptography.
- Hashing low-entropy data (emails, phone numbers) is reversible by
  enumeration; use a keyed HMAC if you need pseudonymisation.

## Related
- [[authentication-and-sessions]] - password hashing and token signing in practice.
- [[secrets-management]] - where keys live, KMS, rotation and audit.
- [[networking-fundamentals]] - TCP/TLS handshake and HTTPS context.
- [[webhooks]] - HMAC signatures and replay protection for callbacks.
- [[owasp-top-10]] - A04:2025 Cryptographic Failures.
- [[load-balancing]] - TLS termination and certificate placement.
- [[privacy-and-pii-handling]] - field encryption and crypto-shredding for personal data.
## References
- RFC 8446 (TLS 1.3); OWASP Cryptographic Storage and TLS cheat sheets.
- NIST cryptographic standards and guidelines (SP 800-57 key management).
- Python `cryptography` documentation, https://cryptography.io/
- Server-side TLS guidelines (moved from Mozilla's wiki to the community
  TLSRef project), https://docs.tlsref.org/
- RFC 8996 (deprecating TLS 1.0 and 1.1); NIST SP 800-38D (GCM).
