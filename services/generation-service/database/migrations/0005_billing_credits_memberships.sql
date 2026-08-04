BEGIN;

CREATE TYPE ai.billing_plan_kind AS ENUM ('free', 'subscription', 'credit_pack');
CREATE TYPE ai.billing_interval AS ENUM ('month', 'year');
CREATE TYPE ai.payment_order_status AS ENUM ('created', 'checkout_open', 'paid', 'failed', 'expired', 'refunded', 'partially_refunded');
CREATE TYPE ai.subscription_status AS ENUM ('incomplete', 'trialing', 'active', 'past_due', 'paused', 'cancelled', 'unpaid');
CREATE TYPE ai.webhook_event_status AS ENUM ('received', 'processing', 'processed', 'ignored', 'failed');
CREATE TYPE ai.credit_reservation_status AS ENUM ('active', 'settled', 'released');

CREATE TABLE ai.billing_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug varchar(80) NOT NULL UNIQUE,
  display_name varchar(100) NOT NULL,
  description text NOT NULL DEFAULT '',
  kind ai.billing_plan_kind NOT NULL,
  billing_interval ai.billing_interval,
  currency char(3) NOT NULL DEFAULT 'USD' CHECK (currency = upper(currency)),
  amount_minor bigint NOT NULL DEFAULT 0 CHECK (amount_minor >= 0),
  credit_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (credit_amount >= 0),
  entitlements jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(entitlements) = 'object'),
  payment_provider varchar(32),
  external_price_ref varchar(255),
  is_enabled boolean NOT NULL DEFAULT false,
  is_public boolean NOT NULL DEFAULT false,
  sort_order integer NOT NULL DEFAULT 100,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (kind = 'free' AND billing_interval IS NULL AND amount_minor = 0 AND payment_provider IS NULL AND external_price_ref IS NULL)
    OR (kind = 'subscription' AND billing_interval IS NOT NULL AND amount_minor > 0 AND payment_provider IS NOT NULL AND external_price_ref IS NOT NULL)
    OR (kind = 'credit_pack' AND billing_interval IS NULL AND amount_minor > 0 AND credit_amount > 0 AND payment_provider IS NOT NULL AND external_price_ref IS NOT NULL)
  )
);

CREATE UNIQUE INDEX uq_ai_billing_plan_external_price
  ON ai.billing_plans (payment_provider, external_price_ref)
  WHERE external_price_ref IS NOT NULL;
CREATE INDEX ix_ai_billing_plans_public ON ai.billing_plans (sort_order, slug)
  WHERE is_enabled AND is_public;

INSERT INTO ai.billing_plans (
  slug, display_name, description, kind, credit_amount, entitlements, is_enabled, is_public, sort_order
) VALUES (
  'free', 'Free', '适合体验公开画廊与基础创作流程。', 'free', 0,
  '{"private_generation": false, "priority_queue": false}'::jsonb, true, true, 10
);

CREATE TABLE ai.billing_customers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  payment_provider varchar(32) NOT NULL,
  external_customer_id varchar(255) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, payment_provider),
  UNIQUE (payment_provider, external_customer_id)
);

CREATE TABLE ai.payment_orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES ai.billing_plans(id) ON DELETE RESTRICT,
  payment_provider varchar(32) NOT NULL,
  idempotency_key varchar(128) NOT NULL,
  status ai.payment_order_status NOT NULL DEFAULT 'created',
  currency char(3) NOT NULL CHECK (currency = upper(currency)),
  amount_minor bigint NOT NULL CHECK (amount_minor > 0),
  credited_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (credited_amount >= 0),
  refunded_amount_minor bigint NOT NULL DEFAULT 0 CHECK (refunded_amount_minor >= 0 AND refunded_amount_minor <= amount_minor),
  revoked_credit_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (revoked_credit_amount >= 0),
  external_checkout_id varchar(255),
  external_checkout_url text CHECK (external_checkout_url IS NULL OR external_checkout_url LIKE 'https://%'),
  external_payment_id varchar(255),
  external_invoice_id varchar(255),
  external_subscription_id varchar(255),
  expires_at timestamptz,
  paid_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, idempotency_key),
  UNIQUE (payment_provider, external_checkout_id),
  UNIQUE (payment_provider, external_payment_id),
  UNIQUE (payment_provider, external_subscription_id)
);

CREATE INDEX ix_ai_payment_orders_user_created ON ai.payment_orders (user_id, created_at DESC);
CREATE INDEX ix_ai_payment_orders_status_created ON ai.payment_orders (status, created_at);

CREATE TABLE ai.subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES ai.billing_plans(id) ON DELETE RESTRICT,
  payment_provider varchar(32) NOT NULL,
  external_subscription_id varchar(255) NOT NULL,
  status ai.subscription_status NOT NULL DEFAULT 'incomplete',
  cancel_at_period_end boolean NOT NULL DEFAULT false,
  current_period_start timestamptz,
  current_period_end timestamptz,
  last_provider_event_at timestamptz NOT NULL DEFAULT '-infinity',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (payment_provider, external_subscription_id)
);

CREATE UNIQUE INDEX uq_ai_one_live_subscription_per_user
  ON ai.subscriptions (user_id)
  WHERE status IN ('incomplete', 'trialing', 'active', 'past_due', 'paused', 'unpaid');
CREATE INDEX ix_ai_subscriptions_user_updated ON ai.subscriptions (user_id, updated_at DESC);

CREATE TABLE ai.payment_webhook_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  payment_provider varchar(32) NOT NULL,
  external_event_id varchar(255) NOT NULL,
  event_type varchar(128) NOT NULL,
  event_created_at timestamptz NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  payload_sha256 char(64) NOT NULL,
  status ai.webhook_event_status NOT NULL DEFAULT 'received',
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  locked_at timestamptz,
  processed_at timestamptz,
  last_error_code varchar(80),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (payment_provider, external_event_id)
);

CREATE INDEX ix_ai_payment_webhook_due
  ON ai.payment_webhook_events (available_at, created_at)
  WHERE status IN ('received', 'failed');

CREATE TABLE ai.credit_accounts (
  user_id integer PRIMARY KEY REFERENCES public.users(id) ON DELETE RESTRICT,
  available_amount numeric(18, 4) NOT NULL DEFAULT 0,
  reserved_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (reserved_amount >= 0),
  lifetime_granted numeric(18, 4) NOT NULL DEFAULT 0 CHECK (lifetime_granted >= 0),
  lifetime_spent numeric(18, 4) NOT NULL DEFAULT 0 CHECK (lifetime_spent >= 0),
  version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai.credit_ledger_entries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
  entry_type varchar(40) NOT NULL CHECK (entry_type IN (
    'signup_grant', 'subscription_grant', 'pack_purchase', 'admin_adjustment',
    'generation_reserve', 'generation_settle', 'generation_release', 'payment_refund', 'credit_expiry'
  )),
  delta_available numeric(18, 4) NOT NULL DEFAULT 0,
  delta_reserved numeric(18, 4) NOT NULL DEFAULT 0,
  available_after numeric(18, 4) NOT NULL,
  reserved_after numeric(18, 4) NOT NULL CHECK (reserved_after >= 0),
  source_type varchar(40) NOT NULL,
  source_ref varchar(255) NOT NULL,
  idempotency_key varchar(180) NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, idempotency_key),
  CHECK (delta_available <> 0 OR delta_reserved <> 0)
);

CREATE INDEX ix_ai_credit_ledger_user_created ON ai.credit_ledger_entries (user_id, created_at DESC, id DESC);
CREATE INDEX ix_ai_credit_ledger_source ON ai.credit_ledger_entries (source_type, source_ref);

CREATE TABLE ai.credit_reservations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
  generation_job_id uuid NOT NULL REFERENCES ai.generation_jobs(id) ON DELETE RESTRICT,
  amount numeric(18, 4) NOT NULL CHECK (amount > 0),
  charged_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (charged_amount >= 0),
  status ai.credit_reservation_status NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  settled_at timestamptz,
  released_at timestamptz,
  UNIQUE (generation_job_id)
);

CREATE INDEX ix_ai_credit_reservations_active ON ai.credit_reservations (user_id, created_at)
  WHERE status = 'active';

CREATE FUNCTION ai.prevent_credit_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'credit_ledger_entries are immutable';
END;
$$;

CREATE TRIGGER trg_ai_credit_ledger_immutable
  BEFORE UPDATE OR DELETE ON ai.credit_ledger_entries
  FOR EACH ROW EXECUTE FUNCTION ai.prevent_credit_ledger_mutation();

CREATE FUNCTION ai.reserve_generation_credits(
  p_user_id integer,
  p_generation_job_id uuid,
  p_amount numeric,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  account ai.credit_accounts%ROWTYPE;
  existing ai.credit_reservations%ROWTYPE;
BEGIN
  IF p_amount <= 0 THEN RAISE EXCEPTION 'invalid_credit_amount' USING ERRCODE = 'P0001'; END IF;
  IF NOT EXISTS (SELECT 1 FROM ai.generation_jobs WHERE id = p_generation_job_id AND user_id = p_user_id) THEN
    RAISE EXCEPTION 'generation_job_user_mismatch' USING ERRCODE = 'P0001';
  END IF;

  SELECT * INTO existing FROM ai.credit_reservations WHERE generation_job_id = p_generation_job_id;
  IF FOUND THEN
    IF existing.user_id <> p_user_id OR existing.amount <> p_amount THEN
      RAISE EXCEPTION 'credit_reservation_conflict' USING ERRCODE = 'P0001';
    END IF;
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.credit_accounts a WHERE a.user_id = p_user_id;
    RETURN;
  END IF;

  INSERT INTO ai.credit_accounts (user_id) VALUES (p_user_id) ON CONFLICT DO NOTHING;
  SELECT * INTO account FROM ai.credit_accounts WHERE user_id = p_user_id FOR UPDATE;
  IF account.available_amount < p_amount THEN RAISE EXCEPTION 'insufficient_credits' USING ERRCODE = 'P0001'; END IF;

  UPDATE ai.credit_accounts AS target SET
    available_amount = target.available_amount - p_amount,
    reserved_amount = target.reserved_amount + p_amount,
    version = target.version + 1
  WHERE target.user_id = p_user_id
  RETURNING * INTO account;

  INSERT INTO ai.credit_reservations (user_id, generation_job_id, amount)
  VALUES (p_user_id, p_generation_job_id, p_amount);
  INSERT INTO ai.credit_ledger_entries (
    user_id, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key
  ) VALUES (
    p_user_id, 'generation_reserve', -p_amount, p_amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key
  );
  UPDATE ai.generation_jobs SET credits_reserved = p_amount WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE FUNCTION ai.settle_generation_credits(
  p_generation_job_id uuid,
  p_charge_amount numeric,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  hold ai.credit_reservations%ROWTYPE;
  account ai.credit_accounts%ROWTYPE;
  release_amount numeric(18, 4);
BEGIN
  SELECT * INTO hold FROM ai.credit_reservations WHERE generation_job_id = p_generation_job_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'credit_reservation_not_found' USING ERRCODE = 'P0001'; END IF;
  IF hold.status = 'settled' THEN
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.credit_accounts a WHERE a.user_id = hold.user_id;
    RETURN;
  END IF;
  IF hold.status <> 'active' THEN RAISE EXCEPTION 'credit_reservation_not_active' USING ERRCODE = 'P0001'; END IF;
  IF p_charge_amount < 0 OR p_charge_amount > hold.amount THEN RAISE EXCEPTION 'invalid_credit_charge' USING ERRCODE = 'P0001'; END IF;
  release_amount := hold.amount - p_charge_amount;

  SELECT * INTO account FROM ai.credit_accounts WHERE user_id = hold.user_id FOR UPDATE;
  UPDATE ai.credit_accounts AS target SET
    available_amount = target.available_amount + release_amount,
    reserved_amount = target.reserved_amount - hold.amount,
    lifetime_spent = target.lifetime_spent + p_charge_amount,
    version = target.version + 1
  WHERE target.user_id = hold.user_id
  RETURNING * INTO account;
  UPDATE ai.credit_reservations SET status = 'settled', charged_amount = p_charge_amount, settled_at = now()
  WHERE id = hold.id;
  INSERT INTO ai.credit_ledger_entries (
    user_id, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key, metadata
  ) VALUES (
    hold.user_id, 'generation_settle', release_amount, -hold.amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key, jsonb_build_object('charged_amount', p_charge_amount)
  );
  UPDATE ai.generation_jobs SET credits_charged = p_charge_amount WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE FUNCTION ai.release_generation_credits(
  p_generation_job_id uuid,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  hold ai.credit_reservations%ROWTYPE;
  account ai.credit_accounts%ROWTYPE;
BEGIN
  SELECT * INTO hold FROM ai.credit_reservations WHERE generation_job_id = p_generation_job_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'credit_reservation_not_found' USING ERRCODE = 'P0001'; END IF;
  IF hold.status = 'released' THEN
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.credit_accounts a WHERE a.user_id = hold.user_id;
    RETURN;
  END IF;
  IF hold.status <> 'active' THEN RAISE EXCEPTION 'credit_reservation_not_active' USING ERRCODE = 'P0001'; END IF;

  SELECT * INTO account FROM ai.credit_accounts WHERE user_id = hold.user_id FOR UPDATE;
  UPDATE ai.credit_accounts AS target SET
    available_amount = target.available_amount + hold.amount,
    reserved_amount = target.reserved_amount - hold.amount,
    version = target.version + 1
  WHERE target.user_id = hold.user_id
  RETURNING * INTO account;
  UPDATE ai.credit_reservations SET status = 'released', released_at = now() WHERE id = hold.id;
  INSERT INTO ai.credit_ledger_entries (
    user_id, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key
  ) VALUES (
    hold.user_id, 'generation_release', hold.amount, -hold.amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key
  );
  UPDATE ai.generation_jobs SET credits_reserved = 0 WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE TRIGGER trg_ai_billing_plans_updated BEFORE UPDATE ON ai.billing_plans
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_billing_customers_updated BEFORE UPDATE ON ai.billing_customers
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_payment_orders_updated BEFORE UPDATE ON ai.payment_orders
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_subscriptions_updated BEFORE UPDATE ON ai.subscriptions
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_payment_webhook_events_updated BEFORE UPDATE ON ai.payment_webhook_events
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_credit_accounts_updated BEFORE UPDATE ON ai.credit_accounts
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();

COMMIT;
