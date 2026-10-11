---
title: Authorization models (RBAC, ABAC, ReBAC)
category: security
tags: [authorization, rbac, abac, rebac, acl, permissions, idor, policy]
use_cases:
  - "add roles and permissions to our SaaS app"
  - "implement per-document sharing like Google Docs"
  - "enforce multi-tenant data isolation in an API"
  - "decide between RBAC, ABAC and a policy engine like OPA"
  - "stop users reading other users' records by changing the ID in the URL"
status: stable
last_verified: 2026-10-10
sources:
  - https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
  - https://csrc.nist.gov/projects/role-based-access-control
  - https://csrc.nist.gov/pubs/sp/800/162/upd2/final
  - https://research.google/pubs/zanzibar-googles-consistent-global-authorization-system/
  - https://www.openpolicyagent.org/docs/latest/
---

# Authorization models (RBAC, ABAC, ReBAC)

## Summary
Authorization decides whether an authenticated principal may perform an action
on a resource. The model you pick (roles, attributes, relationships, or plain
ACLs) determines how rules are expressed and audited. Broken access control is
the number one OWASP Top 10 risk (2021 and 2025), mostly because checks are missing or
inconsistent rather than because the model is wrong.

## Key concepts
- **Decision = (subject, action, resource, context) -> allow/deny.** Default
  deny.
- **ACL:** per-resource list of who can do what. Simple, hard to audit globally.
- **RBAC:** permissions attach to roles, users get roles. Easy to reason about;
  suffers role explosion when rules depend on the data.
- **ABAC:** rules over attributes of subject, resource, environment ("doctors
  can read records of their own department during shift"). Flexible, harder to
  test and explain. NIST SP 800-162 is the reference.
- **ReBAC:** permissions derive from a relationship graph (owner, editor of
  folder implies viewer of its documents). Google Zanzibar; open source
  implementations include OpenFGA and SpiceDB.
- **PDP / PEP:** policy decision point evaluates, policy enforcement point
  (middleware, service) asks and enforces.
- **Horizontal vs vertical:** vertical = privilege levels (user vs admin);
  horizontal = peers' data (IDOR/BOLA).

## When to use / scenarios
- Few fixed job functions (admin, editor, viewer): RBAC.
- Rules depend on data fields, time, location, tenant: ABAC or RBAC plus
  ownership checks.
- Sharing, nested resources, teams, folders: ReBAC.
- Many services needing consistent policy: central PDP (OPA, Cedar, OpenFGA)
  with decisions logged.
- Single-tenant internal tool with three roles: do not adopt a policy engine.

## How it works / example

Layered check: role gate, then object-level ownership/tenant check.

```python
from dataclasses import dataclass
from enum import Enum

class Role(Enum):
    VIEWER = "viewer"; EDITOR = "editor"; ADMIN = "admin"

PERMS = {
    Role.VIEWER: {"doc:read"},
    Role.EDITOR: {"doc:read", "doc:write"},
    Role.ADMIN:  {"doc:read", "doc:write", "doc:delete"},
}

@dataclass(frozen=True)
class User:
    id: int; tenant_id: int; role: Role

@dataclass(frozen=True)
class Doc:
    id: int; tenant_id: int; owner_id: int

def can(user: User, action: str, doc: Doc) -> bool:
    if action not in PERMS[user.role]:            # RBAC: role grants the action
        return False
    if doc.tenant_id != user.tenant_id:           # tenant isolation, always
        return False
    if action == "doc:delete":                    # ABAC-style attribute rule
        return user.role is Role.ADMIN or doc.owner_id == user.id
    return True

def get_doc(repo, user, doc_id):
    doc = repo.get(doc_id)
    if doc is None or not can(user, "doc:read", doc):
        raise LookupError("not found")            # same error for both cases
    return doc
```

Better still, scope queries so forbidden rows are never loaded:
`SELECT ... WHERE id = %s AND tenant_id = %s`. In Postgres, Row Level Security
can enforce tenant filters in the database as a backstop.

ReBAC sketch (relation tuples, Zanzibar style):

```
doc:readme#owner@user:alice
folder:eng#viewer@group:eng-team#member
doc:readme#parent@folder:eng
check(user:bob, viewer, doc:readme) -> walk parent + group membership
```

Write the authorization tests first: a matrix of (role, action, own/other
resource, same/other tenant) with expected allow/deny.

## Trade-offs
- **Embedded checks vs central policy service:** embedded is fast and simple;
  central gives one audit point and consistency across services but adds a
  network dependency and latency (cache decisions carefully).
- **Role explosion vs attribute complexity:** more roles are easy to read but
  multiply; attributes are compact but make "who can access X" hard to answer.
- **Coarse token claims vs live lookups:** roles in JWT claims are fast but
  stale until expiry; live lookups are fresh but cost a query per request.
- **App-layer vs database enforcement (RLS):** RLS cannot be forgotten by a
  new endpoint but is harder to debug and can hurt query plans.

## Gotchas
- Checking authorization only in the UI or only at the route level, not on the
  object. This is IDOR/BOLA, ranked API1 in the OWASP API Security Top 10
  (2023).
- Mass assignment: binding request bodies directly to models lets users set
  `role` or `owner_id`. Use explicit allow-listed fields.
- Authorize every method, including export, bulk, GraphQL nested fields,
  background jobs and webhooks, not just the "main" CRUD endpoint.
- Using sequential IDs makes enumeration easy; random IDs help but are not a
  control. The check is the control.
- Forgetting indirect access: a user removed from a group still holds cached
  decisions or long-lived tokens.
- Returning 403 for resources the caller should not know exist leaks
  existence; prefer 404 where that matters.
- Admin impersonation and support tooling need audit logs and separate
  privileges.

## Related
- [[authentication-and-sessions]] - establishes the identity authorization uses.
- [[oauth2-and-oidc]] - scopes and claims as inputs to decisions.
- [[owasp-top-10]] - A01 Broken Access Control.
- [[threat-modeling]] - identify elevation-of-privilege paths before coding.
- [[data-modeling-and-schema-design]] - tenant_id and ownership columns.
- [[rest-api-design]] - object-level checks on resource routes.

## References
- OWASP Authorization Cheat Sheet.
- NIST SP 800-162 (ABAC); Sandhu, Ferraiolo and Kuhn, "The NIST Model for
  Role-Based Access Control: Towards a Unified Standard" (ACM RBAC Workshop
  2000), basis of ANSI INCITS 359.
- Pang et al., "Zanzibar: Google's Consistent, Global Authorization System"
  (USENIX ATC 2019), OpenFGA https://openfga.dev/, OPA docs.
