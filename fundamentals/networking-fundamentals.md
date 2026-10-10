---
title: Networking fundamentals for application engineers
category: fundamentals
tags: [networking, tcp, udp, http, dns, tls, latency, sockets, http2, http3]
use_cases:
  - "explain why the first request to a new host is slow and later ones are fast"
  - "pick between TCP, UDP and HTTP/3 for a real-time feature"
  - "debug intermittent timeouts and connection resets between two services"
  - "tune connection pooling and keep-alive for a service making many outbound calls"
  - "understand what happens between typing a URL and seeing the page"
status: draft
last_verified: 2026-10-10
sources:
  - "High Performance Browser Networking, Ilya Grigorik - https://hpbn.co/"
  - "RFC 9293 (TCP) - https://www.rfc-editor.org/rfc/rfc9293"
  - "RFC 9110 (HTTP Semantics) - https://www.rfc-editor.org/rfc/rfc9110"
  - "RFC 9114 (HTTP/3) - https://www.rfc-editor.org/rfc/rfc9114"
  - "Computer Networking: A Top-Down Approach, Kurose and Ross"
---

# Networking fundamentals for application engineers

## Summary
Application engineers need a working model of the layers between code and wire: DNS resolves names, TCP (or QUIC) gives reliable streams, TLS secures them, HTTP carries requests. Most "mysterious" latency and timeout issues come from round trips (handshakes), connection reuse, and unbounded waits, all of which are predictable from this model.

## Key concepts
- **Layers (practical view):** link/IP (addressing, routing, best-effort packets) -> TCP/UDP (transport) -> TLS (security) -> HTTP/gRPC/WebSocket (application).
- **Latency vs bandwidth:** latency (round-trip time, RTT) is bounded by distance and the speed of light in fiber; bandwidth can be bought. For small requests, latency dominates, so count round trips.
- **DNS:** name to IP, cached at many levels with TTLs. A lookup can add tens to hundreds of ms when uncached. Low TTL helps failover but increases lookups.
- **TCP:** connection-oriented, reliable, ordered byte stream. Three-way handshake costs 1 RTT before data. Congestion control starts small (slow start), so fresh connections are slow to ramp up. Head-of-line blocking: one lost packet stalls everything behind it.
- **UDP:** unordered, unreliable datagrams, no handshake. Used for DNS, real-time media, games, and as the base for QUIC.
- **TLS:** adds handshake round trips (TLS 1.3 needs 1 RTT, with 0-RTT resumption for repeat visitors); see [[cryptography-and-tls]].
- **HTTP/1.1:** one request at a time per connection; browsers open several connections. Keep-alive reuses connections.
- **HTTP/2:** multiplexed streams over one TCP connection, header compression; still suffers TCP head-of-line blocking.
- **HTTP/3:** HTTP over QUIC (UDP); per-stream loss recovery, faster connection setup, connection migration.
- **Ports, sockets:** a connection is identified by (src IP, src port, dst IP, dst port). Ephemeral ports can be exhausted.
- **NAT, load balancers, proxies:** middleboxes with idle timeouts that silently drop long-quiet connections.
- **Timeouts, retries, back-off:** the network may drop, delay or duplicate; every call needs a deadline.

## When to use / scenarios
- Cold-start latency: cost of a new HTTPS connection is DNS + TCP (1 RTT) + TLS (1 RTT on 1.3) + request RTT. Reuse connections and pool them.
- Real-time features: WebSocket or SSE over TCP for chat/notifications (see [[realtime-websockets-sse]]); UDP/QUIC/WebRTC for latency-critical media where a late packet is worthless.
- Many small RPCs between services: HTTP/2 or gRPC multiplexing, keep-alive, connection pools; see [[grpc-and-protobuf]].
- Global users: CDN and edge termination shorten the RTT for TLS and static content; see [[cdn-and-edge]].
- NOT needed: hand-rolled sockets for ordinary CRUD; use mature HTTP clients with sane defaults, but verify those defaults (many have no timeout).

## How it works / example

What happens on `GET https://example.com/` from a cold client:

```
client                                           server
  | -- DNS query (UDP) ----------------------->  resolver     (0..n RTT, cached)
  | -- SYN ------------------------------------>
  | <- SYN/ACK --------------------------------        1 RTT  TCP handshake
  | -- ACK + TLS ClientHello ------------------>
  | <- ServerHello, cert, Finished -------------        1 RTT  TLS 1.3
  | -- HTTP request ---------------------------->
  | <- HTTP response ---------------------------        1 RTT  + server time
```

Roughly 3 RTTs plus DNS before the first byte on a cold connection; a reused connection pays 1 RTT.

Python client with explicit timeouts and connection reuse (stdlib only):

```python fragment
import http.client

conn = http.client.HTTPSConnection("example.com", timeout=3.0)  # connect+read timeout
for path in ("/", "/robots.txt"):
    conn.request("GET", path)                 # same TCP+TLS connection reused
    resp = conn.getresponse()
    body = resp.read()                        # must drain before reusing
    print(path, resp.status, len(body))
conn.close()
```

Minimal TCP echo server showing the socket lifecycle:

```python fragment
import socket

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 9000)); srv.listen()
conn, addr = srv.accept()
with conn:
    while data := conn.recv(4096):            # b"" means peer closed
        conn.sendall(data)
```

Rule of thumb for failures: classify them. Connection refused (nothing listening), timeout (packets dropped or server overloaded), reset (peer or middlebox killed the connection), DNS failure. Each points to a different layer.

## Trade-offs
- **TCP vs UDP/QUIC:** TCP gives reliability and ubiquity for free; UDP gives control (drop stale data, no head-of-line blocking) but you build reliability yourself or adopt QUIC.
- **Long-lived vs short-lived connections:** long-lived amortizes handshakes and avoids slow start but needs keep-alives, health checks and handling of idle drops; short-lived is simple but wasteful.
- **Low DNS TTL vs high:** low TTL enables fast failover and traffic shifts; high TTL reduces latency and load on resolvers.
- **Retry aggressively vs fail fast:** retries mask transient loss but amplify load during outages; need budgets, jitter and idempotency; see [[resilience-patterns]].
- **Chatty vs batched APIs:** fewer, larger requests save RTTs; larger payloads raise head-of-line risk and retry cost.

## Gotchas
- Default timeouts are often infinite (`requests`, many sockets). Always set connect and read timeouts, plus an overall deadline.
- Idle connection killed by a NAT, firewall or load balancer (often a few minutes) then reused: first request fails with reset. Use TCP keep-alive or retry idempotent calls on stale connections.
- Connection pool exhaustion looks like latency: requests queue waiting for a free connection.
- Ephemeral port exhaustion (`TIME_WAIT` pile-up) when opening a new connection per request at high rate.
- Nagle's algorithm and delayed ACK can add tens of milliseconds to small writes; disable Nagle (`TCP_NODELAY`) for latency-sensitive protocols.
- IPv4/IPv6 dual-stack: a broken IPv6 path can add seconds of fallback delay.
- Clock-based cert errors and expired certificates cause outages that look like network failures.
- "It works on localhost": localhost hides latency, MTU and packet loss. Test with injected delay.
- Packet size and MTU: large UDP datagrams fragment or get dropped.

## Related
- [[concurrency-and-parallelism]] - blocking vs non-blocking sockets, connection pools
- [[cryptography-and-tls]] - the handshake costs and certificate pitfalls
- [[load-balancing]] - L4 vs L7 balancing and health checks
- [[cdn-and-edge]] - cutting RTT by terminating near the user
- [[rest-api-design]] - HTTP semantics at the API level
- [[failure-modes-and-fallacies]] - the fallacies of distributed computing start here

## References
- Grigorik, "High Performance Browser Networking": https://hpbn.co/
- RFC 9293 (TCP), RFC 9110 (HTTP semantics), RFC 9114 (HTTP/3)
- Kurose and Ross, "Computer Networking: A Top-Down Approach"
