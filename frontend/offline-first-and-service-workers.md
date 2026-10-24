---
title: Offline-first web apps, service workers and sync
category: frontend
tags: [offline-first, service-worker, pwa, cache-storage, indexeddb, background-sync, outbox, sync, conflict-resolution, local-first]
use_cases:
  - "the web app must keep working on flaky mobile networks or with no connection at all"
  - "queue user edits made offline and sync them later without duplicates or lost updates"
  - "cache the app shell and assets with a service worker so repeat visits load instantly"
  - "users stuck on an old version after deploy because the service worker serves stale files"
  - "two devices edited the same record offline; decide how to merge or surface the conflict"
status: draft
last_verified: 2026-10-24
sources:
  - https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API
  - https://web.dev/articles/service-worker-lifecycle
  - https://web.dev/articles/offline-cookbook
  - https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria
  - https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API
  - https://www.inkandswitch.com/local-first/
---

# Offline-first web apps, service workers and sync

## Summary
An offline-first app treats the network as an enhancement: it renders from
local data, writes changes locally first, and syncs with the server when it
can. In the browser this rests on three pieces: a **service worker** that
intercepts requests and serves the app shell and assets from a cache,
**IndexedDB** for structured local data, and a **sync protocol** that sends
queued changes with idempotency keys and resolves conflicts when two devices
changed the same thing. The hard part is not caching files; it is sync,
conflicts and updating the app itself without stranding users on old code.

## Key concepts
- **Service worker**: a script that runs separately from pages, in a secure
  context only (HTTPS, or localhost for development), and acts as a
  programmable proxy for requests within its scope (`fetch` event). It has no
  DOM access and can be stopped by the browser at any time, so it keeps no
  state in memory between events.
- **Lifecycle**: register, `install` (pre-cache the shell), wait, `activate`
  (delete old caches), then control pages. A new version waits until no page
  uses the old one, unless it calls `skipWaiting()`; `clients.claim()` makes
  it control already open pages.
- **Caching strategies** (offline cookbook): *cache first* for versioned
  static assets; *network first* with cache fallback for HTML and fresh data;
  *stale-while-revalidate* when showing slightly old data instantly is fine;
  *network only* for things that must not be stale (payments, auth).
- **Local storage options**: IndexedDB for structured data and queues (async,
  large, transactional); Cache Storage for request/response pairs;
  `localStorage` only for tiny settings (synchronous, strings, small).
- **Quota and eviction**: browser storage is *best-effort* by default and can
  be evicted under storage pressure; `navigator.storage.persist()` asks for
  persistent storage and `navigator.storage.estimate()` reports usage.
  Treat local data as a cache of the server unless the user was told
  otherwise.
- **Outbox**: user mutations are appended to a durable local queue with a
  client-generated operation ID, applied optimistically to local state, and
  sent in order when online. The ID is an idempotency key, so a resend after
  a lost response is not applied twice ([[idempotency-and-exactly-once]]).
- **Conflict detection**: each mutation carries the version (or per-field
  revision) it was based on; the server rejects or merges when the current
  version moved on. Options: last-writer-wins, field-level merge, keep both
  and ask the user, or CRDTs that merge automatically
  ([[design-collaborative-editor]]).
- **Background Sync API** lets a service worker retry sends after
  connectivity returns even if the page is closed, but it is not available in
  every browser; always also sync on app start and on the `online` event.
- **`navigator.onLine` is a hint**: `true` only means a network interface is
  up, not that your API is reachable. Decide by whether requests succeed.
- **Local-first software** (Ink and Switch): the stronger form, where the
  local copy is primary and the server is a sync and backup peer.

## When to use / scenarios
- Field and mobile users on unreliable networks: inspections, delivery,
  sales, healthcare rounds, note-taking, to-do and email clients.
- Repeat-visit performance for any app: cache-first hashed assets and an app
  shell make second loads near-instant even online ([[web-performance]]).
- Read-mostly content that should remain readable offline: docs, articles,
  saved items.
- When NOT to: flows that are meaningless offline or must be authoritative
  (checkout, stock reservation, bank transfers): show a clear offline state
  instead of queueing. Highly collaborative real-time editing needs CRDT or
  OT sync, not a simple outbox ([[design-collaborative-editor]]). Purely
  server-rendered content sites often only need HTTP caching and a CDN.

## How it works / example

```
 UI ──read──> local store (IndexedDB) <──pull── server
  │                 ^
  └─write─> apply locally + append to outbox ──push (op_id, base_rev)──> server
                                                 lost response? resend same op_id
                                                 base_rev stale?  conflict -> merge or ask
 service worker: /app.3f9a.js  cache first | /index.html network first, cached fallback
```

A minimal sync engine: two devices edit offline, non-overlapping edits merge
by field revision, a resend after a lost response is deduplicated by
operation ID, and a real conflict is surfaced instead of silently lost.

```python
import uuid

class Server:
    def __init__(self):
        self.records, self.applied = {}, {}      # applied: op_id -> response

    def put_initial(self, rid, data):
        self.records[rid] = {f: {"value": v, "rev": 1} for f, v in data.items()}

    def apply(self, op):
        if op["op_id"] in self.applied:          # retry of an applied op
            return self.applied[op["op_id"]]
        rec = self.records[op["rid"]]
        stale = {f: rec[f]["value"] for f in op["changes"]
                 if rec[f]["rev"] != op["base_revs"][f]}
        if stale:
            resp = {"status": "conflict", "server": stale}
        else:
            for f, v in op["changes"].items():
                rec[f] = {"value": v, "rev": rec[f]["rev"] + 1}
            resp = {"status": "ok"}
        self.applied[op["op_id"]] = resp
        return resp

    def snapshot(self, rid):
        return {f: dict(c) for f, c in self.records[rid].items()}

class Client:
    def __init__(self, server, name):
        self.server, self.name, self.online = server, name, True
        self.base, self.local, self.outbox, self.conflicts = {}, {}, [], []
        self.drop_next_response = False

    def pull(self, rid):
        self.base[rid] = self.server.snapshot(rid)
        self.local[rid] = {f: c["value"] for f, c in self.base[rid].items()}
        for op in self.outbox:                   # re-apply unsent local edits
            if op["rid"] == rid:
                self.local[rid].update(op["changes"])

    def edit(self, rid, **changes):
        self.local[rid].update(changes)          # optimistic, works offline
        self.outbox.append({"op_id": str(uuid.uuid4()), "rid": rid,
                            "changes": changes,
                            "base_revs": {f: self.base[rid][f]["rev"]
                                          for f in changes}})

    def sync(self):
        if not self.online:
            return
        while self.outbox:
            op = self.outbox[0]
            resp = self.server.apply(op)
            if self.drop_next_response:          # network drops the reply
                self.drop_next_response = False
                continue                         # resend the same op_id
            if resp["status"] == "conflict":
                self.conflicts.append((op["changes"], resp["server"]))
            self.outbox.pop(0)
        for rid in list(self.local):
            self.pull(rid)

server = Server()
server.put_initial("note-1", {"title": "Groceries", "body": "milk"})
a, b = Client(server, "phone"), Client(server, "laptop")
a.pull("note-1"); b.pull("note-1")

a.online = False                                 # phone goes into a tunnel
a.edit("note-1", title="Groceries (Sat)")
a.sync()                                         # no-op while offline
assert a.local["note-1"]["title"] == "Groceries (Sat)" and len(a.outbox) == 1

b.edit("note-1", body="milk, eggs")
b.sync()

a.online, a.drop_next_response = True, True
a.sync()                                         # sent twice, applied once
assert server.snapshot("note-1")["title"] == {"value": "Groceries (Sat)", "rev": 2}
assert a.local["note-1"] == {"title": "Groceries (Sat)", "body": "milk, eggs"}

b.pull("note-1")                                 # both now at title rev 2
a.online = b.online = False                      # both edit the title offline
a.edit("note-1", title="Shopping")
b.edit("note-1", title="Errands")
b.online = True; b.sync()
a.online = True; a.sync()
assert server.snapshot("note-1")["title"]["value"] == "Errands"
assert a.conflicts == [({"title": "Shopping"}, {"title": "Errands"})]
assert a.local["note-1"]["title"] == "Errands"   # server value shown...
print("conflict to show the user:", a.conflicts[0])  # ...and theirs kept
```

A service worker for the app shell (JavaScript, runs only in a browser):
versioned caches deleted on activate, cache first for hashed assets, network
first for pages with an offline fallback.

```js
const CACHE = "shell-v42";                     // bump on every release
const SHELL = ["/", "/offline.html", "/app.3f9a.js", "/app.91c2.css"];

self.addEventListener("install", (e) =>
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))));

self.addEventListener("activate", (e) =>
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;            // writes go through the outbox
  if (req.mode === "navigate") {               // HTML: network first
    e.respondWith(fetch(req).catch(async () =>
      (await caches.match(req)) || caches.match("/offline.html")));
    return;
  }
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
```

## Trade-offs
- **Online-first with offline fallback vs offline-first**: a cached shell and
  read-only fallback page is cheap and covers most sites; full offline writes
  need an outbox, conflict policy, migrations of local schemas and UI for
  sync state, which is a product decision, not just a technical one.
- **Conflict policy**: last-writer-wins is simple but silently drops one
  user's work; field-level merge handles most form-like data; asking the user
  is correct but adds UI; CRDTs merge automatically but constrain the data
  model and grow metadata ([[consistency-models]]).
- **Operation log vs state sync**: sending operations ("add item") preserves
  intent and merges better; sending whole records is simpler but conflicts
  more and wastes bandwidth.
- **`skipWaiting` immediately vs on user prompt**: activating at once gets
  fixes out fast but can swap code under an open page that still expects old
  assets; prompting ("new version available, reload") is safer for apps with
  long sessions.
- **How much to keep locally**: more data means more offline capability but
  larger storage, slower first sync, eviction risk and more sensitive data on
  devices ([[privacy-and-pii-handling]]).

## Gotchas
- Caching `index.html` cache-first: users never get the new release. Serve
  navigations network first, and serve the service worker script itself with
  `Cache-Control: no-cache`.
- Never deleting old caches: storage fills up and old assets linger; clean up
  in `activate`.
- A broken service worker deployed to production keeps controlling pages;
  keep a kill switch (a no-op worker that unregisters itself) ready to ship.
- Caching authenticated API responses in the service worker: after logout,
  the next user on a shared device can see them. Clear caches and IndexedDB
  on logout.
- Server-generated IDs for records created offline: the client cannot
  reference them until sync. Use client-generated UUIDs or ULIDs
  ([[unique-id-generation]]).
- Replaying the outbox without idempotency keys: a lost response turns into a
  duplicate order or comment.
- Trusting the client's clock for last-writer-wins: device clocks are wrong;
  use server-assigned revisions or logical clocks ([[time-clocks-and-ordering]]).
- Local schema changes without migrations: IndexedDB versions must be
  upgraded in `onupgradeneeded`, and the outbox may hold operations in the
  old shape.
- Relying on Background Sync alone: where it is unsupported, queued edits
  wait until the user happens to reopen the app. Also sync on start, on the
  `online` event and on visibility change.
- Assuming local data is permanent: best-effort storage can be evicted, and
  some browsers clear script-written storage for sites the user has not
  visited recently. Sync promptly and request persistence for apps that need it.

## Related
- [[frontend-state-management]] - server-state caches and optimistic updates that an outbox extends offline.
- [[web-performance]] - HTTP caching and hashed assets that the service worker builds on.
- [[idempotency-and-exactly-once]] - operation IDs that make outbox resends safe.
- [[design-collaborative-editor]] - CRDT and OT sync for concurrent rich editing.
- [[design-file-sync]] - the same sync, conflict and resume problems for whole files.
- [[replication]] - multi-leader replication is what offline clients are, with the same conflict issues.
- [[unique-id-generation]] - client-generated IDs for records created offline.
- [[browser-security-cors-csp-headers]] - secure-context and origin rules that service workers depend on.

## References
- MDN Web Docs, "Service Worker API": https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API
- Jake Archibald, "The service worker lifecycle", web.dev: https://web.dev/articles/service-worker-lifecycle
- Jake Archibald, "The offline cookbook", web.dev: https://web.dev/articles/offline-cookbook
- MDN Web Docs, "Storage quotas and eviction criteria": https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria
- MDN Web Docs, "Background Synchronization API" (browser compatibility): https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API
- Martin Kleppmann, Adam Wiggins, Peter van Hardenberg, Mark McGranaghan, "Local-first software", Ink and Switch, 2019: https://www.inkandswitch.com/local-first/
