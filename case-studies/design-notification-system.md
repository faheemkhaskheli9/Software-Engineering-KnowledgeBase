---
title: Design a notification system
category: case-studies
tags: [notifications, push, email, sms, fan-out, retries, templates, user-preferences, case-study]
use_cases:
  - "build a service that sends push, email and SMS notifications on behalf of many product teams"
  - "make notification delivery reliable with retries, dedupe and provider failover"
  - "let users control channels and quiet hours without every team re-implementing it"
  - "send a marketing or breaking-news blast to millions without overloading providers"
  - "avoid sending the same notification twice when a job is retried"
status: draft
last_verified: 2026-10-10
sources:
  - "System Design Interview, Vol. 1 (Alex Xu), ch. 10 'Design a Notification System'"
  - https://firebase.google.com/docs/cloud-messaging
  - https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns
  - https://docs.aws.amazon.com/sns/latest/dg/welcome.html
  - "Designing Data-Intensive Applications (Martin Kleppmann), 2017"
---

# Design a notification system

## Summary
A notification platform accepts "notify this user about X" requests from
internal services and delivers them over push (APNs, FCM), SMS, email and in-app
channels. Its job is routing, templating, preference enforcement, rate control and
reliable delivery with retries. The hard parts are reliability without duplicates,
bursty fan-out, and dependence on slow, rate-limited third-party providers.

## Key concepts
- **Channels and providers:** iOS push via APNs, Android via FCM, SMS via
  aggregators (Twilio-like), email via SMTP/ESP, plus web push and in-app inbox.
- **Notification types:** transactional (receipt, 2FA, must arrive), social/product
  (someone liked your post), marketing/broadcast (low priority, consent-gated).
- **Decoupling with queues:** per-channel queues isolate a slow SMS provider from push.
- **Idempotency:** a notification has a unique ID; delivery workers dedupe on it.
- **Preferences and consent:** opt-in/out per channel and type, quiet hours, locale, device tokens.
- **Delivery is best-effort:** providers acknowledge acceptance, not display; read/open tracking is approximate.

## When to use / scenarios
Build a central notification service when several teams send user messages and
you want shared preferences, rate limits, templates and observability. For one
product with one channel, call the provider SDK from a background job and skip the platform.
Related fan-out systems: chat offline push ([[design-chat-system]]), feed updates ([[design-news-feed]]).

## How it works / example

### 1. Requirements
Functional: send via push/SMS/email/in-app; templated, localised content; schedule
and delay; user preferences and unsubscribe; bulk/broadcast to segments; delivery status
and analytics; idempotent sends; per-tenant API keys.

Non-functional: soft real-time (transactional within seconds); at-least-once with dedupe so
important messages are never silently dropped; high availability of the ingest API; horizontally
scalable for bursts; graceful degradation when a provider is down; auditability.

### 2. Back-of-envelope (assumptions)
See [[back-of-envelope-estimation]].
- 10 M notifications/day average (about 120/s) but a broadcast of 20 M within an hour is about 5,500/s sustained,
  bursts higher. Size for the burst, not the mean.
- Payload under about 4 KB per push (APNs and FCM enforce limits around that size; check provider docs).
- Event log: 10 M/day x 1 KB = 10 GB/day, about 3.6 TB/year if you keep status events forever; apply retention.
- Provider quotas and per-device limits, not our hardware, are the binding constraint.

### 3. API
```
POST /v1/notifications
{ "idempotency_key": "order-123-shipped",
  "user_id": "u42" | "segment": "all-ios",
  "type": "order_shipped",
  "channels": ["push","email"],          // optional override; default from type policy
  "template": "order_shipped_v3", "params": {"order_id":"123"},
  "send_at": "2026-10-11T09:00:00Z", "priority": "high" }
-> 202 { "notification_id": "n_9f..." }
GET  /v1/notifications/{id}               -> status per channel
PUT  /v1/users/{id}/preferences           -> channels, quiet hours, locale
POST /v1/devices                          -> register/refresh push token
```
Return 202 and process asynchronously. Authenticate producers (service tokens),
[[rate-limiting]] per tenant.

### 4. Data model
```
notification(id, idempotency_key UNIQUE, user_id, type, template, params, priority, created_at, send_at)
delivery(notification_id, channel, status[queued|sent|failed|delivered|opened], provider, attempts, last_error, ts)
user_prefs(user_id, locale, tz, quiet_hours, channel_optins{type -> channels})
device(user_id, platform, token, last_seen)         -- remove on provider "unregistered" feedback
template(id, version, channel, locale, body)
```
Store state in a relational DB for correctness-critical records, or a KV store
at larger scale ([[sql-vs-nosql]]). Contact info should come from the user service, not be duplicated carelessly.

### 5. High-level architecture
```
 producer services --> Notification API (validate, auth, dedupe by idempotency_key)
                              |
                              v
                      Kafka topic: notifications (partition by user_id)
                              |
                       Orchestrator workers
          (load prefs, consent, quiet hours, rate limits, render template, pick channels)
              |             |             |             |
          push queue    sms queue    email queue   in-app queue   (per-channel, per-priority)
              |             |             |             |
         push workers   sms workers   email workers   inbox writer
              |             |             |
         APNs / FCM   SMS provider(s)  ESP / SMTP
              \_____________|_____________/
                  provider callbacks / webhooks --> status updater --> delivery table + analytics
```
See [[message-queues-and-streams]], [[webhooks]] (provider delivery receipts), [[api-gateway-and-service-mesh]].

### 6. Deep dive A: reliable delivery without duplicates
Providers can time out after having accepted a message, so exactly-once is impossible end to end; target
at-least-once with idempotent sends ([[idempotency-and-exactly-once]]).
1. Ingest dedupes on `idempotency_key` (unique constraint). Retried producer calls return the original ID.
2. Orchestrator writes a `delivery` row per channel *before* enqueuing (outbox pattern: DB write and
   message publish tied together so neither is lost, see [[distributed-transactions-and-sagas]]).
3. Worker marks `sending`, calls the provider with the notification ID as the provider-side
   dedupe/collapse key where supported (e.g. APNs `apns-collapse-id`, FCM collapse keys, email `Message-ID`).
4. On transient error: retry with exponential backoff and jitter, up to a cap, then move to a dead-letter queue and alert.
5. On permanent error (invalid token, hard-bounced email): mark failed, deactivate the device/address.

```python
def deliver(job, provider, db):
    row = db.get_delivery(job.notification_id, job.channel)
    if row.status in ("sent", "delivered"):
        return                                    # duplicate job, skip
    try:
        provider.send(job.payload, dedupe_key=job.notification_id)
        db.mark(row, "sent")
    except Transient as e:
        raise Retry(delay=backoff(row.attempts))  # queue redelivers later
    except Permanent as e:
        db.mark(row, "failed", error=str(e)); handle_bad_address(job)
```

### 7. Deep dive B: preferences, throttling, priority
- Orchestrator enforces: consent and unsubscribe (legal requirement for marketing), quiet hours in the
  user's time zone, per-user frequency caps ("max 3 marketing pushes/day"), and per-type channel policy.
- Priority isolation: separate queues and worker pools for transactional (2FA, security) and bulk (marketing).
  A broadcast must never delay a one-time password.
- Throttle toward each provider to its quota using a token bucket ([[rate-limiting]]);
  excess waits in the queue. Smooth broadcasts over time instead of firing all at once.
- Collapse/aggregate: "5 people liked your post" instead of 5 pushes (batching window).

### 8. Deep dive C: broadcasts and provider failure
Broadcast: a job expands a segment into per-user notifications in pages (stream the segment, do not
load millions in memory), writing batches into the topic with a rate cap. Track progress for pause/resume/cancel.
Provider outage: circuit breaker per provider ([[resilience-patterns]]); fail over to a secondary SMS/email
provider; for push there is no alternative, so queue and retry within the message's TTL; expired
transactional messages may be re-sent via another channel (push failed -> SMS) according to policy.
Templates: render per locale, version them, validate params, and never put secrets or full PII in push payloads
(lock screens expose them).

### 9. Scaling and failure handling
- Partition the topic by `user_id` to keep per-user ordering and ease frequency caps; scale consumers per partition.
- Autoscale workers on queue depth and age ([[capacity-planning-and-autoscaling]]).
- Dead-letter queues with replay tooling; alert on DLQ growth and delivery-success-rate drops.
- Observability: per-channel/provider success rate, queue lag, p99 time-to-deliver, bounce and unsubscribe rates
  ([[observability-logs-metrics-traces]]).
- Data retention: keep detailed status for days/weeks, aggregates longer.
- Security: signed provider webhooks, secrets in a vault ([[secrets-management]]), no PII in logs.

## Trade-offs
- At-least-once (possible duplicates) vs at-most-once (possible loss): choose at-least-once for transactional
  messages, at-most-once is tolerable for ephemeral nudges.
- One queue per channel and priority adds isolation but more operational surface.
- Build vs buy: SNS, Firebase, SendGrid-like services remove undifferentiated plumbing; build the orchestration
  (preferences, policy, idempotency) that is specific to your product.
- Real-time push vs batching/digests: digests reduce fatigue and cost at the price of immediacy.
- Centralised platform standardises behaviour but becomes a shared dependency with its own SLOs.

## Gotchas
- Retrying a non-idempotent provider call after a timeout sends duplicates; use dedupe keys and record state first.
- Stale device tokens: ignore provider "unregistered" feedback and the token table fills with dead entries and wastes quota.
- Time zones and daylight-saving changes in scheduled sends; store the user's zone and schedule in UTC.
- Marketing blasts sharing a queue with OTP codes.
- Unsubscribe links and consent records are legal obligations in many jurisdictions; treat them as hard constraints.
- Treating "accepted by provider" as "delivered to the user"; use receipts where available and treat the rest as unknown.
- Template changes without versioning break in-flight messages.

## Related
- [[message-queues-and-streams]] - queues, partitions, dead-letter handling
- [[idempotency-and-exactly-once]] - dedupe keys and the outbox idea
- [[rate-limiting]] - provider quotas and per-user frequency caps
- [[resilience-patterns]] - retries, circuit breakers, failover between providers
- [[webhooks]] - delivery receipts and bounce callbacks
- [[design-chat-system]] - consumer of push for offline users
- [[distributed-transactions-and-sagas]] - atomic write+publish via the outbox pattern

## References
- Alex Xu, *System Design Interview Vol. 1*, ch. 10
- Firebase Cloud Messaging docs: https://firebase.google.com/docs/cloud-messaging
- Apple, sending notification requests to APNs: https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns
- Amazon SNS developer guide: https://docs.aws.amazon.com/sns/latest/dg/welcome.html
- Kleppmann, *Designing Data-Intensive Applications* (2017)
