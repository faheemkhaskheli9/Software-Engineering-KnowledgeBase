---
title: Geospatial indexing (geohash, quadtree, S2, H3, R-tree)
category: system-design
tags: [geospatial, geohash, quadtree, s2, h3, r-tree, postgis, redis-geo, proximity-search, location, haversine]
use_cases:
  - "find the nearest drivers, stores or restaurants within a radius of the user"
  - "store millions of moving locations and query them by area quickly"
  - "choose between geohash, quadtree, S2, H3 and PostGIS for a location feature"
  - "shard location data by region without hot spots in dense cities"
  - "aggregate events into map cells for heatmaps or surge pricing"
status: draft
last_verified: 2026-10-24
sources:
  - https://en.wikipedia.org/wiki/Geohash
  - https://h3geo.org/docs/
  - https://s2geometry.io/devguide/s2cell_hierarchy
  - https://postgis.net/docs/using_postgis_query.html
  - https://redis.io/docs/latest/develop/data-types/geospatial/
  - https://dl.acm.org/doi/10.1145/602259.602266
---

# Geospatial indexing (geohash, quadtree, S2, H3, R-tree)

## Summary
A B-tree on latitude and a B-tree on longitude cannot answer "what is within
2 km of me" efficiently: each index alone returns a whole stripe of the
planet. Geospatial indexes map two-dimensional positions onto structures
that keep nearby points together: space-filling-curve cell ids (geohash, S2)
that fit in ordinary sorted indexes and key-value stores, hierarchical
hexagon cells (H3), adaptive trees (quadtree), or bounding-box trees (R-tree,
used by PostGIS through GiST). A query becomes "fetch the few cells covering
the search area, then filter candidates by exact distance".

## Key concepts
- **Two-phase query**: a cheap index lookup returns *candidates* from cells
  that cover the search circle or polygon; an exact distance test (haversine
  for points on a sphere, or the database's geodesic function) removes false
  positives. Cell lookups never answer the question alone.
- **Geohash**: interleave longitude and latitude bits and write them in
  base32. Each extra character subdivides the cell 32 ways; a shared prefix
  means the same containing cell. Roughly: 5 characters about 4.9 km x 4.9
  km, 6 about 1.2 km x 0.6 km, 7 about 153 m x 153 m (cells narrow in
  longitude away from the equator).
- **Boundary problem**: two points a metre apart can sit in cells with no
  common prefix (across a cell edge, the equator or the antimeridian), so a
  radius query must check the cell *and its 8 neighbours*, sized so the
  radius fits inside one cell.
- **Quadtree**: recursively split a square into four until each leaf holds
  at most N points. Adapts to density (deep in Manhattan, shallow in the
  desert); usually an in-memory structure rebuilt or updated as points move.
- **S2** (Google): projects the sphere onto a cube and orders cells along a
  Hilbert curve, giving 64-bit cell ids at 31 levels (0-30) with good
  locality; a region is covered by a small set of id ranges.
- **H3** (Uber): hierarchical hexagonal grid with 16 resolutions (0-15) and
  12 pentagons at every resolution. Every neighbour of a hexagon is the same
  distance away, which suits aggregation, smoothing and movement analysis.
- **R-tree**: a balanced tree of nested bounding rectangles (Guttman, 1984);
  handles shapes (polygons, lines), not just points. PostGIS builds it as a
  GiST index; `ST_DWithin` uses the index, a bare `ST_Distance(...) < r` in a
  WHERE clause does not.
- **Redis geo**: `GEOADD` / `GEOSEARCH` store points in a sorted set whose
  score is a 52-bit geohash, so radius and box queries are range scans plus
  distance filtering.

## When to use / scenarios
- Nearby search on points (drivers, stores, friends) with frequent updates:
  geohash or S2 cell ids in Redis or a key-value store, or an in-memory
  quadtree per region ([[design-ride-sharing]]).
- Rich spatial queries (polygons, intersections, routes, "which delivery zone
  contains this address"): PostGIS or another database with R-tree/GiST
  indexes ([[database-indexing]]).
- Heatmaps, surge pricing, demand forecasting, privacy-preserving location
  bucketing: H3 cells as group-by keys ([[batch-and-stream-processing]]).
- Combined text and location search ("pizza near me"): a search engine's
  geo-point fields and distance sort ([[search-systems]]).
- Sharding location data: partition by a coarse cell id, but split dense
  cells further or hash within them to avoid hot shards
  ([[partitioning-and-sharding]]).
- When NOT to build one: a few thousand points fit in memory and a linear
  scan with haversine takes well under a millisecond; a city- or
  country-level lookup is a plain column.

## How it works / example
Geohash encoding and a radius search that checks the cell plus its eight
neighbours, then filters by haversine distance. The result is compared with
a brute-force scan.

```python
import math
import random

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"     # no a, i, l, o
EARTH_RADIUS_M = 6_371_000
M_PER_DEG = math.pi * EARTH_RADIUS_M / 180   # about 111 km

def encode(lat, lon, precision):
    lat_rng, lon_rng = [-90.0, 90.0], [-180.0, 180.0]
    bits, even, out, ch = 0, True, [], 0
    while len(out) < precision:
        rng, val = (lon_rng, lon) if even else (lat_rng, lat)   # lon bit first
        mid = (rng[0] + rng[1]) / 2
        ch <<= 1
        if val >= mid:
            ch |= 1
            rng[0] = mid
        else:
            rng[1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(BASE32[ch])
            bits, ch = 0, 0
    return "".join(out)

def cell_size_deg(precision):
    total = 5 * precision
    lon_bits, lat_bits = (total + 1) // 2, total // 2
    return 180 / 2 ** lat_bits, 360 / 2 ** lon_bits

def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

def precision_for(radius_m, lat):
    """Finest precision whose cell is still at least `radius_m` in both directions."""
    for p in range(12, 0, -1):
        dlat, dlon = cell_size_deg(p)
        height = dlat * M_PER_DEG
        width = dlon * M_PER_DEG * math.cos(math.radians(lat))
        if height >= radius_m and width >= radius_m:
            return p
    return 1

def neighbours(lat, lon, precision):
    dlat, dlon = cell_size_deg(precision)
    return {encode(max(-90.0, min(90.0, lat + dy * dlat)),
                   (lon + dx * dlon + 180) % 360 - 180, precision)
            for dy in (-1, 0, 1) for dx in (-1, 0, 1)}

class GeoIndex:
    def __init__(self, precision):
        self.precision, self.cells = precision, {}

    def add(self, pid, lat, lon):
        self.cells.setdefault(encode(lat, lon, self.precision), []).append((pid, lat, lon))

    def within(self, lat, lon, radius_m):
        candidates = [p for cell in neighbours(lat, lon, self.precision)
                      for p in self.cells.get(cell, [])]
        hits = {pid for pid, plat, plon in candidates
                if haversine_m(lat, lon, plat, plon) <= radius_m}
        return hits, len(candidates)

assert encode(57.64911, 10.40744, 11) == "u4pruydqqvj"   # example from the Geohash article

rng = random.Random(42)
points = [(i, 40.7 + rng.uniform(-0.2, 0.2), -74.0 + rng.uniform(-0.2, 0.2))
          for i in range(20_000)]
radius = 1_000
idx = GeoIndex(precision_for(radius, 40.7))
for pid, lat, lon in points:
    idx.add(pid, lat, lon)

for _ in range(50):
    qlat, qlon = 40.7 + rng.uniform(-0.15, 0.15), -74.0 + rng.uniform(-0.15, 0.15)
    hits, scanned = idx.within(qlat, qlon, radius)
    brute = {pid for pid, lat, lon in points if haversine_m(qlat, qlon, lat, lon) <= radius}
    assert hits == brute, (qlat, qlon)
    assert scanned < len(points) / 5           # index touched a small fraction

print(f"precision {idx.precision}: last query {len(hits)} hits from {scanned} candidates "
      f"out of {len(points)} points")
```

The same query in PostGIS (index on a `geography` column):

```sql
CREATE INDEX drivers_loc_gix ON drivers USING GIST (loc);
SELECT id FROM drivers
WHERE ST_DWithin(loc, ST_MakePoint(-73.99, 40.73)::geography, 1000)   -- metres, uses the index
ORDER BY loc <-> ST_MakePoint(-73.99, 40.73)::geography                -- index-assisted nearest first
LIMIT 20;
```

## Trade-offs
- **Cell ids vs trees**: geohash and S2 ids are plain keys, so any sorted
  store, cache or shard map can hold them and updates are cheap; trees
  (quadtree, R-tree) adapt to density and handle shapes but live inside one
  process or one database.
- **Geohash vs S2 vs H3**: geohash is trivial to implement and read but its
  cells are rectangles that distort with latitude and its curve has bad jumps;
  S2 has better locality and coverings at the cost of a library; H3 gives
  uniform neighbours for analytics, but hexagons do not nest exactly, so
  parent and child cells only approximately contain each other.
- **Cell size**: small cells mean fewer false candidates but more cells to
  fetch per query and more cell changes as points move; large cells mean the
  opposite. Pick by query radius, and use several levels if radii vary.
- **Dedicated geo store vs your database**: PostGIS keeps location next to
  transactional data and supports complex queries; Redis or an in-memory
  index handles very high update rates (moving vehicles) with fewer query
  types and weaker durability.

## Gotchas
- Treating degrees as distances: one degree of longitude is about 111 km at
  the equator and shrinks with `cos(latitude)` to zero at the poles; a
  "radius" in degrees is an ellipse.
- Checking only the query point's own cell: misses everything just across
  the edge. Always include neighbours, or use a proper covering.
- Argument order: GeoJSON, PostGIS `ST_MakePoint` and Redis take longitude
  first; most UIs and many APIs say "lat, lng". Swapped coordinates put
  points in the wrong hemisphere without any error.
- The antimeridian (180 deg) and the poles break naive bounding boxes; wrap
  longitudes and test those cases if your users can be there.
- Dense cells become hot keys or hot shards (an airport, a stadium);
  subdivide adaptively or add a hash suffix ([[partitioning-and-sharding]]).
- Moving objects: re-indexing on every GPS ping at high rates overloads a
  database; batch updates, update only on cell change, or keep the live index
  in memory and persist trips separately ([[design-ride-sharing]]).
- `ST_Distance` on `geometry` in SRID 4326 returns degrees, not metres; use
  `geography` or a projected coordinate system.
- Location is personal data: store the precision you need, coarsen for
  analytics, and set retention ([[privacy-and-pii-handling]]).

## Related
- [[design-ride-sharing]] - case study: nearby-driver matching on a live geospatial index.
- [[database-indexing]] - B-tree, GiST and inverted indexes; why two B-trees do not make a 2D index.
- [[partitioning-and-sharding]] - sharding by region and handling hot cells.
- [[search-systems]] - geo filters and distance sort combined with text relevance.
- [[core-data-structures]] - trees and hash maps underneath quadtrees and cell indexes.
- [[caching-strategies]] - Redis geo sets as a fast, in-memory location index.
- [[privacy-and-pii-handling]] - location precision, retention and anonymisation.

## References
- Wikipedia, "Geohash" (algorithm, base32 alphabet, cell dimensions per length, worked example): https://en.wikipedia.org/wiki/Geohash
- H3 documentation (resolutions, hexagon grid, pentagons): https://h3geo.org/docs/
- S2 Geometry, "S2 Cell Hierarchy": https://s2geometry.io/devguide/s2cell_hierarchy
- PostGIS manual, "Spatial Queries" (index use, `ST_DWithin`, KNN `<->`): https://postgis.net/docs/using_postgis_query.html
- Redis documentation, "Redis geospatial": https://redis.io/docs/latest/develop/data-types/geospatial/
- Antonin Guttman, "R-trees: A Dynamic Index Structure for Spatial Searching", SIGMOD 1984: https://dl.acm.org/doi/10.1145/602259.602266
