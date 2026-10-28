# ADR-0019: Phase D Code Quality and Governance Cleanup

Status: accepted (2026-08-09)

## Why

Several file-processing tools contained identical temporary-download staging
logic. The root Flask example still advertised image-provider variables that
the Generation Service now owns. The reimbursement module also contains a
legacy stateless export protocol beside the owner-scoped persisted API used by
the current web client. These duplicates make future security fixes and
operator configuration harder to reason about.

## Decision

- All seven affected file tools now delegate staging to `utils.stage_download`.
  The shared helper rejects path components, verifies containment under
  `UPLOAD_DIR`, and preserves the existing session-bound `safe_filename`
  authorization model.
- The persisted endpoint `GET /tools/reimbursement/api/export/<kind>/<period>`
  is the canonical reimbursement export API. It retains period ownership
  checks and is the only export route called by the maintained web client.
  The older JSON POST export endpoints remain temporarily as compatibility
  endpoints because they accept a different, stateless payload contract;
  removing them requires an announced client migration.
- Root Flask configuration and README no longer advertise `AI_PROVIDER`,
  `AI_API_KEY`, `AI_BASE_URL`, or `AI_MODEL`. Image generation configuration
  belongs in `services/generation-service/.env.example`.
- `GenerationQueueObservability` remains exported: it has an API contract and
  regression coverage and is a reusable input for the planned M5 monitoring
  surface. It is not deleted merely because no HTTP route invokes it yet.
- Only local `codex/*` branches proven reachable from `main` may be removed;
  remote branches are left unchanged until a reviewed remote cleanup is
  explicitly approved.

## Alternatives Considered

1. Keep a separate copy of staging code in every tool. This leaves filename
   validation and future download policy changes inconsistently applied.
2. Delete the legacy reimbursement export POST routes immediately. That would
   silently break untracked integrations because their payload is not
   compatible with the persisted period API.
3. Delete queue observability as apparently unused. This discards a small,
   tested operational primitive before M5 can consume it.

## Future Impact

New file-producing tools must use `safe_filename` followed by
`stage_download`. A future reimbursement API version can remove the legacy
POST endpoints after a documented deprecation window and access-log review.
M5 should expose queue snapshots through the unified administrative control
plane rather than creating a new module-specific dashboard.

## Performance

The shared staging helper adds one local path-resolution check per generated
file. This is insignificant next to file conversion and prevents repeated
implementation work.

## Cost

No new infrastructure, dependency, storage, or database migration is needed.

## Security

Centralizing staging closes the risk that a future copied helper omits path
containment. Canonical reimbursement exports remain owner-scoped. Provider
secrets stay in the service that uses them, reducing accidental configuration
leakage from the public Flask deployment.

## Rollback Plan

The helper preserves each tool's existing filename generation and response
contracts. If a deployment reveals an incompatible platform path, restore the
previous per-tool staging wrapper and investigate before loosening containment.
Configuration rollback consists of restoring only the documented legacy
variables; no persisted setting or migration changes are involved.
