BEGIN;

-- Phase 2/3: model credit tiers and per-model credit pricing.
-- free credits may only call tier='free' models; member credits may call any.
ALTER TABLE ai.provider_models
  ADD COLUMN tier varchar(16) NOT NULL DEFAULT 'free'
  CHECK (tier IN ('free', 'member'));
ALTER TABLE ai.provider_models
  ADD COLUMN credit_cost numeric(18, 4);

-- Record which credit tier a generation job was created under so the worker
-- can refuse member-tier models for free-tier jobs and settle the right ledger.
ALTER TABLE ai.generation_jobs
  ADD COLUMN credit_tier varchar(16) NOT NULL DEFAULT 'free'
  CHECK (credit_tier IN ('free', 'member'));

COMMIT;
