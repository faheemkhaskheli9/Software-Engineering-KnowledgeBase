---
title: Backup and disaster recovery
category: reliability
tags: [backup, disaster-recovery, dr, rpo, rto, pitr, wal-archiving, snapshots, ransomware, 3-2-1, failover]
use_cases:
  - "set backup frequency and retention so we can lose at most 15 minutes of orders"
  - "restore a Postgres database to the minute before someone ran a bad DELETE"
  - "protect backups from ransomware that has admin access to production"
  - "choose between backup-restore, pilot light, warm standby and active/active for a regional outage"
  - "prove our backups actually restore with a scheduled restore drill"
status: draft
last_verified: 2026-10-11
sources:
  - https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html
  - https://www.cisa.gov/sites/default/files/publications/data_backup_options.pdf
  - https://www.cisa.gov/stopransomware/ransomware-guide
  - https://www.postgresql.org/docs/current/continuous-archiving.html
  - https://csrc.nist.gov/pubs/sp/800/34/r1/upd1/final
  - https://sre.google/sre-book/data-integrity/
---

# Backup and disaster recovery

## Summary
Backups protect against losing data (deletion, corruption, ransomware, a bad
migration); disaster recovery (DR) is the plan and standby infrastructure that
brings the whole service back after losing a site or region. Two business
targets drive every choice: how much data you may lose (RPO) and how long you
may be down (RTO). A backup that has never been restored is a hope, not a
backup, so restore drills are part of the design, not an afterthought.

## Key concepts
- **RPO (recovery point objective)**: maximum acceptable data loss, measured
  as time before the incident. Backup or replication frequency sets the
  achievable RPO.
- **RTO (recovery time objective)**: maximum acceptable time from disruption
  to restored service. Restore speed, automation and standby capacity set it.
- **Full / incremental / differential**: full copies everything; incremental
  copies changes since the last backup of any kind (small, but restore needs
  the whole chain); differential copies changes since the last full (grows
  over time, restore needs full + latest differential).
- **Snapshots**: storage-level point-in-time copies (EBS, LVM, ZFS, managed DB
  snapshots). Fast, but often in the same account and region as the source;
  copy them elsewhere to count as a backup.
- **PITR (point-in-time recovery)**: a base backup plus a continuous archive of
  the write-ahead log (WAL); replay the log up to just before the bad event.
- **Replication is not backup**: replicas copy deletes and corruption within
  seconds. The AWS DR whitepaper notes continuous replication "may not protect
  against disaster events such as data corruption or malicious attack" as well
  as point-in-time backups.
- **3-2-1 rule** (CISA / US-CERT "Data Backup Options"): keep 3 copies (1
  primary, 2 backups), on 2 different media types, with 1 copy offsite.
- **Immutable / offline copies**: write-once storage (object lock, WORM) or
  copies in a separate account that production credentials cannot delete.
  CISA's ransomware guide: "Maintain offline, encrypted backups of critical
  data", because ransomware looks for reachable backups to delete or encrypt.
- **DR strategies** (AWS "Disaster Recovery of Workloads on AWS"), in order of
  cost and complexity: backup and restore; pilot light (data replicated, core
  infrastructure provisioned, app servers switched off); warm standby (scaled
  down but fully functional copy that can take traffic immediately);
  multi-site active/active (all regions serve traffic).

## When to use / scenarios
- Every system with state needs backups; the questions are only frequency,
  retention, isolation and how fast you can restore.
- Lose at most minutes of data: PITR (WAL archiving or a managed database's
  PITR feature) instead of nightly dumps.
- Single-region outage must not take you down for hours: pilot light or warm
  standby, chosen by RTO; the AWS paper's distinction is that pilot light
  cannot serve requests without first switching on servers, while warm standby
  only needs to scale up.
- Near-zero RTO and you can afford two full stacks and a multi-writer data
  design: multi-site active/active. You still need point-in-time backups,
  because corruption replicates to every region.
- Not the right tool: high availability within one site (redundant instances,
  multi-AZ) is handled by [[replication]] and [[resilience-patterns]]; DR is for
  when that whole failure domain is gone.

## How it works / example

```
            RPO (data lost)          RTO (downtime)
  last good backup ---- incident ------------------- service restored
       |<------------------>|<----------------------------->|
```

PostgreSQL PITR in outline (PostgreSQL docs, "Continuous Archiving and
Point-in-Time Recovery"):

```ini
# postgresql.conf on the primary
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /mnt/archive/%f && cp %p /mnt/archive/%f'
# take base backups with pg_basebackup on a schedule

# on the restore host, after unpacking a base backup
restore_command = 'cp /mnt/archive/%f %p'
recovery_target_time = '2026-10-11 09:41:00+00'   # just before the bad DELETE
# then: touch $PGDATA/recovery.signal and start the server
```

A restore drill should check the two things a backup job's "success" exit code
does not: that the newest restorable point meets the RPO, and that the
restored bytes match what was backed up.

```python
import hashlib
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def achieved_rpo(backup_times: list[datetime], incident: datetime) -> timedelta:
    """Data lost if the incident happened now: time since the newest usable backup."""
    usable = [t for t in backup_times if t <= incident]
    if not usable:
        raise RuntimeError("no backup before the incident: RPO is unbounded")
    return incident - max(usable)

def restore_drill(backup: Path, manifest_sha: str, restore_dir: Path) -> Path:
    restored = restore_dir / backup.name
    shutil.copyfile(backup, restored)          # stand-in for the real restore tool
    if sha256(restored) != manifest_sha:
        raise RuntimeError(f"checksum mismatch on {restored}")
    return restored

now = datetime(2026, 10, 11, 9, 41, tzinfo=timezone.utc)
backups = [now - timedelta(minutes=m) for m in (130, 70, 12)]
target = timedelta(minutes=15)
assert achieved_rpo(backups, now) == timedelta(minutes=12) <= target
assert achieved_rpo(backups[:2], now) > target            # last job missed: alert

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    src = tmp / "orders.dump"
    src.write_bytes(b"order-1,42.00\norder-2,13.50\n")
    manifest = sha256(src)                                  # recorded at backup time
    (tmp / "restore").mkdir()
    assert restore_drill(src, manifest, tmp / "restore").read_bytes() == src.read_bytes()
    src.write_bytes(b"corrupted")                           # simulate a bad backup
    try:
        restore_drill(src, manifest, tmp / "restore")
        raise AssertionError("corrupt backup was accepted")
    except RuntimeError:
        pass
print("restore drill checks passed")
```

A real drill restores into an isolated environment, runs application-level
checks (row counts, latest order id, the app boots against it), records how
long it took (the measured RTO), and alerts when any step fails.

## Trade-offs
- **Frequency vs cost**: shorter RPO needs more frequent backups or continuous
  log shipping, which costs storage and I/O.
- **Incremental vs full**: incrementals are cheap to take and slow and fragile
  to restore (one broken link breaks the chain); schedule periodic fulls.
- **DR tier vs spend**: each step from backup-restore to active/active cuts
  RTO and raises standing cost and operational complexity. Match the tier to
  each workload's RTO, not one tier for everything.
- **Automatic vs manual failover**: the AWS paper cautions that automatic
  failover on health checks risks failing over on a false alarm, and that
  manual initiation is common, with the steps themselves automated.
- **Immutability vs flexibility**: locked retention defeats ransomware and also
  stops you deleting data early (for example for an erasure request); see
  [[privacy-and-pii-handling]] on crypto-shredding.
- **Retention length**: longer retention catches slow-burn corruption found
  weeks later, and keeps personal data longer than you may be allowed to.

## Gotchas
- Backups in the same account, with credentials production can use, are
  deleted together with production by an attacker or a bad script.
- Snapshots of a running database without a consistent backup mode can be
  unrestorable; use the database's own backup tooling or crash-consistent
  snapshots it supports.
- WAL archiving that fails silently: the PostgreSQL docs require
  `archive_command` to return zero only on success, and a full `pg_wal/`
  eventually stops the server. Monitor archive lag.
- PITR only reaches points after a base backup finished, and PostgreSQL PITR
  restores a whole cluster, not one table.
- Backing up data but not configuration, secrets, IaC, DNS and images: the
  restored database has nothing to run against (see [[infrastructure-as-code]]).
- Backup encryption keys stored only inside the environment you are recovering
  from.
- Untested runbooks: the first real restore reveals missing permissions,
  quotas in the DR region and undocumented steps. Drill on a schedule.
- Restoring old data re-introduces records deleted since for privacy reasons;
  keep a deletion log to re-apply after a restore.

## Related
- [[incident-response-and-postmortems]] - a DR invocation is a major incident; the runbook lives there.
- [[slis-slos-error-budgets]] - RPO and RTO are commitments in the same spirit as SLOs.
- [[replication]] - replicas give availability, not protection from bad writes.
- [[infrastructure-as-code]] - rebuilding a region quickly needs infrastructure defined as code.
- [[blob-object-storage]] - versioning and object lock for backup targets.
- [[schema-migrations]] - take and verify a backup before risky migrations.
- [[privacy-and-pii-handling]] - retention limits and erasure inside backups.
- [[software-supply-chain-security]] - golden images and artifacts you restore from must be trustworthy.

## References
- AWS, "Disaster Recovery of Workloads on AWS: Recovery in the Cloud", Disaster recovery options in the cloud: https://docs.aws.amazon.com/whitepapers/latest/disaster-recovery-workloads-on-aws/disaster-recovery-options-in-the-cloud.html
- Ruggiero and Heckathorn, "Data Backup Options", US-CERT/CISA (3-2-1 rule): https://www.cisa.gov/sites/default/files/publications/data_backup_options.pdf
- CISA, #StopRansomware Guide (offline, encrypted backups; restore testing): https://www.cisa.gov/stopransomware/ransomware-guide
- PostgreSQL documentation, Continuous Archiving and Point-in-Time Recovery: https://www.postgresql.org/docs/current/continuous-archiving.html
- NIST SP 800-34 Rev. 1, Contingency Planning Guide for Federal Information Systems: https://csrc.nist.gov/pubs/sp/800/34/r1/upd1/final
- Google SRE book, chapter 26 "Data Integrity: What You Read Is What You Wrote": https://sre.google/sre-book/data-integrity/
