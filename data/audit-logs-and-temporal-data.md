---
title: Audit logs, history tables and temporal data
category: data
tags: [audit-log, audit-trail, history-table, temporal-table, system-versioning, bitemporal, soft-delete, tamper-evident, hash-chain, as-of-query, triggers, retention]
use_cases:
  - "answer who changed this record, when, and what the value was before"
  - "show what a customer's plan or price was on a past date for billing disputes"
  - "let users delete and restore records without breaking unique constraints"
  - "keep an audit trail that admins cannot quietly edit, for compliance reviews"
  - "record a correction to past data without losing what we believed at the time"
status: draft
last_verified: 2026-10-24
sources:
  - https://martinfowler.com/eaaDev/AuditLog.html
  - https://martinfowler.com/articles/bitemporal-history.html
  - https://learn.microsoft.com/en-us/sql/relational-databases/tables/temporal-tables
  - https://www.postgresql.org/docs/current/plpgsql-trigger.html
  - https://www.sqlite.org/lang_createtrigger.html
  - https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
  - https://www.rfc-editor.org/rfc/rfc6962
---

# Audit logs, history tables and temporal data

## Summary
Most tables store only the current value, so "what was it last month and who
changed it?" has no answer. Three related techniques fix that: an **audit log**
records each change event with actor, time and before/after values; a
**history (temporal) table** keeps every past version of a row with the period
it was valid, so you can query the data as of any moment; and **bitemporal**
modelling separately tracks when a fact was true in the world and when the
database learned it, so corrections do not erase what was believed before.
Add soft deletes for restorable deletion, tamper evidence (hash chains,
write-once storage) when the trail is itself evidence, and a retention policy
so history does not keep personal data forever.

## Key concepts
- **Audit log (audit trail)**: append-only records of who did what to which
  record, when, from where, and the old and new values. Answers accountability
  questions; it is not the application's source of truth.
- **History table**: a copy of each superseded row version with `valid_from` and
  `valid_to`. The current table stays fast and simple; history grows beside it.
- **System-versioned temporal table**: the database maintains the history table
  itself (SQL:2011 `PERIOD FOR SYSTEM_TIME`; SQL Server, MariaDB, Db2 and
  others) and supports `FOR SYSTEM_TIME AS OF` queries. PostgreSQL has no
  built-in version; use triggers or an extension.
- **Valid time vs transaction (system) time**: valid time is when the fact was
  true in the business world (a price effective from 1 March); transaction time
  is when the row was recorded. Storing both is **bitemporal** data.
- **Half-open periods** `[valid_from, valid_to)`: adjacent versions never
  overlap or leave gaps; the current row has `valid_to` = infinity (or NULL).
- **Soft delete**: mark rows `deleted_at` instead of removing them, so they can
  be restored and still join to history. Every query and unique constraint must
  then account for it.
- **Tamper evidence**: each audit record stores a hash of its content plus the
  previous record's hash (a hash chain); editing or deleting one record breaks
  every later hash. Merkle-tree logs (as in Certificate Transparency, RFC 6962)
  allow efficient proofs. Write-once (WORM) storage and a separate account make
  the log tamper-resistant, not just tamper-evident.
- **Where changes are captured**: application code (knows the actor and
  reason), database triggers (cannot be bypassed by other writers, but must be
  told the actor), or change data capture from the WAL (no write-path cost,
  usually no actor) ([[change-data-capture]]).

## When to use / scenarios
- Regulated or financial data, admin actions, permission and role changes,
  security settings: an audit log with actor, reason and request id.
- Prices, plans, tax rates, contracts, org charts, anything billed or reported
  "as of" a date: a history table or valid-time columns.
- Late-arriving corrections ("the rate changed in March, but we only heard in
  May") where reports already sent must stay reproducible: bitemporal.
- Users expect a trash bin or undo: soft delete with a purge job.
- The whole domain is naturally a sequence of events and you need to rebuild
  state from them: event sourcing instead ([[cqrs-and-event-sourcing]]).
- When NOT to: high-churn, low-value data (counters, sessions, caches) where
  history is pure cost; use metrics or logs. For debugging-only traces use
  application logs ([[observability-logs-metrics-traces]]), not audit tables.

## How it works / example
Trigger-maintained history with an as-of query, soft delete with a partial
unique index, and a tamper-evident audit chain, using the stdlib `sqlite3`:

```python
import hashlib
import json
import sqlite3

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE account (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL,
  plan TEXT NOT NULL,
  updated_at TEXT NOT NULL,         -- set by the application (system time)
  updated_by TEXT NOT NULL,         -- actor, passed explicitly
  deleted_at TEXT                   -- soft delete marker
);
-- Only live rows must have unique emails; a deleted address can be reused.
CREATE UNIQUE INDEX account_email_live ON account(email) WHERE deleted_at IS NULL;

CREATE TABLE account_history (
  id INTEGER NOT NULL, email TEXT, plan TEXT, deleted_at TEXT,
  valid_from TEXT NOT NULL, valid_to TEXT NOT NULL,   -- half-open [from, to)
  changed_by TEXT NOT NULL
);
-- Every update copies the superseded version; writers cannot skip it.
CREATE TRIGGER account_versioning AFTER UPDATE ON account BEGIN
  INSERT INTO account_history
  VALUES (OLD.id, OLD.email, OLD.plan, OLD.deleted_at,
          OLD.updated_at, NEW.updated_at, OLD.updated_by);
END;
CREATE TRIGGER account_no_hard_delete BEFORE DELETE ON account BEGIN
  SELECT RAISE(ABORT, 'use soft delete; purge runs as a separate job');
END;
""")

def write(sql, *args):
    with db:
        db.execute(sql, args)

write("INSERT INTO account VALUES (1, 'a@x.io', 'free', '2026-01-01', 'signup', NULL)")
write("UPDATE account SET plan='pro', updated_at='2026-03-01', updated_by='alice' WHERE id=1")
write("UPDATE account SET plan='team', updated_at='2026-06-01', updated_by='bob' WHERE id=1")

AS_OF = """
SELECT plan, deleted_at FROM (
  SELECT plan, deleted_at, valid_from, valid_to FROM account_history WHERE id = ?
  UNION ALL
  SELECT plan, deleted_at, updated_at, '9999-12-31' FROM account WHERE id = ?
) WHERE valid_from <= ? AND ? < valid_to
"""

def plan_as_of(account_id, at):
    row = db.execute(AS_OF, (account_id, account_id, at, at)).fetchone()
    return None if row is None or row[1] else row[0]

assert plan_as_of(1, "2025-12-31") is None          # did not exist yet
assert plan_as_of(1, "2026-02-15") == "free"
assert plan_as_of(1, "2026-03-01") == "pro"         # boundary belongs to the new version
assert plan_as_of(1, "2026-07-01") == "team"

# Soft delete, then the same email can sign up again.
write("UPDATE account SET deleted_at='2026-08-01', updated_at='2026-08-01', updated_by='carol' WHERE id=1")
write("INSERT INTO account VALUES (2, 'a@x.io', 'free', '2026-09-01', 'signup', NULL)")
assert plan_as_of(1, "2026-09-01") is None and plan_as_of(1, "2026-07-01") == "team"
try:
    write("DELETE FROM account WHERE id=2")
except sqlite3.IntegrityError:
    pass
else:
    raise AssertionError("hard delete allowed")
history = db.execute("SELECT changed_by FROM account_history WHERE id=1 ORDER BY valid_from").fetchall()
assert [r[0] for r in history] == ["signup", "alice", "bob"]

# Tamper-evident audit log: each entry commits to the previous one.
def entry_hash(prev_hash, record):
    body = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()

def append(log, record):
    prev = log[-1]["hash"] if log else "0" * 64
    log.append({"record": record, "prev": prev, "hash": entry_hash(prev, record)})

def verify(log):
    prev = "0" * 64
    for i, e in enumerate(log):
        if e["prev"] != prev or e["hash"] != entry_hash(prev, e["record"]):
            return i                                  # first broken entry
        prev = e["hash"]
    return None

audit = []
append(audit, {"actor": "alice", "action": "plan.change", "id": 1, "from": "free", "to": "pro"})
append(audit, {"actor": "bob", "action": "plan.change", "id": 1, "from": "pro", "to": "team"})
append(audit, {"actor": "carol", "action": "account.delete", "id": 1})
assert verify(audit) is None
audit[1]["record"]["actor"] = "mallory"                # an admin quietly edits history
assert verify(audit) == 1
print("ok")
```

Bitemporal correction, as rows (valid time = when the price applies;
recorded = transaction time):

| price | valid_from | valid_to | recorded_from | recorded_to |
|---|---|---|---|---|
| 10 | 2026-01-01 | infinity | 2026-01-01 | 2026-05-10 |
| 10 | 2026-01-01 | 2026-03-01 | 2026-05-10 | infinity |
| 12 | 2026-03-01 | infinity | 2026-05-10 | infinity |

"What was the price on 15 April?" is 12 today, but a report run on 1 May
correctly said 10; both questions stay answerable.

## Trade-offs
- **Application-level vs trigger vs CDC capture**: the application knows the
  actor, reason and request id but any other writer (scripts, migrations,
  another service) skips it; triggers catch every write in the database but
  add write latency and need the actor passed in (session variable or column);
  CDC costs nothing on the write path and catches everything, but typically
  loses the actor and arrives asynchronously.
- **Row snapshots vs field diffs**: full snapshots make as-of queries trivial
  and cost storage; diffs are compact but must be replayed to reconstruct a
  version.
- **Same database vs separate audit store**: the same database gives
  transactional consistency with the change; a separate append-only store
  (different credentials, WORM bucket, SIEM) survives a compromised or careless
  database admin.
- **Soft vs hard delete**: soft delete enables restore and keeps referential
  history, but every query, index and unique constraint must filter it, and it
  conflicts with erasure obligations; many teams soft delete, then hard delete
  or anonymize after a grace period.
- **Uni- vs bitemporal**: system time alone is enough for "what did the row
  look like"; add valid time only when the business backdates or corrects
  facts, because every query and write gets harder.

## Gotchas
- Using the database clock in the trigger while the app uses its own clock:
  versions get periods that overlap or go backwards. Pick one time source.
- Closed periods (`<=` on both ends) make a boundary instant match two
  versions; use half-open periods.
- Audit rows that store full before/after values copy personal data, secrets
  and tokens into a table nobody purges; redact and apply retention
  ([[privacy-and-pii-handling]]).
- "Right to erasure" vs immutable history: plan crypto-shredding or
  pseudonymous actor ids before the log fills up.
- Soft-deleted rows leaking through: an ORM default scope covers most queries,
  but raw SQL, reports, joins and search indexes forget the filter.
- A plain unique index blocks re-registration with a soft-deleted email; use a
  partial (filtered) unique index on live rows.
- Bulk updates and migrations write millions of history rows and can fill the
  disk or lock tables; batch them and size history storage.
- A hash chain only detects tampering if the latest hash is anchored somewhere
  the attacker cannot rewrite (another system, a signed checkpoint).
- Audit logs written outside the transaction can record changes that rolled
  back, or miss ones that committed; write them in the same transaction or
  from the outbox/CDC stream.
- History tables still need indexes on `(id, valid_from)`; as-of queries
  otherwise scan everything.

## Related
- [[cqrs-and-event-sourcing]] - when the event history is the source of truth, not a side table.
- [[change-data-capture]] - capturing every committed change from the WAL.
- [[data-modeling-and-schema-design]] - soft delete and audit columns in the base schema.
- [[privacy-and-pii-handling]] - retention, redaction and erasure for history and audit data.
- [[authorization-models]] - audit role and permission changes and admin actions.
- [[database-indexing]] - partial unique indexes and indexes for as-of queries.
- [[time-clocks-and-ordering]] - choosing a single, trustworthy time source for versions.
- [[design-payment-system]] - append-only ledgers as the strictest form of history.
- [[merkle-trees-and-anti-entropy]] - Merkle-tree logs with inclusion and consistency proofs.

## References
- Martin Fowler, "Audit Log" (martinfowler.com/eaaDev) and "Bitemporal History" (2021).
- Richard T. Snodgrass, *Developing Time-Oriented Database Applications in SQL* (Morgan Kaufmann, 1999).
- Krishna Kulkarni and Jan-Eike Michels, "Temporal features in SQL:2011", *SIGMOD Record* 41(3), 2012.
- Microsoft Learn, "Temporal tables" (SQL Server system-versioned tables).
- PostgreSQL documentation, "Trigger Functions" (PL/pgSQL); SQLite documentation, "CREATE TRIGGER".
- OWASP Logging Cheat Sheet (what to log, protection of logs).
- RFC 6962, *Certificate Transparency* (Merkle-tree append-only logs).
