---
title: Long-running operations and async request-reply
category: apis
tags: [long-running-operations, async-request-reply, 202-accepted, polling, retry-after, operation-resource, jobs, cancellation]
use_cases:
  - "an API call takes minutes (export, video transcode, report) and times out behind the load balancer"
  - "design a job status endpoint clients can poll without hammering the server"
  - "let clients cancel or retry a long-running request safely"
  - "choose between polling, webhooks and server-sent events for async results"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.rfc-editor.org/rfc/rfc9110
  - https://google.aip.dev/151
  - https://learn.microsoft.com/en-us/azure/architecture/patterns/async-request-reply
  - https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md
---

# Long-running operations and async request-reply

## Summary
When work takes longer than a client, proxy or load balancer will wait, the
API should accept the request, return `202 Accepted` at once with a link to an
operation (job) resource, and let the client poll that resource, or receive a
callback, until the work succeeds or fails. The operation resource is a small
state machine with an ID, status, progress, result or error, and optional
cancellation. Google's AIP-151 and Microsoft's Azure guidelines describe the
same pattern.

## Key concepts
- **202 Accepted** (RFC 9110 section 15.3.3): the request was accepted for processing, which has not completed and may still fail. Return a `Location` (or `Operation-Location`) header pointing at the status resource.
- **Operation resource**: `GET /operations/{id}` returns `status` (`queued`, `running`, `succeeded`, `failed`, `cancelled`), timestamps, optional `progress`, and on completion the `result` or a link to it, or an `error` (see [[error-handling-strategies]]).
- **Retry-After** (RFC 9110 section 10.2.3): tells clients how many seconds to wait before polling again; clients should honour it and back off with jitter otherwise.
- **Idempotent submission**: accept an `Idempotency-Key` header so a retried submit returns the same operation instead of starting the work twice ([[idempotency-and-exactly-once]]).
- **Terminal states are final**: once `succeeded`, `failed` or `cancelled`, the operation never changes again; clients can stop polling.
- **Cancellation**: `POST /operations/{id}:cancel` (AIP-151 style) or `DELETE`; best-effort, the final state may still be `succeeded` if the work finished first.
- **Retention**: keep finished operations for a documented period (for example a few days), then `404` or `410 Gone`.

## When to use / scenarios
- Work regularly exceeds a few seconds: exports, report generation, media processing, bulk imports, provisioning infrastructure, ML batch jobs.
- The request path has timeouts you do not control (gateways, CDNs, mobile networks).
- Not for fast calls: if the p99 latency is well under your timeouts, a synchronous response is simpler.
- Prefer webhooks ([[webhooks]]) or server-sent events when clients can receive callbacks and polling volume would be high; still keep the status endpoint as the source of truth.

## How it works / example
```
Client                         API                    Worker queue
  | POST /exports  ---------->  | enqueue job --------->  |
  | <- 202, Location: /operations/op_1, Retry-After: 2    |
  | GET /operations/op_1 ---->  |  {"status":"running","progress":40}
  | GET /operations/op_1 ---->  |  {"status":"succeeded","result":{"url":...}}
```

An in-memory operation store with idempotent submit, polling and cancellation:

```python
import itertools
import threading
import time

class Operations:
    TERMINAL = {"succeeded", "failed", "cancelled"}

    def __init__(self):
        self.ops, self.by_key, self.lock = {}, {}, threading.Lock()
        self.ids = itertools.count(1)

    def submit(self, work, idempotency_key):
        with self.lock:
            if idempotency_key in self.by_key:  # retried POST: same operation
                return 202, {"Location": f"/operations/{self.by_key[idempotency_key]}", "Retry-After": "1"}
            op_id = f"op_{next(self.ids)}"
            self.ops[op_id] = {"id": op_id, "status": "queued", "progress": 0}
            self.by_key[idempotency_key] = op_id
        threading.Thread(target=self._run, args=(op_id, work), daemon=True).start()
        return 202, {"Location": f"/operations/{op_id}", "Retry-After": "1"}

    def _run(self, op_id, work):
        op = self.ops[op_id]
        try:
            for pct in work():
                with self.lock:
                    if op["status"] == "cancelled":
                        return
                    op.update(status="running", progress=pct)
            with self.lock:
                if op["status"] != "cancelled":
                    op.update(status="succeeded", progress=100, result={"rows": 3})
        except Exception as exc:
            with self.lock:
                op.update(status="failed", error={"type": "about:blank", "title": str(exc)})

    def get(self, op_id):
        with self.lock:
            return dict(self.ops[op_id])

    def cancel(self, op_id):
        with self.lock:
            op = self.ops[op_id]
            if op["status"] not in self.TERMINAL:
                op["status"] = "cancelled"
            return dict(op)

def export():
    for pct in (25, 50, 75):
        time.sleep(0.01)
        yield pct

ops = Operations()
code, headers = ops.submit(export, idempotency_key="k1")
assert code == 202 and ops.submit(export, "k1")[1]["Location"] == headers["Location"]
op_id = headers["Location"].rsplit("/", 1)[1]
while ops.get(op_id)["status"] not in Operations.TERMINAL:  # a client honours Retry-After
    time.sleep(0.01)
print(ops.get(op_id))
assert ops.get(op_id)["status"] == "succeeded"
assert ops.cancel(op_id)["status"] == "succeeded"  # terminal states never change
```

In production the store is a database table and the work runs on a queue
([[message-queues-and-streams]]), so operations survive restarts.

## Trade-offs
- **Polling vs push**: polling is simple and works through any firewall but costs requests and adds latency up to the poll interval; webhooks and SSE are prompt but need delivery, retries and security.
- **Generic `/operations` vs per-resource status**: one generic resource gives clients one polling helper (AIP-151); a per-resource `status` field (e.g. `export.status`) is simpler when there is one kind of job.
- **Result inline vs link**: small results inline save a call; large results belong in object storage behind a signed URL.
- **Retention period**: longer helps slow clients and debugging; shorter limits storage and data exposure.

## Gotchas
- Returning `200` with `"status": "pending"` from the submit call hides the asynchrony; use `202` and a `Location`.
- Without an idempotency key, a client retry after a timeout starts the job twice.
- Clients that ignore `Retry-After` poll in tight loops; rate-limit the status endpoint ([[rate-limiting]]).
- Operations stuck in `running` after a worker crash: use heartbeats or leases and move stale ones to `failed`.
- Authorize the status endpoint: operation IDs are not secrets, so check the caller owns the operation.

## Related
- [[rest-api-design]] - status codes, headers and resource design used here.
- [[webhooks]] - push the result instead of making clients poll.
- [[idempotency-and-exactly-once]] - safe retries of the submit call.
- [[message-queues-and-streams]] - the worker queue behind the operation.
- [[design-job-scheduler]] - running and tracking background jobs at scale.

## References
- RFC 9110 HTTP Semantics (202 Accepted, Retry-After, Location): https://www.rfc-editor.org/rfc/rfc9110
- Google AIP-151, Long-running operations: https://google.aip.dev/151
- Azure Architecture Center, Asynchronous Request-Reply pattern: https://learn.microsoft.com/en-us/azure/architecture/patterns/async-request-reply
- Microsoft Azure REST API Guidelines, long-running operations: https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md
