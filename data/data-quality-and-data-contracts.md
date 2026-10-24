---
title: Data quality and data contracts
category: data
tags: [data-quality, data-contracts, data-validation, data-observability, freshness, schema-checks, write-audit-publish, quarantine, dbt-tests, great-expectations]
use_cases:
  - "dashboards silently showed wrong numbers after an upstream team renamed a column"
  - "agree with a producing team on the schema, meaning and freshness of a table or event stream"
  - "add checks so a bad batch (nulls, duplicates, half a day missing) never reaches reports or ML training"
  - "decide what to do with bad rows: fail the pipeline, quarantine them or publish with a warning"
  - "detect a stale or shrunken table before users notice"
status: draft
last_verified: 2026-10-24
sources:
  - https://bitol-io.github.io/open-data-contract-standard/
  - https://docs.getdbt.com/docs/build/data-tests
  - https://docs.greatexpectations.io/docs/
  - "Sebastian Schelter et al., Automating Large-Scale Data Quality Verification, VLDB 2018"
  - "Eric Breck et al., Data Validation for Machine Learning, MLSys 2019"
  - "Barr Moses, Lior Gavish, Molly Vorwerck, Data Quality Fundamentals, O'Reilly, 2022"
  - "Andrew Jones, Driving Data Quality with Data Contracts, Packt, 2023"
---

# Data quality and data contracts

## Summary
Data pipelines fail quietly: a renamed column, a duplicated batch or a feed
that stopped yesterday still produces a table, and the error surfaces weeks
later as a wrong dashboard or a degraded model. Data quality engineering
turns expectations about data (schema, nulls, uniqueness, ranges, freshness,
volume) into automated checks that run where data enters and before it is
published. A data contract is the producer-owned, versioned agreement that
states those expectations for a dataset or event stream, so breaking it is
caught in the producer's CI rather than in a consumer's report.

## Key concepts
- **Quality dimensions** (DAMA UK's commonly cited set): completeness (no
  missing rows or values), uniqueness (no duplicates), validity (type,
  format, allowed values), accuracy (matches reality), consistency (agrees
  across systems), timeliness (fresh enough). Each check targets one.
- **Check kinds**:
  - *Schema*: columns exist with expected types; no unexpected columns.
  - *Row-level*: not null, regex or enum, range, cross-field rules
    (`shipped_at >= ordered_at`).
  - *Table-level*: primary key unique, row count within expected band,
    referential integrity to dimension tables, sums that reconcile to a
    source of truth (ledger totals).
  - *Freshness*: newest event time or load time within an SLA.
  - *Distribution / anomaly*: null rate, mean or category mix compared with
    recent history; catches problems no fixed rule names. Deequ and TFDV
    (Breck et al.) compute such statistics at scale.
- **Data contract**: a document kept in version control by the producer,
  naming owner, schema, semantics of each field, quality rules, freshness and
  support terms, and the versioning policy. The Open Data Contract Standard
  (ODCS, Bitol project under the Linux Foundation) is one YAML format for it;
  dbt model contracts enforce column names and types at build time.
- **Contract enforcement points**: producer CI (a schema change that breaks
  the contract fails the build), the write path or schema registry (rejects
  incompatible events, [[schema-evolution-and-serialization]]), and the
  pipeline (checks before publish).
- **Write-audit-publish (WAP)**: write a new batch to a staging location or
  branch, run the checks, and only then swap it into the published table.
  Consumers never see an unchecked batch.
- **Severity and action**: each check is *blocking* (stop publish, page the
  owner), *quarantine* (route bad rows to a side table, publish the rest) or
  *warn* (publish, open a ticket). Decide per check, not per pipeline.
- **Data observability**: monitoring freshness, volume, schema changes and
  distributions of every important table continuously, with lineage to see
  which consumers a broken table affects ([[observability-logs-metrics-traces]]).

## When to use / scenarios
- Any table that feeds money, compliance, executive dashboards or model
  training: blocking checks on keys, nulls, freshness and reconciled totals.
- Data crosses a team boundary (service database to warehouse, event stream
  to many consumers): a contract owned by the producer, checked in its CI
  ([[change-data-capture]], [[event-driven-architecture]]).
- Repeated incidents of the type "upstream changed something": add schema
  and distribution checks at ingestion, plus lineage.
- ML features and training sets: distribution checks and training/serving
  skew detection; a model happily learns from a broken column.
- When NOT to go heavy: exploratory or throwaway datasets, or a single team
  owning producer and consumer in one repository; a few tests next to the
  transformation are enough. Formal contracts for every table become
  paperwork nobody reads.

## How it works / example

```
 producer service --(contract v3: schema, rules, freshness 1h, owner)--> CI check
        |
        v  write
   staging table / branch --> checks --pass--> publish (swap) --> consumers
                                 |fail
                                 +--> blocking: stop + page owner
                                 +--> quarantine: bad rows to side table
                                 +--> warn: publish + ticket
```

A small contract with row, table, freshness and volume checks; bad rows are
quarantined and blocking failures stop the publish:

```python
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev

CONTRACT = {
    "dataset": "orders_daily", "version": "3.1.0", "owner": "team-checkout",
    "columns": {
        "order_id": {"type": str, "required": True, "unique": True},
        "amount_cents": {"type": int, "required": True, "min": 0},
        "currency": {"type": str, "required": True, "allowed": {"EUR", "USD", "PKR"}},
        "created_at": {"type": datetime, "required": True},
    },
    "freshness": timedelta(hours=2),
    "volume_sigma": 3.0,               # flag counts beyond mean +/- 3 sd of history
}

def row_errors(row: dict, cols: dict) -> list:
    errs = [f"unexpected column {c}" for c in row if c not in cols]
    for name, rule in cols.items():
        v = row.get(name)
        if v is None:
            if rule.get("required"):
                errs.append(f"{name} is null")
            continue
        if not isinstance(v, rule["type"]) or isinstance(v, bool):
            errs.append(f"{name} has type {type(v).__name__}")
            continue
        if "min" in rule and v < rule["min"]:
            errs.append(f"{name}={v} below {rule['min']}")
        if "allowed" in rule and v not in rule["allowed"]:
            errs.append(f"{name}={v!r} not allowed")
    return errs

def audit(batch: list, history_counts: list, now: datetime) -> dict:
    cols = CONTRACT["columns"]
    good, quarantined, seen = [], [], set()
    for row in batch:
        errs = row_errors(row, cols)
        key = row.get("order_id")
        if key in seen:
            errs.append(f"duplicate order_id {key}")
        seen.add(key)
        (quarantined if errs else good).append((row, errs))
    blocking = []
    newest = max((r["created_at"] for r, _ in good), default=None)
    if newest is None or now - newest > CONTRACT["freshness"]:
        blocking.append(f"stale: newest row {newest}")
    mu, sd = mean(history_counts), pstdev(history_counts)
    if abs(len(batch) - mu) > CONTRACT["volume_sigma"] * max(sd, 1):
        blocking.append(f"volume {len(batch)} vs typical {mu:.0f}")
    if len(quarantined) > 0.01 * max(len(batch), 1):
        blocking.append(f"{len(quarantined)} bad rows exceed 1% budget")
    return {"publish": not blocking, "blocking": blocking,
            "good": [r for r, _ in good], "quarantine": quarantined}

now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
def order(i, **over):
    row = {"order_id": f"o{i}", "amount_cents": 1999, "currency": "EUR",
           "created_at": now - timedelta(minutes=i % 90)}
    row.update(over)
    return row

history = [1000, 980, 1015, 1003, 990, 1010, 995]
batch = [order(i) for i in range(1000)]
batch[10] = order(10, amount_cents=-5)              # invalid value
batch[11] = order(5)                                # duplicate key
result = audit(batch, history, now)
assert result["publish"] and len(result["quarantine"]) == 2
print("published", len(result["good"]), "rows; quarantined:",
      [errs for _, errs in result["quarantine"]])

# Upstream renamed a column and the feed stalled: block, do not publish.
stale = [{**order(i), "created_at": now - timedelta(hours=6)} for i in range(400)]
for r in stale[:50]:
    r["amount"] = r.pop("amount_cents")
result = audit(stale, history, now)
assert not result["publish"]
print("blocked:", result["blocking"])
```

## Trade-offs
- **Block vs quarantine vs warn**: blocking protects consumers from bad data
  but makes them wait for fixes and can stop everything for one bad row;
  quarantining keeps data flowing but publishes an incomplete set that must
  be visibly marked; warnings keep latency low but rely on someone reading
  them. Money and compliance data lean to blocking.
- **Checks at ingestion vs before publish**: early checks catch problems
  close to the cause and cheaply; late checks see the final shape that
  consumers use. Important pipelines need both.
- **Hand-written rules vs learned anomaly detection**: rules are explicit
  and reviewable but only catch what someone anticipated; statistical
  monitors catch the unexpected but raise false alarms on holidays, launches
  and seasonality. Start with rules on keys, nulls and freshness; add
  anomaly monitors on the tables that matter most.
- **Producer-owned contracts vs consumer-side defence**: contracts move
  responsibility to the team that can fix the cause, but need producers to
  accept the work and an organisation that treats data as an interface;
  consumer-side checks work without agreement but only detect, never prevent.
- **Strictness vs evolution**: a contract that rejects any new column blocks
  harmless additive change; one that allows anything protects nothing. Use
  the same compatibility rules as APIs: additive changes are minor versions,
  removals and type changes need a new major version and a migration period
  ([[api-versioning-and-evolution]]).

## Gotchas
- Checks that only test the schema: the column still exists, but it is now
  in dollars instead of cents. Add range and reconciliation checks that
  encode meaning.
- Row-count checks against a fixed number: traffic grows and weekends dip.
  Compare with the same weekday or a rolling window.
- Freshness measured by load time: the job ran on schedule but loaded
  yesterday's data again. Measure the newest event time in the data.
- Quarantine tables nobody owns grow forever and hide a real upstream bug.
  Alert on quarantine rate and give it an owner and a retention period.
- Too many warning-level alerts train people to ignore all of them; keep
  alerts few, owned and actionable, as with service alerts
  ([[slis-slos-error-budgets]]).
- Null vs empty string vs `"N/A"` vs `0`: decide one representation of
  "unknown" per field in the contract, or completeness checks miss it.
- Deduplicating on the wrong key, or before late-arriving corrections
  land, deletes legitimate rows ([[batch-and-stream-processing]]).
- Backfills that bypass the checks because "it is a one-off" rewrite
  history with the bad data the checks were built to stop.
- Personal data copied into quarantine tables and check logs: they need the
  same access control and retention as the source ([[privacy-and-pii-handling]]).

## Related
- [[schema-evolution-and-serialization]] - compatible schema changes and registries that enforce them.
- [[data-warehousing-and-olap]] - where checked data is published for analytics.
- [[batch-and-stream-processing]] - the pipelines that run checks per batch or window.
- [[change-data-capture]] - service database changes flowing to consumers who need a contract.
- [[integration-and-contract-testing]] - consumer-driven contracts for APIs, the service-side analogue.
- [[input-validation-and-parsing]] - the same parse-at-the-boundary idea for request data.
- [[observability-logs-metrics-traces]] - monitoring and alerting patterns reused for data freshness and volume.
- [[data-modeling-and-schema-design]] - keys, types and constraints that prevent bad data in the first place.

## References
- Open Data Contract Standard (Bitol, Linux Foundation AI & Data): https://bitol-io.github.io/open-data-contract-standard/
- dbt documentation, "Add data tests to your DAG" (unique, not_null, accepted_values, relationships): https://docs.getdbt.com/docs/build/data-tests
- Great Expectations documentation: https://docs.greatexpectations.io/docs/
- Sebastian Schelter et al., "Automating Large-Scale Data Quality Verification", PVLDB 11(12), 2018 (Deequ).
- Eric Breck, Neoklis Polyzotis, Sudip Roy, Steven Whang, Martin Zinkevich, "Data Validation for Machine Learning", MLSys 2019.
- DAMA UK Working Group, "The Six Primary Dimensions for Data Quality Assessment", 2013.
- Barr Moses, Lior Gavish, Molly Vorwerck, *Data Quality Fundamentals*, O'Reilly, 2022.
- Andrew Jones, *Driving Data Quality with Data Contracts*, Packt, 2023.
- Joe Reis and Matt Housley, *Fundamentals of Data Engineering*, O'Reilly, 2022 (data quality across the data engineering lifecycle).
