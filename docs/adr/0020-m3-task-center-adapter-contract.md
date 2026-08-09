# ADR-0020: M3 Task Center Adapter Contract

Status: accepted (2026-08-09)

## Why

Generation jobs already have a durable PostgreSQL record, owner-scoped reads,
signed pagination, audited cancellation, and credit settlement. Users still
had to find their work through the creation screen, and future async modules
need a consistent way to surface status and output without duplicating task
state or building separate dashboards.

## Decision

- Add a read-only platform task contract: stable task key, source module,
  source ID, status, timestamps, credit fields, sanitized error, and output
  links.
- Register the Generation Service as the first task source. It maps its
  existing task view after its existing owner and cursor checks; PostgreSQL
  `generation_jobs` remains the only source of truth.
- Expose authenticated `GET /v1/tasks` and the Gallery BFF `GET /api/tasks`.
  Gallery adds `/tasks` as the user-facing task center.
- Do not add a generic `tasks` table, dual-write path, or module-specific
  administration screen. Future async modules add an adapter and retain their
  own transactional source records.
- With only one source registered, its signed keyset cursor remains valid.
  Cross-source pagination will be designed when a second source exists, rather
  than shipping an untested composite cursor prematurely.

## Alternatives Considered

1. Create an `ai.tasks` table and dual-write every generation transition.
   This introduces reconciliation risk for status and credits without adding a
   second source today.
2. Leave task history inside `/create`. It does not form a discoverable,
   reusable platform capability and cannot serve later modules.
3. Build a cross-module cursor now. There is no second source with which to
   validate ordering, deletion, or partial-page behavior.

## Future Impact

OCR, video, and other async modules should implement the same source adapter.
When the second source is introduced, extend the task center with a signed
composite cursor and source-aware filtering; do not change existing task keys.
Notifications and SLA aggregation belong to the task center once at least two
sources provide equivalent lifecycle timestamps.

## Performance

The first source delegates directly to the indexed generation-job list query.
No table scan, replication job, cache, or extra infrastructure is added.

## Cost

The task center uses existing Next.js, Generation Service, PostgreSQL, and
internal HMAC authentication. It creates no new billable dependency.

## Security

The service verifies the signed viewer context and delegates authorization to
the existing owner-scoped Generation Service query. The browser can only use
the BFF and receives sanitized errors; provider routing data and prompts are
not added to the task summary.

## Rollback Plan

The endpoints and page are additive. Disable the Gallery navigation/page or
remove the task route registration to roll back without database migration or
affecting task execution, credits, or existing generation endpoints.
