---
title: Vector databases for engineers
category: data
tags: [vector-database, ann, hnsw, ivf, pgvector, qdrant, similarity-search, filtering, multi-tenancy, recall]
use_cases:
  - "add similarity search over embeddings to an app that already runs on Postgres"
  - "decide between pgvector and a dedicated vector store for production"
  - "vector search returns fewer than k results once we filter by tenant or permission"
  - "keep a vector index consistent with the source documents through updates and deletes"
status: draft
last_verified: 2026-10-11
sources:
  - https://github.com/pgvector/pgvector
  - "Malkov and Yashunin, 'Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs': https://arxiv.org/abs/1603.09320"
  - https://github.com/facebookresearch/faiss/wiki/Faster-search
  - https://qdrant.tech/documentation/guides/multiple-partitions/
---

# Vector databases for engineers

## Summary
A vector database stores fixed-length float vectors (embeddings) with an id and
metadata, and answers "the k nearest vectors to this query vector", usually
with a metadata filter. This topic covers the system side: indexes, filtering,
build and update cost, tenancy, backups and keeping the index in sync with the
source of truth. Which embedding model, metric and chunking to use is the AI
side, covered in the AI knowledge base (links below).

## Key concepts
- **Exact vs approximate (ANN)**: exact search compares the query with every vector, perfect recall at linear cost; pgvector does this by default. An ANN index trades some recall for much less work per query.
- **HNSW**: a multi-layer hierarchy of proximity graphs; search starts at the sparse top layer and descends (Malkov and Yashunin). In pgvector it has a better speed-recall trade-off than IVFFlat, but builds slower and uses more memory.
- **IVF**: k-means centroids split space into `nlist` cells; a query scans only the `nprobe` nearest cells. `nprobe = nlist` equals brute force (Faiss wiki). pgvector's IVFFlat must be built after the table has data, because the lists are trained on it.
- **Recall vs latency knob**: `hnsw.ef_search` (pgvector default 40) and `ivfflat.probes` (default 1) / Faiss `nprobe`. Higher means better recall, slower queries. Tune against exact results on a sample, not by feel.
- **Filtering + ANN**: in pgvector, "filtering is applied after the index is scanned", so a selective filter can return fewer than k rows. Fixes: iterative index scans (pgvector 0.8.0+), partial indexes for a few filter values, partitioning for many, or an engine with filter-aware search.

## When to use / scenarios
- **pgvector first** when you already run Postgres: vectors live next to rows, so filters, joins, transactions, row-level security and backups come for free.
- **Dedicated store** (Qdrant, Milvus, Weaviate, managed services) when vector volume or query load should be isolated from OLTP, or you need filter-aware ANN, quantization and sharding built in.
- **Brute force** (no index) is right for small or heavily pre-filtered sets: it is exact and has no build or tuning cost.
- Not a vector problem: exact keyword, id or attribute lookups belong in SQL or a search engine ([[search-systems]]).

## How it works / example
Exact cosine top-k with a tenant filter: the baseline an ANN index approximates,
and the yardstick for measuring its recall. The last asserts show why
"global top-k, then filter" (post-filtering) under-returns.

```python
import heapq
import math

def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

rows = [  # (id, tenant, vector)
    ("a1", "acme", [1.0, 0.0, 0.0]), ("a2", "acme", [0.9, 0.1, 0.0]),
    ("a3", "acme", [0.0, 1.0, 0.0]), ("g1", "globex", [1.0, 0.05, 0.0]),
    ("g2", "globex", [0.95, 0.0, 0.05]), ("g3", "globex", [0.8, 0.2, 0.0]),
]

def top_k(query, k, tenant=None):
    candidates = (r for r in rows if tenant is None or r[1] == tenant)   # pre-filter
    best = heapq.nlargest(k, candidates, key=lambda r: cosine(query, r[2]))
    return [r[0] for r in best]

q = [1.0, 0.0, 0.0]
assert top_k(q, 2, tenant="acme") == ["a1", "a2"]          # exact, filtered
assert top_k(q, 3, tenant="acme") == ["a1", "a2", "a3"]

global_top3 = top_k(q, 3)                                   # ["a1", "g1", "g2"]
post_filtered = [i for i in global_top3 if i.startswith("a")]
assert post_filtered == ["a1"]                              # asked for 3, got 1
```

## Trade-offs
- **pgvector vs dedicated store**: one system with transactional consistency and familiar ops vs better filtered-ANN behaviour, scale-out and isolation, at the cost of a sync pipeline.
- **HNSW vs IVF**: HNSW for query speed at a given recall; IVF for faster builds and less memory, but its lists are trained on the data present at build time, so rebuild after the data changes substantially.
- **Index build cost**: HNSW builds are CPU- and memory-heavy; pgvector builds "significantly faster" when the graph fits in `maintenance_work_mem`, but setting that too high can exhaust server memory. Bulk-load first, then build.
- **Multi-tenancy**: a tenant filter on one shared index vs index (or collection) per tenant. Qdrant recommends one collection with payload-based partitioning for many small tenants and separate collections only for a few tenants needing strict isolation ([[choosing-a-multi-tenancy-model]]).

## Gotchas
- Deletes and updates are not free: an update is a delete plus an insert into the graph or list, and pgvector notes vacuuming HNSW indexes "can take a while" (reindexing first speeds it up). Plan rebuild windows for churn-heavy tables.
- The vector index is a derived store. Write the source of truth first and feed the index from it (outbox or CDC, [[event-driven-architecture]]), with deterministic ids so re-ingestion is idempotent; a deleted source document must delete its vectors.
- Backups: a dedicated store needs its own snapshot and restore drill, and restoring it to a different point in time than the source database leaves orphans or gaps. Treat it as rebuildable and keep a re-embed or re-index path ([[schema-migrations]]).
- Changing the embedding model or dimension means a full re-embed into a new index and a switchover, never mixing vectors from two models.
- Recall regressions are silent: monitor ANN results against exact search on a sample after each data or parameter change.

## Related
- [[design-rag-chat]] - full RAG design with ACL filtering, ingestion and tenant sharding
- [[search-systems]] - keyword and hybrid search around the vector index
- [[database-indexing]] - how ordinary indexes compare; partial indexes reused for filtered ANN
- [[partitioning-and-sharding]] - scaling an index past one node
- [[choosing-a-database]] - when a vector extension or store enters the stack
- [[time-series-databases]] - another specialised store to justify against plain Postgres
- [[graph-databases]] - relationship traversal rather than similarity
- See also (AI KB): [Vector databases and indexes](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/vector-databases.md) and [Embeddings](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/concepts/embeddings.md) - model, metric and store choice from the AI side.

## References
- pgvector README (exact default, HNSW vs IVFFlat, `ef_search`, `probes`, filtering, iterative scans, vacuum): https://github.com/pgvector/pgvector
- Malkov and Yashunin, HNSW paper: https://arxiv.org/abs/1603.09320
- Faiss wiki, "Faster search" (IVF, `nlist`, `nprobe`): https://github.com/facebookresearch/faiss/wiki/Faster-search
- Qdrant, multitenancy and partitions: https://qdrant.tech/documentation/guides/multiple-partitions/
