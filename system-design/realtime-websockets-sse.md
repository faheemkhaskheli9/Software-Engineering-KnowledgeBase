---
title: Realtime with WebSockets, SSE and polling
category: system-design
tags: [websocket, sse, long-polling, realtime, push, pubsub, presence, reconnect]
use_cases:
  - "push live updates (notifications, prices, chat messages) from server to browser"
  - "choose between polling, long polling, Server-Sent Events and WebSockets"
  - "scale a websocket service across many servers with pub/sub fan-out"
  - "handle reconnects, missed messages and presence for a chat or collaborative app"
status: draft
last_verified: 2026-10-10
sources:
  - https://www.rfc-editor.org/rfc/rfc6455
  - https://html.spec.whatwg.org/multipage/server-sent-events.html
  - https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API
  - https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
  - https://socket.io/docs/v4/
---

# Realtime with WebSockets, SSE and polling

## Summary
HTTP is request/response, so servers cannot spontaneously push to a client.
Realtime techniques close that gap: short polling, long polling,
Server-Sent Events (one-way server to client over HTTP) and WebSockets (full
duplex over a single upgraded TCP connection). The hard part is not the
protocol but operating millions of long-lived connections: routing, fan-out,
reconnects, ordering and backpressure.

## Key concepts
- **Short polling**: client asks every N seconds. Simplest, wasteful, latency up to N.
- **Long polling**: server holds the request until data or timeout, then client immediately re-requests. Works through any proxy; one request per message batch.
- **SSE (EventSource)**: single long-lived HTTP response with `Content-Type: text/event-stream`; text frames; built-in auto-reconnect and `Last-Event-ID` resume; server to client only.
- **WebSocket (RFC 6455)**: HTTP `Upgrade` handshake then bidirectional message frames (text/binary), low overhead, client and server can send anytime. No built-in reconnect, ack or resume.
- **WebTransport / HTTP/2-3 streams**: newer alternatives over QUIC; check browser support before relying on them.
- **Heartbeat/ping-pong**: detect dead connections that TCP has not noticed (NAT/mobile).
- **Connection registry**: mapping user/session to the server holding their connection.
- **Fan-out via pub/sub**: a message for user X reaches whichever node holds X's socket through a broker (Redis pub/sub, NATS, Kafka).
- **Presence**: who is online, via heartbeats with TTL.

## When to use / scenarios
- Chat, collaborative editing, multiplayer, live dashboards, tickers, notifications ([[design-chat-system]], [[design-notification-system]]).
- Choose by direction and frequency:

| Need | Pick |
|---|---|
| Updates every minute or slower, simple | short polling |
| Occasional server events, must work behind strict proxies | long polling |
| Server to client stream only (notifications, progress, feeds, LLM token streaming) | SSE |
| Bidirectional, low latency, frequent small messages (chat, games, cursors) | WebSocket |
| Mobile app backgrounded | platform push (APNs/FCM), not sockets |

- Not for: infrequent one-off events where polling with backoff is cheaper to run; background mobile delivery (use push notifications).

## How it works / example

Scaling pattern: stateless-ish gateway nodes hold sockets; a broker routes
messages between nodes.

```
 clients <--ws--> [ws node 1] \                      / [ws node 1]
 clients <--ws--> [ws node 2]  >-- pub/sub broker --<  ...
 clients <--ws--> [ws node 3] /     (Redis/NATS)      \ chat service -> DB
        ^ LB with long idle timeout, sticky not required if reconnect + resume is supported
 registry: user42 -> node2 (TTL, refreshed by heartbeat)
```

Minimal SSE endpoint (FastAPI-free, stdlib only) and browser client:

```python
# server: python sse.py  -> curl -N http://localhost:8000
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = int(self.headers.get("Last-Event-ID", 0))   # resume support
        for i in range(last + 1, last + 6):
            self.wfile.write(f"id: {i}\ndata: tick {i}\n\n".encode())
            self.wfile.flush()
            time.sleep(1)

if __name__ == "__main__":
    ThreadingHTTPServer(("", 8000), H).serve_forever()
```

```javascript
const es = new EventSource("/stream");        // reconnects automatically
es.onmessage = (e) => console.log(e.lastEventId, e.data);
```

WebSocket echo with reconnect logic on the client (browser):

```javascript
function connect(attempt = 0) {
  const ws = new WebSocket("wss://example.com/ws");
  ws.onopen = () => { attempt = 0; ws.send(JSON.stringify({ type: "resume", since: lastSeq })); };
  ws.onmessage = (m) => handle(JSON.parse(m.data));   // apply by seq, drop duplicates
  ws.onclose = () => setTimeout(() => connect(attempt + 1),
                  Math.min(30000, 500 * 2 ** attempt) * (0.5 + Math.random()));  // backoff + jitter
}
```

### Reliable delivery on top of sockets
Sockets are best-effort: assign each message a per-channel sequence number;
clients track the last seen `seq` and on reconnect request everything after it
(from a short-retention log such as Redis Streams or Kafka,
[[message-queues-and-streams]]). Persist messages first, push second; the
socket is a delivery optimisation, the database is the truth.

## Trade-offs
- **SSE vs WebSocket**: SSE is plain HTTP (works with existing auth, proxies, HTTP/2 multiplexing, auto-resume) but one-directional and text only; WebSocket is more flexible and needs its own framing, auth and resume logic. Prefer SSE when you only push.
- **HTTP/1.1 connection limits**: browsers cap about 6 connections per host; many SSE streams on HTTP/1.1 exhaust it. HTTP/2 multiplexing removes this.
- **Stateful connections vs stateless scaling**: sockets pin clients to nodes; deployments must drain gracefully and clients must reconnect with jitter to avoid a reconnect storm.
- **Fan-out cost**: broadcasting to large rooms is O(members); for huge channels shard rooms, batch frames, or switch to pull (clients poll a cached feed).
- **Managed services** (Pusher, Ably, AWS API Gateway WebSockets, Firebase) trade per-message/connection cost for no connection fleet to run.

## Gotchas
- Load balancer or proxy idle timeouts (often 60 s) close quiet sockets; send heartbeats below that interval and tune LB timeouts ([[load-balancing]]).
- Reconnect storms after a deploy or outage: use exponential backoff with jitter and server-side connection rate limiting ([[rate-limiting]]).
- Authentication: browsers cannot set arbitrary headers on the WebSocket handshake; use cookies, a short-lived ticket in the query string (not a long-lived token, URLs get logged), or an auth message as the first frame. Validate `Origin` to prevent cross-site WebSocket hijacking ([[owasp-top-10]]).
- Unbounded per-connection send buffers cause memory blowups with slow clients; apply backpressure or drop/close slow consumers.
- Ordering across multiple nodes is not guaranteed without sequence numbers or a single-partition route per conversation.
- Authorization must be re-checked on every subscription and when permissions change, not just at connect.
- Kernel and file-descriptor limits (`ulimit -n`, ephemeral ports, memory per connection) cap connections per node; test with a realistic load generator ([[performance-and-load-testing]]).
- Sticky assumptions: do not store session state only in node memory.

## Related
- [[design-chat-system]] - the canonical WebSocket design problem.
- [[design-notification-system]] - push vs pull delivery channels.
- [[message-queues-and-streams]] - broker for cross-node fan-out and replay.
- [[load-balancing]] - long-lived connection balancing and timeouts.
- [[networking-fundamentals]] - TCP, HTTP upgrade and keep-alive behaviour.
- [[choosing-communication-style]] - when realtime push beats request/response.

## References
- RFC 6455 The WebSocket Protocol: https://www.rfc-editor.org/rfc/rfc6455
- WHATWG HTML Standard, Server-sent events: https://html.spec.whatwg.org/multipage/server-sent-events.html
- MDN WebSockets API: https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API
- MDN Server-sent events: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- Socket.IO docs: https://socket.io/docs/v4/
