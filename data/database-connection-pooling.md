---
title: Database connection pooling
category: data
tags: [connection-pool, pgbouncer, hikaricp, sqlalchemy, pool-sizing, littles-law, max-connections, rds-proxy, serverless]
use_cases:
  - "requests time out waiting for a database connection under load"
  - "choose pool size and max overflow for a web service talking to Postgres"
  - "Postgres hits too many clients already after scaling out the app tier"
  - "put PgBouncer in front of Postgres and pick session or transaction pooling"
  - "serverless functions open a new database connection on every invocation"
status: draft
last_verified: 2026-10-24
sources:
  - https://docs.sqlalchemy.org/en/20/core/pooling.html
  - https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing
  - https://wiki.postgresql.org/wiki/Number_Of_Database_Connections
  - https://www.pgbouncer.org/features.html
  - https://www.pgbouncer.org/config.html
  - https://www.postgresql.org/docs/current/runtime-config-connection.html
---

# Database connection pooling

## Summary
A connection pool keeps a bounded set of open database connections and lends
them to requests, so each request skips the TCP, TLS and authentication
handshake and the database sees a controlled number of sessions. The pool is
also a concurrency limit: too small and requests queue inside the app, too
large and the database spends its time on contention instead of work. In
multi-instance or serverless deployments an external pooler (PgBouncer, a
managed proxy) caps the total across all clients.

## Key concepts
- **Why pool**: opening a connection costs network round trips and, for
  Postgres, a new backend process per connection; reusing connections removes
  that per-request cost and bounds the server's memory and process count.
- **Pool parameters** (names from SQLAlchemy's `QueuePool`, similar in
  HikariCP and others): `pool_size` (connections kept open), `max_overflow`
  (extra connections allowed temporarily), `pool_timeout` (how long a request
  waits for a free connection before failing), `pool_recycle` / max lifetime
  (replace connections older than this), `pool_pre_ping` (validate a
  connection before handing it out).
- **Sizing with Little's Law**: connections in use = query rate x time each
  connection is held. 200 transactions/s each holding a connection for 20 ms
  needs about 4 connections on average; size for peaks, then measure.
- **Smaller is often faster**: the database can only run as many queries in
  parallel as it has cores and I/O capacity. The HikariCP "About Pool Sizing"
  page and the PostgreSQL wiki give the starting formula
  `connections = (core_count * 2) + effective_spindle_count` for the database
  server, to be tuned by load testing, not a hard rule.
- **Total connections = instances x pool size (+ overflow)**. Scaling the app
  tier multiplies connections against a fixed `max_connections` on the server
  (Postgres default 100).
- **External pooler modes** (PgBouncer): *session* (client keeps a server
  connection until it disconnects), *transaction* (server connection returned
  after each transaction; most multiplexing), *statement* (after each
  statement; multi-statement transactions not allowed).
- **Connection hold time** is the real driver: a connection held across a
  slow HTTP call or user think time is a connection no one else can use.

## When to use / scenarios
- Any long-running service talking to a relational database: use the
  driver's or ORM's pool, configured explicitly.
- Many app instances, autoscaling or many worker processes: add an external
  pooler in transaction mode so the database sees a stable number of
  connections ([[capacity-planning-and-autoscaling]]).
- Serverless functions: a managed proxy (for example Amazon RDS Proxy) or a
  pooler, because each concurrent function instance otherwise opens its own
  connection ([[serverless-architecture]]).
- Isolate workloads with separate pools (web requests vs background jobs vs
  reporting) so one cannot starve another, a bulkhead
  ([[resilience-patterns]]).
- When NOT to: short-lived CLI scripts and migrations that open one connection
  (use `NullPool` or a single connection); databases or drivers that already
  multiplex over few connections, where a client pool adds nothing.

## How it works / example

```
request -> checkout() --free conn?--> yes: validate, hand out
                 |                    no: below max? open new
                 |                        else wait up to pool_timeout -> error
request done -> checkin(): rollback leftovers, return to idle queue
```

A minimal pool over SQLite (stdlib only) showing bounded size, waiting with a
timeout, reset on return, max lifetime, and how a held connection starves
other requests:

```python
import queue
import sqlite3
import threading
import time

class PoolTimeout(Exception):
    pass

class Pool:
    def __init__(self, factory, size, timeout_s, max_lifetime_s=1800):
        self._factory, self._timeout, self._max_life = factory, timeout_s, max_lifetime_s
        self._idle = queue.LifoQueue()          # LIFO keeps a hot subset warm
        self._slots = threading.BoundedSemaphore(size)
        self.opened = 0

    def _open(self):
        self.opened += 1
        return (self._factory(), time.monotonic())

    def checkout(self):
        if not self._slots.acquire(timeout=self._timeout):
            raise PoolTimeout("no free connection within pool_timeout")
        try:
            conn, born = self._idle.get_nowait()
            if time.monotonic() - born > self._max_life:   # recycle old connections
                conn.close()
                conn, born = self._open()
            else:
                conn.execute("SELECT 1")                    # pre-ping
        except queue.Empty:
            conn, born = self._open()
        return conn, born

    def checkin(self, item):
        conn, born = item
        conn.rollback()                    # never hand on an open transaction
        self._idle.put((conn, born))
        self._slots.release()

    def connection(self):
        pool = self
        class _Ctx:
            def __enter__(self):
                self.item = pool.checkout()
                return self.item[0]
            def __exit__(self, *exc):
                pool.checkin(self.item)
        return _Ctx()

factory = lambda: sqlite3.connect(":memory:", check_same_thread=False)
pool = Pool(factory, size=3, timeout_s=0.2)

# 1. Reuse: 50 sequential requests open only one connection.
for _ in range(50):
    with pool.connection() as conn:
        conn.execute("SELECT 1")
assert pool.opened == 1

# 2. Concurrency is capped at the pool size.
active, peak, lock = 0, 0, threading.Lock()
def work():
    global active, peak
    with pool.connection() as conn:
        with lock:
            active += 1
            peak = max(peak, active)
        conn.execute("SELECT 1")
        time.sleep(0.02)                  # time the connection is held
        with lock:
            active -= 1
threads = [threading.Thread(target=work) for _ in range(12)]
for t in threads: t.start()
for t in threads: t.join()
assert peak <= 3 and pool.opened <= 3

# 3. Holding connections during slow non-DB work starves everyone else.
held = [pool.checkout() for _ in range(3)]   # e.g. kept open across an HTTP call
try:
    pool.checkout()
    raise AssertionError("expected PoolTimeout")
except PoolTimeout:
    pass
for item in held:
    pool.checkin(item)
print(f"opened={pool.opened} peak_in_use={peak}")
```

The same knobs in SQLAlchemy (defaults are `pool_size=5`, `max_overflow=10`,
`pool_timeout=30`):

```python fragment
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql+psycopg://app@db/app",
    pool_size=10, max_overflow=5, pool_timeout=5,
    pool_recycle=1800, pool_pre_ping=True,
)
```

## Trade-offs
- **Large vs small pool**: a large pool absorbs bursts without queuing in the
  app but pushes contention (locks, CPU, memory per backend) into the
  database; a small pool keeps the database efficient and makes overload
  visible as fast pool timeouts.
- **Fail fast vs wait**: a short `pool_timeout` sheds load and frees request
  threads; a long one hides overload as latency and ties up workers.
- **Client pool only vs external pooler**: client pools are simple and keep
  session features; an external pooler caps totals across many clients but
  adds a hop and, in transaction mode, restricts session state.
- **Transaction vs session pooling**: transaction mode multiplexes far more
  clients per server connection; session mode keeps `SET`, temporary tables,
  `LISTEN`, session advisory locks and similar features working.
- **Pre-ping vs no validation**: pre-ping costs a round trip per checkout but
  avoids errors from connections dropped by firewalls, failovers or idle
  timeouts.

## Gotchas
- Scaling out the app tier until the database hits `max_connections` and
  starts refusing everyone; multiply instances by pool size before scaling.
- Holding a connection (or an open transaction) across external calls,
  queue waits or streaming responses; acquire late, release early.
- Connection leaks: a code path that never returns the connection. Use
  context managers and enable leak detection or logging of long checkouts.
- Session state leaking between requests: `SET search_path`, tenant id
  settings or temp tables left on a pooled connection
  ([[choosing-a-multi-tenancy-model]]).
- Transaction-mode poolers break features that rely on the session staying
  on one server connection; older PgBouncer versions also did not support
  protocol-level prepared statements in this mode (newer ones can track them
  via `max_prepared_statements`). Check your driver settings.
- Forking after the pool is created (pre-fork servers, multiprocessing) shares
  sockets between processes; create or reset the pool in each child
  (SQLAlchemy documents `engine.dispose(close=False)` for this).
- Idle connections killed by load balancers, NAT or the server without the
  pool noticing; set max lifetime below those timeouts and enable validation.
- Pool exhaustion looks like database slowness in latency graphs; export
  pool metrics (in use, idle, waiters, wait time)
  ([[observability-logs-metrics-traces]]).

## Related
- [[capacity-planning-and-autoscaling]] - Little's Law and sizing pools against a fixed database.
- [[orm-and-n-plus-one]] - session lifetime and query count decide connection hold time.
- [[transactions-and-isolation-levels]] - a transaction pins a connection until commit or rollback.
- [[networking-fundamentals]] - TCP and TLS handshake costs that pooling removes.
- [[resilience-patterns]] - separate pools per workload act as bulkheads.
- [[serverless-architecture]] - why functions need a proxy or external pooler.
- [[processes-threads-and-io-models]] - worker model decides how many pools and connections exist.

## References
- SQLAlchemy 2.0 documentation, "Connection Pooling": https://docs.sqlalchemy.org/en/20/core/pooling.html
- HikariCP wiki, "About Pool Sizing": https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing
- PostgreSQL wiki, "Number Of Database Connections": https://wiki.postgresql.org/wiki/Number_Of_Database_Connections
- PgBouncer features (pooling modes and SQL feature support): https://www.pgbouncer.org/features.html
- PgBouncer configuration reference: https://www.pgbouncer.org/config.html
- PostgreSQL documentation, "Connections and Authentication" (`max_connections`): https://www.postgresql.org/docs/current/runtime-config-connection.html
