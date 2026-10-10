---
title: ORMs and the N+1 query problem
category: data
tags: [orm, n-plus-one, sqlalchemy, django, hibernate, eager-loading, performance, query-optimization]
use_cases:
  - "an endpoint makes hundreds of SQL queries to render a list"
  - "decide whether to use an ORM or raw SQL for a service"
  - "detect N+1 queries in tests before they reach production"
  - "load related objects efficiently with joins or batched queries"
status: draft
last_verified: 2026-10-10
sources:
  - https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html
  - https://docs.djangoproject.com/en/stable/ref/models/querysets/#select-related
  - https://vladmihalcea.com/n-plus-1-query-problem/
  - "Martin Fowler, Patterns of Enterprise Application Architecture (Addison-Wesley, 2002)"
---

# ORMs and the N+1 query problem

## Summary
An ORM maps rows to objects so code manipulates models instead of SQL strings. Its most common performance bug is N+1: one query to load a list, then one more query per item to load a related object lazily. Fix it by loading relations explicitly (joins or batched `IN` queries), and guard against regressions with query-count tests.

## Key concepts
- **Lazy loading**: related objects load on first attribute access, issuing a hidden query. Convenient, dangerous inside loops.
- **N+1**: 1 query for N parents plus N queries for children; latency grows linearly with list size.
- **Eager loading strategies**: JOIN (one wide query; can multiply rows for collections), subquery/`IN` batch (two queries; usually best for collections).
- **Impedance mismatch**: objects form graphs; relational data is sets. ORMs hide but do not remove the difference.
- **Unit of work / identity map**: the session tracks loaded objects and flushes changes (SQLAlchemy, Hibernate); sessions have lifecycle rules.
- **Active Record vs Data Mapper**: models that save themselves (Django, Rails) vs separate mapping layer (SQLAlchemy, Hibernate).
- **Query builders / micro-ORMs / raw SQL**: thinner alternatives (SQLAlchemy Core, jOOQ, Dapper, sqlc).

## When to use / scenarios
- Use an ORM for CRUD-heavy domain code, migrations integration, and developer productivity.
- Switch to raw SQL or a query builder for reports, bulk updates, complex joins, window functions, and any hot path where you need to see exactly what runs.
- Suspect N+1 whenever response time scales with page size, or query logs show the same statement repeated with different ids.
- GraphQL resolvers naturally produce N+1; use a batching loader (see [[graphql]]).
- Do NOT fetch full entities when you need two columns; project only those columns.
- Do NOT use the ORM to loop over millions of rows updating one by one; issue a set-based `UPDATE` or batch.

## How it works / example
The bug (SQLAlchemy 2.x style):
```python
# 1 query
authors = session.scalars(select(Author).limit(50)).all()
for a in authors:
    print(a.name, len(a.books))     # lazy load: +1 query per author => 51 queries
```

Fixes:
```python
from sqlalchemy.orm import selectinload, joinedload

# Collections: batch with IN (2 queries total)
authors = session.scalars(
    select(Author).options(selectinload(Author.books)).limit(50)
).all()

# Many-to-one / one-to-one: JOIN (1 query)
books = session.scalars(
    select(Book).options(joinedload(Book.author))
).all()

# Need only a count: aggregate in SQL, do not load objects
rows = session.execute(
    select(Author.name, func.count(Book.id)).join(Book).group_by(Author.id)
).all()
```

Django equivalents:
```python
Book.objects.select_related("author")            # JOIN for FK / one-to-one
Author.objects.prefetch_related("books")          # separate IN query for collections
Author.objects.annotate(n=Count("books")).values("name", "n")   # aggregate in SQL
```

Detecting it in tests: count queries and assert a ceiling.
```python
from sqlalchemy import event

class QueryCounter:
    def __init__(self, engine): self.n = 0; self.engine = engine
    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._inc); return self
    def __exit__(self, *a):
        event.remove(self.engine, "before_cursor_execute", self._inc)
    def _inc(self, *args): self.n += 1

def test_list_authors_uses_constant_queries(engine, client):
    with QueryCounter(engine) as qc:
        client.get("/authors?limit=50")
    assert qc.n <= 3      # constant, independent of the 50
```
Django has `assertNumQueries`; Rails has Bullet; Hibernate has `hibernate.generate_statistics`; django-debug-toolbar and SQL logging reveal duplicates in development.

JOIN vs IN-batch for collections: a JOIN of authors with 20 books each returns 20 rows per author with the author columns repeated; the `IN` strategy sends author columns once and avoids row multiplication.

## Trade-offs
- **JOIN vs separate query**: JOIN is one round trip but duplicates parent data and cannot paginate collections cleanly; batch `IN` is two round trips and usually cleaner for one-to-many.
- **ORM vs raw SQL**: ORM speeds up routine work and keeps schema in sync; raw SQL gives control and clarity for complex queries. Mixing both is normal.
- **Lazy by default vs explicit loading**: lazy is forgiving but hides cost; many teams disable lazy loading (`raiseload`) to force explicit decisions.
- **Entity loading vs projections**: DTO or column projections are lighter than full entities and avoid accidental lazy access.
- **Caching**: a second-level or query cache can mask N+1 but adds invalidation burden; fix the query first.

## Gotchas
- Looping and calling `.count()`, `.exists()` or an attribute per item is N+1 in disguise.
- Serializers (DRF, Pydantic from-attributes, JSON mappers) trigger lazy loads when they walk relations.
- Eager loading everything "just in case" creates huge cartesian-product joins; load what the use case needs.
- `joinedload` on two collections multiplies rows (cartesian explosion); use `selectinload` for each.
- `LIMIT` with a collection join limits joined rows, not parents; ORMs sometimes wrap in a subquery, check the SQL.
- Detached/closed sessions raise errors on lazy access (SQLAlchemy `DetachedInstanceError`, Hibernate `LazyInitializationException`); load before the session closes.
- Bulk ORM operations (`bulk_create`, `update(...)` queries) skip signals/validation/hooks; know what is bypassed.
- Missing indexes on foreign keys make even correct batched queries slow (see [[database-indexing]]).
- Transactions and sessions left open across requests leak connections (see [[transactions-and-isolation-levels]]).

## Related
- [[database-indexing]] - batched queries still need supporting indexes
- [[graphql]] - resolver-per-field design makes N+1 the default without DataLoader
- [[transactions-and-isolation-levels]] - session and unit-of-work lifetime
- [[caching-strategies]] - caching as a second line of defence, not the fix
- [[rest-api-design]] - endpoint shapes (embedding, expansion) decide what must be loaded together

## References
- SQLAlchemy relationship loading techniques: https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html
- Django QuerySet reference (`select_related`, `prefetch_related`): https://docs.djangoproject.com/en/stable/ref/models/querysets/#select-related
- Vlad Mihalcea on N+1: https://vladmihalcea.com/n-plus-1-query-problem/
- Fowler, Patterns of Enterprise Application Architecture (Lazy Load, Unit of Work, Identity Map).
