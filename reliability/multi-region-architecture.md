---
title: Multi-region architecture (active-passive, active-active, cells)
category: reliability
tags: [multi-region, active-active, active-passive, failover, cell-based-architecture, static-stability, home-region, data-residency, geo-routing, disaster-recovery]
use_cases:
  - "keep the service up when a whole cloud region goes down"
  - "serve users on several continents with low latency without breaking consistency"
  - "decide between active-passive failover and active-active across two regions"
  - "split the system into cells so one bad deploy or poison request cannot take down every customer"
  - "keep EU customer data in the EU while running one global product"
status: draft
last_verified: 2026-10-24
sources:
  - https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html
  - https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.html
  - https://aws.amazon.com/builders-library/static-stability-using-availability-zones/
  - https://research.google/pubs/spanner-googles-globally-distributed-database-2/
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://sre.google/sre-book/managing-critical-state/
---

# Multi-region architecture (active-passive, active-active, cells)

## Summary
Multi-region architecture runs a service in two or more geographically separate
cloud regions so it survives the loss of a region and serves distant users with
lower latency. The hard part is not the stateless tier but the data: where each
write is accepted, how it replicates, and what happens to in-flight writes when
a region fails. The main patterns are active-passive (one region serves, others
stand by), active-active (all regions serve, with data partitioned by home
region or replicated with conflict handling) and cell-based architecture (many
independent copies of the stack, each serving a slice of customers).

## Key concepts
- **Failure domains**: host < availability zone (AZ) < region. Multi-AZ inside
  one region covers most hardware and data-centre failures with synchronous
  replication at low latency; multi-region covers regional outages, regional
  control-plane failures and geographic latency, at the cost of slow,
  usually asynchronous, cross-region replication.
- **RPO and RTO**: data you may lose and time you may be down
  ([[backup-and-disaster-recovery]]). With asynchronous replication the RPO of a
  regional failover is at least the replication lag at the moment of failure.
- **Active-passive**: writes go to a primary region; standbys receive
  replicated data. DR tiers in the AWS whitepaper, from cheapest to fastest:
  backup and restore, pilot light, warm standby, multi-site active/active.
- **Active-active**: every region serves reads and writes. Two ways to keep
  data correct:
  - **Partition by home region**: each user, tenant or entity has one home
    region that owns its writes; other regions forward or read replicas. No
    write conflicts, failover moves ownership.
  - **Multi-leader or globally consistent store**: writes anywhere; conflicts
    resolved by last-writer-wins, CRDTs or application merge
    ([[replication]]), or avoided by a consensus-based database (Spanner-style)
    that pays cross-region round trips on each write ([[consensus-raft-paxos]]).
- **Global traffic routing**: latency- or geo-based DNS, anycast IPs or a
  global load balancer send users to a healthy nearby region; health checks
  remove a failed region ([[load-balancing]], [[cdn-and-edge]]).
- **Static stability** (Amazon Builders' Library): the system keeps working
  during a failure without needing to make changes, for example by already
  running enough capacity in the surviving locations instead of relying on
  scaling up or on a control plane that may be impaired.
- **Cell-based architecture**: the stack is replicated into many isolated cells
  (each with its own data), a thin routing layer maps each customer to a cell,
  and deployments go cell by cell. A failure or bad deploy affects one cell's
  customers, not all of them.
- **Data residency**: legal rules that keep some personal data inside a
  jurisdiction; a home-region model makes this enforceable
  ([[privacy-and-pii-handling]]).

## When to use / scenarios
- An SLO or contract that a single region cannot meet, or a business that
  cannot tolerate a regional outage of hours ([[slis-slos-error-budgets]]).
- Users far from the only region and latency that caching and a CDN do not
  fix (writes and personalised reads).
- Regulation requiring in-country data, or customers who demand it.
- Large blast radius: one deploy or one tenant's traffic can take everything
  down; cells reduce that even within one region.
- When NOT to: before multi-AZ, tested backups and good deployment safety are
  in place. Most outages are self-inflicted (bad deploys, config, expired
  certificates), and a second region with the same bad config fails the same
  way. If an RTO of hours is acceptable, backup-and-restore or pilot light to
  another region is far cheaper than active-active. Read
  [[scaling-from-zero-to-millions]] first: multi-region is a late step.

## How it works / example
Home-region active-active with failover:

```
           global DNS / anycast LB (health-checked)
              /                         \
     region EU (home of EU users)   region US (home of US users)
     app tier  -> EU primary DB      app tier  -> US primary DB
                  \  async replica  <-> async replica  /
 request for a US user arriving in EU: forward to US (or read EU replica if stale reads are allowed)
 US region fails: promote the US replica held in EU, repoint US users' home to EU
```

A simulation of that model: each user's writes go to the home region, which
replicates asynchronously with some lag. When the home region fails, the
router promotes the other region. Writes that were acknowledged but not yet
replicated are lost, so the achieved RPO equals the replication lag at the
time of the failure. The second part shows that serving a stale replica during
failover is a choice: availability now, missing recent writes.

```python
from dataclasses import dataclass, field

@dataclass
class Region:
    name: str
    healthy: bool = True
    data: dict = field(default_factory=dict)          # user -> list of writes

class MultiRegion:
    def __init__(self, names, lag_s):
        self.regions = {n: Region(n) for n in names}
        self.lag_s = lag_s
        self.pending = []                              # (apply_at, src, user, value)
        self.home = {}

    def tick(self, now):
        """Apply replication for writes older than the lag."""
        keep = []
        for apply_at, src, user, value in self.pending:
            if apply_at <= now:
                for r in self.regions.values():
                    if r.name != src and r.healthy:
                        r.data.setdefault(user, []).append(value)
            else:
                keep.append((apply_at, src, user, value))
        self.pending = keep

    def write(self, now, user, value):
        region = self.regions[self.home[user]]
        if not region.healthy:
            raise RuntimeError("home region down: fail over first")
        region.data.setdefault(user, []).append(value)   # acknowledged here
        self.pending.append((now + self.lag_s, region.name, user, value))

    def fail_region(self, name):
        self.regions[name].healthy = False
        # unreplicated writes from that region are gone with it
        self.pending = [p for p in self.pending if p[1] != name]
        for user, home in self.home.items():
            if home == name:
                self.home[user] = next(r for r, reg in self.regions.items() if reg.healthy)

    def read(self, user):
        return self.regions[self.home[user]].data.get(user, [])

mr = MultiRegion(["us", "eu"], lag_s=2)
mr.home = {"alice": "us", "bruno": "eu"}

for t in range(10):                                     # one write per second each
    mr.tick(t)
    mr.write(t, "alice", f"a{t}")
    mr.write(t, "bruno", f"b{t}")
mr.tick(10)                                             # writes up to t=8 replicated

mr.fail_region("us")                                    # region outage at t=10
assert mr.home["alice"] == "eu"                         # failover moved her home
alice = mr.read("alice")
lost = [f"a{t}" for t in range(10) if f"a{t}" not in alice]
print("alice after failover:", alice[-3:], "lost:", lost)
assert lost == ["a9"]                                   # RPO ~ replication lag
assert mr.read("bruno")[-1] == "b9"                     # EU users unaffected
mr.write(11, "alice", "a11")                            # writes continue in EU
assert mr.read("alice")[-1] == "a11"
```

Practical checklist for a regional failover plan:
1. Decide per data set: home-region owned, globally replicated, or global
   consensus. Most data can be home-region owned.
2. Keep enough capacity running in surviving regions (static stability), or
   accept a longer RTO while they scale.
3. Make failover a single, rehearsed, automated action with a human decision
   to trigger it; avoid automatic flapping between regions.
4. Fence the old primary so it cannot accept writes after promotion
   ([[distributed-locks-and-leader-election]]).
5. Exercise it regularly with region-evacuation game days
   ([[chaos-engineering]]).

## Trade-offs
- **Active-passive vs active-active**: active-passive is simpler and avoids
  conflicts but wastes standby capacity and has a failover delay; active-active
  uses all capacity and lowers latency but needs a data ownership or conflict
  strategy for every write path.
- **Async vs sync cross-region replication**: async keeps write latency low and
  loses the lag window on failover; sync (or consensus) gives RPO near zero but
  adds a cross-region round trip to every write ([[cap-and-pacelc]]).
- **Home region vs write-anywhere**: home regions give single-writer
  simplicity and residency control but higher latency for travelling users and
  cross-home operations (a transfer between users in two regions); write
  anywhere suits mergeable data (counters, carts, presence) and hurts for
  invariants like balances or inventory.
- **Few large regions vs many cells**: cells shrink blast radius and make
  capacity units repeatable, but add a routing layer, cell migration tooling
  and cross-cell queries.
- **Automatic vs manual regional failover**: automatic is faster but risks
  failing over on a monitoring blip or into a region without capacity; many
  teams automate the steps and keep a human decision to start them.

## Gotchas
- Hidden single-region dependencies: the identity provider, DNS provider,
  secrets store, container registry, CI system or a global control plane lives
  in one region and fails with it.
- Failover never tested: replication is broken, capacity is missing or the
  runbook is wrong, and you find out during the outage.
- Split brain: both regions believe they are primary after a network
  partition and accept conflicting writes.
- Treating replicas as backups: corruption and accidental deletes replicate to
  every region within seconds; keep point-in-time backups.
- Cross-region chatter: a request that fans out to services in another region
  adds round trips and couples failures; keep a request's work inside one
  region.
- Cache and session state left behind: users failed over to another region
  lose sessions or see cold caches that overload the database.
- Failback is a second, riskier migration (data written in the standby must
  flow back); plan and rehearse it too.
- Cross-region data transfer is billed by most cloud providers; replication of
  chatty data can cost more than the extra compute.

## Related
- [[replication]] - leader, multi-leader and leaderless replication that carry data between regions.
- [[backup-and-disaster-recovery]] - RPO/RTO targets and the DR tiers from backup-restore to active/active.
- [[cap-and-pacelc]] - the latency vs consistency cost of cross-region writes.
- [[consistency-models]] - what users see when they read from a lagging region.
- [[load-balancing]] - global traffic steering and health checks between regions.
- [[partitioning-and-sharding]] - partitioning by home region or cell.
- [[chaos-engineering]] - region evacuation and AZ-loss experiments.
- [[choosing-a-multi-tenancy-model]] - tenant-to-cell placement and isolation.

## References
- AWS, *Disaster Recovery of Workloads on AWS*, "Disaster recovery options in the cloud": https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html
- AWS Well-Architected, *Reducing the Scope of Impact with Cell-Based Architecture*: https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.html
- Becky Weiss and Mike Furr, "Static stability using Availability Zones", Amazon Builders' Library: https://aws.amazon.com/builders-library/static-stability-using-availability-zones/
- James C. Corbett et al., "Spanner: Google's Globally-Distributed Database", OSDI 2012: https://research.google/pubs/spanner-googles-globally-distributed-database-2/
- Martin Kleppmann, *Designing Data-Intensive Applications*, ch. 5 "Replication" (multi-leader replication, multi-datacenter operation): https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
- Betsy Beyer et al., *Site Reliability Engineering*, ch. 23 "Managing Critical State: Distributed Consensus for Reliability": https://sre.google/sre-book/managing-critical-state/
