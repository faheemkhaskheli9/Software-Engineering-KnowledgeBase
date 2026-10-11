---
title: Design a chat system
category: case-studies
tags: [chat, messaging, websocket, presence, fan-out, message-ordering, whatsapp, slack, case-study]
use_cases:
  - "design a WhatsApp or Slack style chat with 1:1 and group messaging"
  - "add real-time messaging with delivery receipts and offline sync to our app"
  - "keep message order and avoid duplicates when clients reconnect and retry"
  - "show online/offline presence and typing indicators at scale"
  - "store and search years of message history cheaply"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 12 'Design a Chat System'"
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
  - https://www.rfc-editor.org/rfc/rfc6455.html
  - https://discord.com/blog/how-discord-stores-trillions-of-messages
  - https://engineering.fb.com/2014/10/09/production-engineering/building-mobile-first-infrastructure-for-messenger/
---

# Design a chat system

## Summary
A chat system delivers messages between users in near real time over
persistent connections, supports 1:1 and group conversations, stores history,
and syncs across devices. The hard parts are connection management at scale,
per-conversation ordering, reliable delivery with retries (no loss, no
visible duplicates), and group fan-out.

## Key concepts
- **Persistent connections:** WebSocket (RFC 6455) as the primary transport,
  with long-polling/SSE or push notifications as fallbacks ([[realtime-websockets-sse]]).
- **Stateful gateway tier** holds connections; stateless services behind it do the logic.
- **Per-conversation ordering** is enough; global ordering is unnecessary and expensive.
- **At-least-once delivery + client-generated message IDs = effectively once**
  ([[idempotency-and-exactly-once]]).
- **Fan-out on write for small groups; read-time or bounded fan-out for large ones.**
- **Presence is soft state:** heartbeats with TTL, lossy by design.
- **Inbox/sync model:** each device keeps a cursor (last seen sequence) and
  pulls anything newer.

## When to use / scenarios
Applies to: consumer messengers, team chat, in-app support chat, live comments,
multiplayer lobby chat, collaborative app notifications. For broadcast-only
one-way events see [[design-notification-system]]; for very large public
channels (live streams with millions) treat it as pub/sub with sampling, not as chat.

## How it works / example

### 1. Requirements
Functional: 1:1 chat; group chat (assume up to 500 members; larger is a different design);
online/offline presence; delivery states (sent, delivered, read); multi-device sync;
media attachments (stored in [[blob-object-storage]]); push notification when offline;
history and search.

Non-functional: low latency delivery (hundreds of ms typical), high availability,
no message loss once acknowledged, per-conversation ordering, end-to-end encryption
optional (changes server design: server cannot index content).

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 50 M daily active users, each sends 40 messages/day -> 2 B messages/day -> about 23,000 msgs/s average, peak maybe 3x.
- Concurrent connections: assume 20 M peak. A tuned gateway server can hold on the order of
  100k connections (memory and file descriptors bound; verify by load test), so around 200+ gateways.
- Storage: 100 bytes average text message -> 200 GB/day, about 73 TB/year before replication (media excluded).
- Fan-out: a group message to N members is N deliveries; average group size matters more than user count.

### 3. API
Client <-> gateway over WebSocket, JSON or protobuf frames:
```
-> {"type":"send","client_msg_id":"uuid","conv_id":"c1","body":"hi"}
<- {"type":"ack","client_msg_id":"uuid","server_msg_id":"m9","seq":1042}
<- {"type":"message","conv_id":"c1","seq":1043,"from":"u2","body":"..","ts":...}
-> {"type":"read","conv_id":"c1","upto_seq":1043}
-> {"type":"typing","conv_id":"c1"}                 (ephemeral, not persisted)
```
HTTP for the rest: `GET /conversations/{id}/messages?after_seq=..&limit=..`
(see [[pagination-filtering-sorting]]), media upload via pre-signed URLs, login ([[authentication-and-sessions]]).

### 4. Data model
```
conversations(conv_id, type, member_ids[], created_at)
messages(conv_id, seq, msg_id, sender_id, body, ts, attachment_ref)   PK (conv_id, seq)
inbox_cursor(user_id, device_id, conv_id, last_seq_delivered, last_seq_read)
presence(user_id) -> {status, last_seen, gateway_id}   (Redis, TTL)
connection_map(user_id, device_id) -> gateway_id        (Redis)
```
Access pattern: "latest N messages of a conversation, range by seq", which fits a
wide-column store (Cassandra/ScyllaDB/HBase), partitioned by `conv_id` (Discord
documents this style of design). Relational DBs work until history size exceeds
one node ([[sql-vs-nosql]], [[partitioning-and-sharding]]). Use a time bucket in
the partition key for very busy channels to keep partitions bounded.

### 5. High-level architecture
```
 clients <==WebSocket==> L4 LB ==> Chat gateways (stateful, many)
                                       |  publish/subscribe
 HTTP --> API gateway --> User/Group svc, Media svc, History svc
                                       v
                          Message service (assign seq, persist)
                             |                      |
                  Kafka/queue per partition      Message store (wide-column)
                             |
        Delivery workers --> look up connection_map --> gateway --> client
                             \--> offline? --> Push service (APNs/FCM)
 Presence service <-- heartbeats via gateways (Redis TTL), fan-out to friends
```
See [[message-queues-and-streams]], [[load-balancing]], [[api-gateway-and-service-mesh]].

### 6. Deep dive A: send path, ordering and exactly-once
1. Client sends with a client-generated `client_msg_id` and retries until acked.
2. Gateway forwards to the message service which, partitioned by `conv_id`,
   serialises messages for that conversation and assigns the next `seq`
   (single writer per conversation partition: a Kafka partition key or a
   row-level counter). That yields a total order per conversation without a
   global clock ([[time-clocks-and-ordering]]).
3. Persist, then ack to the sender (ack means durable). Dedup on
   `(conv_id, client_msg_id)` makes retries safe ([[idempotency-and-exactly-once]]).
4. Publish to delivery workers; push to every online recipient device through its gateway.
5. Receivers ack delivery; the server records `last_seq_delivered`. Offline
   devices simply pull `after_seq` when they reconnect (and get a push notification).
6. Client detects gaps in `seq` and requests the missing range, so loss on the
   push path heals itself.

```python
def handle_send(msg):
    if store.exists(msg.conv_id, msg.client_msg_id):          # retry dedupe
        return store.get_ack(msg.conv_id, msg.client_msg_id)
    seq = store.next_seq(msg.conv_id)                         # single writer / partition
    store.append(msg.conv_id, seq, msg)                       # durable
    queue.publish(topic="deliver", key=msg.conv_id, value=(msg.conv_id, seq))
    return Ack(msg.client_msg_id, seq)
```

### 7. Deep dive B: connection management and routing
Gateways register `user_id/device -> gateway_id` in a Redis map with TTL refreshed by heartbeats.
To deliver, a worker looks up the map and sends to that gateway over an internal channel
(gRPC stream or pub/sub topic per gateway, see [[grpc-and-protobuf]]). On gateway crash,
clients reconnect through the LB to another gateway and resync from their cursor,
so gateway death costs a reconnect, not data. Use consistent hashing if you
want connection affinity per user ([[consistent-hashing]]). Deploys drain connections
gradually (send "reconnect later" with jitter) to avoid a reconnect stampede.

### 8. Deep dive C: group fan-out and presence
- Group of N: the message is stored **once** per conversation; delivery fan-out
  is N lookups + pushes. Cost is acceptable for N up to hundreds. For very large
  groups, do not push per member; clients pull on a signal ("new in c1") or subscribe only when the channel is open.
- Per-user read state is stored separately from the message (cursor table), avoiding N message copies.
- Presence: heartbeat every ~5-30 s refreshes `presence:{user}` with a TTL slightly
  larger than the interval; absent heartbeat means offline. Publish status changes
  only to friends/open conversations, not to the entire graph; for big contact
  lists fetch on demand (lazy) rather than push.
- Typing indicators are ephemeral, rate-limited, not stored.

### 9. Scaling and failure handling
- Scale gateways horizontally; they hold no durable state.
- Shard the message store by `conv_id`; replicate across AZs ([[replication]]).
- Backpressure: bound per-connection send buffers and drop slow consumers to
  resync mode instead of exhausting gateway memory.
- Multi-region: pin each conversation's home region for ordering; users in
  other regions connect to the nearest gateway that forwards to the home region.
- Search: index messages asynchronously into a search cluster ([[search-systems]]);
  not possible server-side with end-to-end encryption.
- Retention and cold storage: move old partitions to cheaper storage.
- Media: upload to object storage via pre-signed URL, send only the reference in the message.

## Trade-offs
- WebSocket gives lowest latency but stateful connections complicate scaling; long-polling is simpler but heavier per message.
- Per-conversation sequencing limits throughput of a single hot conversation to one partition; acceptable for chat.
- Push fan-out vs pull-on-signal for large groups: latency vs server cost.
- End-to-end encryption protects content but kills server search, spam filtering and easy multi-device history.
- Exactly-once is built from at-least-once plus dedupe, not delivered by the network.

## Gotchas
- Using wall-clock timestamps for ordering: skew reorders messages; use server-assigned `seq`.
- Acking before persisting: a crash then loses an "acknowledged" message.
- Reconnect storms after a gateway or network blip; add jittered backoff.
- Unbounded presence fan-out ("thundering herd" on a celebrity going online).
- Storing per-recipient message copies for groups: storage multiplies by group size.
- Mobile reality: OS kills background sockets; push notifications and resync-on-open are mandatory, not optional.
- Message edits/deletes need their own events with sequence numbers.

## Related
- [[realtime-websockets-sse]] - the transport layer and its scaling limits
- [[message-queues-and-streams]] - decouples send, persistence and delivery
- [[idempotency-and-exactly-once]] - client message IDs and dedupe
- [[time-clocks-and-ordering]] - why per-conversation sequence beats timestamps
- [[design-notification-system]] - push delivery to offline users
- [[partitioning-and-sharding]] - sharding message history by conversation
- [[blob-object-storage]] - attachments
- [[choosing-realtime-updates]] - why WebSockets here rather than polling or SSE

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 12
- RFC 6455 The WebSocket Protocol: https://www.rfc-editor.org/rfc/rfc6455.html
- Discord, "How Discord Stores Trillions of Messages": https://discord.com/blog/how-discord-stores-trillions-of-messages
- Kleppmann, *Designing Data-Intensive Applications* (2017)
