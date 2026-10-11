---
title: Choosing real-time updates - polling vs SSE vs WebSockets
category: scenarios
tags: [realtime, polling, long-polling, sse, websocket, push-notifications, webhooks, llm-streaming, decision-guide]
use_cases:
  - "show live order status, notifications or dashboard numbers without a page refresh"
  - "pick between polling, long polling, Server-Sent Events and WebSockets"
  - "stream LLM tokens or job progress to a browser"
  - "build chat or collaborative editing that needs two-way low latency"
  - "deliver updates to a mobile app in the background"
status: stable
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc6202
  - https://www.rfc-editor.org/rfc/rfc6455
  - https://html.spec.whatwg.org/multipage/server-sent-events.html
  - https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
  - https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API
---

# Choosing real-time updates - polling vs SSE vs WebSockets

## Summary
Pick by direction, frequency and who the receiver is. Infrequent updates or a handful of users: poll (with ETags and backoff). Server-to-browser streams such as notifications, progress and LLM tokens: Server-Sent Events. Two-way, frequent, low-latency messages such as chat, cursors and games: WebSockets. Backgrounded mobile apps: platform push. Other servers: webhooks. In every case the database is the source of truth and the push channel is a delivery optimisation, so clients must be able to resync after a reconnect.

## Key concepts
- **Direction.** Server to client only, or both ways. Most "real-time" features are one-way.
- **Freshness need.** How late may an update arrive? That sets the polling interval or justifies a persistent connection.
- **Connection cost.** Polling spends requests; SSE and WebSockets spend long-lived connections, memory and file descriptors per client.
- **Resume.** SSE has `Last-Event-ID` and auto-reconnect built in; WebSockets need your own sequence numbers and resume message.
- **Fan-out.** With more than one server, a broker routes a message to the node holding the user's connection ([[realtime-websockets-sse]]).
- **Receiver type.** Browser tab open, mobile app in background (push service), or another backend (webhook).

## When to use / scenarios
Master table:

| Situation | Choose | Read |
|---|---|---|
| Status that changes rarely, few users, simplest possible | Short polling with `ETag`/`If-None-Match` and backoff | [[choosing-a-caching-strategy]], [[rest-api-design]] |
| Occasional events, strict proxies, no streaming support | Long polling | [[realtime-websockets-sse]] |
| Notifications, feeds, live dashboards, job progress | SSE | [[realtime-websockets-sse]] |
| LLM token streaming to a browser | SSE (or streamed HTTP response) | [[realtime-websockets-sse]], AI KB link below |
| Chat, collaborative editing, multiplayer, cursors | WebSocket with seq numbers and resume | [[realtime-websockets-sse]], [[design-chat-system]] |
| Mobile app in background, user offline | Platform push (APNs/FCM) + fetch on open | [[design-notification-system]] |
| Notify customers' servers | Webhooks, signed, retried | [[webhooks]] |
| Internal service-to-service streaming | gRPC streams or a message broker | [[grpc-and-protobuf]], [[message-queues-and-streams]] |
| Huge broadcast audiences (live scores to everyone) | Pull a CDN-cached snapshot, or SSE through an edge provider | [[cdn-and-edge]] |
| No team to run a connection fleet | Managed realtime service | [[realtime-websockets-sse]] |

Decision flow:

```
Receiver is another server?            -> webhook (or broker if internal)
Receiver is a backgrounded mobile app? -> platform push, then fetch
Browser:
  client must send frequent messages too (chat, cursors)? -> WebSocket
  server -> client only?                                  -> SSE
  updates rare / users few / infra must stay plain HTTP?  -> polling (ETag + backoff)
Many servers? -> broker fan-out + per-channel sequence numbers + resume on reconnect
```

When NOT to use WebSockets: one-way feeds (SSE is simpler, works with cookie auth and ordinary HTTP proxies), or data that changes rarely (polling costs less to operate). When NOT to poll: many clients needing low latency, where polling load scales with clients times frequency even when nothing changes.

## How it works / example
Long polling is the bridge between polling and push: the server parks the request until the version moves past what the client has, or a timeout fires. Runnable stdlib sketch of the server-side wait:

```python
import threading

class Channel:
    def __init__(self):
        self.version, self.data = 0, None
        self.cond = threading.Condition()

    def publish(self, data):
        with self.cond:
            self.version += 1
            self.data = data
            self.cond.notify_all()

    def wait_newer(self, since: int, timeout: float):
        """Return (version, data) newer than `since`, or None on timeout (client re-polls)."""
        with self.cond:
            self.cond.wait_for(lambda: self.version > since, timeout=timeout)
            return (self.version, self.data) if self.version > since else None

if __name__ == "__main__":
    ch = Channel()
    assert ch.wait_newer(0, timeout=0.05) is None           # nothing yet: timeout
    threading.Timer(0.05, ch.publish, args=("shipped",)).start()
    assert ch.wait_newer(0, timeout=2) == (1, "shipped")    # woken by publish
    assert ch.wait_newer(1, timeout=0.05) is None           # already up to date
    print("ok")
```

The client sends its last seen version on each request, which is the same resume idea SSE (`Last-Event-ID`) and WebSocket designs (`since: seq`) use. The SSE endpoint and WebSocket reconnect code are in [[realtime-websockets-sse]].

Reference architecture once there is more than one server:

```
 writer -> DB (commit) -> outbox/event -> broker (pub/sub per channel)
                                            |
               SSE / WS nodes subscribe <---+---> push each event with seq
 client reconnects with last seq -> node replays from short-retention log, then streams live
```

AI-specific angle: streaming LLM output over SSE from a Python API is covered in the AI Knowledge Base, [Serving LLM apps with FastAPI](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/deployment/serving-with-fastapi.md).

## Trade-offs
| Axis | Short polling | Long polling | SSE | WebSocket |
|---|---|---|---|---|
| Direction | Client pull | Client pull, server holds | Server to client | Both ways |
| Latency | Up to the interval | Low | Low | Lowest |
| Infra | Plain HTTP, cacheable | Plain HTTP, held requests | Plain HTTP, long response | Upgrade, own framing |
| Reconnect / resume | Implicit | Implicit (send version) | Built in (`Last-Event-ID`) | Build it yourself |
| Auth | Normal | Normal | Cookies (browser `EventSource` cannot set headers; fetch-based clients can) | Handshake limits; cookie, ticket or first message |
| Server cost | Requests even when idle | Parked requests | Open connections | Open connections + per-socket state |

- **Build vs buy:** running a connection fleet (heartbeats, drains on deploy, reconnect storms, FD limits) is real operations work; managed services trade it for per-connection or per-message pricing.
- **Push everything vs push a hint:** pushing a "something changed" hint and letting clients fetch keeps authorization and payload logic in the normal API.

## Gotchas
- Treating the socket as the source of truth; messages are lost on disconnect unless clients resync from the DB or a log.
- Proxy and load balancer idle timeouts closing quiet connections; send heartbeats ([[load-balancing]]).
- Reconnect storms after a deploy; clients need exponential backoff with jitter.
- SSE over HTTP/1.1 is limited by the browser's per-host connection cap; serve over HTTP/2.
- WebSocket handshake cannot carry arbitrary headers from browsers; do not put long-lived tokens in the URL, and validate `Origin`.
- Authorization checked only at connect; re-check per subscription and when permissions change ([[authorization-models]]).
- Polling clients all firing on the same schedule; add jitter and honour `Retry-After`.
- Buffering proxies or compression middleware holding SSE frames; disable buffering for the stream route.

## Related
- [[realtime-websockets-sse]] - protocols, scaling pattern, SSE and WebSocket code.
- [[choosing-communication-style]] - where push fits among sync and async styles.
- [[design-chat-system]] - the canonical WebSocket design.
- [[design-notification-system]] - push channels including mobile push.
- [[webhooks]] - real-time updates to other servers.
- [[message-queues-and-streams]] - broker fan-out and replay logs.
- [[scenario-chooser]] - other problem-to-topic mappings.

## References
- RFC 6202, Known Issues and Best Practices for the Use of Long Polling and Streaming in Bidirectional HTTP.
- RFC 6455, The WebSocket Protocol.
- WHATWG HTML Standard, Server-sent events.
- MDN, Server-sent events and WebSockets API.
