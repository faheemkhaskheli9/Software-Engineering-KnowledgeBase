---
title: Choosing file and media storage
category: scenarios
tags: [file-upload, object-storage, s3, presigned-url, cdn, media-processing, image, video, malware-scan, decision-guide]
use_cases:
  - "let users upload avatars, documents or videos and serve them back"
  - "decide between storing files in the database, on local disk, or in object storage"
  - "serve private files securely and public media fast"
  - "generate thumbnails and video renditions after upload"
  - "validate uploads so users cannot upload malware or oversized files"
status: stable
last_verified: 2026-10-10
sources:
  - https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html
  - https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PrivateContent.html
  - https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
  - https://cloud.google.com/storage/docs
  - https://www.usenix.org/conference/osdi10/finding-needle-haystack-facebooks-photo-storage
---

# Choosing file and media storage

## Summary
Put file bytes in object storage and file metadata (owner, key, size, type, status) in your database. Uploads go directly from the client to storage through short-lived presigned URLs, are validated and processed asynchronously, and are served through a CDN: public assets with long cache lifetimes, private files through short-lived signed URLs. Local disk and database BLOBs are only right for small, single-server or tightly transactional cases.

## Key concepts
- **Bytes vs metadata.** The bucket holds bytes; the database holds the record and is what you query. Never list buckets to find files.
- **Server-generated keys.** Keys come from the server (ids, tenant prefix), never from the user's filename.
- **Direct upload.** Presigned PUT or POST lets the client send bytes straight to storage, keeping large transfers off app servers; multipart for large files ([[blob-object-storage]]).
- **Upload state machine.** `pending -> uploaded -> scanned -> ready` (or `rejected`); only `ready` files are served.
- **Trust nothing the client declares.** Name, size and content type are claims; check magic bytes, size limits and scan for malware server-side.
- **Originals vs derivatives.** Keep the original untouched; produce thumbnails and renditions asynchronously under predictable keys.
- **Public vs private delivery.** Public: CDN with long TTL and versioned keys. Private: signed URLs or signed cookies with short expiry ([[cdn-and-edge]]).

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| User uploads (avatars, attachments, documents) | Object storage + DB metadata + presigned direct upload | [[blob-object-storage]], [[data-modeling-and-schema-design]] |
| Public media served worldwide | CDN in front of the bucket, fingerprinted/versioned keys | [[cdn-and-edge]], [[choosing-a-caching-strategy]] |
| Private files (invoices, medical scans) | Private bucket, short-lived signed URLs after an authorization check | [[authorization-models]], [[blob-object-storage]] |
| Thumbnails, image resizing | Async worker triggered by upload event, store derivatives | [[background-jobs-and-queues]], [[message-queues-and-streams]] |
| Video | Transcode to adaptive streaming renditions, serve segments via CDN | [[design-video-streaming]] |
| Very large files, unreliable networks | Multipart / resumable uploads | [[blob-object-storage]] |
| Tiny files that must commit atomically with a row | DB column (BLOB/bytea) is acceptable at small scale | [[transactions-and-isolation-levels]] |
| Single server prototype, no cloud | Local disk behind an interface you can swap for object storage | [[layered-hexagonal-clean-architecture]], [[twelve-factor-app]] |
| Multi-tenant SaaS | Tenant prefix in keys, per-tenant authorization on every signed URL | [[choosing-a-multi-tenancy-model]] |
| Backups, exports, logs, data lake | Object storage with lifecycle rules to colder tiers | [[blob-object-storage]], [[data-warehousing-and-olap]] |
| Self-hosting required | S3-compatible store (MinIO, Ceph) | [[blob-object-storage]] |

Decision flow:

```
More than one app server, or files larger than tiny?  -> object storage (not local disk, not DB)
Who may read it?
  anyone             -> public via CDN, immutable versioned keys, long TTL
  owner / tenant     -> private bucket, authz check, short-lived signed URL (or CDN signed cookie)
Needs processing (scan, resize, transcode)? -> upload event -> queue -> worker -> status=ready
```

When NOT to use object storage: small values updated in place many times a second, or data you query by content (that belongs in a database or search index). When NOT to store in the DB: files of any real size; they bloat backups, replication and the buffer cache.

## How it works / example
Upload flow:

```
 1. client -> API: POST /files {filename, size, type}
 2. API: authn/authz, size + type allow-list, INSERT files(status='pending', key=server key)
         -> presigned PUT URL (short expiry, content-type and length bound)
 3. client -> bucket: PUT bytes (multipart if large)
 4. bucket event -> queue -> worker: check magic bytes, AV scan, strip metadata,
         make derivatives -> status='ready' (or 'rejected' and delete)
 5. GET /files/{id}: authz -> public CDN URL or short-lived signed URL
 6. lifecycle: delete abandoned 'pending' objects and incomplete multipart uploads
```

Server-side key generation and content sniffing, runnable stdlib sketch (step 2 and the first check in step 4):

```python
import uuid

ALLOWED = {                                 # magic bytes -> (mime, extension)
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"%PDF-": ("application/pdf", "pdf"),
}

def object_key(tenant_id: int, user_id: int) -> str:
    # never derived from the uploaded filename
    return f"t/{tenant_id}/u/{user_id}/{uuid.uuid4().hex}"

def sniff(head: bytes):
    for magic, kind in ALLOWED.items():
        if head.startswith(magic):
            return kind
    return None                              # reject: not an allowed type

if __name__ == "__main__":
    key = object_key(7, 42)
    assert key.startswith("t/7/u/42/") and ".." not in key
    assert sniff(b"\x89PNG\r\n\x1a\n....") == ("image/png", "png")
    assert sniff(b"MZ\x90\x00") is None       # a Windows executable claiming to be .png
    print(key)
```

Magic bytes only prove the header; still enforce size limits, re-encode images where possible, and run a malware scanner for documents. The presigned URL code (boto3) is in [[blob-object-storage]].

## Trade-offs
- **Direct upload vs proxy through the app:** direct upload saves app bandwidth and scales with the storage service, but validation happens after the bytes land; proxying allows inline checks but makes app servers carry every byte.
- **Public CDN vs private signed URLs:** public delivery is cheapest and fastest; private delivery protects data but signed URLs are bearer tokens and per-user URLs reduce cache sharing unless the CDN validates signatures itself.
- **Process on upload vs on first request:** eager derivatives cost compute for files nobody views; on-demand resizing needs a cache in front to avoid repeated work.
- **Managed vs self-hosted storage:** managed gives durability engineering for free but charges for egress and requests; self-hosted shifts durability and operations to you.
- **Storage tiers:** colder tiers cut storage cost but add retrieval fees and minimum durations; tier only data with known access patterns.

## Gotchas
- Using the user's filename as the key: path traversal, overwrites, PII in URLs.
- Trusting `Content-Type` or extension from the client; serve with your own detected type and `Content-Disposition: attachment` for documents to stop stored XSS from uploaded HTML/SVG.
- Public buckets by accident; block public access at the account level and expose files through the CDN or signed URLs only.
- Long-lived signed URLs logged or shared; keep expiry short and never log them.
- DB row and object out of sync (row deleted, object remains, or the reverse); use status states and a reconciliation job.
- Forgetting CORS configuration for browser direct uploads.
- Image processing libraries are attack surface (decompression bombs, parser bugs); run them in isolated workers with resource limits.
- Deletion promises (user request, tenant offboarding) must cover derivatives, CDN caches, versions and backups.

## Related
- [[blob-object-storage]] - object storage concepts, presigned URLs, lifecycle rules.
- [[cdn-and-edge]] - delivering media near users, signed URLs and cookies.
- [[background-jobs-and-queues]] - post-upload processing workers.
- [[design-video-streaming]] - large-media pipeline case study.
- [[owasp-top-10]] - upload-related injection and access-control risks.
- [[choosing-a-database]] - why metadata lives in the database.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- Amazon S3 User Guide (presigned URLs, multipart upload, lifecycle, Block Public Access).
- Amazon CloudFront Developer Guide, serving private content with signed URLs and signed cookies.
- OWASP File Upload Cheat Sheet.
- Google Cloud Storage documentation.
- Beaver et al., "Finding a needle in Haystack: Facebook's photo storage", OSDI 2010.
