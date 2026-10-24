---
title: Schema evolution and serialization formats
category: data
tags: [schema-evolution, serialization, avro, protobuf, json-schema, schema-registry, backward-compatibility, forward-compatibility, encoding, events]
use_cases:
  - "add or remove a field in Kafka events without breaking consumers that deploy later"
  - "choose between JSON, Avro and Protobuf for events, files or service calls"
  - "set schema registry compatibility mode (backward, forward, full) and know what order to deploy in"
  - "old data written years ago must still be readable by new code"
  - "a rename or type change in a message broke a downstream team"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
  - https://avro.apache.org/docs/1.12.0/specification/
  - https://protobuf.dev/programming-guides/proto3/
  - https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html
  - https://json-schema.org/understanding-json-schema/reference/object
  - https://buf.build/docs/breaking/
---

# Schema evolution and serialization formats

## Summary
Data outlives the code that wrote it: messages sit in a topic, rows sit in
files and object storage, and producers and consumers deploy at different
times. Schema evolution is the set of rules that let a schema change while
old readers can still read new data (forward compatibility) and new readers
can still read old data (backward compatibility). The serialization format
decides how much of this is enforced: JSON relies on discipline, Protobuf
on field numbers, and Avro on resolving the writer's schema against the
reader's, usually with a schema registry checking every change.

## Key concepts
- **Backward compatible**: code using the *new* schema reads data written
  with the *old* one. Needed because old data exists. Upgrade readers first.
- **Forward compatible**: code using the *old* schema reads data written with
  the *new* one. Needed because old readers are still running during a
  rollout. Upgrade writers first.
- **Full** compatibility is both; **transitive** variants check against every
  earlier version, not just the previous one (Confluent Schema Registry modes
  BACKWARD (its default), FORWARD, FULL, their `_TRANSITIVE` forms, and NONE).
- **Field identity**: Protobuf and Thrift identify fields by number (tag), so
  names can change but numbers never can; Avro matches fields by name (with
  aliases), and data carries no tags at all, so the reader needs the exact
  writer's schema; JSON matches by name.
- **Writer's and reader's schema** (Avro): the decoder walks the writer's
  schema and maps each field into the reader's: fields only in the writer are
  skipped, fields only in the reader take the reader's default, and a field
  with no default that is missing is an error.
- **Unknown fields**: a good decoder skips fields it does not know and, for
  pass-through services, preserves them (proto3 keeps unknown fields).
  Rejecting unknown fields makes every addition a breaking change.
- **Schema registry**: a service that stores versioned schemas per subject,
  rejects incompatible changes at publish time and gives each message a small
  schema id so consumers can fetch the writer's schema.
- **Safe changes, in practice**: add an optional field with a default; remove
  a field that had a default (and never reuse its tag or name); widen enums
  only if readers tolerate unknown values. **Unsafe**: rename without alias,
  change a type, make an optional field required, reuse a Protobuf field
  number, change field order in positional formats (CSV, some binary
  encodings).

## When to use / scenarios
- Events on Kafka or another log consumed by teams you do not deploy with:
  binary format plus registry (Avro or Protobuf) with BACKWARD or FULL
  compatibility enforced in CI ([[event-driven-architecture]],
  [[message-queues-and-streams]]).
- Service-to-service RPC with generated clients: Protobuf, with `buf
  breaking` in CI ([[grpc-and-protobuf]]).
- Public HTTP APIs and webhooks: JSON with an OpenAPI or JSON Schema contract
  and the additive-change rules of [[api-versioning-and-evolution]].
- Long-lived files in a data lake: self-describing formats (Avro container
  files, Parquet) that embed the schema next to the data
  ([[data-warehousing-and-olap]]).
- CDC streams: the database schema becomes an event schema; database
  migrations must follow the same rules ([[change-data-capture]],
  [[schema-migrations]]).
- When NOT to bother: a private cache entry or a message produced and consumed
  by the same deploy unit can just be versioned and thrown away. Never use
  language-native serialization (Python `pickle`, Java serialization) for
  data that crosses a trust or version boundary: it is tied to class layout
  and decoding untrusted input can execute code.

## How it works / example
Deploy order follows the compatibility direction:

```
BACKWARD: new reader + old data OK  -> deploy consumers first, then producers
FORWARD:  old reader + new data OK  -> deploy producers first, then consumers
FULL:     both                      -> any order (what you want for independent teams)
```

A minimal Avro-style resolver and compatibility checker (stdlib only). A
schema is a list of fields with a type and an optional default; a reader
resolves a record written with the writer's schema, and the checker says
whether a change is backward, forward or fully compatible.

```python
MISSING = object()

def field(name, type_, default=MISSING, aliases=()):
    return {"name": name, "type": type_, "default": default, "aliases": tuple(aliases)}

def resolve(record, writer, reader):
    """Read `record` (written with `writer`) as the `reader` schema expects."""
    by_name = {f["name"]: f for f in writer}
    out = {}
    for rf in reader:
        wf = next((by_name[n] for n in (rf["name"], *rf["aliases"]) if n in by_name), None)
        if wf is not None:
            if wf["type"] != rf["type"]:
                raise TypeError(f"{rf['name']}: {wf['type']} -> {rf['type']}")
            out[rf["name"]] = record[wf["name"]]
        elif rf["default"] is not MISSING:
            out[rf["name"]] = rf["default"]       # field the writer did not know
        else:
            raise ValueError(f"missing field {rf['name']!r} with no default")
    return out                                    # writer-only fields are skipped

def can_read(reader, writer):
    sample = {f["name"]: f["default"] if f["default"] is not MISSING else 0 for f in writer}
    try:
        resolve(sample, writer, reader)
        return True
    except (TypeError, ValueError):
        return False

def compatibility(old, new):
    backward = can_read(reader=new, writer=old)   # new code, old data
    forward = can_read(reader=old, writer=new)    # old code, new data
    return {(True, True): "FULL", (True, False): "BACKWARD",
            (False, True): "FORWARD", (False, False): "NONE"}[(backward, forward)]

v1 = [field("order_id", "long"), field("amount_cents", "long"),
      field("note", "string", default="")]

# Add an optional field with a default: safe in both directions.
v2 = v1 + [field("currency", "string", default="USD")]
assert compatibility(v1, v2) == "FULL"
old_event = {"order_id": 7, "amount_cents": 1250, "note": ""}
assert resolve(old_event, v1, v2)["currency"] == "USD"

# Add a required field (no default): new readers cannot read old data.
v2_bad = v1 + [field("customer_id", "long")]
assert compatibility(v1, v2_bad) == "FORWARD"

# Remove a field that had a default: old readers fill it in.
v3 = [f for f in v1 if f["name"] != "note"]
assert compatibility(v1, v3) == "FULL"

# Remove a required field: old readers break.
v3_bad = [f for f in v1 if f["name"] != "amount_cents"]
assert compatibility(v1, v3_bad) == "BACKWARD"

# Rename: breaks both ways without an alias; an alias fixes the new reader.
renamed = [field("order_id", "long"), field("total_cents", "long"),
           field("note", "string", default="")]
assert compatibility(v1, renamed) == "NONE"
aliased = [field("order_id", "long"), field("total_cents", "long", aliases=["amount_cents"]),
           field("note", "string", default="")]
assert compatibility(v1, aliased) == "BACKWARD"
assert resolve(old_event, v1, aliased)["total_cents"] == 1250

# Type change: incompatible here (real Avro allows some promotions, e.g. int -> long).
retyped = [field("order_id", "string")] + v1[1:]
assert compatibility(v1, retyped) == "NONE"
print("all compatibility checks passed")
```

The same rules for Protobuf, where the field number is the identity:

```proto
message Order {
  reserved 3;                 // was `string note = 3;` - never reuse the number
  reserved "note";            // or the name
  int64 order_id = 1;
  int64 amount_cents = 2;
  string currency = 4;        // added later; old readers skip it, new readers see "" for old data
}
```

## Trade-offs
- **JSON vs binary with schema**: JSON is readable, universal and needs no
  tooling, but is larger, has weak number semantics (large integers lose
  precision in JavaScript) and compatibility is a convention; Avro and
  Protobuf are compact and checkable but need generated code or a registry,
  and are opaque in logs.
- **Avro vs Protobuf**: Avro has no tags in the data (smallest output, good
  for files and dynamically generated schemas) but needs the writer's schema
  at read time; Protobuf data is decodable with any later schema version and
  has broad RPC tooling, but numbers must be managed by hand.
- **Strict vs tolerant readers**: rejecting unknown fields catches typos and
  contract drift early but makes every addition breaking; tolerant readers
  (ignore what you do not understand) make evolution easy but can silently
  drop data a pass-through service should have kept.
- **BACKWARD vs FULL**: BACKWARD also lets you delete required fields, but
  every consumer must upgrade before any producer does, which is manageable
  for one team; FULL restricts you to adding or removing fields that have
  defaults but lets producers and consumers deploy in any order.
- **New version vs new topic**: some changes (re-keying, semantic changes)
  cannot be made compatible; publish a new event type or topic and run both
  during migration rather than forcing it through compatibility rules.

## Gotchas
- A compatible schema change with an incompatible *meaning* change (amount
  now in dollars instead of cents) passes every checker and corrupts data.
  Semantic changes need a new field or a new event type.
- Proto3 scalar fields cannot distinguish "absent" from the zero value unless
  declared `optional`; a reader cannot tell "not set" from `0` or `""`.
- Adding an enum value breaks readers that switch exhaustively or map
  unknown values to an error; define an UNKNOWN or UNSPECIFIED zero value and
  handle the default branch ([[api-versioning-and-evolution]]).
- JSON Schema with `additionalProperties: false` on a consumer makes every
  new producer field a breaking change.
- Checking compatibility only against the previous version while old data
  from several versions back is still in the topic or lake: use transitive
  modes for long-retention data.
- Defaults are part of the contract: changing a default changes how old data
  is read.
- Reusing a deleted Protobuf field number or Avro field name with a new type:
  old data decodes into the wrong field. Reserve them.
- Schema registry outage or a missing schema id stops consumers; cache
  schemas locally and treat the registry as a critical dependency.

## Related
- [[api-versioning-and-evolution]] - the same additive-change rules for HTTP APIs and deprecation.
- [[grpc-and-protobuf]] - Protobuf field numbers, reserved fields and breaking-change detection.
- [[event-driven-architecture]] - events as long-lived public contracts between teams.
- [[message-queues-and-streams]] - topics where data written by old producers is read by new consumers.
- [[schema-migrations]] - expand/contract for database schemas, which CDC turns into event schemas.
- [[change-data-capture]] - database changes published as events inherit these compatibility rules.
- [[integration-and-contract-testing]] - consumer-driven contracts that catch breaking changes before deploy.
- [[data-modeling-and-schema-design]] - designing the record shape in the first place.

## References
- Martin Kleppmann, *Designing Data-Intensive Applications* (1st ed., 2017), ch. 4 "Encoding and Evolution": https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
- Apache Avro 1.12.0 Specification, "Schema Resolution" and "Aliases": https://avro.apache.org/docs/1.12.0/specification/
- Protocol Buffers Language Guide (proto3), "Updating A Message Type", "Reserved Fields", "Unknown Fields": https://protobuf.dev/programming-guides/proto3/
- Confluent documentation, "Schema Evolution and Compatibility for Schema Registry": https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html
- JSON Schema reference, "object" (`additionalProperties`): https://json-schema.org/understanding-json-schema/reference/object
- Buf documentation, breaking change detection: https://buf.build/docs/breaking/
