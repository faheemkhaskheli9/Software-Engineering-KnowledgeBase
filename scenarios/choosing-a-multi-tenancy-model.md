---
title: Choosing a multi-tenancy model
category: scenarios
tags: [multi-tenancy, saas, tenant-isolation, silo, pool, bridge, row-level-security, noisy-neighbor, sharding, decision-guide]
use_cases:
  - "build a B2B SaaS where each customer's data must stay isolated"
  - "choose between a shared database with tenant_id, schema per tenant, or database per tenant"
  - "stop one large customer from slowing everyone else down"
  - "offer a dedicated deployment to an enterprise customer"
  - "make sure a query can never return another tenant's rows"
status: stable
last_verified: 2026-10-10
sources:
  - https://docs.aws.amazon.com/whitepapers/latest/saas-tenant-isolation-strategies/saas-tenant-isolation-strategies.html
  - https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/considerations/tenancy-models
  - https://www.postgresql.org/docs/current/ddl-rowsecurity.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
---

# Choosing a multi-tenancy model

## Summary
Multi-tenancy serves many customers (tenants) from shared software. The main choice is how much is shared per layer: everything pooled with a `tenant_id` on every row, a silo (own schema, database or whole stack) per tenant, or a mix where most tenants are pooled and a few pay for silos. Default to a pooled database with `tenant_id`, enforced in one place in the app and backed by database row-level security; add silos for tenants with contractual isolation, residency or scale needs. Isolation is an authorization problem first and an infrastructure problem second.

## Key concepts
- **Tenant.** The unit of isolation and billing, usually a customer organisation; define it explicitly (users can belong to several tenants).
- **Silo, pool, bridge** (AWS terms). Silo: dedicated resources per tenant. Pool: shared resources, isolation by tenant key. Bridge: mixed per layer (shared web tier, siloed data).
- **Tenant context.** Resolved once per request (subdomain, token claim, header) from the authenticated identity, never from a client-supplied id alone, and carried to every query, job and log line.
- **Enforcement point.** Scoped repositories or query filters in the app; row-level security (RLS) in the database as a backstop.
- **Noisy neighbour.** One tenant's load degrading others in a pooled system; mitigated with per-tenant quotas, rate limits and queue isolation.
- **Tenant lifecycle.** Onboarding, plan changes, export, deletion, moving a tenant between shards or into a silo.

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Many small tenants, one product, early stage | Pool: shared DB, `tenant_id` column on every tenant-owned table | [[data-modeling-and-schema-design]], [[authorization-models]] |
| Pooled data, fear of a forgotten `WHERE tenant_id` | App-level scoped repository + Postgres RLS backstop | [[authorization-models]], [[owasp-top-10]] |
| Tens to hundreds of tenants wanting logical separation, per-tenant restore | Schema per tenant (migrations run N times) | [[schema-migrations]] |
| Contractual isolation, data residency, per-tenant encryption keys | Database (or account) per tenant: silo | [[secrets-management]], [[cryptography-and-tls]] |
| Enterprise tier wants dedicated deployment | Bridge/tier-based: same version deployed as a silo stack | [[infrastructure-as-code]], [[deployment-strategies]] |
| Pooled DB outgrows one node | Shard by `tenant_id`, keep a tenant directory, move big tenants to own shard | [[partitioning-and-sharding]], [[consistent-hashing]] |
| One tenant's traffic hurts others | Per-tenant rate limits and quotas, separate job queues for heavy tenants | [[rate-limiting]], [[background-jobs-and-queues]] |
| Per-tenant features and plans | Feature flags keyed by tenant | [[deployment-strategies]] |
| Cost per tenant needed for pricing | Tag metrics, logs and jobs with tenant id | [[observability-logs-metrics-traces]] |
| Tenant users log in with their company IdP | Per-tenant OIDC/SAML connection | [[choosing-an-auth-approach]], [[oauth2-and-oidc]] |

Decision flow:

```
Contract, regulation or residency requires physical/logical separation? -> silo for those tenants
Number of tenants large and growing?           -> pool (tenant_id + RLS); silo only as a paid tier
Few large tenants with very different loads?   -> shard by tenant, or silo the largest
Need per-tenant backup/restore of the pooled DB? -> design export/restore by tenant_id early
```

When NOT to silo by default: per-tenant databases multiply migrations, connection pools, monitoring and cost; with many small tenants they become an operations problem. When NOT to pool: when a customer contract or regulator requires separation you cannot demonstrate with a shared database.

## How it works / example
Pool model with tenant scoping done once, in a repository the rest of the code must use. Runnable with stdlib `sqlite3`:

```python
import sqlite3

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, total INTEGER)")
db.execute("CREATE INDEX ix_invoices_tenant ON invoices(tenant_id, id)")   # tenant first

class InvoiceRepo:
    """Every query is scoped; callers cannot pass a different tenant per call."""
    def __init__(self, conn, tenant_id: int):
        self.conn, self.tenant_id = conn, tenant_id

    def add(self, total: int) -> int:
        cur = self.conn.execute("INSERT INTO invoices(tenant_id, total) VALUES (?, ?)",
                                (self.tenant_id, total))
        return cur.lastrowid

    def get(self, invoice_id: int):
        return self.conn.execute(
            "SELECT id, total FROM invoices WHERE id = ? AND tenant_id = ?",
            (invoice_id, self.tenant_id)).fetchone()

if __name__ == "__main__":
    acme, globex = InvoiceRepo(db, 1), InvoiceRepo(db, 2)
    inv = acme.add(100)
    assert acme.get(inv) == (inv, 100)
    assert globex.get(inv) is None        # other tenant's id behaves as "not found"
    print("ok")
```

The tenant id comes from the authenticated session or token, set when the request enters the app. Postgres RLS as the backstop (SQL, run per table):

```sql
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;          -- applies to the table owner too
CREATE POLICY tenant_isolation ON invoices
  USING (tenant_id = current_setting('app.tenant_id')::bigint);
-- per transaction, with a bound parameter (SET LOCAL cannot take one):
-- SELECT set_config('app.tenant_id', $1, true);   -- true = local to this transaction
```

Use a database role for the app that is not a superuser and lacks `BYPASSRLS` (both skip every policy, even with `FORCE`), and set the setting per transaction so pooled connections do not leak a previous request's tenant. Never build the `SET` statement by string formatting: the tenant value would be an SQL-injection point. If the setting was never set, `current_setting` raises an error, and on a pooled connection where an earlier transaction set it, it reads back as an empty string that fails the `::bigint` cast, so a query without tenant context errors instead of returning rows.

Layer-by-layer view of a bridge model:

```
 edge / web tier      : pooled, tenant resolved from subdomain or token
 app services         : pooled, tenant in context, per-tenant rate limits
 job queues           : pooled, heavy tenants on their own queue
 database             : pooled (tenant_id + RLS) | enterprise tenants: own database
 object storage       : key prefix t/<tenant>/..., per-tenant KMS key for siloed tenants
```

## Trade-offs
| Axis | Pool (shared DB) | Schema per tenant | Database / stack per tenant |
|---|---|---|---|
| Cost per tenant | Lowest | Medium | Highest |
| Isolation strength | Logical (app + RLS) | Logical, clearer boundary | Strongest, easy to explain to auditors |
| Migrations | Once | Once per schema | Once per database, fleet tooling needed |
| Noisy neighbour | Highest risk | High (same server) | Lowest |
| Cross-tenant analytics | Easy | Harder | Needs a pipeline |
| Per-tenant restore / move | Needs export by tenant_id | Easier | Native |

- **Uniform deployment vs per-tenant customisation:** one version for all tenants keeps operations sane; per-tenant forks do not scale.
- **Tenant id in every key vs global ids:** composite keys `(tenant_id, id)` keep indexes and shard moves tenant-local; global ids simplify references.

## Gotchas
- One forgotten `WHERE tenant_id` leaks data across customers; centralise scoping and add RLS, then test it with a two-tenant matrix.
- Taking the tenant id from a request parameter instead of the authenticated identity.
- Caches, search indexes and object-store keys without the tenant in the key ([[choosing-a-caching-strategy]]).
- Background jobs and exports that run without tenant context.
- Connection pools carrying tenant session settings between requests.
- Unique constraints that should be per tenant (`UNIQUE(tenant_id, email)`) declared globally, or the reverse.
- Logs and error reports mixing tenants with no tenant field, so you cannot answer a customer's audit request.
- Deleting a tenant: data in backups, caches, search, blobs and analytics must follow your retention promise.

## Related
- [[authorization-models]] - tenant checks as part of every authorization decision.
- [[partitioning-and-sharding]] - sharding by tenant when the pool outgrows a node.
- [[data-modeling-and-schema-design]] - tenant columns, composite keys, constraints.
- [[rate-limiting]] - per-tenant quotas against noisy neighbours.
- [[schema-migrations]] - running migrations across many schemas or databases.
- [[choosing-an-auth-approach]] - per-tenant SSO and identity.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- AWS whitepaper, "SaaS Tenant Isolation Strategies" (silo, pool, bridge, tier-based isolation).
- Microsoft Azure Architecture Center, "Tenancy models for a multitenant solution".
- PostgreSQL documentation, "Row Security Policies".
- OWASP Authorization Cheat Sheet.
