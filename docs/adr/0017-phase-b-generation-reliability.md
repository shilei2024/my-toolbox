# ADR-0017: Phase B Generation Reliability and Provider Control Plane

Status: accepted (2026-08-09)

## Why

An interrupted worker could leave a generation job in `running` with an active credit reservation. A waiting BullMQ job removed during cancellation also had no worker remaining to settle the database row. Stripe delayed-payment events were ignored, and provider health information was present in PostgreSQL but never refreshed. These failures risk permanent credit locks, unpaid credits, and preventable provider outages.

## Decision

- Cancellation now requests queue removal/signalling for both pending and running jobs. Removed, missing, terminal, or unavailable queue receipts are finalized synchronously and use existing idempotent credit-release functions.
- Queue completion, failure, and cancellation transitions only update jobs still in eligible non-terminal states.
- Every worker runs a bounded reconciler. It locks stale running jobs with `FOR UPDATE SKIP LOCKED`, records a terminal failure (or cancellation when a cancellation was already requested), releases only active reservations, and writes an audit log.
- Stripe normalizes `checkout.session.async_payment_succeeded` and platform-owned `payment_intent.succeeded` as the existing idempotent checkout event.
- Workers periodically call the provider contract's `healthCheck`, persist consecutive failures, move active providers to `degraded` at a configurable threshold, and refresh local routing from PostgreSQL.
- ComfyUI model, LoRA, sampler and similar execution controls are sourced only from server-side provider bindings/defaults; the browser may still provide a bounded seed.

## Alternatives Considered

1. Rely only on BullMQ stalled-job recovery. It cannot settle PostgreSQL credit reservations after a process/database failure and is not the business source of truth.
2. Add a separate scheduler service. A periodic loop in each existing worker has lower deployment cost; row locks make replicas safe.
3. Accept arbitrary client ComfyUI parameters with validation. This cannot enforce model tiering or prevent unreviewed LoRA/model selection.

## Future Impact

The reconciler, health monitor, and catalog state are provider-agnostic and can be reused by video, OCR, audio, and future generation modules. New providers must implement the existing `healthCheck` contract and ensure their submission API is idempotent before being eligible for automatic retry/failover.

## Performance

Health checks run at most once per configured interval and sequentially to avoid burst load. Reconciliation defaults to 50 rows per minute and uses a status/updated-at index plus `SKIP LOCKED`, so multiple worker replicas do not block one another. These limits are configurable in the Generation Service environment.

## Cost

No new infrastructure, queue, table, or SaaS dependency is introduced. The solution uses the existing PostgreSQL business ledger and worker processes.

## Security

Payment intent events are accepted only when they contain a server-created order reference. Provider health logs contain only stable provider codes, booleans, and latency. ComfyUI routing configuration never crosses the public request boundary.

## Rollback Plan

The changes are backward-compatible with the existing schema. If reconciliation or health checks cause operational issues, set their intervals to a larger value while investigating; do not remove terminal-state guards or ledger release idempotency. Reverting code does not require a database rollback. Before a production rollout, verify one stale-job recovery and one delayed Stripe event in staging, then monitor `queue.generation_reconciled` and `provider.health_checked` logs.
