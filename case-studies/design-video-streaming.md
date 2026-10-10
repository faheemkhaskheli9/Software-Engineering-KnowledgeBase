---
title: Design a video streaming platform
category: case-studies
tags: [video-streaming, youtube, netflix, transcoding, hls, dash, cdn, adaptive-bitrate, case-study]
use_cases:
  - "design a YouTube style platform for uploading and watching videos"
  - "design a Netflix style on-demand streaming service with global delivery"
  - "build a transcoding pipeline that produces multiple resolutions and formats"
  - "keep playback smooth on varying networks with adaptive bitrate streaming"
  - "cut bandwidth cost for a video product using CDNs and caching tiers"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 14 'Design YouTube'"
  - https://www.rfc-editor.org/rfc/rfc8216.html
  - https://dashif.org/guidelines/
  - https://netflixtechblog.com/tagged/video-encoding
  - https://openconnect.netflix.com/en/
  - https://github.com/donnemartin/system-design-primer
---

# Design a video streaming platform

## Summary
A video platform lets creators upload videos, converts them into many
renditions, and delivers them to viewers worldwide with adaptive bitrate
streaming. Cost and latency are dominated by two things: the compute-heavy
transcoding pipeline on the write path, and bandwidth on the read path, which is
why delivery leans on CDNs and edge caches.

## Key concepts
- **Container and codec:** container (MP4, fMP4, MPEG-TS) holds codec streams (H.264/AVC, H.265/HEVC, VP9, AV1; audio AAC/Opus). Newer codecs save bandwidth at higher encode cost and varying device support.
- **Transcoding:** convert the source into a ladder of resolutions/bitrates (e.g. 240p to 4K) and formats.
- **Segmenting + adaptive bitrate (ABR):** split into short segments (a few seconds). HLS (RFC 8216) and MPEG-DASH publish a manifest listing renditions; the player picks the best rendition per segment based on measured throughput and buffer.
- **DAG pipeline:** split, encode, thumbnail, audio, watermark, subtitle tasks form a directed acyclic graph.
- **Origin + CDN:** object storage as origin, CDN edge caches deliver ([[cdn-and-edge]]).
- **Pre-signed uploads:** clients upload straight to object storage, not through app servers.
- **Live streaming** is a different (latency-first) problem: ingest via RTMP/SRT/WebRTC, low-latency HLS/DASH.

## When to use / scenarios
Applies to VOD platforms, course sites, internal video libraries, social video,
and video attachments in other products. For small catalogues use a managed service
(Mux, Cloudflare Stream, AWS MediaConvert + CloudFront) instead of building the pipeline;
build custom only when scale, cost or control justifies it. Live/interactive video
(video calls, auctions) needs WebRTC/SFU designs not covered here.

## How it works / example

### 1. Requirements
Functional: upload video; process into multiple qualities; stream with adaptive quality; search and browse (metadata);
thumbnails/previews; resume position; recommendations (out of scope detail); optional DRM for premium content; subtitles.

Non-functional: fast time-to-first-frame (target roughly 1-2 s, assumption); minimal rebuffering; high availability
of playback; reliable uploads of multi-GB files with resume; global reach; storage and bandwidth cost control;
copyright/abuse handling.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 5 M DAU, each watches 5 videos/day, average 10 minutes at about 3 Mbit/s average delivered bitrate:
  per-view data = 10 x 60 x 3 Mbit = 1.8 Gbit = 225 MB. Daily egress = 25 M views x 225 MB = about 5.6 PB/day, around 520 Gbit/s average.
  This is why CDN offload and cost dominate. (All figures are illustrative assumptions.)
- Uploads: assume 1% of DAU upload 1 video/day = 50k videos/day at avg 300 MB source = 15 TB/day raw.
- Renditions multiply stored size (rule of thumb: all renditions together often exceed the source size; measure).
- Transcoding CPU: video encoding is much slower than real time on CPU at high quality; budget with a benchmark of your own codec settings.

### 3. API
```
POST /v1/videos                  { title, description } -> { video_id, upload_url (pre-signed, multipart) }
PUT  <upload_url parts>          (client to object storage, resumable multipart)
POST /v1/videos/{id}/complete    -> 202 (starts processing)
GET  /v1/videos/{id}             -> metadata + status (processing|ready|failed) + manifest_url
GET  <cdn>/vod/{id}/master.m3u8  -> HLS master manifest; variant playlists; .m4s/.ts segments
POST /v1/videos/{id}/progress    { position_s }            (watch history, resume)
```
Authorization on manifests/segments with signed URLs or cookies ([[authorization-models]]).

### 4. Data model
```
video(id, owner_id, title, desc, status, duration, created_at, visibility, original_blob_ref)
rendition(video_id, profile[e.g. 1080p_h264], bitrate, codec, manifest_ref, size)
upload(video_id, parts[], state)
watch_progress(user_id, video_id, position, updated_at)
view_counts / analytics events -> stream pipeline
```
Metadata in a relational DB with read replicas and a cache, sharded later by `video_id`
([[sql-vs-nosql]], [[caching-strategies]]); video bytes in object storage ([[blob-object-storage]]);
search index separate ([[search-systems]]); watch events via streams ([[message-queues-and-streams]]).

### 5. High-level architecture
```
UPLOAD
 client --pre-signed multipart--> Object store (originals)
   --> "upload-complete" event --> Workflow/Task scheduler (DAG)
         |-- Splitter (GOP-aligned chunks)
         |-- Encoder worker pool (per chunk x per profile) --> Object store (renditions, segments)
         |-- Audio, thumbnails, subtitles, watermark, content-safety scan
         |-- Packager (HLS/DASH manifests, DRM encryption)
         '-- Update metadata DB: status=ready, invalidate caches

PLAYBACK
 player --> API (metadata, signed manifest URL) 
 player --> CDN edge --miss--> regional cache --miss--> origin (object store)
 player fetches master manifest, picks rendition, requests segments, switches with ABR logic
```
See [[cdn-and-edge]], [[api-gateway-and-service-mesh]], [[load-balancing]].

### 6. Deep dive A: the transcoding pipeline
Model as a DAG of tasks consumed from queues (see [[message-queues-and-streams]]):
1. Validate and probe the file (codec, duration, corrupt streams); reject bad input early.
2. Split the video into GOP-aligned chunks (each independently decodable) so encoding parallelises across
   many workers and a failed chunk is retried alone (`ffmpeg` segment muxer).
3. For each chunk and each profile in the ladder, encode; a stitched result is later packaged into segments.
   Use a per-title or per-shot ladder to save bits (Netflix has published on this) when scale justifies it.
4. Generate audio tracks, thumbnails/sprites, captions (speech-to-text optional), watermark.
5. Package HLS/DASH manifests, optionally encrypt with CENC/DRM keys.
6. Mark ready; publish an event for search indexing and notifications ([[design-notification-system]]).

Operational notes: tasks are idempotent and write to deterministic output paths so retries are safe
([[idempotency-and-exactly-once]]); use spot/preemptible workers for cost; prioritise short/popular uploads;
make the encode job-level state durable in a workflow engine so a scheduler crash resumes.

```python
LADDER = [("240p", 400), ("480p", 1000), ("720p", 2800), ("1080p", 5000)]   # kbps, illustrative
def plan(video):
    chunks = split_on_keyframes(video, target_s=10)
    return [Task("encode", c, p) for c in chunks for p, _ in LADDER] + \
           [Task("package", video, after="encode"), Task("thumbs", video)]
```

### 7. Deep dive B: adaptive streaming and delivery
HLS master playlist lists variants (resolution, bandwidth). The player starts conservatively, measures
download throughput and buffer level, then upgrades or downgrades per segment (e.g. 2-6 s segments). Short segments
adapt faster but add request overhead; long ones are efficient but slow to adapt. Delivery optimisation:
- CDN with tiered caching (edge -> regional -> origin shield) so origin sees few requests. Large streamers deploy
  caches inside ISPs (e.g. Netflix Open Connect) to cut transit cost.
- Pre-position (push) popular titles to edges during off-peak; long-tail titles pulled on demand.
- Cache key by segment URL; segments are immutable, so TTLs can be long and invalidation rarely needed.
- Prefer HTTP/2 or HTTP/3 and keep-alive connections; avoid redirects on the segment path.

### 8. Deep dive C: reliable large uploads and storage lifecycle
Use multipart/resumable uploads (S3 multipart, tus protocol): the client uploads parts in parallel, retries failed parts,
and finalises with a manifest of ETags. Validate size and type limits and scan for malware/copyright (fingerprint
matching against a reference DB). Lifecycle: keep originals on cheaper storage, keep popular renditions hot,
move cold renditions to infrequent-access tiers, and re-encode lazily on demand for very long-tail content.
Store deterministic paths: `/{video_id}/{profile}/seg_{n}.m4s`.

### 9. Scaling and failure handling
- Playback availability is the priority: serve from CDN even if the origin or metadata DB is degraded; cache manifests.
- Multiple CDNs with health-based steering protect against a single-CDN outage.
- Encode farm autoscales on queue age ([[capacity-planning-and-autoscaling]]); poison inputs go to a DLQ.
- Metadata DB scaled with replicas, caching and sharding; view counters are approximate and aggregated asynchronously
  (do not do a DB write per view).
- Observability: time-to-first-frame, rebuffer ratio, bitrate distribution, CDN hit ratio, encode queue wait
  ([[observability-logs-metrics-traces]], [[slis-slos-error-budgets]]).
- Geo restrictions, signed URLs with short expiry, hotlink protection, and DRM for premium content.

## Trade-offs
- More renditions and better codecs cut bandwidth and improve quality but raise encode cost and storage; AV1 saves bits but needs more compute and device support.
- Shorter segments adapt faster and lower latency but increase request overhead and manifest size.
- Pre-encode everything vs just-in-time transcoding: JIT saves storage for the long tail but adds first-play latency and CPU spikes.
- Own CDN/ISP caches reduce cost massively at large scale but need business relationships and operations; use commercial CDNs until traffic justifies it.
- Strong DRM protects content but restricts devices and complicates playback.

## Gotchas
- Sending uploads through application servers; they become bandwidth bottlenecks. Use pre-signed direct upload.
- Non-GOP-aligned splitting causes visual glitches at chunk boundaries.
- Cache stampede at origin when a viral new video is requested simultaneously; use origin shield and request coalescing.
- Rendition/profile changes without versioned paths make CDN caches inconsistent.
- Counting views with a synchronous DB increment.
- Forgetting audio/video sync, variable frame rate and rotation metadata in user-uploaded files.
- Unbounded retries of a permanently failing encode burn compute.
- Egress cost surprises: model bandwidth early; it often exceeds compute cost.

## Related
- [[cdn-and-edge]] - delivers the segments; main cost lever
- [[blob-object-storage]] - originals, renditions and multipart upload
- [[message-queues-and-streams]] - the DAG task queue and view-event streams
- [[caching-strategies]] - manifest, metadata and hot-title caching
- [[capacity-planning-and-autoscaling]] - scaling the encode farm
- [[back-of-envelope-estimation]] - bandwidth and storage sizing
- [[design-notification-system]] - "your video is ready" notifications

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 14 (Design YouTube)
- RFC 8216 HTTP Live Streaming: https://www.rfc-editor.org/rfc/rfc8216.html
- DASH Industry Forum guidelines: https://dashif.org/guidelines/
- Netflix Tech Blog, video encoding posts: https://netflixtechblog.com/tagged/video-encoding
- Netflix Open Connect: https://openconnect.netflix.com/en/
