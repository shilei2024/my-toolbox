BEGIN;

-- Phase 3: member credit ledger (paid credits) separate from the free ledger.
CREATE TABLE ai.member_credit_accounts (
  user_id integer PRIMARY KEY REFERENCES public.users(id) ON DELETE RESTRICT,
  available_amount numeric(18, 4) NOT NULL DEFAULT 0,
  reserved_amount numeric(18, 4) NOT NULL DEFAULT 0 CHECK (reserved_amount >= 0),
  lifetime_granted numeric(18, 4) NOT NULL DEFAULT 0 CHECK (lifetime_granted >= 0),
  lifetime_spent numeric(18, 4) NOT NULL DEFAULT 0 CHECK (lifetime_spent >= 0),
  version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Which ledger a ledger row belongs to (free = default signup grants).
ALTER TABLE ai.credit_ledger_entries
  ADD COLUMN account_type varchar(16) NOT NULL DEFAULT 'free'
  CHECK (account_type IN ('free', 'member'));

ALTER TABLE ai.credit_ledger_entries
  DROP CONSTRAINT IF EXISTS credit_ledger_entries_user_id_idempotency_key_key;
ALTER TABLE ai.credit_ledger_entries
  ADD CONSTRAINT uq_ai_credit_ledger_user_idem_account
  UNIQUE (user_id, account_type, idempotency_key);

-- Redemption codes: the China-friendly payment path v1 (admin generates codes,
-- user pays via WeChat/Alipay manually and redeems the code for member credits).
CREATE TABLE ai.redemption_codes (
  code varchar(40) PRIMARY KEY,
  amount numeric(18, 4) NOT NULL CHECK (amount > 0),
  status varchar(16) NOT NULL DEFAULT 'unused' CHECK (status IN ('unused', 'redeemed', 'revoked')),
  created_by integer REFERENCES public.users(id),
  redeemed_by integer REFERENCES public.users(id),
  redeemed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ai_redemption_codes_status ON ai.redemption_codes (status, created_at);

COMMIT;
