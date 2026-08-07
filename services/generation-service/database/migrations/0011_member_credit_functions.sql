BEGIN;

CREATE FUNCTION ai.reserve_member_generation_credits(
  p_user_id integer,
  p_generation_job_id uuid,
  p_amount numeric,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  account ai.member_credit_accounts%ROWTYPE;
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
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.member_credit_accounts a WHERE a.user_id = p_user_id;
    RETURN;
  END IF;

  INSERT INTO ai.member_credit_accounts (user_id) VALUES (p_user_id) ON CONFLICT DO NOTHING;
  SELECT * INTO account FROM ai.member_credit_accounts WHERE user_id = p_user_id FOR UPDATE;
  IF account.available_amount < p_amount THEN RAISE EXCEPTION 'insufficient_credits' USING ERRCODE = 'P0001'; END IF;

  UPDATE ai.member_credit_accounts AS target SET
    available_amount = target.available_amount - p_amount,
    reserved_amount = target.reserved_amount + p_amount,
    version = target.version + 1
  WHERE target.user_id = p_user_id
  RETURNING * INTO account;

  INSERT INTO ai.credit_reservations (user_id, generation_job_id, amount)
  VALUES (p_user_id, p_generation_job_id, p_amount);
  INSERT INTO ai.credit_ledger_entries (
    user_id, account_type, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key
  ) VALUES (
    p_user_id, 'member', 'generation_reserve', -p_amount, p_amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key
  );
  UPDATE ai.generation_jobs SET credits_reserved = p_amount WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE FUNCTION ai.settle_member_generation_credits(
  p_generation_job_id uuid,
  p_charge_amount numeric,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  hold ai.credit_reservations%ROWTYPE;
  account ai.member_credit_accounts%ROWTYPE;
  release_amount numeric(18, 4);
BEGIN
  SELECT * INTO hold FROM ai.credit_reservations WHERE generation_job_id = p_generation_job_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'credit_reservation_not_found' USING ERRCODE = 'P0001'; END IF;
  IF hold.status = 'settled' THEN
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.member_credit_accounts a WHERE a.user_id = hold.user_id;
    RETURN;
  END IF;
  IF hold.status <> 'active' THEN RAISE EXCEPTION 'credit_reservation_not_active' USING ERRCODE = 'P0001'; END IF;
  IF p_charge_amount < 0 OR p_charge_amount > hold.amount THEN RAISE EXCEPTION 'invalid_credit_charge' USING ERRCODE = 'P0001'; END IF;
  release_amount := hold.amount - p_charge_amount;

  SELECT * INTO account FROM ai.member_credit_accounts WHERE user_id = hold.user_id FOR UPDATE;
  UPDATE ai.member_credit_accounts AS target SET
    available_amount = target.available_amount + release_amount,
    reserved_amount = target.reserved_amount - hold.amount,
    lifetime_spent = target.lifetime_spent + p_charge_amount,
    version = target.version + 1
  WHERE target.user_id = hold.user_id
  RETURNING * INTO account;
  UPDATE ai.credit_reservations SET status = 'settled', charged_amount = p_charge_amount, settled_at = now()
  WHERE id = hold.id;
  INSERT INTO ai.credit_ledger_entries (
    user_id, account_type, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key, metadata
  ) VALUES (
    hold.user_id, 'member', 'generation_settle', release_amount, -hold.amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key, jsonb_build_object('charged_amount', p_charge_amount)
  );
  UPDATE ai.generation_jobs SET credits_charged = p_charge_amount WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE FUNCTION ai.release_member_generation_credits(
  p_generation_job_id uuid,
  p_idempotency_key varchar
) RETURNS TABLE (available_amount numeric, reserved_amount numeric)
LANGUAGE plpgsql AS $$
DECLARE
  hold ai.credit_reservations%ROWTYPE;
  account ai.member_credit_accounts%ROWTYPE;
BEGIN
  SELECT * INTO hold FROM ai.credit_reservations WHERE generation_job_id = p_generation_job_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'credit_reservation_not_found' USING ERRCODE = 'P0001'; END IF;
  IF hold.status = 'released' THEN
    RETURN QUERY SELECT a.available_amount, a.reserved_amount FROM ai.member_credit_accounts a WHERE a.user_id = hold.user_id;
    RETURN;
  END IF;
  IF hold.status <> 'active' THEN RAISE EXCEPTION 'credit_reservation_not_active' USING ERRCODE = 'P0001'; END IF;

  SELECT * INTO account FROM ai.member_credit_accounts WHERE user_id = hold.user_id FOR UPDATE;
  UPDATE ai.member_credit_accounts AS target SET
    available_amount = target.available_amount + hold.amount,
    reserved_amount = target.reserved_amount - hold.amount,
    version = target.version + 1
  WHERE target.user_id = hold.user_id
  RETURNING * INTO account;
  UPDATE ai.credit_reservations SET status = 'released', released_at = now() WHERE id = hold.id;
  INSERT INTO ai.credit_ledger_entries (
    user_id, account_type, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key
  ) VALUES (
    hold.user_id, 'member', 'generation_release', hold.amount, -hold.amount, account.available_amount, account.reserved_amount,
    'generation_job', p_generation_job_id::text, p_idempotency_key
  );
  UPDATE ai.generation_jobs SET credits_reserved = 0 WHERE id = p_generation_job_id;
  RETURN QUERY SELECT account.available_amount, account.reserved_amount;
END;
$$;

CREATE FUNCTION ai.redeem_redemption_code(
  p_user_id integer,
  p_code varchar
) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE
  row ai.redemption_codes%ROWTYPE;
  account ai.member_credit_accounts%ROWTYPE;
BEGIN
  SELECT * INTO row FROM ai.redemption_codes WHERE code = p_code FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'redemption_code_not_found' USING ERRCODE = 'P0001'; END IF;
  IF row.status <> 'unused' THEN RAISE EXCEPTION 'redemption_code_used' USING ERRCODE = 'P0001'; END IF;
  IF row.expires_at IS NOT NULL AND row.expires_at < now() THEN RAISE EXCEPTION 'redemption_code_expired' USING ERRCODE = 'P0001'; END IF;
  UPDATE ai.redemption_codes SET status = 'redeemed', redeemed_by = p_user_id, redeemed_at = now() WHERE code = p_code;

  INSERT INTO ai.member_credit_accounts (user_id, available_amount, lifetime_granted)
  VALUES (p_user_id, row.amount, row.amount)
  ON CONFLICT (user_id) DO UPDATE SET
    available_amount = ai.member_credit_accounts.available_amount + EXCLUDED.available_amount,
    lifetime_granted = ai.member_credit_accounts.lifetime_granted + EXCLUDED.available_amount,
    version = ai.member_credit_accounts.version + 1;
  SELECT * INTO account FROM ai.member_credit_accounts WHERE user_id = p_user_id;
  INSERT INTO ai.credit_ledger_entries (
    user_id, account_type, entry_type, delta_available, delta_reserved, available_after, reserved_after,
    source_type, source_ref, idempotency_key, metadata
  ) VALUES (
    p_user_id, 'member', 'pack_purchase', row.amount, 0, account.available_amount, account.reserved_amount,
    'redemption_code', p_code, 'redemption:' || p_code, jsonb_build_object('code', p_code)
  );
  RETURN row.amount;
END;
$$;

COMMIT;
