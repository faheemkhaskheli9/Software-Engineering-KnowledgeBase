---
title: Concurrency and parallelism
category: fundamentals
tags: [concurrency, parallelism, threads, asyncio, locks, race-condition, deadlock, gil, multiprocessing]
use_cases:
  - "make a service handle thousands of slow network calls without a thread per request"
  - "speed up a CPU-heavy batch job across cores in Python"
  - "track down an intermittent bug where a counter or balance is occasionally wrong under load"
  - "decide between threads, processes and async for a new component"
  - "avoid deadlocks when two jobs need the same pair of resources"
status: stable
last_verified: 2026-10-10
sources:
  - "https://docs.python.org/3/library/concurrent.futures.html"
  - "https://docs.python.org/3/library/asyncio.html"
  - "https://docs.python.org/3/howto/free-threading-python.html"
  - "Java Concurrency in Practice, Brian Goetz et al."
  - "The Art of Multiprocessor Programming, Herlihy and Shavit"
---

# Concurrency and parallelism

## Summary
Concurrency is structuring a program as independently progressing tasks (dealing with many things at once); parallelism is executing tasks literally simultaneously on multiple cores. Pick the model by the bottleneck: I/O-bound work wants async or threads, CPU-bound work wants processes or native code. Most concurrency bugs come from shared mutable state; the best fix is usually not sharing it.

## Key concepts
- **Concurrency vs parallelism:** a single core can be concurrent (interleaving) but not parallel.
- **I/O-bound vs CPU-bound:** I/O-bound tasks spend time waiting (network, disk, DB); CPU-bound tasks burn cycles. This one distinction decides the tool.
- **Threads:** share memory, preemptively scheduled by the OS. Cheap-ish, but need synchronization. In CPython the GIL lets only one thread run Python bytecode at a time, so threads help I/O-bound work but not CPU-bound. Check the free-threaded build status of your interpreter before assuming either.
- **Processes:** separate memory, true parallelism, communicate via pipes, queues or shared memory. Higher startup and serialization cost.
- **Async / event loop (`asyncio`):** one thread, cooperative multitasking; tasks yield at `await`. Scales to very many idle connections; one blocking call stalls everything.
- **Race condition:** result depends on interleaving. Check-then-act and read-modify-write on shared state are the classic shapes.
- **Mutual exclusion:** locks, semaphores. Keep critical sections tiny.
- **Deadlock:** circular wait. Prevent by a global lock-ordering, timeouts, or avoiding nested locks.
- **Livelock / starvation:** progress without completion; a task never gets the resource.
- **Memory visibility / atomicity:** without synchronization, one thread may not see another's writes (language memory model). `x += 1` is not atomic.
- **Message passing / actor / CSP:** share nothing, communicate through queues. Easier to reason about than locks.
- **Immutability:** immutable data needs no locks.

## When to use / scenarios

| Workload | Reach for |
|---|---|
| Thousands of concurrent network calls (HTTP clients, websockets) | `asyncio` |
| A few dozen blocking I/O calls, legacy blocking libraries | `ThreadPoolExecutor` |
| CPU-heavy pure-Python (parsing, image work, simulations) | `ProcessPoolExecutor`, or native/numpy that releases the GIL |
| Pipeline stages with back-pressure | `queue.Queue` / `asyncio.Queue` with bounded size |
| Cross-machine parallelism | a task queue or batch framework; see [[message-queues-and-streams]] |

- Do NOT add concurrency to code that is fast enough; it multiplies bug surface. Profile first ([[memory-and-performance]]).
- For distributed state shared between services, locks in one process are meaningless; see [[distributed-transactions-and-sagas]] and [[idempotency-and-exactly-once]].

## How it works / example

Race condition and fix:

```python
import threading

counter = 0
lock = threading.Lock()

def unsafe(n):
    global counter
    for _ in range(n):
        counter += 1              # read, add, write: interleaving loses updates

def safe(n):
    global counter
    for _ in range(n):
        with lock:                # critical section
            counter += 1
```

Async fan-out with a concurrency limit:

```python
import asyncio

async def fetch(i, sem):
    async with sem:                      # bound concurrency
        await asyncio.sleep(0.1)         # stands in for a network call
        return i * 2

async def main():
    sem = asyncio.Semaphore(100)
    results = await asyncio.gather(*(fetch(i, sem) for i in range(1000)))
    print(len(results))

asyncio.run(main())
```

CPU-bound with processes:

```python
from concurrent.futures import ProcessPoolExecutor

def heavy(n):
    return sum(i * i for i in range(n))

if __name__ == "__main__":              # required on Windows/macOS (spawn)
    with ProcessPoolExecutor() as pool:
        print(list(pool.map(heavy, [10**6] * 8)))
```

Deadlock shape and the fix (consistent ordering):

```
Thread A: lock(account1) -> lock(account2)
Thread B: lock(account2) -> lock(account1)      # circular wait

Fix: always lock in a global order, e.g. sorted by account id
     for acct in sorted([a, b], key=lambda x: x.id): acct.lock.acquire()
```

Producer/consumer with bounded queue (back-pressure):

```
producers --> [ Queue(maxsize=100) ] --> consumers
              full => producers block (or shed load)
```

## Trade-offs
- **Threads vs async:** threads work with blocking libraries and are simpler to adopt; async scales further per node and makes yield points explicit, but "colors" the codebase (async all the way) and punishes any blocking call.
- **Processes vs threads:** processes give parallelism and isolation (a crash does not kill siblings) at the cost of memory and pickling overhead for arguments and results.
- **Locks vs message passing:** locks are fine-grained and fast when used right; queues or actors serialize access and are easier to verify but may add latency.
- **Coarse vs fine-grained locking:** a coarse lock is easy and safe but caps throughput; fine-grained improves it and invites deadlocks.
- **Optimistic vs pessimistic:** compare-and-swap or version checks (retry on conflict) beat locking under low contention; locks win under high contention.

## Gotchas
- `asyncio` + a blocking call (`requests.get`, `time.sleep`, heavy CPU) freezes the whole loop. Use `await loop.run_in_executor(...)` or an async client.
- Forgetting to bound concurrency: `gather` on 100k tasks opens 100k sockets. Use a semaphore.
- Fire-and-forget tasks: an unreferenced `asyncio.create_task` can be garbage collected and its exceptions lost; keep references and handle errors.
- Exceptions in thread/process pools are swallowed until you read the future's result.
- Check-then-act (`if not exists: create`) races across threads and, more importantly, across processes and hosts; use a DB uniqueness constraint or atomic operation.
- Unbounded queues turn overload into memory exhaustion rather than back-pressure.
- Shared mutable defaults and module-level caches are hidden shared state.
- Testing: concurrency bugs are probabilistic. Use stress loops, thread sanitizers where available, and design so correctness does not depend on timing.
- Time-based "fixes" (`sleep(1)` to wait for the other task) are bugs deferred.

## Related
- [[memory-and-performance]] - profile whether you are I/O- or CPU-bound before parallelizing
- [[networking-fundamentals]] - sockets, blocking vs non-blocking I/O, connection pools
- [[message-queues-and-streams]] - the distributed version of producer/consumer
- [[idempotency-and-exactly-once]] - retries in concurrent/distributed settings
- [[transactions-and-isolation-levels]] - database-level answers to the same race conditions
- [[resilience-patterns]] - bulkheads, timeouts and bounded pools

## References
- Python docs: concurrent.futures, asyncio, threading, multiprocessing; free-threading HOWTO
- Goetz et al., "Java Concurrency in Practice"
- Herlihy and Shavit, "The Art of Multiprocessor Programming"
