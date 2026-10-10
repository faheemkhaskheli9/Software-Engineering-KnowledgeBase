---
title: Blob and object storage
category: system-design
tags: [object-storage, s3, blob, presigned-url, multipart-upload, erasure-coding, lifecycle]
use_cases:
  - "store user uploads such as images, videos and documents cheaply and durably"
  - "let browsers upload large files directly to storage without passing through our servers"
  - "serve private files with expiring links"
  - "move old data to cheaper storage tiers automatically"
status: draft
last_verified: 2026-10-10
sources:
  - https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html
  - https://cloud.google.com/storage/docs
  - https://learn.microsoft.com/azure/storage/blobs/
  - "Martin Kleppmann, Designing Data-Intensive Applications, ch. 5-6"
  - https://www.usenix.org/conference/osdi10/finding-needle-haystack-facebooks-photo-storage
---

# Blob and object storage

## Summary
Object storage (Amazon S3, Google Cloud Storage, Azure Blob, MinIO, Ceph)
stores immutable-ish blobs addressed by key in flat buckets, accessed over
HTTP. It offers very high durability, near-unlimited capacity and low cost per
GB, in exchange for no in-place edits, no POSIX semantics and higher per-op
latency than a disk or database. It is the default home for files, media,
backups, logs and data-lake files.

## Key concepts
- **Bucket / container** and **object key**: flat namespace; "folders" are just key prefixes (`2026/10/img.jpg`).
- **Object** = bytes + metadata + (optional) version. Objects are written whole (PUT) and replaced, not patched.
- **Durability** achieved by replication across zones or erasure coding (split into data + parity shards so loss of several shards is recoverable at lower overhead than 3x copies). Vendors publish durability targets; read them in the provider docs.
- **Consistency**: major providers now offer strong read-after-write consistency for object PUT and LIST (S3 since Dec 2020); verify for your provider/store (some S3-compatible systems differ).
- **Multipart upload**: split big files into parts uploaded in parallel and resumed; required for objects above the single-PUT limit.
- **Presigned URL / SAS token / signed URL**: time-limited URL granting a specific operation on a specific key without sharing credentials.
- **Storage classes / lifecycle rules**: hot, infrequent access, archive tiers; rules transition or expire objects by age or prefix.
- **Versioning, object lock (WORM), cross-region replication**: protection against deletion, ransomware, regional loss.
- **Metadata separation**: DB holds the record (owner, key, size, mime, status); the bucket holds bytes.

## When to use / scenarios
- User-generated content: avatars, photos, video, attachments.
- Static website assets and CDN origin ([[cdn-and-edge]]).
- Backups, exports, logs, ML datasets, data-lake Parquet files ([[data-warehousing-and-olap]]).
- Any blob larger than a few hundred KB; storing these in a relational DB bloats backups and buffer cache.
- Not for: low-latency random small reads/writes or transactions (use a DB), frequently modified files with in-place updates (use block/file storage), or lists of millions of tiny objects you must scan often (cost and latency per request add up; pack them).

## How it works / example

Direct-to-storage upload keeps large bytes off your app servers:

```
 1. client -> API:  POST /uploads {name, size, type}
 2. API: authz check, create DB row status=pending, return presigned PUT URL (expires in minutes)
 3. client -> object store: PUT bytes (multipart for big files)   <-- bypasses our servers
 4. store -> event (S3 notification) -> queue -> worker: validate, scan, thumbnail, set status=ready
 5. reads: private -> presigned GET (short TTL); public -> CDN URL with long cache
```

Python (boto3) presigned upload and download, runnable with credentials:

```python
import boto3

s3 = boto3.client("s3")
BUCKET = "my-app-uploads"

def upload_url(key: str, content_type: str, expires: int = 600) -> str:
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )

def download_url(key: str, expires: int = 300) -> str:
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=expires
    )

if __name__ == "__main__":
    # key is server-generated, never trust a client-supplied path
    print(upload_url("u/42/6f1c-avatar.jpg", "image/jpeg"))
```

### Key design
- Generate keys server-side (UUID/ULID plus a prefix like `u/<user>/`), not from user filenames (collisions, path tricks, PII in URLs).
- Use content-hash keys for deduplication and immutable caching (`sha256/ab/cd...`).
- Older guidance said to randomize key prefixes to avoid hot partitions; S3 now scales request rate per prefix automatically, but check current provider docs for request-rate guidance.

### Lifecycle example
```
 0-30 days   standard (hot)
 30-90 days  infrequent access
 90+ days    archive tier
 temp/ prefix: expire after 1 day;  abort incomplete multipart uploads after 7 days
```

### Photo/video pipelines
Store original untouched; derive thumbnails and renditions asynchronously via
a queue ([[message-queues-and-streams]]); store derivatives under predictable
keys so the CDN can cache them. Video: transcode into HLS/DASH segments
([[design-video-streaming]]).

## Trade-offs
- **Presigned direct upload vs proxy through app**: direct saves bandwidth and CPU but you validate after the fact (size, type, malware) and need completion callbacks; proxying gives control at the cost of scale.
- **Public vs private objects**: public + CDN is cheapest; private + short-lived signed URLs protects data but defeats CDN caching unless you use CDN signed URLs/cookies.
- **Storage class**: cheaper tiers charge retrieval fees and minimum storage durations; wrong tiering costs more than it saves.
- **Replication scope**: cross-region replication adds resilience and cost; many apps only need multi-zone (default).
- **Self-hosted (MinIO, Ceph) vs managed**: control and no egress fees vs durability engineering and ops burden.
- **Small-file packing**: per-request pricing and latency favour batching small objects into larger archives or columnar files.

## Gotchas
- DB row and object can disagree: upload succeeds but row not marked, or row deleted but object remains. Use status states, reconciliation jobs and lifecycle cleanup.
- Trusting client-declared content type or size; enforce `Content-Length` conditions in the presign policy and validate server-side (magic bytes, AV scan).
- Public buckets by accident are a leading source of data leaks; block public access at account level and grant explicitly.
- Presigned URLs are bearer tokens: anyone with the link has access until expiry; keep TTLs short and never log them.
- CORS must be configured for browser direct uploads.
- Egress and request charges surprise teams; estimate them ([[back-of-envelope-estimation]]).
- LIST is slow/expensive for large prefixes; keep an index in the DB instead of listing buckets.
- Deleting versioned buckets/objects needs delete-markers handling; versioning also means storage cost growth.

## Related
- [[cdn-and-edge]] - the delivery layer in front of buckets.
- [[message-queues-and-streams]] - event-driven post-upload processing.
- [[design-video-streaming]] - large media storage and delivery design.
- [[secrets-management]] - credentials and signing keys for storage access.
- [[sql-vs-nosql]] - why metadata goes in a database and bytes in object storage.
- [[data-warehousing-and-olap]] - object storage as the data-lake substrate.

## References
- Amazon S3 user guide: https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html
- Google Cloud Storage docs: https://cloud.google.com/storage/docs
- Azure Blob Storage docs: https://learn.microsoft.com/azure/storage/blobs/
- Beaver et al., "Finding a needle in Haystack: Facebook's photo storage", OSDI 2010.
