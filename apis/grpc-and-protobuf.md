---
title: gRPC and Protocol Buffers
category: apis
tags: [grpc, protobuf, rpc, http2, streaming, microservices, schema, buf]
use_cases:
  - "define typed service-to-service APIs with generated clients in several languages"
  - "stream data between services with low latency over HTTP/2"
  - "evolve a message schema without breaking old producers and consumers"
  - "decide between gRPC and REST for internal microservice calls"
status: draft
last_verified: 2026-10-10
sources:
  - https://grpc.io/docs/
  - https://protobuf.dev/programming-guides/proto3/
  - https://protobuf.dev/best-practices/dos-donts/
  - https://buf.build/docs/
  - https://grpc.io/docs/guides/deadlines/
---

# gRPC and Protocol Buffers

## Summary
Protocol Buffers (protobuf) is a compact, schema-first binary serialisation format with generated code; gRPC is an RPC framework that uses protobuf over HTTP/2 to give typed unary and streaming calls across languages. It suits internal service-to-service communication where contracts, performance and streaming matter more than browser-friendliness.

## Key concepts
- **`.proto` file**: the single source of truth for messages and services; compiled by `protoc` or `buf` into client/server stubs.
- **Field numbers**: wire identity of a field. Names can change, numbers never. Never reuse a number; mark removed ones `reserved`.
- **Four call types**: unary, server streaming, client streaming, bidirectional streaming.
- **HTTP/2**: multiplexed streams over one connection, header compression, flow control.
- **Deadlines**: the client sets how long it will wait; deadlines propagate to downstream calls so work is cancelled when no one is waiting.
- **Status codes**: gRPC has its own (OK, INVALID_ARGUMENT, NOT_FOUND, ALREADY_EXISTS, PERMISSION_DENIED, UNAUTHENTICATED, RESOURCE_EXHAUSTED, FAILED_PRECONDITION, UNAVAILABLE, DEADLINE_EXCEEDED, INTERNAL ...). Rich error details via `google.rpc.Status`.
- **Metadata**: headers/trailers for auth tokens, trace ids.
- **Interceptors**: middleware for auth, logging, retries, metrics.
- **grpc-web / Connect / gRPC-Gateway**: bridges for browsers and JSON/HTTP clients.

## When to use / scenarios
- Internal microservices with many languages and a need for strict contracts and fast, small payloads (see [[monolith-vs-microservices]]).
- Streaming: telemetry ingestion, chat/presence, long-lived feeds, large transfers in chunks.
- Polyglot teams wanting generated, versioned SDKs from one schema.
- Use REST/JSON instead for public APIs, browser-first clients, and where HTTP caching and human debuggability matter (see [[rest-api-design]]).
- Use GraphQL when client-driven field selection is the main requirement (see [[graphql]]).
- Do NOT expose raw gRPC to browsers without grpc-web/Connect; load balancers must understand HTTP/2 (see [[load-balancing]]).

## How it works / example
Schema:
```proto
syntax = "proto3";
package shop.v1;

service OrderService {
  rpc GetOrder(GetOrderRequest) returns (Order);
  rpc WatchOrders(WatchOrdersRequest) returns (stream Order);   // server streaming
}

message GetOrderRequest { int64 id = 1; }
message WatchOrdersRequest { int64 customer_id = 1; }

message Order {
  int64 id = 1;
  int64 customer_id = 2;
  Status status = 3;
  repeated Item items = 4;
  reserved 5, 6;                 // removed fields: never reuse the numbers
  reserved "legacy_note";
  enum Status { STATUS_UNSPECIFIED = 0; OPEN = 1; PAID = 2; SHIPPED = 3; }
}
message Item { string sku = 1; int32 qty = 2; int64 unit_price_cents = 3; }
```

Python server and client (`grpcio`, generated `order_pb2*`):
```python fragment
import grpc
from concurrent import futures
import order_pb2, order_pb2_grpc

class Orders(order_pb2_grpc.OrderServiceServicer):
    def GetOrder(self, request, context):
        if request.id <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "id must be positive")
        return order_pb2.Order(id=request.id, status=order_pb2.Order.OPEN)

server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
order_pb2_grpc.add_OrderServiceServicer_to_server(Orders(), server)
server.add_insecure_port("[::]:50051")      # use TLS credentials in production
server.start(); server.wait_for_termination()

# client: always set a deadline
with grpc.insecure_channel("localhost:50051") as ch:
    stub = order_pb2_grpc.OrderServiceStub(ch)
    try:
        print(stub.GetOrder(order_pb2.GetOrderRequest(id=7), timeout=0.5))
    except grpc.RpcError as e:
        print(e.code(), e.details())
```

Schema evolution rules (wire compatible):
- Safe: add new fields with new numbers; add new RPCs; add enum values (consumers must tolerate unknown values).
- Unsafe: change a field's type or number, reuse numbers, rename an enum value if JSON mapping is used, change `repeated` to singular.
- Enforce with `buf breaking --against '.git#branch=main'` in CI (see [[ci-cd-pipelines]]).

## Trade-offs
- **Performance vs debuggability**: binary is compact and fast but cannot be `curl`ed; use `grpcurl`, reflection, or Connect for JSON.
- **Strong contracts vs coupling**: shared schemas catch errors at compile time but couple teams to a schema repository and release process.
- **Streaming power vs complexity**: streams need backpressure, reconnection and resumption logic.
- **gRPC vs REST for public APIs**: ecosystem, caches, API gateways and browsers favour REST.
- **Proto3 optional/presence**: default zero values cannot distinguish "unset" from 0 unless you use `optional` or wrapper types.
- **Client-side vs proxy load balancing**: long-lived HTTP/2 connections defeat L4 balancers; use L7, headless service plus client-side balancing, or a mesh (see [[api-gateway-and-service-mesh]]).

## Gotchas
- No deadline means a stuck downstream holds resources forever; set deadlines on every client call and propagate the remaining budget.
- Retrying non-idempotent RPCs on `UNAVAILABLE` can duplicate effects; add idempotency keys (see [[idempotency-and-exactly-once]]) and use retry policies only for safe methods.
- Large messages: default max is 4 MB receive; stream chunks instead of raising limits.
- Reusing or renumbering fields silently corrupts data between versions.
- Enum zero value must be a meaningful `UNSPECIFIED`; otherwise missing data looks like a real state.
- Using one giant shared `common.proto` creates a dependency tangle; version packages (`shop.v1`) and keep ownership clear.
- Timestamps: use `google.protobuf.Timestamp`; money as integer minor units, not `double`.
- Health checking and graceful shutdown (drain streams) must be implemented explicitly for Kubernetes rollouts (see [[kubernetes-basics]]).

## Related
- [[rest-api-design]] - the common alternative, especially for public APIs
- [[graphql]] - another typed API option with a different strengths profile
- [[api-versioning-and-evolution]] - schema evolution principles apply to protobuf
- [[api-gateway-and-service-mesh]] - routing, mTLS and load balancing for gRPC traffic
- [[resilience-patterns]] - deadlines, retries and circuit breakers on RPC calls
- [[schema-evolution-and-serialization]] - backward/forward compatibility rules and how Protobuf compares with Avro and JSON

## References
- gRPC documentation: https://grpc.io/docs/
- Protobuf language guide (proto3): https://protobuf.dev/programming-guides/proto3/
- Protobuf do's and don'ts: https://protobuf.dev/best-practices/dos-donts/
- Buf documentation (lint, breaking change detection): https://buf.build/docs/
- gRPC deadlines guide: https://grpc.io/docs/guides/deadlines/
