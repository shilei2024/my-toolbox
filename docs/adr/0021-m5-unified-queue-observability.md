# ADR-0021: M5 Unified Queue Observability

Status: accepted (2026-08-09)

## Why

The Generation Service already had a bounded queue snapshot primitive, but it
was not connected to a production control-plane route. Operators could see
historical jobs while lacking a direct, role-protected view of worker count,
backlog, Redis latency, and retained failures.

## Decision

- Reuse `GenerationQueueObservability` through `GenerationQueueService` and
  expose a read-only `GET /v1/admin/queue` route under the existing
  `AdminService` RBAC boundary.
- Proxy it only through the Gallery BFF at `GET /api/admin/queue`; the Gallery
  unified admin view loads it on demand in its Queue Monitoring tab.
- Treat Redis unavailable, or a positive wait backlog with zero workers, as
  an attention condition. Emit a safe structured `admin.queue_attention`
  event containing counters only; never log job prompts, payloads, secrets,
  or user content.
- If Redis/queue is not configured, return a sanitized 503 rather than a
  misleading healthy snapshot.

## Alternatives Considered

1. Build a separate monitoring dashboard. This fragments the unified admin
   surface and introduces another deployment and authentication boundary.
2. Add an external alerting vendor first. A destination, escalation policy,
   retention agreement, and data-processing review are required before an
   external notification can be sent safely.
3. Report an empty healthy queue when Redis is absent. This hides an
   operational misconfiguration during a production incident.

## Future Impact

M5 alert delivery can consume `admin.queue_attention` through an approved
notification sink after the operator chooses a channel and escalation policy.
Provider health, reconciliation counts, and payment/webhook inbox lag should
be added as sibling read-only signals to the same unified admin surface.

## Performance

Snapshots run only when an administrator opens the operations tab. Each read
uses one Redis ping plus bounded BullMQ counts and worker count; it does not
inspect job payloads or scan PostgreSQL.

## Cost

The implementation reuses the existing Redis connections and Gallery BFF. It
adds no database table, polling process, vendor, or paid monitoring service.

## Security

Both the BFF and Generation Service enforce administrator identity. Metrics
are aggregate counters only, and unavailable monitoring fails closed with a
sanitized error.

## Rollback Plan

Remove the additive route and Queue Monitoring UI tab. Queue execution,
credit settlement, Redis configuration, and existing administration endpoints
continue to work without migration or data recovery.
