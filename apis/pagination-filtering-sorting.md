---
title: Pagination, filtering and sorting
category: apis
tags: [pagination, cursor, keyset, offset, filtering, sorting, api-design, sql]
use_cases:
  - "add a list endpoint that must stay fast with millions of rows"
  - "implement infinite scroll without skipped or duplicated items"
  - "choose between offset and cursor pagination"
  - "let clients filter and sort a collection safely"
status: stable
last_verified: 2026-10-10
sources:
  - https://use-the-index-luke.com/no-offset
  - https://relay.dev/graphql/connections.htm
  - https://cloud.google.com/apis/design/design_patterns#list_pagination
  - https://www.rfc-editor.org/rfc/rfc8288
---

# Pagination, filtering and sorting

## Summary
List endpoints must never return unbounded results. Offset pagination (`LIMIT/OFFSET`) is simple but gets slow and unstable on large or changing data; cursor (keyset) pagination is fast and consistent but gives up random page access. Filtering and sorting need a whitelist of fields backed by indexes.

## Key concepts
- **Offset/limit (or page/size)**: `OFFSET n` makes the database walk and discard n rows; cost grows with depth.
- **Cursor/keyset**: "give me rows after this key" using an indexed `WHERE (sort_col, id) > (:last_sort, :last_id)`; constant cost per page.
- **Opaque cursor**: a base64 token encoding the last key (and sort order); clients treat it as a black box so you can change internals.
- **Stable total order**: sort must include a unique tiebreaker (`id`), otherwise rows can repeat or vanish across pages.
- **Total count**: `COUNT(*)` on large filtered sets is expensive; offer it optionally or approximate.
- **Link headers / response envelope**: `next`/`prev` links (RFC 8288 `Link`) or `{"data": [...], "next_cursor": "..."}`.
- **Filtering**: explicit query params (`?status=open&created_after=...`) or a small filter DSL; **sorting**: `?sort=-created_at,id`.
- **Relay connections** in GraphQL: `edges { node cursor }`, `pageInfo { hasNextPage endCursor }`.

## When to use / scenarios
- Offset pagination: small, rarely-changing datasets, admin UIs that need "jump to page 7", and total pages displayed. Cap max offset.
- Cursor pagination: feeds, activity logs, large tables, mobile infinite scroll, public APIs, anything where rows are inserted while users page (see [[design-news-feed]]).
- Exports and syncs: cursor over an `updated_at, id` ordering (or a change feed) to process everything exactly once.
- Filtering: expose only the fields you have indexes for; combine with sort order so the same composite index serves both (see [[database-indexing]]).
- Search relevance ranking or full-text: delegate to a search engine; use `search_after` style cursors there (see [[search-systems]]).
- Do NOT let clients pass arbitrary column names or raw SQL fragments in `sort` or `filter`.

## How it works / example
Offset (simple but degrades):
```sql
SELECT id, title, created_at FROM posts
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 100000;     -- reads and discards 100000 rows
```

Keyset (constant cost, needs index `(created_at DESC, id DESC)`):
```sql
-- first page
SELECT id, title, created_at FROM posts
ORDER BY created_at DESC, id DESC LIMIT 21;     -- fetch limit+1 to know if there is a next page

-- next page, given last row (created_at = :c, id = :i)
SELECT id, title, created_at FROM posts
WHERE (created_at, id) < (:c, :i)
ORDER BY created_at DESC, id DESC LIMIT 21;
```

Opaque cursor in Python:
```python
import base64, json

def encode_cursor(created_at: str, id_: int) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at, id_]).encode()).decode()

def decode_cursor(token: str):
    try:
        created_at, id_ = json.loads(base64.urlsafe_b64decode(token.encode()))
        return created_at, int(id_)
    except Exception:
        raise ValueError("invalid cursor")   # map to 400

def list_posts(db, limit=20, cursor=None):
    limit = max(1, min(limit, 100))               # always cap
    sql = "SELECT id, title, created_at FROM posts "
    args = []
    if cursor:
        c, i = decode_cursor(cursor)
        sql += "WHERE (created_at, id) < (%s, %s) "; args += [c, i]
    sql += "ORDER BY created_at DESC, id DESC LIMIT %s"
    rows = db.execute(sql, args + [limit + 1]).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(str(rows[-1].created_at), rows[-1].id) if has_more else None
    return {"data": rows, "next_cursor": next_cursor}
```

HTTP shape:
```http
GET /v1/posts?limit=20&status=published&sort=-created_at HTTP/1.1

HTTP/1.1 200 OK
Link: </v1/posts?limit=20&cursor=eyJ...>; rel="next"

{"data": [ ... ], "next_cursor": "eyJ..."}
```

Filtering whitelist: map `?status=open` and `?created_after=` onto allowed, indexed columns; reject unknown params with 400. Support ranges (`_gte`, `_lt`) and `in` lists with an upper bound on list length.

## Trade-offs
- **Offset vs cursor**: offset allows page jumping and totals; cursor wins on speed and consistency under concurrent writes.
- **Totals**: exact counts cost a scan; return `has_more` by default and counts on request or as estimates.
- **Opaque vs transparent cursors**: opaque tokens allow changing implementation (and signing/encryption); transparent ones are easier to debug.
- **Sorting flexibility vs index count**: each allowed sort order wants an index; limit to a few supported orders.
- **Page size**: bigger pages cut round trips but raise latency and memory; set a default and a hard max.
- **Filter DSL vs fixed params**: a DSL is flexible and invites abuse; fixed params are simple and predictable.

## Gotchas
- Sorting on a non-unique column without a tiebreaker produces duplicate or missing rows between pages.
- Offset pagination over a table receiving inserts shows duplicates (items shift down) or skips; users notice in feeds.
- Keyset with `NULL` values in the sort column needs explicit `NULLS FIRST/LAST` handling and matching index definitions.
- Mixed sort directions (`created_at DESC, id ASC`) break simple tuple comparison; use consistent directions or expand the predicate.
- Cursors that embed sorting and filters must be rejected if the client changes filters mid-pagination (include a filter hash).
- Deep `OFFSET` plus `COUNT(*)` is a classic way to melt a database; cap `limit` and `offset`, and rate limit (see [[rate-limiting]]).
- Soft-deleted or permission-filtered rows: apply visibility filters in the query, not after, otherwise pages come back short or leak counts.
- Changing the default sort later is a breaking change (see [[api-versioning-and-evolution]]).
- Sharded data needs a merge strategy across shards; cursors become per-shard (see [[partitioning-and-sharding]]).

## Related
- [[rest-api-design]] - where list endpoints sit in overall API conventions
- [[database-indexing]] - keyset pagination depends on a matching composite index
- [[graphql]] - Relay cursor connections specification
- [[design-news-feed]] - feeds are the canonical cursor-pagination case
- [[search-systems]] - search-engine pagination and deep paging limits

## References
- Markus Winand, "We need tool support for keyset pagination": https://use-the-index-luke.com/no-offset
- GraphQL Cursor Connections Specification: https://relay.dev/graphql/connections.htm
- Google API Design Guide, list pagination: https://cloud.google.com/apis/design/design_patterns#list_pagination
- RFC 8288 Web Linking: https://www.rfc-editor.org/rfc/rfc8288
