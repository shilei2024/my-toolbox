# Generation Service

Internal, provider-agnostic image generation service for MindfulPenpal.

## Current phase

Phase 5 keeps the framework-independent Provider core from Phase 3:

- unified generation request/result types;
- `ImageProvider` contract;
- capability matching and deterministic provider selection;
- registry with duplicate protection;
- normalized provider errors and retry classification;
- deterministic synchronous/asynchronous Mock Provider.

Phase 4 added the first production adapter and persistence path:

- `ComfyUIProvider` and configurable HTTP client;
- external, versioned API workflow files with typed placeholder injection;
- polling, cancellation, safe error mapping and structured logging;
- generic `StorageProvider` with Tencent COS as the default implementation;
- temporary output cleanup and compensating COS deletion;
- contract and integration tests using the Node.js built-in test runner.

Phase 5 adds:

- BullMQ/Redis producer and worker runtime;
- transactional outbox dispatching;
- identifier-only queue payloads and database-first idempotency;
- exponential retry, stalled recovery and cross-process cancellation;
- queue health/count snapshots and bounded graceful shutdown.

Phase 6 adds a production Gallery module:

- HMAC-scoped cursor pagination and signed BFF viewer context;
- PostgreSQL repository with prompt/privacy enforcement and atomic interactions;
- public Gallery, personal images, favorites, downloads and owner/admin deletion;
- Redis public read cache and provider-aware deferred object deletion;
- Next.js SSR/BFF in `apps/gallery-web` with the existing Flask session bridge.

Phase 9 adds:

- OpenAI Images, Google Gemini Image and 即梦/Seedream adapters;
- a PostgreSQL provider model catalog and database-driven runtime routing state;
- bounded same-provider retry and policy-aware cross-provider fallback;
- response-size, Base64, image-format and dimension validation before Tencent COS persistence;
- credential-gated adapter registration with no provider fields added to frontend or Redis contracts.

Payments, credits and membership remain outside Phase 9.

M1 adds the production loop and operational defaults:

- signed internal Generation API (`/v1/generations`, `/v1/generation/workflows`) with durable create/get/cancel;
- one-time `signup_grant` credits (`BILLING_SIGNUP_GRANT`, default 10) granted idempotently on first account summary;
- remote-provider bindings for every active workflow (migration `0007`);
- `GALLERY_DEFAULT_MODERATION` controlling immediate public publish vs. pending admin review;
- Next.js login/logout redirects through `MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL`.

M1.2 adds the creation-workbench feedback loop:

- `GET /v1/generations` viewer-scoped recent task list with signed keyset cursors and an optional status filter;
- `GenerationView` now includes the owner's `prompt`/`negativePrompt` so the workbench can restore parameters after a failure;
- the Next.js workbench renders inline completed-image previews through the existing Gallery BFF, a recent-tasks panel, per-task cancellation, and one-click parameter restore for failed tasks.

M1.3 fixes creation-homepage feedback and workflow constraints:

- `GenerationWorkflowView` exposes schema-derived `countRange`/`sizes`; `create` now rejects dimensions or counts outside the workflow `input_schema`;
- the workbench derives login state from the session route instead of billing, localizes all user-facing service errors, and removes non-essential homepage copy.

## Run tests

```powershell
npm.cmd run typecheck
npm.cmd test
```

The browser-facing request contract contains no Provider field. Provider selection is performed only from server-side workflow bindings and registered capabilities.

See [Phase 4 architecture](../../docs/architecture/phase-4-comfyui-production-provider.md), [configuration](../../docs/deployment/phase-4-configuration.md), and [deployment](../../docs/deployment/phase-4-deployment.md).

See [Phase 5 architecture](../../docs/architecture/phase-5-redis-bullmq-queue.md), [configuration](../../docs/deployment/phase-5-configuration.md), and [deployment](../../docs/deployment/phase-5-deployment.md).

See [Phase 6 Gallery architecture](../../docs/architecture/phase-6-gallery-system.md), [configuration](../../docs/deployment/phase-6-configuration.md), and [deployment](../../docs/deployment/phase-6-deployment.md).

See [Phase 9 multi-provider architecture](../../docs/architecture/phase-9-multi-provider.md), [configuration](../../docs/deployment/phase-9-configuration.md), and [deployment](../../docs/deployment/phase-9-deployment.md).
