---
title: Design a web crawler
category: case-studies
tags: [web-crawler, spider, url-frontier, politeness, deduplication, bloom-filter, robots-txt, case-study]
use_cases:
  - "design a crawler that fetches billions of pages for a search index"
  - "build a polite scraper that respects robots.txt and per-site rate limits"
  - "detect and skip duplicate pages and URLs during a large crawl"
  - "keep crawled content fresh by re-crawling pages at the right frequency"
  - "make a crawler resilient to spider traps, slow hosts and crashes"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 9 'Design a Web Crawler'"
  - https://nlp.stanford.edu/IR-book/html/htmledition/web-crawling-and-indexes-1.html
  - https://www.rfc-editor.org/rfc/rfc9309.html
  - https://research.google/pubs/the-anatomy-of-a-large-scale-hypertextual-web-search-engine/
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
---

# Design a web crawler

## Summary
A web crawler discovers and downloads pages by following links from seed URLs,
feeding a search index, an ML corpus or an archive. Design pressure comes from
scale (billions of pages), politeness (never hammer one site), freshness
(re-crawl what changes), and robustness (malformed HTML, traps, slow servers).
The central structure is the URL frontier.

## Key concepts
- **Crawl loop:** pick URL from frontier -> resolve DNS -> fetch -> parse -> extract
  links -> dedupe -> add new URLs to the frontier -> store content.
- **URL frontier:** a prioritised, politeness-aware queue of URLs to fetch.
- **Politeness:** limit concurrent/frequent requests per host; honour `robots.txt`
  (RFC 9309) and `Crawl-delay`-style hints; identify yourself with a User-Agent and contact.
- **Priority:** by page importance (PageRank-like score, domain authority), update frequency, depth.
- **Deduplication:** URL-level (seen set, canonicalisation) and content-level
  (hashes, SimHash/MinHash near-duplicate detection).
- **Freshness:** re-crawl based on observed change rate (HTTP `ETag`/`Last-Modified`, sitemaps).
- **Spider traps:** infinite calendars, session IDs in URLs, dynamically generated link graphs.

## When to use / scenarios
Use for search engines, price/market monitoring, link-graph analysis, archival
(Internet Archive style) and training data collection. For a small known set of
sites, a simple scheduler with a per-host rate limit is enough; reach for the
distributed design only past what one machine and a database queue can handle.
Respect legal and ethical limits: terms of service, copyright, personal data.

## How it works / example

### 1. Requirements
Functional: start from seed URLs; fetch HTML (and optionally other content types); extract links;
store raw/parsed content for downstream indexing; re-crawl for freshness; support filters
(domains, content types, depth); report crawl status.

Non-functional: scalable (parallelise across machines), polite, robust (crash recovery, bad HTML,
timeouts), extensible (new content types such as images/PDF), efficient (no duplicate work), and
observable.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Target 1 B pages/month -> about 400 pages/s average (1e9 / 2.6e6).
- Average page 500 KB with resources, but fetch HTML only maybe 100 KB: 400 x 100 KB = 40 MB/s ingress
  (about 320 Mbit/s), over a month about 100 TB raw HTML. Compress to roughly 25-35 TB (assumes 3-4x gzip ratio).
- URL records: 1 B x 100 bytes = 100 GB for the seen-set metadata; a Bloom filter at 1% false positive
  needs about 9.6 bits per element (about 1.2 GB for 1 B) as a first filter.
- Fetchers: if one fetcher thread completes ~10 fetches/s (latency-bound, assumption), about 40 threads would suffice for 400/s; real fleets are larger to absorb slow hosts and DNS.

### 3. API (internal and operational)
```
POST /crawl/seeds        { urls[], priority }
GET  /crawl/status       -> counters per stage
POST /crawl/recrawl      { url } | { host, policy }
Storage interface for consumers: content store keyed by (url_hash, fetch_time) -> blob + metadata
```
Mostly an internal pipeline; the external contract is the content store and its change stream
(topic `page-fetched`).

### 4. Data model
```
url_state(url_hash PK, url, host, last_fetch_ts, next_fetch_ts, change_rate, etag, status, depth, priority)
host_state(host PK, robots_txt, robots_fetched_at, crawl_delay_ms, next_allowed_ts, error_count)
content(url_hash, fetch_ts, content_hash, raw_blob_ref, http_status, headers)
link_graph(src_hash, dst_hash)                       -- for ranking
content_fingerprint(simhash) -> representative url_hash   -- near-duplicate index
```
Raw bodies go to [[blob-object-storage]] (HDFS/S3-style); metadata in a sharded KV/wide-column store
partitioned by `url_hash` or host ([[partitioning-and-sharding]], [[sql-vs-nosql]]).

### 5. High-level architecture
```
 seeds --> URL frontier  <------------------------------------+
              |  (priority queues + per-host politeness queues)|
              v                                                 |
        Fetcher workers --DNS cache--> Internet                 |
              | (robots check, timeouts, conditional GET)       |
              v                                                 |
        Content parser/validator --> Link extractor --> URL normaliser/filter
              |                                           |
              v                                           v
     Content dedupe (hash/SimHash)               URL dedupe (Bloom + KV seen-set)
              |                                           |
              v                                           +------> frontier
       Content store + queue "page-fetched" --> indexer / ML pipeline
```
Stages connect through queues ([[message-queues-and-streams]]) so each scales independently.

### 6. Deep dive A: the URL frontier (priority + politeness)
Two-tier design (Mercator-style):
- **Front queues (priority):** F queues by priority; a prioritiser assigns a score from page importance,
  freshness need and depth. A selector picks from queues with weights favouring higher priority.
- **Back queues (politeness):** one FIFO queue per host (or small set of hosts), and a mapping table
  `host -> back queue`. Each back queue is served by exactly one fetcher thread at a time, with a min-heap
  keyed by `next_allowed_ts` so a host is revisited no sooner than its delay (e.g. 1 s default, or more if
  the server is slow, adapt using observed response time and `robots.txt`).
- Distribute by hashing the host to a frontier shard so one worker owns each host's politeness state
  ([[consistent-hashing]]); this avoids cross-node coordination for rate limits ([[rate-limiting]]).

```python
import heapq, time
class Frontier:
    def __init__(self): self.ready = []; self.queues = {}      # host -> deque of urls
    def push(self, host, url):
        q = self.queues.setdefault(host, []);
        if not q: heapq.heappush(self.ready, (time.time(), host))
        q.append(url)
    def pop(self, delay=1.0):
        while self.ready:
            t, host = heapq.heappop(self.ready)
            if t > time.time(): heapq.heappush(self.ready, (t, host)); return None
            url = self.queues[host].pop(0)
            if self.queues[host]: heapq.heappush(self.ready, (time.time() + delay, host))
            return url
        return None
```
Persistence: keep the frontier mostly on disk with in-memory buffers at head and tail so a crash does not lose
billions of URLs; checkpoint host state.

### 7. Deep dive B: deduplication
- **URL canonicalisation:** lowercase host, remove default ports and fragments, resolve `..`, sort query params,
  strip tracking and session params, follow canonical link tags.
- **Seen-URL check:** Bloom filter in memory as a fast "definitely new / probably seen" gate, backed by a
  persistent KV on hash(url). A false positive means a page is occasionally skipped (acceptable); false negatives never occur.
- **Content dedupe:** exact via content hash (SHA-1/MD5 of normalised text); near-duplicates via SimHash or
  MinHash with locality-sensitive lookup. Skip indexing duplicates but still record links.
- **Trap defenses:** max URL length and depth, cap pages per host/path pattern, detect repeating path segments,
  budget per site, ignore calendar-style infinite parameters.

### 8. Deep dive C: freshness and re-crawl
Estimate each page's change rate from history (pages with unchanged hashes get exponentially longer intervals;
changed ones shorter). Use conditional requests (`If-None-Match`, `If-Modified-Since`) to save bandwidth;
`304` costs almost nothing. Use sitemaps and feeds as hints. Prioritise important pages (home pages, news indexes)
for frequent revisits, long-tail pages monthly. Re-crawl scheduling is another priority input to the frontier.

### 9. Scaling and failure handling
- Workers are stateless apart from leased frontier partitions; if one dies its lease expires and another takes over.
  Fetch is idempotent (re-fetching a page is harmless).
- Timeouts everywhere (connect, read, total), response size caps, content-type checks, and retry with backoff
  for transient errors; mark hosts with repeated failures as degraded ([[resilience-patterns]]).
- DNS is a bottleneck: run a caching resolver, pre-resolve in batches.
- Spread fetchers across regions to be near target sites and use many egress IPs sensibly (without evading blocks).
- Handle JavaScript-rendered pages by a separate, expensive headless-browser tier invoked only when needed.
- Metrics: pages/s per stage, fetch success rate, queue depth, per-host error rates, duplicate ratio
  ([[observability-logs-metrics-traces]]).
- Downstream: write results to the index pipeline ([[search-systems]], [[batch-and-stream-processing]]).

## Trade-offs
- Breadth-first crawl finds important pages early; depth-first risks getting stuck. Priority-driven beats both.
- Bloom filter saves memory but loses recall; exact seen-set costs storage and I/O.
- Aggressive crawl speed vs politeness and getting blocked or sued; slower is usually the right choice.
- Rendering JS captures more content at 10-100x the CPU cost per page (order of magnitude varies; measure).
- Centralised frontier is simple but a bottleneck; sharded-by-host scales but needs rebalancing on node changes.

## Gotchas
- Ignoring `robots.txt` or the crawl-delay hints gets IP ranges banned; cache robots with a TTL, not per request.
- Treating each URL variant as unique (tracking parameters) explodes the frontier.
- Memory growth from unbounded in-memory queues or seen sets.
- Following links into non-HTML or giant files (videos, ISOs): stream and abort by content-length and type.
- Character-encoding mistakes corrupt content; detect charset from headers and meta tags.
- Soft 404s (pages that return 200 for missing content) pollute the index.
- Time-bound duplicate detection: syndicated content appears on many domains; keep the original-source signal.
- Security: crawler fetches attacker-chosen URLs. Block private and link-local IP ranges (SSRF), limit redirects, sandbox parsers.

## Related
- [[message-queues-and-streams]] - connects fetch, parse and dedupe stages
- [[consistent-hashing]] - assigns hosts to frontier shards
- [[rate-limiting]] - per-host politeness is a rate limiter
- [[search-systems]] - the main downstream consumer of crawled content
- [[blob-object-storage]] - stores raw page bodies
- [[caching-strategies]] - DNS and robots.txt caches
- [[back-of-envelope-estimation]] - sizing bandwidth and storage
- [[probabilistic-data-structures]] - Bloom filter for seen-URL dedup in fixed memory

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 9
- Manning, Raghavan, Schutze, *Introduction to Information Retrieval*, ch. 20 Web crawling: https://nlp.stanford.edu/IR-book/html/htmledition/web-crawling-and-indexes-1.html
- RFC 9309 Robots Exclusion Protocol: https://www.rfc-editor.org/rfc/rfc9309.html
- Brin and Page, "The Anatomy of a Large-Scale Hypertextual Web Search Engine": https://research.google/pubs/the-anatomy-of-a-large-scale-hypertextual-web-search-engine/
