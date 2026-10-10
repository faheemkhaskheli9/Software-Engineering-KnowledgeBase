---
title: OS processes, threads and I/O models
category: fundamentals
tags: [operating-systems, processes, threads, context-switch, blocking-io, non-blocking-io, epoll, io-multiplexing, event-loop, io-uring]
use_cases:
  - "explain why a thread-per-connection server falls over with many idle clients"
  - "choose between blocking I/O with threads, an event loop, or a process pool"
  - "understand what asyncio, nginx or Node do underneath with select/epoll/kqueue"
  - "debug a worker that hangs because one call blocks the whole event loop"
  - "decide whether a crashing component should run in its own process"
status: draft
last_verified: 2026-10-10
sources:
  - "Operating Systems: Three Easy Pieces, Remzi and Andrea Arpaci-Dusseau - https://pages.cs.wisc.edu/~remzi/OSTEP/"
  - "The Linux Programming Interface, Michael Kerrisk"
  - "UNIX Network Programming Vol. 1, W. Richard Stevens (ch. 6, I/O models)"
  - "epoll(7) man page - https://man7.org/linux/man-pages/man7/epoll.7.html"
  - "io_uring(7) man page - https://man7.org/linux/man-pages/man7/io_uring.7.html"
  - "The C10K problem, Dan Kegel - http://www.kegel.com/c10k.html"
  - "Python selectors docs - https://docs.python.org/3/library/selectors.html"
---

# OS processes, threads and I/O models

## Summary
A process is an isolated address space with its own resources; a thread is a schedulable flow of execution inside a process that shares its memory. How a program waits for I/O (blocking, non-blocking, multiplexed with select/epoll/kqueue, or completion-based like io_uring and IOCP) decides how many concurrent connections it can hold per core. Event loops such as asyncio, Node and nginx are a readiness-multiplexing loop around non-blocking sockets.

## Key concepts
- **Process:** own virtual address space, file descriptor table, credentials. Created with `fork`/`exec` (Unix) or `CreateProcess` (Windows). A crash or memory corruption stays inside it.
- **Thread:** shares the process's memory and file descriptors; has its own stack and registers. Cheaper to create and switch than a process, but every shared object needs synchronization ([[concurrency-and-parallelism]]).
- **Kernel vs user threads:** OS threads are scheduled by the kernel and can run in parallel; green threads, coroutines and goroutines are scheduled in user space, multiplexed onto fewer OS threads.
- **Context switch:** the kernel saves one thread's registers and loads another's; switching processes also changes the address-space mapping, which disturbs the TLB and caches ([[cpu-caches-and-memory-hierarchy]]).
- **Scheduler states:** running, runnable (waiting for a CPU), blocked (waiting for I/O, a lock, a timer). A blocked thread costs memory (its stack), not CPU.
- **System call:** a controlled transition into the kernel (`read`, `write`, `accept`). Each one has a fixed overhead, so batching matters.
- **File descriptor:** an integer handle to a kernel object (file, socket, pipe). Per-process limits apply (`ulimit -n`).
- **The five Unix I/O models (Stevens):**
  1. *Blocking:* `read` sleeps until data arrives. Simple; one thread per in-flight operation.
  2. *Non-blocking:* `read` returns `EAGAIN`/`EWOULDBLOCK` immediately when no data; you must retry.
  3. *I/O multiplexing:* `select`/`poll`/`epoll` (Linux)/`kqueue` (BSD, macOS) block on many descriptors and report which are *ready*.
  4. *Signal-driven:* the kernel signals when a descriptor is ready; rarely used.
  5. *Asynchronous (completion):* submit the operation, get notified when it *completed* (POSIX AIO, Linux io_uring, Windows IOCP).
- **Readiness vs completion:** epoll says "you may now read without blocking"; io_uring/IOCP say "the read you asked for is done, here is the data".
- **Level- vs edge-triggered:** level-triggered keeps reporting a ready descriptor until drained; edge-triggered reports only the transition, so you must read until `EAGAIN` or you lose wake-ups.
- **Regular files are always "ready":** epoll does not help with disk files; runtimes use a thread pool for file I/O (libuv, asyncio's `to_thread`) or io_uring.

## When to use / scenarios

| Situation | Model |
|---|---|
| A handful of concurrent blocking calls, simple code | blocking I/O + thread pool |
| Many mostly idle connections (websockets, long polling, proxies) | non-blocking sockets + epoll/kqueue event loop (asyncio, Node, nginx) |
| CPU-heavy work, or untrusted / crash-prone code | separate processes (isolation and parallelism) |
| Very high-rate disk or network I/O on modern Linux | io_uring (check kernel version and your runtime's support) |
| Pre-fork web servers (gunicorn, PHP-FPM) | process pool: one crash or leak kills one worker |

- Do NOT write your own epoll loop for application code; use the runtime (asyncio, libuv, Netty, Tokio). The example below exists to show the mechanism.
- Thread-per-connection is fine when connection counts are bounded and modest; the C10K problem is about unbounded counts of mostly idle clients.

## How it works / example

Blocking vs multiplexed server shapes:

```
Thread per connection                 Event loop (readiness)
  accept() -> spawn thread             loop:
  thread: read() blocks                  ready = epoll_wait(all_fds)
          handle, write()                for fd in ready: non-blocking read/write
  N connections = N stacks             N connections = N small state objects, 1 thread
```

A minimal readiness loop with the stdlib `selectors` module (picks epoll/kqueue/select for the platform). It echoes over a local socket pair so it finishes on its own:

```python
import selectors
import socket

sel = selectors.DefaultSelector()          # epoll on Linux, kqueue on macOS, select on Windows
server_side, client_side = socket.socketpair()
server_side.setblocking(False)

def on_readable(conn):
    data = conn.recv(1024)                 # will not block: selector said it is ready
    if data:
        conn.sendall(data.upper())

sel.register(server_side, selectors.EVENT_READ, on_readable)

client_side.sendall(b"hello")
for key, _ in sel.select(timeout=1):       # wait for readiness on all registered fds
    key.data(key.fileobj)                  # dispatch to the handler

print(client_side.recv(1024))              # b'HELLO'
sel.close(); server_side.close(); client_side.close()
```

Non-blocking read semantics: an empty non-blocking socket raises instead of sleeping.

```python
import socket

a, b = socket.socketpair()
a.setblocking(False)
try:
    a.recv(1024)
except BlockingIOError as e:               # EAGAIN / EWOULDBLOCK
    print("no data yet:", type(e).__name__)
a.close(); b.close()
```

Process isolation: a crash in a child process does not take the parent down.

```python
import subprocess
import sys

r = subprocess.run([sys.executable, "-c", "import os; os._exit(3)"])
print("child exit code:", r.returncode, "- parent still running")
```

## Trade-offs
- **Threads vs event loop:** threads let you write straight-line blocking code and use any library; each costs a stack and scheduler work. An event loop holds many connections cheaply but any blocking call stalls all of them, and code must be written in callback or async style.
- **Processes vs threads:** processes isolate faults and (in CPython) sidestep the GIL; they cost more memory and need IPC with serialization.
- **Readiness (epoll) vs completion (io_uring/IOCP):** readiness is portable across Unixes and well understood; completion avoids extra syscalls and works for files, but is platform-specific and newer.
- **Level vs edge triggered:** level is forgiving; edge saves wake-ups but punishes any handler that does not drain the descriptor.
- **Pre-fork vs threaded workers:** pre-fork gives isolation and simple memory accounting; threads share caches and connection pools.

## Gotchas
- `select` has a descriptor limit (`FD_SETSIZE`) and scans all descriptors each call; that is why `poll`, `epoll` and `kqueue` exist.
- Forgetting `setblocking(False)` on a socket registered with a selector: one slow peer blocks the loop.
- DNS resolution with `getaddrinfo` is blocking; async runtimes run it in a thread pool, and a small pool becomes a hidden bottleneck.
- Disk reads look non-blocking to epoll but still block; use a thread pool or io_uring.
- `fork` in a multithreaded process copies only the calling thread; locks held by other threads stay locked in the child. Prefer `spawn` or fork before starting threads.
- Running out of file descriptors shows up as `EMFILE` on `accept`; raise the limit and close idle connections.
- Edge-triggered handlers that read once instead of until `EAGAIN` lose events silently.
- Thread stacks reserve virtual memory; thousands of threads can exhaust address space or memory limits in containers.

## Related
- [[concurrency-and-parallelism]] - choosing threads, processes or async at the language level
- [[networking-fundamentals]] - sockets, TCP and connection behavior the I/O models sit on
- [[cpu-caches-and-memory-hierarchy]] - why context switches and cross-core sharing are expensive
- [[memory-and-performance]] - profiling whether time is spent waiting or computing
- [[realtime-websockets-sse]] - the workload that most needs an event-loop server

## References
- Arpaci-Dusseau, "Operating Systems: Three Easy Pieces" (processes, threads, scheduling, concurrency)
- Kerrisk, "The Linux Programming Interface" (fork/exec, epoll, file descriptors)
- Stevens, "UNIX Network Programming", Vol. 1, ch. 6 (the five I/O models)
- epoll(7), io_uring(7) Linux man pages
- Kegel, "The C10K problem"
- Python docs: selectors, socket, subprocess
