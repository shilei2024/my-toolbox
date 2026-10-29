-- Rehearsal ONLY. Never run against production; exact DB guard precedes DDL.
-- Actual revision f5a6b7c8d9e0; source SHA-256: 42b3e6c6a337a0066dd52bf61a9f35ce1ee7536e1c6effcc2ec7c74123fefcd8
\set ON_ERROR_STOP on
SET search_path TO public, pg_catalog;
SET lock_timeout = '15s';
SET statement_timeout = '120s';
DO $guard$
BEGIN
    IF current_database() <> 'mytoolbox_invoice_verify_20261028_111850' THEN
        RAISE EXCEPTION 'Refusing to run outside the designated rehearsal database';
    END IF;
    IF (SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) IS DISTINCT FROM 'e4f5a6b7c8d9' THEN
        RAISE EXCEPTION 'Expected e4 rehearsal baseline; do not rerun blindly';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='reimbursement_attachments' AND column_name='content_sha256')
       OR to_regclass('public.account_external_identities') IS NOT NULL
       OR to_regclass('public.account_binding_challenges') IS NOT NULL
       OR to_regclass('public.account_mobile_sessions') IS NOT NULL
       OR to_regclass('public.account_mobile_audits') IS NOT NULL
       OR to_regclass('public.reimbursement_upload_receipts') IS NOT NULL THEN
        RAISE EXCEPTION 'Mobile schema already exists; stop and inspect';
    END IF;
END
$guard$;
CREATE TEMP TABLE mobile_rehearsal_baseline ON COMMIT PRESERVE ROWS AS
SELECT
    (SELECT count(*) FROM public.users) AS user_count,
    (SELECT md5(COALESCE(string_agg(md5(to_jsonb(u)::text), '' ORDER BY u.id), '')) FROM public.users u) AS user_hash,
    (SELECT count(*) FROM public.reimbursement_invoices) AS invoice_count,
    (SELECT md5(COALESCE(string_agg(md5(to_jsonb(i)::text), '' ORDER BY i.id), '')) FROM public.reimbursement_invoices i) AS invoice_hash,
    (SELECT count(*) FROM public.reimbursement_attachments) AS attachment_count,
    (SELECT md5(COALESCE(string_agg(md5(to_jsonb(a)::text), '' ORDER BY a.id), '')) FROM public.reimbursement_attachments a) AS attachment_hash;
CREATE FUNCTION pg_temp.mobile_rehearsal_assert_unchanged() RETURNS void
LANGUAGE plpgsql AS $check$
DECLARE
    baseline record;
BEGIN
    SELECT * INTO STRICT baseline FROM pg_temp.mobile_rehearsal_baseline;
    IF (SELECT count(*) FROM public.users) <> baseline.user_count
       OR (SELECT md5(COALESCE(string_agg(md5(to_jsonb(u)::text), '' ORDER BY u.id), '')) FROM public.users u) IS DISTINCT FROM baseline.user_hash THEN
        RAISE EXCEPTION 'Historical users changed during rehearsal';
    END IF;
    IF (SELECT count(*) FROM public.reimbursement_invoices) <> baseline.invoice_count
       OR (SELECT md5(COALESCE(string_agg(md5(to_jsonb(i)::text), '' ORDER BY i.id), '')) FROM public.reimbursement_invoices i) IS DISTINCT FROM baseline.invoice_hash THEN
        RAISE EXCEPTION 'Historical invoice amounts or retention metadata changed during rehearsal';
    END IF;
    IF (SELECT count(*) FROM public.reimbursement_attachments) <> baseline.attachment_count
       OR (SELECT md5(COALESCE(string_agg(md5((to_jsonb(a) - 'content_sha256')::text), '' ORDER BY a.id), '')) FROM public.reimbursement_attachments a) IS DISTINCT FROM baseline.attachment_hash THEN
        RAISE EXCEPTION 'Historical original BLOBs changed during rehearsal';
    END IF;
END
$check$;
CREATE FUNCTION pg_temp.mobile_rehearsal_assert_schema() RETURNS void
LANGUAGE plpgsql AS $schema$
DECLARE
    table_name text;
BEGIN
    IF (SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) IS DISTINCT FROM 'f5a6b7c8d9e0' THEN
        RAISE EXCEPTION 'Mobile revision was not applied';
    END IF;
    FOREACH table_name IN ARRAY ARRAY['account_external_identities','account_binding_challenges','account_mobile_sessions','account_mobile_audits','reimbursement_upload_receipts'] LOOP
        IF to_regclass('public.' || table_name) IS NULL THEN
            RAISE EXCEPTION 'Mobile table is missing';
        END IF;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.reimbursement_attachments'::regclass AND conname='uq_rb_attachment_content')
       OR EXISTS (SELECT 1 FROM public.reimbursement_attachments WHERE content_sha256 IS NOT NULL) THEN
        RAISE EXCEPTION 'Attachment unique constraint or legacy NULL digests invalid';
    END IF;
END
$schema$;
BEGIN;
CREATE TABLE account_external_identities (
    id SERIAL NOT NULL,
    provider VARCHAR(32) NOT NULL,
    client_id VARCHAR(64) NOT NULL,
    subject VARCHAR(128) NOT NULL,
    user_id INTEGER,
    active BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_external_identity_subject UNIQUE (provider, client_id, subject),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_account_external_identities_user_id ON account_external_identities (user_id);

CREATE TABLE account_binding_challenges (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    provider VARCHAR(32) NOT NULL,
    client_id VARCHAR(64) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    UNIQUE (token_hash)
);

CREATE INDEX ix_account_binding_challenges_user_id ON account_binding_challenges (user_id);

CREATE TABLE account_mobile_sessions (
    id SERIAL NOT NULL,
    identity_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(identity_id) REFERENCES account_external_identities (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    UNIQUE (token_hash)
);

CREATE INDEX ix_account_mobile_sessions_identity_id ON account_mobile_sessions (identity_id);

CREATE TABLE account_mobile_audits (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    action VARCHAR(48) NOT NULL,
    details_json TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_account_mobile_audits_user_id ON account_mobile_audits (user_id);

CREATE TABLE reimbursement_upload_receipts (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    idempotency_key VARCHAR(80) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    invoice_id INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_rb_upload_receipt_key UNIQUE (user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(invoice_id) REFERENCES reimbursement_invoices (id) ON DELETE SET NULL
);

ALTER TABLE reimbursement_attachments ADD COLUMN content_sha256 VARCHAR(64);

ALTER TABLE reimbursement_attachments ADD CONSTRAINT uq_rb_attachment_content UNIQUE (owner_type, owner_id, content_sha256);
UPDATE public.alembic_version SET version_num='f5a6b7c8d9e0' WHERE version_num='e4f5a6b7c8d9';
SELECT pg_temp.mobile_rehearsal_assert_unchanged();
SELECT pg_temp.mobile_rehearsal_assert_schema();
COMMIT;
SELECT 'MOBILE_UPGRADE_OK' AS rehearsal_status;
BEGIN;
DROP TABLE reimbursement_upload_receipts;

DROP TABLE account_mobile_sessions;

DROP TABLE account_binding_challenges;

DROP TABLE account_mobile_audits;

DROP TABLE account_external_identities;

ALTER TABLE reimbursement_attachments DROP CONSTRAINT uq_rb_attachment_content;

ALTER TABLE reimbursement_attachments DROP COLUMN content_sha256;
UPDATE public.alembic_version SET version_num='e4f5a6b7c8d9' WHERE version_num='f5a6b7c8d9e0';
SELECT pg_temp.mobile_rehearsal_assert_unchanged();
COMMIT;
SELECT 'MOBILE_ROLLBACK_OK' AS rehearsal_status;
BEGIN;
CREATE TABLE account_external_identities (
    id SERIAL NOT NULL,
    provider VARCHAR(32) NOT NULL,
    client_id VARCHAR(64) NOT NULL,
    subject VARCHAR(128) NOT NULL,
    user_id INTEGER,
    active BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_external_identity_subject UNIQUE (provider, client_id, subject),
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_account_external_identities_user_id ON account_external_identities (user_id);

CREATE TABLE account_binding_challenges (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    provider VARCHAR(32) NOT NULL,
    client_id VARCHAR(64) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    consumed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    UNIQUE (token_hash)
);

CREATE INDEX ix_account_binding_challenges_user_id ON account_binding_challenges (user_id);

CREATE TABLE account_mobile_sessions (
    id SERIAL NOT NULL,
    identity_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(identity_id) REFERENCES account_external_identities (id),
    FOREIGN KEY(user_id) REFERENCES users (id),
    UNIQUE (token_hash)
);

CREATE INDEX ix_account_mobile_sessions_identity_id ON account_mobile_sessions (identity_id);

CREATE TABLE account_mobile_audits (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    action VARCHAR(48) NOT NULL,
    details_json TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_account_mobile_audits_user_id ON account_mobile_audits (user_id);

CREATE TABLE reimbursement_upload_receipts (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    idempotency_key VARCHAR(80) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    invoice_id INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_rb_upload_receipt_key UNIQUE (user_id, idempotency_key),
    FOREIGN KEY(user_id) REFERENCES users (id),
    FOREIGN KEY(invoice_id) REFERENCES reimbursement_invoices (id) ON DELETE SET NULL
);

ALTER TABLE reimbursement_attachments ADD COLUMN content_sha256 VARCHAR(64);

ALTER TABLE reimbursement_attachments ADD CONSTRAINT uq_rb_attachment_content UNIQUE (owner_type, owner_id, content_sha256);
UPDATE public.alembic_version SET version_num='f5a6b7c8d9e0' WHERE version_num='e4f5a6b7c8d9';
SELECT pg_temp.mobile_rehearsal_assert_unchanged();
SELECT pg_temp.mobile_rehearsal_assert_schema();
COMMIT;
SELECT 'MOBILE_REUPGRADE_OK' AS rehearsal_status;
SELECT version_num FROM public.alembic_version;
SELECT user_count, invoice_count, attachment_count FROM pg_temp.mobile_rehearsal_baseline;
SELECT 'MOBILE_MIGRATION_REHEARSAL_OK' AS rehearsal_status;
