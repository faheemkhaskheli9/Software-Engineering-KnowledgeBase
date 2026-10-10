---
title: Design a ride-sharing service
category: case-studies
tags: [ride-sharing, uber, lyft, geospatial, geohash, quadtree, matching, location-tracking, case-study]
use_cases:
  - "design an Uber or Lyft style service that matches riders with nearby drivers"
  - "track millions of moving drivers and query who is within 2 km of a point"
  - "build dispatch and matching with timeouts when drivers decline"
  - "add real-time location tracking and ETA to a delivery or logistics product"
  - "store and index geospatial data for proximity search at high write rates"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 2 (Alex Xu and Sahn Lam), 'Proximity Service' and 'Nearby Friends' chapters"
  - https://www.uber.com/blog/h3/
  - https://h3geo.org/
  - https://en.wikipedia.org/wiki/Geohash
  - https://redis.io/docs/latest/commands/geosearch/
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
---

# Design a ride-sharing service

## Summary
A ride-sharing platform connects riders to nearby available drivers in real
time. Core challenges are ingesting a continuous stream of driver locations,
answering "which drivers are near this point" in milliseconds, matching and
dispatching with fair handling of timeouts and declines, and keeping trip state
correct across flaky mobile networks.

## Key concepts
- **Geospatial indexing:** convert 2D location into something indexable: geohash (string prefix = containing cell), quadtree (adaptive subdivision), S2 or H3 (hierarchical cell systems; H3 uses hexagons, published by Uber).
- **Location updates are high-volume, ephemeral writes:** latest position matters; history is for analytics.
- **Supply/demand matching:** nearest driver, or an optimisation across many riders and drivers (batch matching) to reduce total wait time.
- **Trip state machine:** requested -> matching -> driver_assigned -> en_route -> arrived -> in_progress -> completed | cancelled.
- **ETA and routing:** map data, road graph, traffic; a separate maps service.
- **Dynamic (surge) pricing** based on local supply/demand imbalance.
- **Soft real-time:** a few seconds of staleness in position is acceptable.

## When to use / scenarios
Design applies to taxi/ride apps, food and package delivery, field service
dispatch, scooter fleets, and "nearby" features in social apps (see proximity search).
For a few hundred vehicles a single database with a spatial index (PostGIS) suffices;
the in-memory sharded design below is for heavy write rates and tight latency.

## How it works / example

### 1. Requirements
Functional: rider requests trip with pickup/destination; see nearby drivers and fare/ETA estimate; the system matches
and notifies a driver who accepts or declines; live tracking for rider; trip lifecycle and payment (see
[[design-payment-system]]); ratings; driver availability toggle.

Non-functional: low latency for nearby queries and dispatch (sub-second query, seconds to match); high availability
(an outage strands users); location data freshness of a few seconds; correctness: one driver never assigned two
trips, one trip not double-charged; scale to millions of drivers; regional isolation (cities are largely independent).

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 5 M active drivers at peak, each sending location every 4 s: 1.25 M updates/s globally at peak. Per city it is far lower, which is why the system shards by region.
- Update payload about 100 bytes -> 125 MB/s ingress globally.
- Latest-position state: 5 M x 100 B = 0.5 GB, trivially fits in memory; the hard part is write throughput, not size.
- Trips: assume 20 M/day -> about 230/s average, peaks several times that. Trip records are small and relational.
- History: 1.25 M updates/s x 100 B = 10 TB/day if all kept; sample or aggregate for analytics and retain briefly.

### 3. API
```
WS/UDP-ish  driver -> POST /v1/drivers/{id}/location { lat, lng, heading, speed, ts }   (high frequency)
PUT         /v1/drivers/{id}/status { available | offline }
GET         /v1/rides/estimate?pickup=..&dest=..         -> fare range, ETA, nearby drivers
POST        /v1/rides { pickup, dest, product }  (Idempotency-Key)  -> { ride_id, state }
GET/WS      /v1/rides/{id}                        -> state stream, driver location
POST        /v1/rides/{id}/cancel
Driver app: offers via push/WebSocket; POST /v1/offers/{id}/accept|decline
```
Use persistent connections for tracking ([[realtime-websockets-sse]]) and idempotency keys for ride creation
([[idempotency-and-exactly-once]]).

### 4. Data model
```
driver(id, vehicle, rating, status)                     -- relational
trip(id, rider_id, driver_id, pickup, dest, state, fare, created_at, version)  -- relational, strongly consistent
driver_location(driver_id) -> (cell_id, lat, lng, ts)   -- in-memory geo store (Redis GEO / custom), TTL
cell_index(cell_id) -> set(driver_id)                   -- derived: drivers per geo cell
location_history(driver_id, ts, lat, lng)               -- append-only stream/lake for analytics
```
Trips need transactions and exactly-one-driver invariants, so a relational store with row versioning is a good fit
([[transactions-and-isolation-levels]], [[sql-vs-nosql]]). Locations are ephemeral, overwritten state in memory.

### 5. High-level architecture
```
 driver apps --location--> Location gateway (WS) --> Kafka "locations" --> Location service
                                                                    |  update cell index in memory (sharded by city/cell)
                                                                    '-> history sink (data lake)
 rider app --> API gateway --> Trip service --> Matching/Dispatch service
                                    |                |-- query Location service: drivers near pickup
                                    |                |-- ETA service (maps/routing) to rank candidates
                                    |                '-- offer to driver (push/WS), wait with timeout
                                    v
                               Trip DB (relational, sharded by city/region)
 Pricing service (surge by cell supply/demand)   Payment service   Notification service
```
See [[message-queues-and-streams]], [[api-gateway-and-service-mesh]], [[partitioning-and-sharding]].

### 6. Deep dive A: geospatial index and nearby search
Options:
- **Geohash:** encode lat/lng to a base32 string; shared prefix means nearby (with edge cases at cell borders, so
  query the 8 neighbouring cells too). Simple, works with any KV store or Redis (`GEOSEARCH` uses a geohash-based sorted set internally).
- **Quadtree:** recursively split dense regions into four; adaptive to uneven density (Manhattan vs countryside). Typically in-memory, rebuilt/updated as drivers move.
- **S2 / H3:** hierarchical cell IDs; H3 hexagons give uniform neighbour distances, handy for surge pricing and smoothing.

Practical design: choose a cell resolution where a cell is around the search radius (about 1-2 km). Keep
`cell_id -> {driver_id}` in memory sharded by cell prefix (so a query touches one shard plus neighbours).
On location update: compute new cell; if changed, remove from old cell set and add to new one. Search = union of
the cell and its neighbours, filter by exact distance (haversine), take the top K, then rank by ETA.

```python
import math
def haversine_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2 * R * math.asin(math.sqrt(d))

def nearby(point, radius_km, grid, k=10):
    cands = [d for cell in grid.cell_and_neighbors(point) for d in grid.drivers(cell)
             if d.available and haversine_km(point, d.pos) <= radius_km]
    return sorted(cands, key=lambda d: haversine_km(point, d.pos))[:k]
```
Reduce write load: drivers send updates only when moved meaningfully or at adaptive rates (slower when idle);
batch updates; accept that the index lags by a couple of seconds. Expire entries by TTL when updates stop
(app killed) so ghost drivers vanish.

### 7. Deep dive B: matching, dispatch and the one-driver-one-trip invariant
1. Trip service creates trip `requested` (idempotent on request key).
2. Dispatch fetches K candidate drivers near pickup, ranks by ETA (and rating/acceptance rate), and offers to the best one.
3. Offer has a short TTL (e.g. 10-15 s, tunable). Accept: atomically transition the driver `available -> reserved` and
   the trip `matching -> driver_assigned` (compare-and-set / conditional update on version, or a per-driver lock/lease).
   If another trip already reserved this driver, the CAS fails and dispatch moves on.
4. Decline or timeout: offer to the next candidate; widen the radius gradually; after N attempts report no drivers.
5. Alternatives: batch matching every couple of seconds over all pending riders and nearby drivers (a bipartite
   assignment minimising total ETA) beats greedy nearest-first at high demand.

```python
def accept_offer(db, driver_id, trip_id):
    with db.tx():
        ok = db.execute("UPDATE driver SET status='reserved' WHERE id=%s AND status='available'", driver_id)
        if not ok: return False
        ok = db.execute("UPDATE trip SET state='driver_assigned', driver_id=%s "
                        "WHERE id=%s AND state='matching'", driver_id, trip_id)
        if not ok: db.rollback(); return False
    return True
```
Trip lifecycle changes are events; a saga coordinates side effects like payment pre-authorisation and
notifications ([[distributed-transactions-and-sagas]]).

### 8. Deep dive C: live tracking, ETA and pricing
- Tracking: after assignment, route the driver's location stream to that rider's connection through pub/sub keyed by trip ID;
  do not fan out through the DB. Smooth and interpolate on the client for a fluid map.
- ETA: routing engine on a road graph with live traffic; precompute heavily used tiles, cache results by
  (origin cell, destination cell, time bucket) ([[caching-strategies]]).
- Surge: compute supply/demand ratio per cell every few seconds (streaming aggregation, see
  [[batch-and-stream-processing]]) and smooth over neighbours and time to avoid flicker; show price before confirmation.

### 9. Scaling and failure handling
- Shard everything by geography (city/region): trips, driver indexes and dispatch are naturally local, which contains blast radius.
- Location service nodes are replaceable: state rebuilds from the next few seconds of updates, so no need for strong durability of the live index ([[replication]] optional).
- Dispatch service stateless; offers state in Redis/DB with TTL so a crash resumes or expires cleanly.
- Mobile network drops: the client retries with the same idempotency key; server treats trip transitions as idempotent state machine moves.
- Degradation: if ETA service is slow, fall back to straight-line distance ranking ([[resilience-patterns]]).
- Hot cells (stadium after an event): split the cell dynamically (finer resolution), queue riders fairly, scale dispatch workers for that region.
- Observability: match time, offer accept rate, location staleness, dispatch failures by city ([[observability-logs-metrics-traces]]).

## Trade-offs
- Geohash is simple but has boundary and aspect-ratio quirks; H3/S2 give cleaner neighbourhoods at the cost of a library dependency; quadtrees adapt to density but need maintenance.
- Greedy nearest-driver matching is simple and fast; batched global matching improves overall wait and utilisation but adds a few seconds of latency and complexity.
- Frequent location updates improve accuracy and cost battery, data, and server load; adaptive rates help.
- Strong consistency on assignment (CAS) costs some latency but prevents double-booking; location data can be eventually consistent.
- In-memory index is fast but needs rebuild logic; a database with spatial index is simpler at smaller scale.

## Gotchas
- Ignoring the antimeridian and poles, or measuring "distance" with straight-line lat/lng deltas.
- Querying only the driver's own cell and missing drivers just across the border.
- Ghost drivers: no TTL on location entries leads to offering rides to offline drivers.
- Double assignment from check-then-act races; use conditional updates or leases.
- Straight-line distance vs road ETA: a driver across a river is "near" but 30 minutes away.
- Retry storms after a regional network blip; use jittered backoff on clients.
- Storing every GPS point in the transactional DB; send to a stream/lake instead.
- GPS noise and spoofing; apply smoothing and sanity checks (speed limits, teleport detection).

## Related
- [[partitioning-and-sharding]] - geographic sharding of the index and trips
- [[realtime-websockets-sse]] - live location and offer delivery
- [[message-queues-and-streams]] - high-volume location ingestion
- [[distributed-transactions-and-sagas]] - trip lifecycle side effects
- [[design-payment-system]] - fare charging after the trip
- [[transactions-and-isolation-levels]] - correctness of driver reservation
- [[unique-id-generation]] - trip and offer IDs

## References
- Alex Xu and Sahn Lam, *System Design Interview Vol. 2* (proximity service, nearby friends)
- Uber Engineering, "H3: Uber's Hexagonal Hierarchical Spatial Index": https://www.uber.com/blog/h3/
- H3 documentation: https://h3geo.org/
- Geohash: https://en.wikipedia.org/wiki/Geohash
- Redis GEOSEARCH: https://redis.io/docs/latest/commands/geosearch/
