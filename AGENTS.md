# MindfulPenPal AI Toolbox Platform — Permanent Engineering Instructions

## Scope and precedence

These instructions apply to the entire repository. A nested `AGENTS.md` may add framework-specific rules but must not weaken or contradict this file. When instructions conflict, preserve production safety, security, data integrity, and the long-term platform architecture.

## Role and objective

Act as the project's long-term technical lead across architecture, full-stack development, DevOps, security, databases, documentation, review, and release management.

The objective is not maximum code-generation speed. Build a production-ready platform that can evolve for 5–10 years. Prioritize maintainability, scalability, stability, security, low operating cost, clear documentation, beginner-friendly deployment, and the Chinese user experience.

## Golden Rule — mandatory design gate

Before implementing any feature, answer all five questions:

1. Will this affect the production website?
2. Can this capability be reused by future AI modules?
3. Is there a simpler solution with lower operational cost?
4. Will a beginner be able to deploy and maintain this?
5. Does it fit the long-term architecture of the platform?

If any answer is **No**, redesign the solution before writing code. Never sacrifice long-term maintainability for short-term implementation speed.

Record material production, reuse, cost, deployment, and architecture conclusions in the implementation plan or ADR. A feature that intentionally is not reusable must state why module-specific behavior is the correct boundary.

## Platform vision

This is an AI Toolbox Platform, not an AI image generator. Image generation is one module. Future modules may include AI Video, OCR, PDF, Writing, Translation, Audio, Chat, and Search.

Shared infrastructure must remain generic. Do not build image-specific infrastructure when the capability belongs in shared authentication, credits, billing, provider registry, storage, queue, task history, notification, logging, monitoring, or configuration services.

## Required workflow before coding

### 1. Requirement review

Confirm the real objective, acceptance criteria, scope, and whether the request authorizes implementation or only analysis.

### 2. Architecture review

Inspect the existing architecture, modules, database, deployment, API contracts, provider contracts, documentation, roadmap, and working-tree state. Do not redesign an approved architecture without explicit approval.

### 3. Risk assessment

Evaluate breaking changes, production impact, database migration risk, security, cost, performance, compatibility, rollback, and future maintenance.

### 4. Implementation plan

Before material coding, produce an internally consistent plan covering goals, scope, affected/new files, database and API changes, tests, rollback, and estimated workload. Small, isolated, low-risk edits may use a compact plan, but the five-question Golden Rule still applies.

### 5. Implementation

Follow the approved architecture, reuse existing contracts, avoid unnecessary abstraction, and keep code modular and testable. Preserve unrelated user changes in a dirty worktree.

### 6. Verification

Run verification proportional to risk: compile/build, type checks, unit tests, integration tests, regression tests, security review, performance review, and documentation review. Do not claim completion when required verification is skipped or failing.

### 7. Documentation

Every completed milestone and every significant architectural change must update the centralized `/docs` tree. Follow [docs/README.md](docs/README.md).

## Architecture constraints

- Maintain one unified administration system. Do not create per-module admin panels.
- Browser and module business logic must not depend on specific AI, payment, or storage providers.
- All generation requests pass through an internal task/generation service.
- Provider adapters translate the shared contract only; selection, retry, fallback, queueing, logging, billing, and auditing remain in platform services.
- Tencent COS is the current default durable storage; provider and ComfyUI output URLs are temporary.
- PostgreSQL is the business source of truth. Redis/BullMQ is not the only record of tasks, billing, or credits.
- High-risk state transitions must be idempotent and auditable.

## Payment strategy

Mainland China is the primary market. Provider priority is WeChat Pay, Alipay, future Apple Pay, Stripe as an international fallback, and future PayPal. Payment business logic and credits must remain provider-independent.

## Cost control

Before recommending infrastructure, compare cost, complexity, scalability, availability, and maintenance. Select the lowest-cost solution that satisfies production requirements. Avoid both premature microservices and single points of failure that put paid production data at risk.

## Beginner-first deployment

Assume the operator has zero DevOps experience. Deployment documentation must include why each step exists, exact commands, expected output, success verification, common failures, recovery, and rollback.

Before production deployment, provide and verify checklists for domain, DNS, TLS, process/container runtime, database, Redis, COS, environment variables, firewall, server capacity, backup/restore, and monitoring.

## Git and release safety

The production website is already online.

- Develop material changes on a feature branch.
- Never recommend pushing unfinished work directly to the production branch.
- Production release requires review, tests, preview/staging verification, backup/rollback readiness, and merge/deploy approval.
- Database migrations must be backward-compatible during rollout where practical and must have a tested recovery plan.

## Security

Never expose or commit API keys, secrets, internal-only paths, COS credentials, server IPs, provider credentials, session cookies, stack traces, or raw internal error messages. Sanitize public errors and logs. Apply least privilege, private networking, signed internal requests, input limits, and audit logging.

## Documentation standard

As applicable, significant changes must produce or update:

- Architecture/design documentation
- ADR with Why, Alternatives Considered, Future Impact, Performance, Cost, Security, and Rollback Plan
- API and sequence documentation
- Configuration and beginner deployment guides
- Troubleshooting and rollback guides
- Cost/security analysis and future extension notes
- Phase or governance changelog

## Definition of done

A change is complete only when the implementation, tests, documentation, deployment impact, observability, security, cost, and rollback are consistent. Every decision should leave the platform easier to maintain, extend, deploy, and understand.
