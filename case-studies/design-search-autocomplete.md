---
title: Design search autocomplete (typeahead)
category: case-studies
tags: [autocomplete, typeahead, trie, prefix-search, top-k, suggestions, caching, case-study]
use_cases:
  - "design Google-style search suggestions that return the top completions for each keystroke"
  - "add typeahead to a product search box, address field or user picker"
  - "serve prefix lookups in tens of milliseconds while query popularity changes over time"
  - "filter offensive or stale suggestions and personalise completions"
  - "practice the autocomplete system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 13 'Design a Search Autocomplete System'"
  - https://www.elastic.co/guide/en/elasticsearch/reference/current/search-suggesters.html
  - https://www.elastic.co/guide/en/elasticsearch/reference/current/search-as-you-type.html
  - https://en.wikipedia.org/wiki/Trie
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017, ch. 3 and ch. 10"
---

# Design search autocomplete (typeahead)

## Summary
As the user types, return the k most relevant completions for the current
prefix (usually 5-10), fast enough to keep up with typing. The core idea is to
do the expensive ranking offline: aggregate query logs into popularity counts,
precompute the top-k completions for every prefix, and serve each keystroke
as a single key lookup from memory or a cache. The interesting parts are the
data structure (trie with cached top-k, or a prefix-to-list map), how fresh
the counts are, and filtering.

## Key concepts
- **Trie** (prefix tree): each node is a prefix; storing the top-k completions at each node turns a query into O(length of prefix) and no subtree scan.
- **Offline aggregation**: query logs -> counts per query per time window (batch or stream) -> build the index -> swap it in atomically.
- **Ranking signal**: popularity with time decay is the baseline; personalisation, locale and trending boosts are added on top.
- **Client-side tricks**: debounce keystrokes, cache responses per prefix in the browser, cancel in-flight requests when a newer prefix is typed.
- **Filtering**: blocklists for offensive, legal-takedown or spammy suggestions, applied before results are published.
- **Search engines' alternatives**: Elasticsearch completion suggester (an in-memory FST built for prefix lookup) or `search_as_you_type` fields for edge n-gram matching.

## When to use / scenarios
- Web or product search suggestions from historical queries.
- Entity typeahead (users, products, places) where the candidate set is a catalogue, not query logs.
- For a small catalogue (tens of thousands of items) a database `LIKE 'pre%'` on an index, or an Elasticsearch suggester, is enough; do not build a custom trie service.
- For fuzzy/typo-tolerant matching of full documents, use the search engine itself ([[search-systems]]).

## How it works / example

### 1. Requirements
Functional:
- Given a prefix, return top 5-10 completions ranked by popularity (optionally personalised).
- Only alphanumeric lowercase queries for v1 (state it; Unicode normalisation is later).
- Suggestions reflect new trends within hours (or minutes for "trending" if required).
- Remove blocked suggestions quickly once flagged.

Non-functional:
- p99 latency well under 100 ms end to end, since a request fires per keystroke.
- Highly available; stale suggestions are fine, an empty box is not.
- Scale with very high read QPS; writes are offline batch.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- Assume 10 M DAU x 10 searches/day x ~10 keystroke requests per search (after debounce, maybe fewer) -> 1 B requests/day -> about 12,000 QPS average, peak 2-5x.
- Distinct queries kept: assume the top 100 M after pruning rare ones. Average query 20 chars. Prefix entries are bounded by total characters (up to 2 B) but most prefixes are shared; pruning to prefixes up to ~20 chars with top-10 lists of IDs keeps the index in the tens of GB range: shard it.
- Query logs: 100 M searches/day x ~100 bytes -> 10 GB/day of raw logs.

### 3. API
```
GET /v1/suggest?q=dinos&limit=8&locale=en-GB   -> 200 { "q": "dinos", "suggestions": ["dinosaur", "dinosaur king", ...] }
Cache-Control: public, max-age=300              (prefix responses are shared across users unless personalised)
```

### 4. Data model
```
query_counts(query, window, count)                 -- output of log aggregation (warehouse/OLAP)
prefix_index: prefix -> [ (query, score) x k ]     -- served from memory / KV store, versioned snapshots
blocklist(query or pattern, reason, added_at)
```
Store the prefix index as a key-value map (prefix -> top-k list) rather than
pointer-based trie nodes: it serialises to any KV store or cache and is
sharded by prefix.

### 5. High-level architecture
```
 search service --query logs--> Kafka --> aggregator (hourly batch / stream with decay)
                                               |
                                               v
                         index builder: counts -> top-k per prefix -> filter blocklist
                                               |  versioned snapshot
                                               v
 client (debounce, local cache) -> CDN -> LB -> suggest service (in-memory index shard)
                                                 |-- miss --> KV store (prefix -> top-k)
 personalisation (optional): merge user's recent queries client- or server-side
```
See [[message-queues-and-streams]], [[batch-and-stream-processing]], [[cdn-and-edge]].

### 6. Deep dive A: precomputed top-k per prefix
Building the map offline means every request is a dictionary lookup. Ranking
logic changes only the builder.

```python
import heapq
from collections import defaultdict

def build_prefix_index(counts, k=3, max_prefix=20):
    """counts: {query: score}. Returns {prefix: [query, ...]} with the top-k per prefix."""
    buckets = defaultdict(list)
    for q, score in counts.items():
        for i in range(1, min(len(q), max_prefix) + 1):
            buckets[q[:i]].append((score, q))
    # ties broken alphabetically so builds are deterministic
    return {p: [q for _, q in heapq.nsmallest(k, items, key=lambda t: (-t[0], t[1]))]
            for p, items in buckets.items()}

counts = {"dinosaur": 90, "dinosaur king": 40, "dinner ideas": 70, "dino game": 60, "dog": 99}
index = build_prefix_index(counts)
assert index["d"] == ["dog", "dinosaur", "dinner ideas"]
assert index["dino"] == ["dinosaur", "dino game", "dinosaur king"]
assert index.get("dinosaurs") is None          # unknown prefix -> no suggestions
```

The bucket lists grow with total characters; at real scale the builder runs as
a MapReduce/Spark job (emit `(prefix, (score, query))`, reduce with a bounded
heap of size k per prefix) rather than in one process.

### 7. Deep dive B: freshness and ranking
- Batch rebuild (hourly/daily) from windowed counts with exponential time decay covers most needs.
- "Trending" needs a stream job counting the last few minutes and a small overlay index merged at query time ([[batch-and-stream-processing]]).
- Swap snapshots atomically: load the new version beside the old one, flip a pointer, then drop the old one. Clients never see a half-built index.
- Personalisation: merge the user's own recent queries (kept on the client or in a small per-user store) with the global list; never cache personalised responses at the CDN.

### 8. Deep dive C: latency budget on the read path
- Client: debounce (e.g. wait for a short pause), cache per prefix, abort stale requests.
- CDN/edge caching for short prefixes, which are the most requested and identical for everyone ([[caching-strategies]]).
- Suggest servers keep their shard in memory; shard by prefix range, with extra replicas or splitting for hot ranges (prefixes starting with common letters are far hotter).
- Return early for prefixes shorter than 1-2 characters from a static precomputed list.

### 9. Scaling and failure handling
- **Index build fails**: keep serving the previous snapshot; alert on index age.
- **Shard down**: replicas behind the LB; if all fail, return empty suggestions, never block the search box ([[resilience-patterns]]).
- **Abuse**: attackers inflate a query's count to plant a suggestion; count unique users per query, not raw requests, and rate-limit logging ([[rate-limiting]]).
- **Takedowns**: blocklist is checked at serve time too, so removal does not wait for the next build.
- **Monitoring**: p99 latency, empty-result rate, suggestion click-through, index age.

## Trade-offs
- Precomputed top-k is fast and simple but fixed at build time; query-time ranking (scan the subtree, score live) is flexible but slower.
- Batch freshness (hours) vs stream freshness (minutes) costs a second pipeline.
- A managed search engine suggester saves building and operating a service; a custom index wins only at large scale or with unusual ranking.
- Personalisation improves relevance but defeats shared caching.

## Gotchas
- Firing a request on every keystroke with no debounce or cancellation: out-of-order responses overwrite newer ones in the UI.
- Not normalising (case, whitespace, accents) splits counts for the same query.
- Popularity feedback loop: suggested queries get clicked more, so they stay on top; decay and diversity help.
- Leaking private queries (emails, names) into global suggestions: require a minimum distinct-user count before a query is eligible.
- Hot prefixes like "a" and "the" land on one shard.

## Related
- [[search-systems]] - inverted indexes, suggesters and the typeahead notes in the search topic
- [[caching-strategies]] - CDN and in-memory caching of prefix responses
- [[batch-and-stream-processing]] - aggregating query logs into counts
- [[core-data-structures]] - tries, heaps and hash maps used here
- [[partitioning-and-sharding]] - sharding the prefix index by range
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 13
- Elasticsearch suggesters (completion suggester): https://www.elastic.co/guide/en/elasticsearch/reference/current/search-suggesters.html
- Elasticsearch `search_as_you_type` field: https://www.elastic.co/guide/en/elasticsearch/reference/current/search-as-you-type.html
- Trie: https://en.wikipedia.org/wiki/Trie
- Kleppmann, *Designing Data-Intensive Applications* (2017)
