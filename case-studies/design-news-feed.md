---
title: Design a news feed
category: case-studies
tags: [news-feed, timeline, fan-out, twitter, facebook, ranking, caching, case-study]
use_cases:
  - "design a Twitter or Facebook style home timeline from the people a user follows"
  - "decide between fan-out on write and fan-out on read for a social feed"
  - "handle celebrity accounts with millions of followers without melting the write path"
  - "serve a personalised, paginated feed in under 200 ms"
  - "add a ranked activity feed to our product"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 11 'Design a News Feed System'"
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017, ch. 1 (Twitter timelines)"
  - https://www.infoq.com/presentations/Twitter-Timeline-Scalability/
  - https://github.com/donnemartin/system-design-primer
---

# Design a news feed

## Summary
A news feed shows each user a reverse-chronological or ranked list of recent
posts from accounts they follow. The central design question is when to
assemble the feed: at write time (push the post into followers' precomputed
timelines) or at read time (pull and merge on request). Production systems use a hybrid.

## Key concepts
- **Fan-out on write (push):** on posting, insert the post ID into every
  follower's timeline cache. Reads are a single fast lookup; writes cost O(followers).
- **Fan-out on read (pull):** at read time, fetch recent posts from each followee and merge.
  Writes are cheap; reads are expensive and slow.
- **Hybrid:** push for normal users, pull for celebrities (followers above a threshold),
  and merge the two at read time. Kleppmann describes Twitter's move to this.
- **Timelines hold IDs, not content;** hydrate post bodies from a post cache/store.
- **Ranking:** chronological is simple; ML ranking scores candidates by relevance,
  recency and engagement.
- **Social graph:** follower/followee relationships, read-heavy, needs both directions.
- **Cursor pagination** keeps scrolling stable while new items arrive ([[pagination-filtering-sorting]]).

## When to use / scenarios
Use when users consume a merged stream of items produced by many sources:
social feeds, activity streams, notifications inbox, "what's new" in a team
tool, marketplace updates. If each user follows only a handful of sources,
pull-on-read with a good index is simplest. If reads vastly outnumber writes
and follower counts are bounded, pure push works.

## How it works / example

### 1. Requirements
Functional: publish post (text, media); follow/unfollow; view home feed; view a user's profile timeline;
likes/comments counts (kept simple here); pagination; optional ranking.

Non-functional: feed read latency under about 200 ms p99 (target); high availability;
eventual consistency is fine (a new post may appear seconds late); handle skewed follower
distribution; 90%+ traffic is reads.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 300 M DAU, each opens the feed 10 times/day -> 3 B feed reads/day -> about 35k reads/s average, peak 3x.
- Assume 10% post daily, 1 post each -> 30 M posts/day, about 350 writes/s.
- Average 200 followers -> push fan-out of 30 M x 200 = 6 B timeline inserts/day, about 70k inserts/s average. Celebrities with 50 M followers make single posts cost tens of millions of inserts.
- Timeline cache: keep newest ~800 post IDs (8 bytes each) per active user: about 6.4 KB x 300 M users = about 1.9 TB (shardable in memory across a cluster; cache only active users to cut it down).

### 3. API
```
POST /v1/posts                      { text, media_ids[] }              -> 201 { post_id }
POST /v1/users/{id}/follow          DELETE to unfollow                 -> 204
GET  /v1/feed?cursor=<opaque>&limit=20   -> { items:[post...], next_cursor }
GET  /v1/users/{id}/posts?cursor=...
```
Authentication and rate limits per user ([[authentication-and-sessions]], [[rate-limiting]]).

### 4. Data model
```
posts(post_id PK(time-ordered), author_id, text, media_refs, created_at)     -- sharded by post_id/author
follows(follower_id, followee_id, created_at)  + reverse index (followee -> followers)
timeline:{user_id}   -- Redis sorted set / list of (post_id, score=ts), capped length
post_cache:{post_id} -- hydrated post bodies
counters             -- likes/comments, eventually consistent
```
Time-ordered IDs (Snowflake style, [[unique-id-generation]]) let the post ID double as the sort key.
Graph storage: sharded relational table or KV with both directions
([[partitioning-and-sharding]], [[sql-vs-nosql]]).

### 5. High-level architecture
```
 client --> LB --> API gateway --> Post service --> Post DB (sharded)
                                        |
                                        +--> Kafka "post-created"
                                                   |
                                          Fan-out workers
                                         /      |       \
                             Social graph svc   |   skip if author is "celebrity"
                                                v
                                     Timeline cache (Redis, per user)
 client --> Feed service --> Timeline cache (IDs) + celebrity pull merge
                       \--> hydrate: Post cache -> Post DB, User cache, counters
                       \--> optional Ranking service
 media --> object store + CDN
```
See [[caching-strategies]], [[message-queues-and-streams]], [[cdn-and-edge]], [[blob-object-storage]].

### 6. Deep dive A: fan-out strategy
Fan-out worker (push path):
```python
CELEB_THRESHOLD = 100_000        # tune from follower distribution (assumption)
def on_post_created(post):
    n = graph.follower_count(post.author_id)
    if n >= CELEB_THRESHOLD:
        return                                   # pulled at read time
    for batch in graph.followers_batched(post.author_id, size=1000):
        redis.pipeline_zadd_all(
            [(f"timeline:{f}", {post.id: post.ts}) for f in batch],
            cap=800)                             # trim to newest 800
```
Read path (merge pushed and pulled):
```python
def home_feed(user, cursor, limit=20):
    ids = redis.zrevrangebyscore(f"timeline:{user}", cursor_ts(cursor), "-inf", limit=limit)
    celebs = graph.followed_celebrities(user)            # small list, cached
    for c in celebs:
        ids += recent_posts(c, since=cursor_ts(cursor), limit=limit)
    ids = top_n_by_time_or_rank(ids, limit)
    return hydrate(ids)                                  # batch multi-get from post cache
```
Why hybrid: pure push cannot afford a 50 M-follower account (one post = 50 M writes, minutes of lag
and a write storm), and pure pull makes every feed open scan hundreds of followees.
Inactive users: skip pushing into timelines of users who have not logged in for N days; rebuild on
their next visit from a pull ("cold start" path).

### 7. Deep dive B: ranking and hydration
Chronological feed = merge of sorted lists. Ranked feed adds: candidate generation (the
timeline plus recommendations), feature fetch (affinity, recency, post engagement), a
scoring model, and filters (blocked/muted, seen). Keep ranking behind a time budget
(e.g. 50 ms) with fallback to chronological if it times out ([[resilience-patterns]]).
Hydration is the latency risk: a 20-item page triggers 20 post lookups + author profiles +
counters. Use batched multi-gets, a post cache keyed by `post_id`, and denormalise author
name/avatar into the cached post. Counters can lag; do not block rendering on them.

### 8. Deep dive C: pagination and consistency
Offset pagination breaks as new posts shift positions; use opaque cursors encoding
`(ts, post_id)` of the last item. Each page query is "items older than the cursor".
Deletions: tombstone the post, filter at hydrate time instead of editing millions of timelines.
Unfollow: lazily filter on read and let old entries age out of the capped list.
Edits: update the post store; timeline stores only IDs, so edits propagate automatically.

### 9. Scaling and failure handling
- Shard timeline cache by `user_id` ([[consistent-hashing]]); replicate for availability; a lost
  timeline is rebuildable from the post store and the graph (derived data).
- Fan-out through a queue makes posting fast and failure-tolerant: workers retry, and the
  insert is idempotent (set add of the same post ID) ([[idempotency-and-exactly-once]]).
- Back-pressure: prioritise fan-out for recently active users; shed or delay low-priority work in spikes.
- Hot posts: heavily cached and CDN-served; counters batched.
- Multi-region: replicate posts globally, build timelines locally per region.
- Monitoring: fan-out lag, timeline hit ratio, hydration latency, p99 feed latency ([[observability-logs-metrics-traces]]).

## Trade-offs
- Push gives O(1) reads but heavy, bursty writes and wasted work for inactive followers; pull is the opposite.
- The celebrity threshold is a tunable that trades read cost against write cost.
- Storing full posts in timelines speeds reads but multiplies storage and complicates edits; store IDs.
- Ranked feeds raise engagement but need ML infrastructure and reduce explainability.
- Eventual consistency makes "my own post missing from my feed" visible; special-case the author's own posts (merge locally).

## Gotchas
- Fan-out-on-write for celebrities causes multi-minute write storms and uneven shard load.
- Unbounded timeline lists blow memory; always cap.
- Not handling deleted or private posts that remain in cached timelines (leak risk).
- Cache stampede when a popular user's timeline is rebuilt by many requests at once; coalesce.
- Mixing relevance ranking with pagination: scores shift between requests, so freeze a ranked snapshot per session or paginate on candidate IDs.
- Counting followers by `COUNT(*)` on each post; maintain counters.

## Related
- [[caching-strategies]] - timeline and post caches carry the read path
- [[message-queues-and-streams]] - asynchronous fan-out pipeline
- [[unique-id-generation]] - time-ordered post IDs as sort keys
- [[pagination-filtering-sorting]] - cursor pagination for infinite scroll
- [[partitioning-and-sharding]] - sharding posts, graph and timelines
- [[design-notification-system]] - sibling fan-out problem for alerts
- [[search-systems]] - post search is a separate index

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 11
- Kleppmann, *Designing Data-Intensive Applications*, ch. 1 (Twitter home timeline example)
- Raffi Krikorian, "Timelines at Scale" (QCon 2013): https://www.infoq.com/presentations/Twitter-Timeline-Scalability/
- System Design Primer: https://github.com/donnemartin/system-design-primer
