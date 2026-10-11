---
title: Distributed locks and leader election
category: distributed-systems
tags: [distributed-lock, leader-election, lease, fencing-token, redlock, redis, zookeeper, etcd, advisory-lock, postgres]
use_cases:
  - "make sure only one instance of a cron job or worker runs at a time across several servers"
  - "elect a single leader among service replicas and fail over when it dies"
  - "decide whether a Redis lock is safe enough or we need ZooKeeper or etcd"
  - "stop a paused or partitioned old lock holder from corrupting data after its lease expired"
  - "use a Postgres advisory lock instead of adding a coordination service"
status: draft
last_verified: 2026-10-11
sources:
  - https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
  - http://antirez.com/news/101
  - https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/
  - https://zookeeper.apache.org/doc/current/recipes.html
  - https://etcd.io/docs/v3.5/dev-guide/api_concurrency_reference_v3/
  - https://www.postgresql.org/docs/current/explicit-locking.html
  - https://www.postgresql.org/docs/current/functions-admin.html
  - https://www.pgbouncer.org/features.html
  - https://research.google/pubs/the-chubby-lock-service-for-loosely-coupled-distributed-systems/
  - "Martin Kleppmann, Designing Data-Intensive Applications (O'Reilly, 2017), ch. 8 'The Truth Is Defined by the Majority' and ch. 9"
---

# Distributed locks and leader election

## Summary
A distributed lock gives one process at a time the right to act on a shared resource; leader election is the same thing held
for a long time by one replica of a service. Because processes can crash, every practical lock is a **lease** that expires.
Expiry creates the core hazard: a holder that pauses (GC, VM stall, network delay) can resume after its lease ran out and act
while someone else holds the lock. The fix is a **fencing token** checked by the resource, plus a lock service built on
consensus (ZooKeeper, etcd) when correctness, not just efficiency, depends on mutual exclusion.

## Key concepts
- **Efficiency vs correctness lock** (Kleppmann): an efficiency lock only avoids duplicate work, so an occasional double holder
  costs a little extra; a correctness lock prevents corruption, so two holders at once is a serious bug. Decide which you have first.
- **Lease**: a lock with a time-to-live. It frees the resource when the holder dies, but the holder cannot know reliably that its
  lease is still valid at the moment its write lands.
- **Fencing token**: a number that increases with every lock grant. The holder sends it with every write; the resource remembers
  the highest token it has accepted and rejects lower ones. This makes safety independent of clocks and pauses.
- **Lock service options**:
  - *Single Redis* `SET key random_value NX PX ttl`, release only if the value still matches. Simple; a single point of failure, and
    failover to an asynchronously replicated replica can grant the lock twice.
  - *Redlock*: acquire the same key on a majority of N independent Redis masters (the docs use N = 5) within the validity time.
    Relies on bounded clock drift and timing; does not issue fencing tokens.
  - *ZooKeeper*: ephemeral sequential znodes; the lowest sequence number holds the lock, and each waiter watches only its
    predecessor. Ephemeral nodes vanish when the session expires. zxid or znode version can serve as a fencing token.
  - *etcd*: `Lock` returns a key that exists while the lock is held and is tied to a lease; the election API (`Campaign`,
    `Proclaim`, `Leader`, `Observe`, `Resign`) returns a leader key whose creation revision `rev` can be checked in transactions.
  - *Postgres advisory locks*: application-defined locks keyed by a `bigint` (or two `integer`s), session- or transaction-scoped.
- **Leader election via consensus**: Raft itself elects a leader per term; applications usually borrow election from an etcd or
  ZooKeeper cluster rather than running their own ([[consensus-raft-paxos]]).

## When to use / scenarios
- Exactly one scheduler or cron trigger across replicas, one compaction or migration runner, one consumer per partition: use
  leader election with a lease ([[design-job-scheduler]]).
- Protecting a shared resource that cannot itself serialise access (a file in object storage, an external API, a legacy system):
  use a lock, and make the resource check fencing tokens wherever it can.
- Efficiency-only (avoid computing the same report twice): a single Redis lock or a DB row with a TTL is fine; document that it is
  approximate.
- Correctness-critical with an existing Postgres: `pg_advisory_xact_lock` inside the same transaction that does the work, or a
  conditional `UPDATE ... WHERE version = ?`, is often all you need, with no new infrastructure.
- Do NOT add a lock when the resource can do the check itself: a unique constraint, compare-and-set, optimistic concurrency or an
  idempotency key ([[idempotency-and-exactly-once]]) is simpler and safer than coordinating outside the database.
- Do NOT treat any lease-based lock as a guarantee for work you cannot fence (sending an email, moving a physical object); design
  that work to tolerate occasional duplicates instead.

## How it works / example
The failure the fencing token prevents (from Kleppmann's post):

```
client 1: acquire lease (token 33) ... GC pause ......................... resume -> write(token 33) -> REJECTED
lock svc:                       lease 33 expires -> grant client 2 (token 34)
client 2:                                           write(token 34) -> ok
storage:  highest seen = 34, so token 33 is stale
```

Runnable model: a lock service with lease expiry and monotonically increasing tokens, a storage server that rejects stale tokens,
and a client that pauses past its lease.

```python
class LockService:
    """Grants one lease at a time; every grant gets a larger token."""
    def __init__(self, ttl):
        self.ttl, self.token, self.holder, self.expires = ttl, 0, None, 0.0

    def acquire(self, client, now):
        if self.holder is not None and now < self.expires:
            return None                                  # held by someone else
        self.token += 1                                  # monotonic, never reused
        self.holder, self.expires = client, now + self.ttl
        return self.token

class Storage:
    """The protected resource: it, not the client, enforces ordering."""
    def __init__(self):
        self.max_token, self.data = 0, {}

    def write(self, key, value, token):
        if token < self.max_token:
            return False                                 # stale holder: fenced off
        self.max_token = token
        self.data[key] = value
        return True

locks, store = LockService(ttl=10), Storage()

t1 = locks.acquire("client-1", now=0)                    # token 1, lease until t=10
assert t1 == 1
assert locks.acquire("client-2", now=5) is None          # mutual exclusion while lease is live

# client-1 now pauses (GC, VM stall) from t=5 to t=15; its lease expires at t=10
t2 = locks.acquire("client-2", now=12)                   # token 2
assert t2 == 2
assert store.write("file", "from client-2", t2)

# client-1 resumes believing it still holds the lock and writes with its old token
assert store.write("file", "from client-1", t1) is False
assert store.data["file"] == "from client-2"             # the stale write did not land
print("fencing ok")
```

Postgres advisory lock for "one runner at a time", released automatically at transaction end:

```sql
BEGIN;
SELECT pg_try_advisory_xact_lock(42);   -- true: we run; false: someone else is running, exit
-- ... do the work in this same transaction ...
COMMIT;                                 -- lock released here, also on crash/disconnect
```

ZooKeeper lock recipe in outline:

```
create /locks/job-/lock-  (EPHEMERAL | SEQUENTIAL)     -> /locks/job-/lock-0000000007
children = getChildren(/locks/job-)
if mine is the lowest: lock held
else: watch only the next-lower node; on its deletion, re-check (avoids the herd effect)
```

## Trade-offs
- **Redis vs consensus store**: Redis is fast and often already deployed; ZooKeeper/etcd give linearizable state, session-based
  ephemeral ownership and natural fencing values, at the cost of running a 3- or 5-node quorum.
- **The Redlock debate**: Kleppmann argues Redlock is unsafe for correctness locks because it depends on timing (clock jumps,
  network delays, process pauses) and cannot produce fencing tokens; use single-node Redis for efficiency and a consensus system
  for correctness. antirez replies that if the resource can check tokens it barely needs a lock, that a large random token with
  check-and-set works on non-linearizable stores, that Redlock re-checks elapsed time after acquiring, and that clock jumps are an
  operations problem; he concedes Redis should use a monotonic clock for this. The Redis docs now advise implementing fencing
  tokens and note that Redis TTLs do not use a monotonic clock. Practical reading: both sides agree a lease alone does not make
  a long or pausing operation safe.
- **Lease length**: short leases fail over quickly but expire on harmless pauses and cause churn; long leases tolerate pauses but
  leave the resource idle longer after a crash. Renew (heartbeat) well before expiry.
- **Advisory locks vs a coordination service**: advisory locks reuse the database you already trust and die with the session;
  they do not span databases, and PgBouncer's transaction pooling mode does not support session-level advisory locks.

## Gotchas
- Checking "do I still hold the lock?" right before writing does not help: the pause can happen between the check and the write.
- Releasing with a plain `DEL` can delete a lock that has since been granted to someone else; release only if the stored value is
  yours.
- Failover of a single Redis primary to an asynchronously replicated replica can hand the same lock to two clients.
- A fencing token is useless unless the resource actually rejects lower tokens; most storage APIs need a conditional write to do it.
- Session-level Postgres advisory locks survive `ROLLBACK` and stay held until unlocked or the session ends; behind a transaction
  pooler that session may be shared. Prefer `pg_advisory_xact_lock`.
- Locking with `SELECT pg_advisory_lock(id) FROM t WHERE ... LIMIT n` can take more locks than intended, because `LIMIT` is not
  guaranteed to apply before the function runs; lock in an outer query over a subquery.
- Leader election without fencing gives split brain during the overlap: two "leaders" both write ([[failure-modes-and-fallacies]]).
- Wall-clock comparisons for lease expiry across machines inherit clock skew ([[time-clocks-and-ordering]]).

## Related
- [[consensus-raft-paxos]] - the algorithms underneath ZooKeeper and etcd, and leader election in Raft
- [[time-clocks-and-ordering]] - why leases cannot rely on synchronised clocks
- [[idempotency-and-exactly-once]] - the alternative to locking when duplicate work must be harmless
- [[design-job-scheduler]] - worked design using leases, fencing and leader election
- [[replication]] - asynchronous failover is what breaks a single-node Redis lock
- [[failure-modes-and-fallacies]] - process pauses and partitions that make leases expire
- [[transactions-and-isolation-levels]] - database locking and conditional updates as a simpler alternative
- [[storage-engines-btree-lsm]] - the storage layer that must enforce the fencing check

## References
- Martin Kleppmann, "How to do distributed locking" (2016): https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
- Salvatore Sanfilippo (antirez), "Is Redlock safe?": http://antirez.com/news/101
- Redis, Distributed Locks with Redis: https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/
- Apache ZooKeeper, Recipes (Locks, Leader Election): https://zookeeper.apache.org/doc/current/recipes.html
- etcd v3 concurrency API reference: https://etcd.io/docs/v3.5/dev-guide/api_concurrency_reference_v3/
- PostgreSQL, Advisory Locks: https://www.postgresql.org/docs/current/explicit-locking.html
- PostgreSQL, Advisory Lock Functions: https://www.postgresql.org/docs/current/functions-admin.html
- PgBouncer features (pooling-mode compatibility): https://www.pgbouncer.org/features.html
- Burrows, "The Chubby lock service for loosely-coupled distributed systems" (OSDI 2006): https://research.google/pubs/the-chubby-lock-service-for-loosely-coupled-distributed-systems/
- Kleppmann, *Designing Data-Intensive Applications*, ch. 8-9.
