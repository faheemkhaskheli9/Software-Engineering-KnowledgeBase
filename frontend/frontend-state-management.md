---
title: Frontend state management (server state, client state, URL state)
category: frontend
tags: [state-management, server-state, client-state, url-state, redux, flux, reducer, normalized-state, query-cache, optimistic-update, stale-while-revalidate, derived-state]
use_cases:
  - "decide where each piece of UI state should live: component, context, global store, URL or server cache"
  - "the same API data is fetched by several components and shows different values on one screen"
  - "a global store has grown into a copy of the backend database and every change re-renders the page"
  - "make a like or edit button feel instant and roll back if the server rejects it"
  - "filters and pagination are lost on reload or when a link is shared"
status: draft
last_verified: 2026-10-24
sources:
  - https://react.dev/learn/managing-state
  - https://react.dev/learn/choosing-the-state-structure
  - https://redux.js.org/understanding/thinking-in-redux/three-principles
  - https://redux.js.org/usage/structuring-reducers/normalizing-state-shape
  - https://tanstack.com/query/latest/docs/framework/react/overview
  - https://www.rfc-editor.org/rfc/rfc5861
  - https://developer.mozilla.org/en-US/docs/Web/API/History_API
---

# Frontend state management (server state, client state, URL state)

## Summary
UI state is not one thing. Most of what a web app "stores" is a cached copy of
data the server owns (server state); the rest is genuinely local, such as an
open dropdown or a half-typed form (client state), or it belongs in the address
bar so reloads and shared links keep it (URL state). Pick the owner for each
piece first: keep local state next to the component that uses it, put
navigational state in the URL, manage server data with a query cache that
handles fetching, deduplication, staleness and invalidation, and reserve a
global store for the small amount of client state that many distant
components really share. Derive everything else instead of storing it.

## Key concepts
- **Server state**: data the backend owns (users, orders, feeds). The client
  holds a possibly stale cache; it needs fetching, caching, deduplication,
  background refresh, invalidation after writes and error/loading states.
  Libraries such as TanStack Query, SWR, RTK Query and Apollo Client do this.
- **Client (UI) state**: owned by the browser session only: modal open, selected
  tab, form drafts, theme. Usually local component state; lift it to the
  nearest common parent only when siblings need it.
- **URL state**: filters, sort, page, selected item, search term. Store it in
  the path or query string (History API) so back/forward, reload, bookmarks and
  shared links work.
- **Single source of truth**: each fact has exactly one owner; everything else
  reads or derives from it. Two copies of the same fact drift.
- **Derived state**: values computable from other state (filtered list, totals,
  "is form valid") should be computed, optionally memoized, not stored.
- **Unidirectional data flow (Flux/Redux)**: the view dispatches actions, a pure
  reducer computes the next state, subscribers re-render. Changes are
  traceable and replayable; the cost is ceremony.
- **Immutability**: produce a new object on change so cheap reference
  comparison detects what changed and history (undo, time travel) is free.
- **Normalized state**: store entities once by id (`{byId, allIds}`) and refer to
  them by id, like database tables, so an update lands in one place.
- **Stale-while-revalidate**: show cached data immediately, refetch in the
  background, swap in the fresh result (the HTTP form is RFC 5861; query caches
  apply the same idea in memory with a `staleTime`).
- **Optimistic update**: apply the expected result locally before the server
  confirms, keep a snapshot, and roll back on error.
- **Selectors and subscriptions**: components subscribe to the slice they read,
  so unrelated changes do not re-render them.

## When to use / scenarios
- Data that came from an API: a query cache keyed by request (`["orders",
  {status, page}]`), with invalidation after mutations. Do not copy it into a
  global store by hand.
- Several distant components share client-only state (current user session
  flags, a shopping cart before checkout, a multi-step wizard, an editor
  document): a small global store or context.
- Complex local transitions with many events (editors, drag and drop, wizards):
  a reducer or an explicit state machine, often still local to one subtree.
- Anything the user would expect to survive reload or to share: URL.
- When NOT to add a global store: the app is mostly forms and API data; a query
  cache plus local state and the URL covers it. Context is for rarely changing
  values (theme, locale, auth); putting fast-changing values in one context
  re-renders every consumer.
- Mostly-static content sites: server rendering with little client state
  ([[rendering-strategies-csr-ssr-ssg]]).

## How it works / example
Where state lives:

```
            +--------------------- browser ----------------------+
 URL  --->  | route params, ?filter=open&page=2                  |
            |                                                    |
 server --> | query cache  key -> {data, fetchedAt, status}      |  <- fetch, dedupe,
  (API)     |   ["orders", {status:"open"}] -> [...ids]          |     revalidate,
            |   normalized entities  order:42 -> {...}           |     invalidate
            |                                                    |
            | global store (small): cart, session flags          |
            | component state: open menus, input drafts          |
            | derived: filtered/sorted lists, totals (computed)  |
            +----------------------------------------------------+
```

A framework-free model of the three core mechanisms: a reducer store with
selective subscriptions, a query cache with deduplication and
stale-while-revalidate, and an optimistic update with rollback.

```python
import copy

# 1. Reducer store: state changes only through pure reducers; subscribers
#    are notified only when the slice they select changes.
def reducer(state, action):
    if action["type"] == "cart/add":
        items = dict(state["cart"])
        items[action["sku"]] = items.get(action["sku"], 0) + action["qty"]
        return {**state, "cart": items}
    if action["type"] == "ui/toggleMenu":
        return {**state, "menu_open": not state["menu_open"]}
    return state

class Store:
    def __init__(self, reducer, state):
        self.reducer, self.state, self.subs = reducer, state, []
        self.history = [state]                       # immutable snapshots: undo for free

    def subscribe(self, selector, callback):
        self.subs.append([selector, selector(self.state), callback])

    def dispatch(self, action):
        self.state = self.reducer(self.state, action)
        self.history.append(self.state)
        for sub in self.subs:
            selected = sub[0](self.state)
            if selected is not sub[1]:               # reference check, enabled by immutability
                sub[1] = selected
                sub[2](selected)

renders = []
store = Store(reducer, {"cart": {}, "menu_open": False})
store.subscribe(lambda s: s["cart"], lambda cart: renders.append(("CartBadge", sum(cart.values()))))
store.dispatch({"type": "ui/toggleMenu"})            # CartBadge does not re-render
store.dispatch({"type": "cart/add", "sku": "A1", "qty": 2})
assert renders == [("CartBadge", 2)]
assert store.history[0]["cart"] == {}                # old snapshot untouched

# Derived state is computed, not stored.
def cart_total(state, prices):
    return sum(prices[sku] * qty for sku, qty in state["cart"].items())
assert cart_total(store.state, {"A1": 500}) == 1000

# 2. Query cache: one entry per key, in-flight dedupe, stale-while-revalidate.
class FakeClock:
    def __init__(self):
        self.now = 0.0

class QueryCache:
    def __init__(self, clock, stale_time):
        self.clock, self.stale_time, self.entries = clock, stale_time, {}
        self.calls = 0

    def get(self, key, fetcher):
        """Return (data, is_stale); refetch at most once per stale period."""
        entry = self.entries.get(key)
        fresh = entry and self.clock.now - entry["fetched_at"] < self.stale_time
        if entry and fresh:
            return entry["data"], False
        if entry and entry.get("refetching"):
            return entry["data"], True               # dedupe: a refetch is already running
        if entry:
            entry["refetching"] = True               # serve stale now, revalidate in background
            return entry["data"], True
        self.calls += 1
        self.entries[key] = {"data": fetcher(), "fetched_at": self.clock.now}
        return self.entries[key]["data"], False

    def complete_refetch(self, key, fetcher):
        self.calls += 1
        self.entries[key] = {"data": fetcher(), "fetched_at": self.clock.now}

    def invalidate(self, prefix):
        for key in list(self.entries):
            if key[0] == prefix:
                self.entries[key]["fetched_at"] = float("-inf")

server = {"order:42": {"id": 42, "status": "open", "likes": 3}}
fetch_order = lambda: copy.deepcopy(server["order:42"])
clock = FakeClock()
cache = QueryCache(clock, stale_time=30)
key = ("order", 42)

header, _ = cache.get(key, fetch_order)              # two components, one request
sidebar, _ = cache.get(key, fetch_order)
assert cache.calls == 1 and header is sidebar        # one copy: both show the same value

clock.now = 31
server["order:42"]["status"] = "shipped"
data, stale = cache.get(key, fetch_order)
assert stale and data["status"] == "open"            # instant render from cache
cache.get(key, fetch_order)                          # second reader does not refetch
cache.complete_refetch(key, fetch_order)
assert cache.get(key, fetch_order)[0]["status"] == "shipped" and cache.calls == 2

# 3. Optimistic update with rollback.
def like(cache, key, send):
    entry = cache.entries[key]
    snapshot = copy.deepcopy(entry["data"])
    entry["data"]["likes"] += 1                      # UI shows the new count immediately
    try:
        send()
    except ConnectionError:
        entry["data"] = snapshot                     # server rejected: restore exactly
        return False
    cache.invalidate("order")                        # then refetch the truth
    return True

def failing_send():
    raise ConnectionError("503")

assert like(cache, key, failing_send) is False
assert cache.entries[key]["data"]["likes"] == 3
assert like(cache, key, lambda: None) is True
assert cache.get(key, fetch_order)[1] is True        # invalidated: next read revalidates
print("ok")
```

Keeping filters in the URL (browser side, shown for shape only):

```js
const params = new URLSearchParams(location.search);
params.set("status", "open");
params.set("page", "2");
history.pushState(null, "", `?${params}`);   // back button and shared links keep the filter
```

## Trade-offs
- **Query cache vs global store for API data**: a query cache gives caching,
  dedupe, retries and invalidation for free but is organised by request, so
  the same entity can sit under several keys; a normalized store keeps one
  copy per entity but you write the fetching and invalidation logic yourself.
  GraphQL clients with normalized caches sit in between ([[graphql]]).
- **Centralized store vs local state**: a store makes changes traceable and
  debuggable across the app; local state is simpler, colocated and easier to
  delete. Start local, lift when two places need it, centralize when many do.
- **Optimistic vs pessimistic updates**: optimistic feels instant but needs
  rollback, conflict handling and honest error messages; use pessimistic
  (spinner until confirmed) for payments, irreversible or high-conflict actions.
- **Short vs long `staleTime`**: short means fresher data and more requests;
  long means fewer requests and more chance of showing outdated values. Pair a
  long one with invalidation after your own writes and live updates for
  others' writes ([[choosing-realtime-updates]]).
- **URL vs memory for view state**: URL state is shareable and survives reload
  but is public, size-limited and must be validated like any input.

## Gotchas
- Copying server data into a global store "to share it", then forgetting to
  update it after a mutation: two components show different values.
- Storing derived values (filtered list, totals, `isValid`) alongside their
  inputs; they drift on the next change. Compute them.
- Mutating state in place: reference checks see no change and the UI does not
  update, or memoized selectors return stale results.
- A new object or array literal in a selector every call defeats memoization
  and re-renders on every change.
- One big context holding fast-changing values re-renders every consumer;
  split contexts or use a store with selectors.
- Optimistic updates without a snapshot cannot roll back correctly; with
  concurrent mutations, roll back only your own change, then refetch.
- Out-of-order responses: a slow response for an old filter overwrites the
  newer one. Key requests by their parameters and ignore or cancel stale ones
  (`AbortController`).
- Hydration mismatch: state read from `localStorage` or the clock on the client
  differs from what the server rendered ([[rendering-strategies-csr-ssr-ssg]]).
- Persisting tokens or personal data to `localStorage` exposes them to any XSS
  ([[browser-security-cors-csp-headers]]).
- Keeping user-visible filters only in memory: reload and shared links lose
  them.

## Related
- [[rendering-strategies-csr-ssr-ssg]] - where state is first produced, serialized and hydrated.
- [[caching-strategies]] - TTL, invalidation and stale-while-revalidate on the server side.
- [[choosing-realtime-updates]] - pushing other users' changes into the client cache.
- [[state-machines]] - explicit states and transitions for complex UI flows.
- [[graphql]] - normalized client caches keyed by type and id.
- [[web-performance]] - re-render cost and bundle size of state libraries.
- [[idempotency-and-exactly-once]] - retried mutations from optimistic UIs must be safe to repeat.
- [[offline-first-and-service-workers]] - outbox, sync and conflict handling when edits are made offline.

## References
- React documentation, "Managing State" and "Choosing the State Structure" (react.dev).
- Redux documentation, "Three Principles" and "Normalizing State Shape" (redux.js.org).
- TanStack Query documentation, "Overview" (server state vs client state, stale time, invalidation).
- RFC 5861, *HTTP Cache-Control Extensions for Stale Content* (stale-while-revalidate).
- MDN Web Docs, History API.
