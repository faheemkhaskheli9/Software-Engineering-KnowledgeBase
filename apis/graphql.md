---
title: GraphQL
category: apis
tags: [graphql, api, schema, resolvers, dataloader, n-plus-one, subscriptions, federation]
use_cases:
  - "let web and mobile clients fetch exactly the fields they need in one request"
  - "aggregate several backend services behind a single typed API"
  - "stop resolver N+1 queries in a GraphQL server"
  - "protect a GraphQL endpoint from expensive or abusive queries"
status: draft
last_verified: 2026-10-10
sources:
  - https://spec.graphql.org/
  - https://graphql.org/learn/
  - https://github.com/graphql/dataloader
  - https://www.apollographql.com/docs/federation/
  - https://graphql.org/learn/best-practices/
---

# GraphQL

## Summary
GraphQL is a query language and runtime for APIs where the client sends a query describing the exact shape of data it wants, against a strongly typed schema, usually through one HTTP endpoint. It removes over-fetching and many round trips for UI-driven clients, at the cost of server complexity: caching, authorisation, query cost and N+1 become your problem.

## Key concepts
- **Schema (SDL)**: types, fields, enums, interfaces, unions, inputs; the contract and the documentation. Non-null (`!`) markers are part of the type.
- **Operations**: `query` (read), `mutation` (write, run serially), `subscription` (push events, usually over WebSocket; see [[realtime-websockets-sse]]).
- **Resolvers**: a function per field that returns its value; the query executes as a tree of resolver calls.
- **DataLoader**: per-request batching and caching of lookups to prevent N+1.
- **Introspection**: clients and tools can query the schema; disable or restrict it for public production APIs if needed.
- **Fragments, variables, aliases, directives**: reuse and parameterise queries.
- **Persisted queries**: client sends a hash of a pre-registered query, enabling allow-listing and smaller requests.
- **Federation / stitching**: compose multiple subgraphs into one supergraph (Apollo Federation, others).
- **Relay connections**: standard cursor pagination shape (`edges`, `node`, `pageInfo`).

## When to use / scenarios
- Many different clients (web, iOS, Android, partners) need different subsets of the same data; frontend teams iterate faster than backend.
- A "backend for frontend" that composes several services or databases into one graph.
- Deeply related data where REST would need many round trips.
- Prefer REST for simple CRUD, public APIs wanting HTTP caching, file uploads, or when team capacity for GraphQL operations is limited (see [[rest-api-design]]).
- Prefer gRPC for internal service calls (see [[grpc-and-protobuf]]).
- Do NOT put GraphQL in front of a database "automatically" and expose it publicly without limits and field-level authorisation.

## How it works / example
Schema and query:
```graphql
type Query {
  author(id: ID!): Author
  authors(first: Int = 20, after: String): AuthorConnection!
}
type Mutation {
  addBook(input: AddBookInput!): AddBookPayload!
}
type Author { id: ID!  name: String!  books: [Book!]! }
type Book   { id: ID!  title: String!  author: Author! }
input AddBookInput { authorId: ID!  title: String! }
type AddBookPayload { book: Book  errors: [UserError!]! }
type UserError { field: String  message: String! }
```
```graphql
query ($id: ID!) {
  author(id: $id) { name  books { title } }
}
```
```http
POST /graphql
Content-Type: application/json

{"query": "query($id: ID!){ author(id:$id){ name books{ title } } }", "variables": {"id": "7"}}
```

Resolver N+1 and the DataLoader fix (Python, `strawberry`-style async with `aiodataloader`):
```python
from aiodataloader import DataLoader

class BooksByAuthor(DataLoader):
    async def batch_load_fn(self, author_ids):
        rows = await db.fetch("SELECT * FROM books WHERE author_id = ANY($1)", list(author_ids))
        grouped = {a: [] for a in author_ids}
        for r in rows:
            grouped[r["author_id"]].append(r)
        return [grouped[a] for a in author_ids]     # same order as keys

# one loader instance per request (never global: it caches per key)
def resolve_author_books(author, info):
    return info.context.books_loader.load(author["id"])
```
Without the loader, 50 authors cause 50 book queries; with it, one `ANY(...)` query (see [[orm-and-n-plus-one]]).

Query cost limiting: reject queries beyond depth N or a computed cost budget, require pagination arguments (`first` max 100), set timeouts, and prefer persisted-query allow-lists for first-party clients.

Errors: HTTP 200 with an `errors` array is normal for resolver failures. Model expected business errors as data in the payload (`errors: [UserError]`), keep the top-level `errors` for unexpected faults.

## Trade-offs
- **Client flexibility vs server control**: arbitrary queries make performance unpredictable; mitigate with cost analysis, depth limits and persisted queries.
- **Single endpoint vs HTTP tooling**: caches, CDNs, rate limiters and logs that key on URL see only `POST /graphql`; use persisted queries via GET or application-level caching.
- **Schema-first vs code-first**: schema-first gives clear contracts; code-first reduces duplication.
- **Federation vs monolithic graph**: federation scales ownership across teams but adds a gateway and composition pipeline.
- **Versioning**: GraphQL favours additive evolution and `@deprecated` over versions; breaking removals need usage tracking.
- **Subscriptions**: powerful but require stateful connections and scaling work.

## Gotchas
- N+1 in resolvers is the default outcome; add DataLoader (or join-aware resolvers) from the start.
- Authorisation belongs in the resolver or domain layer per field/object, not only at the endpoint: a user may reach an object through many paths.
- Introspection plus deep nested queries enable denial of service and schema reconnaissance; limit both.
- Batching attacks: aliases let a client call an expensive field or a login mutation hundreds of times in one request; count aliases and rate-limit by cost (see [[rate-limiting]]).
- Nullability: making fields non-null means one failing resolver nulls its whole parent; choose deliberately.
- File uploads are not in the core spec; use a multipart extension or presigned URLs to object storage (see [[blob-object-storage]]).
- Caching by URL is gone: use per-field caching, response caching with keys on query plus variables, or CDN with persisted GET queries (see [[caching-strategies]]).
- Mutations are executed serially at top level; do not assume parallelism.
- Monitoring by endpoint is useless; trace per operation name and field (see [[observability-logs-metrics-traces]]). Require operation names.

## Related
- [[rest-api-design]] - the main alternative; compare caching and tooling
- [[orm-and-n-plus-one]] - resolver N+1 is the same problem in a new place
- [[pagination-filtering-sorting]] - cursor connections as the standard list shape
- [[api-gateway-and-service-mesh]] - gateway role when federating subgraphs
- [[realtime-websockets-sse]] - transport for subscriptions

## References
- GraphQL specification: https://spec.graphql.org/
- Learn GraphQL and best practices: https://graphql.org/learn/
- DataLoader: https://github.com/graphql/dataloader
- Apollo Federation docs: https://www.apollographql.com/docs/federation/
