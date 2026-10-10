---
title: Search systems
category: system-design
tags: [search, inverted-index, elasticsearch, lucene, bm25, full-text, typeahead, relevance]
use_cases:
  - "add full-text search with ranking and filters to an existing product catalog"
  - "build typeahead / autocomplete suggestions with low latency"
  - "keep a search index in sync with the primary database"
  - "decide between Postgres full-text search and Elasticsearch/OpenSearch"
status: draft
last_verified: 2026-10-10
sources:
  - https://nlp.stanford.edu/IR-book/information-retrieval-book.html
  - https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html
  - https://www.postgresql.org/docs/current/textsearch.html
  - https://lucene.apache.org/core/documentation.html
  - "Robertson and Zaragoza, The Probabilistic Relevance Framework: BM25 and Beyond, 2009"
---

# Search systems

## Summary
A search system answers free-text queries over a corpus by building an
**inverted index** (term to the list of documents containing it) and ranking
matches by relevance (TF-IDF/BM25 plus business signals). Engines such as
Lucene-based Elasticsearch, OpenSearch and Solr, or newer ones like Meilisearch,
Typesense and Tantivy, add sharding, analysis, filters and facets. The search
index is a **derived, eventually consistent copy** of your source of truth.

## Key concepts
- **Inverted index**: `term -> postings list [(doc_id, positions, tf)]`. Query terms intersect/union lists.
- **Analysis pipeline**: tokenization, lowercasing, stop words, stemming/lemmatization, synonyms, n-grams. The same analysis must apply at index and query time (with deliberate exceptions).
- **Relevance scoring**: TF-IDF; **BM25** (default in Lucene since 6.0) improves it with term-frequency saturation and length normalization. Boost fields (title > body), recency, popularity.
- **Filters vs queries**: filters (exact, cached, no scoring) narrow results; queries score. Use filters for category, price, tenant.
- **Facets/aggregations**: counts per attribute for UI filters.
- **Sharding and replicas**: index split into primary shards; replicas for availability and read throughput. Shard count is fixed at index creation in Elasticsearch (reindex or split to change).
- **Near-real-time**: documents become searchable after a refresh (default about 1s in Elasticsearch), not immediately.
- **Typeahead**: prefix lookups via edge n-grams, completion suggester (FST) or a trie with top-K per node.
- **Vector / hybrid search**: embeddings with approximate nearest neighbours (HNSW), often combined with BM25; see the AI knowledge base for the model side.

## When to use / scenarios
- Product, document, or message search with ranking, typo tolerance, facets.
- Log and event search (the ELK/OpenSearch use case) with time-based indices.
- Autocomplete on a bounded vocabulary (products, cities, usernames).
- Start small: Postgres `tsvector` + GIN index handles modest corpora (single node, tens of millions of rows is plausible with care) with transactional consistency and no extra system. Move to a dedicated engine when you need advanced relevance, typo tolerance, facets at scale, or heavy search load that should be isolated from the OLTP database.
- Not for: primary storage of record (engines trade durability and transactions for search speed), exact aggregations needing strict consistency.

## How it works / example

```
 write path:  app -> DB (source of truth)
                 |-- outbox/CDC -> queue -> indexer -> search cluster (shards + replicas)
 read path:   user -> API -> search cluster (query + filters) -> ids/snippets
                         -> optionally hydrate from DB/cache -> response
```

Toy inverted index with AND queries and TF scoring, runnable:

```python
import re
from collections import defaultdict, Counter

class Index:
    def __init__(self):
        self.postings = defaultdict(dict)   # term -> {doc_id: tf}
        self.docs = {}

    @staticmethod
    def analyze(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    def add(self, doc_id, text):
        self.docs[doc_id] = text
        for term, tf in Counter(self.analyze(text)).items():
            self.postings[term][doc_id] = tf

    def search(self, query, k=5):
        terms = self.analyze(query)
        if not terms:
            return []
        lists = [self.postings.get(t, {}) for t in terms]
        common = set(lists[0]).intersection(*lists[1:])      # AND semantics
        scored = {d: sum(l[d] for l in lists) for d in common}
        return sorted(scored, key=scored.get, reverse=True)[:k]

if __name__ == "__main__":
    ix = Index()
    ix.add(1, "red running shoes")
    ix.add(2, "blue running jacket")
    ix.add(3, "running shoes running fast")
    assert ix.search("running shoes")[0] == 3
```

Elasticsearch-style query combining scored text and cached filters:

```json
{
  "query": {
    "bool": {
      "must":   [{ "multi_match": { "query": "running shoes", "fields": ["title^3", "description"], "fuzziness": "AUTO" } }],
      "filter": [{ "term": { "in_stock": true } }, { "range": { "price": { "lte": 100 } } }]
    }
  },
  "aggs": { "brands": { "terms": { "field": "brand" } } }
}
```

### Keeping the index in sync
1. **Dual write** from the app: simple, drifts on partial failure. Avoid.
2. **Outbox/CDC to indexer** (Debezium, DB triggers to queue): reliable, at-least-once; use document version (`updated_at`/sequence) as external version so out-of-order or duplicate events cannot regress the index. See [[message-queues-and-streams]].
3. **Periodic full reindex** into a new index, then swap an alias: needed anyway for analyzer or mapping changes. Plan zero-downtime reindex from day one.

### Typeahead design
Precompute top-K completions per prefix from query logs (offline job), store in a trie/Redis sorted sets or an edge-n-gram field; cache hot prefixes at the edge; debounce client requests (about 100-200 ms) and cancel stale ones. Filter offensive/unsafe suggestions.

## Trade-offs
- **Postgres FTS vs dedicated engine**: Postgres is simpler and consistent but weaker at relevance tuning, fuzzy matching and horizontal scale; a dedicated engine adds an operational system and sync pipeline.
- **Relevance vs latency**: richer scoring, fuzziness and rescoring cost CPU; use two-phase retrieval (cheap candidate generation, expensive rerank on top N).
- **Shard count**: too few limits scale; too many wastes memory and slows queries (per-shard overhead). Size shards by data volume, not by guess; time-based indices for logs.
- **Freshness vs indexing throughput**: lower refresh interval increases segment churn; bulk loads benefit from disabling refresh temporarily.
- **Self-managed vs hosted** (Elastic Cloud, OpenSearch Service, Algolia, Typesense Cloud): hosted trades cost for operations. Licence differences between Elasticsearch and OpenSearch matter for some organisations; check current terms.

## Gotchas
- Treating the search index as source of truth; always be able to rebuild it.
- Mapping changes (field type, analyzer) generally require a reindex; dynamic mapping can create wrong types (explode field count, or treat IDs as text).
- Deep pagination (`from` + `size` large) is expensive; use `search_after`/cursors ([[pagination-filtering-sorting]]).
- Wildcard/regex leading-wildcard queries are slow; use n-grams.
- Index-time and query-time analyzers mismatch yields "can't find what I just indexed".
- Per-tenant isolation: filters on a shared index can leak data if one clause is missing; consider per-tenant indices or routing for strict isolation.
- Cluster instability from huge documents, too many fields, or unbounded aggregations.
- Ignoring relevance evaluation; build a judged query set and measure (nDCG/precision) before and after tuning.

## Related
- [[database-indexing]] - B-tree vs inverted/GIN indexes and when each applies.
- [[message-queues-and-streams]] - transporting changes to the indexer.
- [[partitioning-and-sharding]] - how search shards distribute data and queries.
- [[pagination-filtering-sorting]] - cursor-based paging for result sets.
- [[caching-strategies]] - caching popular queries and typeahead prefixes.
- [[sql-vs-nosql]] - search engines as a specialised secondary store.

## References
- Manning, Raghavan, Schutze, *Introduction to Information Retrieval*: https://nlp.stanford.edu/IR-book/information-retrieval-book.html
- Elasticsearch reference: https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html
- PostgreSQL full text search: https://www.postgresql.org/docs/current/textsearch.html
- Robertson and Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond" (2009).
