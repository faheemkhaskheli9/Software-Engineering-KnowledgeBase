---
title: Design a ticket booking system with seat holds
category: case-studies
tags: [ticket-booking, ticketmaster, seat-reservation, holds, double-booking, optimistic-locking, waiting-room, flash-sale, case-study]
use_cases:
  - "design a Ticketmaster or BookMyShow style system where users pick seats and pay"
  - "hold seats for a few minutes during checkout and release them if payment does not finish"
  - "guarantee a seat, room or slot is never sold twice under heavy concurrency"
  - "survive a flash sale where demand is many times the inventory with a virtual waiting room"
  - "practice the ticket or hotel reservation system design interview question end to end"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 2 (Alex Xu, Sahn Lam), 'Hotel Reservation System' chapter"
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017, ch. 7 (write skew, double booking)"
  - https://www.postgresql.org/docs/current/explicit-locking.html
  - https://www.postgresql.org/docs/current/transaction-iso.html
  - https://redis.io/docs/latest/commands/set/
  - https://stripe.com/blog/idempotency
---

# Design a ticket booking system with seat holds

## Summary
Users browse an event, pick specific seats (or a quantity in a section), hold
them for a few minutes while they pay, and receive tickets. The defining
requirement is **no double booking** under extreme contention: thousands of
people want the same few seats in the same second when sales open. The design
uses the database's atomic conditional update as the source of truth for seat
state, time-limited holds that expire on their own, idempotent payment, and a
waiting room in front of the system to turn a stampede into a queue.

## Key concepts
- **Seat state machine**: `available -> held(hold_id, expires_at) -> sold`, and `held -> available` on expiry or cancel.
- **Hold with TTL**: the hold is a lease; an expired hold is treated as available without needing a cleanup job to run first.
- **Atomic claim**: "set these seats to held only if all of them are available" must be one atomic operation, a conditional `UPDATE ... WHERE status='available'` checked by row count, or row locks (`SELECT ... FOR UPDATE`).
- **Write skew** is the classic double-booking bug: two transactions each check "seat free", both insert a booking ([[transactions-and-isolation-levels]]). Fix by locking the rows checked or putting a unique constraint on `(event_id, seat_id)` for sold tickets.
- **Idempotent payment and confirmation**: payment retries must not charge twice or sell twice ([[design-payment-system]]).
- **Virtual waiting room**: admit users to checkout at a controlled rate when demand far exceeds capacity.

## When to use / scenarios
- Concerts, sports, cinema, flights, trains, hotel rooms, appointment slots, limited product drops.
- General admission (no specific seat) is simpler: an inventory counter decremented atomically, not per-seat rows.
- Low-contention booking (a dentist's calendar) needs only a unique constraint and a transaction; skip the waiting room and the hold service.

## How it works / example

### 1. Requirements
Functional:
- Browse events, see the seat map with availability.
- Select up to N seats and hold them for a fixed time (assume 10 minutes) during checkout.
- Pay; on success the seats are sold and tickets issued; on failure or timeout the hold is released.
- Cancel/refund per event policy (out of scope for v1 beyond releasing seats).

Non-functional:
- Correctness over availability for the claim and sale: never sell a seat twice.
- Seat map may be slightly stale (seconds); the claim is the authoritative check.
- Survive on-sale spikes where traffic is orders of magnitude above normal, with fairness (first come, first served or lottery).
- Payment is a dependency with its own failures and latency.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- A big on-sale: assume 50,000 seats and 2 M people arriving in the first minutes -> 40 users per seat. Most traffic is seat-map reads and retries, not successful holds.
- Peak read QPS on the seat map: assume 2 M users refreshing every few seconds -> hundreds of thousands of reads/s. This is the load to absorb with caching and the waiting room.
- Hold writes are bounded by the admission rate you choose (e.g. admit 2,000 users/minute), not by demand.
- Storage is small: seats x events, a few hundred bytes per seat row.

### 3. API
```
GET  /events/{id}/seats?section=           -> seat map, cached, eventually consistent
POST /events/{id}/holds  { seat_ids: [...] }   Idempotency-Key: <uuid>
                         -> 201 { hold_id, expires_at } | 409 { unavailable: [...] }
POST /holds/{hold_id}/checkout { payment_method }   Idempotency-Key: <uuid>
                         -> 200 { order_id, tickets } | 402 payment failed | 410 hold expired
DELETE /holds/{hold_id}                    -> 204 (release early)
```

### 4. Data model
```
events(event_id, venue_id, starts_at, on_sale_at)
seats(event_id, seat_id, section, row, number, price_tier,
      status, hold_id, hold_expires_at, order_id, version)   PK (event_id, seat_id)
holds(hold_id, user_id, event_id, seat_ids[], expires_at, state)
orders(order_id, hold_id UNIQUE, user_id, amount, payment_ref, state)
```
`orders.hold_id UNIQUE` means one hold can become at most one order, so a
retried checkout finds the existing order instead of creating a second one.
Shard by `event_id`: an event's seats live together, so a multi-seat claim is
a single-shard transaction ([[partitioning-and-sharding]]).

### 5. High-level architecture
```
 users -> CDN (static, seat map snapshots) -> waiting room (queue tokens, admission rate)
                                                   | admitted users only
                                                   v
          LB -> booking service (stateless) --> seats DB (Postgres, sharded by event_id)
                       |                              ^
                       |-- payment service --> PSP    |  confirm sale (conditional update)
                       |-- hold expiry: lazy check on read + periodic sweeper
                       '-- events --> queue --> ticket issuing, email, seat-map cache refresh
```
See [[caching-strategies]], [[message-queues-and-streams]], [[rate-limiting]].

### 6. Deep dive A: claiming seats atomically
The claim treats an expired hold as available, so correctness never depends
on a sweeper having run. All requested seats are claimed or none are.

```python
import sqlite3, uuid

db = sqlite3.connect(":memory:", isolation_level=None)
db.execute("""CREATE TABLE seats(seat_id TEXT PRIMARY KEY, status TEXT DEFAULT 'available',
              hold_id TEXT, hold_expires REAL)""")
db.executemany("INSERT INTO seats(seat_id) VALUES (?)", [("A1",), ("A2",), ("A3",)])

def hold(seat_ids, now, ttl=600):
    hold_id = str(uuid.uuid4())
    marks = ",".join("?" * len(seat_ids))
    db.execute("BEGIN IMMEDIATE")          # Postgres: one UPDATE in a transaction does the same
    cur = db.execute(f"""UPDATE seats SET status='held', hold_id=?, hold_expires=?
        WHERE seat_id IN ({marks}) AND (status='available' OR (status='held' AND hold_expires < ?))""",
        (hold_id, now + ttl, *seat_ids, now))
    if cur.rowcount != len(seat_ids):      # some seat was taken: all or nothing
        db.execute("ROLLBACK")
        return None
    db.execute("COMMIT")
    return hold_id

def sell(hold_id, now):
    cur = db.execute("""UPDATE seats SET status='sold'
        WHERE hold_id=? AND status='held' AND hold_expires >= ?""", (hold_id, now))
    return cur.rowcount > 0                # payment captured only if this succeeded

h1 = hold(["A1", "A2"], now=0)
assert h1 and hold(["A2", "A3"], now=10) is None      # A2 is held: whole request fails
assert db.execute("SELECT status FROM seats WHERE seat_id='A3'").fetchone()[0] == "available"
h2 = hold(["A2", "A3"], now=700)                      # h1 expired at 600: A2 claimable again
assert h2 and not sell(h1, now=700)                   # stale hold cannot be sold
assert sell(h2, now=701)
```

Order of operations at checkout: authorise payment, then run `sell` (the
conditional update), then capture. If `sell` affects no rows (hold expired and
seat resold), void the authorisation. Payment idempotency keys make retries of
each step safe ([[idempotency-and-exactly-once]]).

### 7. Deep dive B: the on-sale spike and the waiting room
- Put a waiting room in front of checkout: arriving users get a signed queue token with a position; the system admits users at a fixed rate that the booking DB can sustain. Everyone else sees their position, served from a CDN-cacheable page.
- Fairness: assign position by arrival time at open (or randomise everyone who arrived before the open time, a lottery) so refreshing does not help.
- Seat map reads come from a cache refreshed every second or two; it may show a seat as free that was just held, which the claim handles with a 409 and a refreshed map.
- Bots: require login, per-account and per-device purchase limits, and rate limits on hold attempts ([[rate-limiting]]).
- For general admission, a Redis atomic decrement (or a DB counter) per section can serve as the fast gate, with the DB still recording each order.

### 8. Deep dive C: hold expiry and consistency
- Expiry is enforced at read time (the `hold_expires < now` condition); a sweeper only tidies state and refreshes caches.
- Use the DB's clock for `now` so app server clock skew cannot shorten or extend holds ([[time-clocks-and-ordering]]).
- Holds in Redis (`SET key value NX PX ttl`) are fast but make Redis a source of truth; if you do this, still confirm the sale with a conditional update or a unique constraint in the durable DB.
- Isolation: with a single conditional `UPDATE` the default Read Committed level in Postgres is enough because the row locks taken by the update serialise competitors; check-then-insert patterns need `SELECT ... FOR UPDATE` or Serializable.

### 9. Scaling and failure handling
- **Hot event shard**: one event's seats on one primary is the bottleneck by design (it is what gives correctness). The waiting room keeps its write rate within budget; a very large venue can split by section across shards since a hold rarely spans sections.
- **Payment provider slow or down**: keep the hold timer running, show a clear error, release on expiry. Never sell without a successful authorisation; reconcile with the PSP afterwards ([[design-payment-system]]).
- **Booking service crash mid-checkout**: the hold expires; an idempotent retry finds the order or the hold state.
- **DB failover**: synchronous replication for the seats DB so a confirmed sale is never lost on failover ([[replication]]).
- **Monitoring**: hold success rate, holds expiring unpaid, checkout latency, oversell check (sold seats > capacity must alert at zero tolerance).

## Trade-offs
- Pessimistic (row locks) vs optimistic (version check or conditional update) concurrency: optimistic is simpler and cheaper under moderate contention; at extreme contention most attempts fail anyway, so admission control matters more than the locking style.
- Hold length: long holds frustrate other buyers and let scalpers park inventory; short holds fail slow payers.
- Redis holds (fast) vs DB holds (one source of truth): start with the DB.
- Specific seat selection is a better product but far more contention than best-available assignment by the server.

## Gotchas
- Check-then-insert without locks: write skew sells the same seat twice.
- Relying on a cron to expire holds: if it falls behind, inventory looks sold out.
- Capturing payment before the sale is confirmed, then failing to sell: refunds and angry users.
- Retry storms at on-sale time from clients hammering a 409 or 503; tell them to back off or queue them.
- Caching the seat map too long: users repeatedly pick seats that are already gone.
- Multi-seat holds claimed one row at a time without all-or-nothing semantics leave partial holds behind.

## Related
- [[transactions-and-isolation-levels]] - write skew and why the claim must be atomic
- [[design-payment-system]] - authorise, capture and reconcile with idempotency
- [[idempotency-and-exactly-once]] - safe retries of holds and checkout
- [[rate-limiting]] - per-account limits and admission control
- [[caching-strategies]] - serving the seat map under read spikes
- [[system-design-interview-framework]] - the procedure this case follows

## References
- Alex Xu and Sahn Lam, *System Design Interview Vol. 2*, "Hotel Reservation System"
- Kleppmann, *Designing Data-Intensive Applications* (2017), ch. 7, write skew and phantoms
- PostgreSQL explicit locking: https://www.postgresql.org/docs/current/explicit-locking.html
- PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- Redis SET with NX and PX: https://redis.io/docs/latest/commands/set/
- Stripe, "Designing robust and predictable APIs with idempotency": https://stripe.com/blog/idempotency
