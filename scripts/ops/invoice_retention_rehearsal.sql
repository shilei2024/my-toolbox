-- Rehearsal ONLY: generated from revision e4f5a6b7c8d9.
-- Never run against production. Exact database guard executes before any DDL.
-- Source SHA-256: e4dd836c3fda160ece96ae461cd8dad2987a4cb52072e0b498b1d43a058589ef
\set ON_ERROR_STOP on
SET search_path TO public, pg_catalog;
DO $guard$
BEGIN
    IF current_database() <> 'mytoolbox_invoice_verify_20261028_111850' THEN
        RAISE EXCEPTION 'Refusing to run outside the designated rehearsal database';
    END IF;
    IF (SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) IS DISTINCT FROM 'd3e4f5a6b7c8' THEN
        RAISE EXCEPTION 'Unexpected rehearsal migration revision; do not rerun blindly';
    END IF;
    IF to_regclass('public.reimbursement_audits') IS NOT NULL THEN
        RAISE EXCEPTION 'Audit table already exists; rehearsal database is not at baseline';
    END IF;
END
$guard$;
CREATE TEMP TABLE invoice_rehearsal_baseline ON COMMIT PRESERVE ROWS AS
SELECT
    (SELECT count(*) FROM public.reimbursement_invoices) AS invoice_count,
    (SELECT md5(COALESCE(string_agg(md5(to_jsonb(i)::text), '' ORDER BY i.id), ''))
        FROM public.reimbursement_invoices i) AS invoice_hash,
    (SELECT count(*) FROM public.reimbursement_attachments) AS attachment_count,
    (SELECT md5(COALESCE(string_agg(md5(to_jsonb(a)::text), '' ORDER BY a.id), ''))
        FROM public.reimbursement_attachments a) AS attachment_hash;
CREATE FUNCTION pg_temp.invoice_rehearsal_assert_unchanged() RETURNS void
LANGUAGE plpgsql AS $check$
DECLARE
    baseline record;
    invoices_hash text;
    attachments_hash text;
BEGIN
    SELECT * INTO STRICT baseline FROM pg_temp.invoice_rehearsal_baseline;
    SELECT md5(COALESCE(string_agg(md5((to_jsonb(i) - ARRAY[
        'inclusion_policy', 'document_kind', 'occurrence_month', 'settlement_month',
        'print_selected', 'amount_confirmed'])::text), '' ORDER BY i.id), ''))
        INTO invoices_hash FROM public.reimbursement_invoices i;
    SELECT md5(COALESCE(string_agg(md5(to_jsonb(a)::text), '' ORDER BY a.id), ''))
        INTO attachments_hash FROM public.reimbursement_attachments a;
    IF invoices_hash IS DISTINCT FROM baseline.invoice_hash
       OR (SELECT count(*) FROM public.reimbursement_invoices) <> baseline.invoice_count THEN
        RAISE EXCEPTION 'Historical invoices changed during rehearsal';
    END IF;
    IF attachments_hash IS DISTINCT FROM baseline.attachment_hash
       OR (SELECT count(*) FROM public.reimbursement_attachments) <> baseline.attachment_count THEN
        RAISE EXCEPTION 'Historical attachments changed during rehearsal';
    END IF;
END
$check$;
BEGIN;
ALTER TABLE reimbursement_invoices ADD COLUMN inclusion_policy VARCHAR(16) DEFAULT 'expense' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN document_kind VARCHAR(16) DEFAULT 'invoice' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN occurrence_month VARCHAR(7) DEFAULT '' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN settlement_month VARCHAR(7) DEFAULT '' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN print_selected BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN amount_confirmed BOOLEAN DEFAULT true NOT NULL;

CREATE TABLE reimbursement_audits (
    id SERIAL NOT NULL, 
    owner_type VARCHAR(8) NOT NULL, 
    owner_id VARCHAR(64) NOT NULL, 
    period_id INTEGER NOT NULL, 
    action VARCHAR(40) NOT NULL, 
    data_json TEXT NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_reimbursement_audits_period_id ON reimbursement_audits (period_id);
UPDATE public.alembic_version SET version_num = 'e4f5a6b7c8d9' WHERE version_num = 'd3e4f5a6b7c8';
DO $defaults$
BEGIN
    IF EXISTS (SELECT 1 FROM public.reimbursement_invoices WHERE
        inclusion_policy IS DISTINCT FROM 'expense' OR document_kind IS DISTINCT FROM 'invoice'
        OR occurrence_month IS DISTINCT FROM '' OR settlement_month IS DISTINCT FROM ''
        OR print_selected IS DISTINCT FROM true OR amount_confirmed IS DISTINCT FROM true) THEN
        RAISE EXCEPTION 'Historical invoice defaults were not preserved';
    END IF;
    IF to_regclass('public.reimbursement_audits') IS NULL
       OR to_regclass('public.ix_reimbursement_audits_period_id') IS NULL THEN
        RAISE EXCEPTION 'Audit schema is incomplete';
    END IF;
END
$defaults$;
SELECT pg_temp.invoice_rehearsal_assert_unchanged();
COMMIT;
SELECT 'UPGRADE_OK' AS rehearsal_status;
BEGIN;
DROP INDEX ix_reimbursement_audits_period_id;

DROP TABLE reimbursement_audits;

ALTER TABLE reimbursement_invoices DROP COLUMN amount_confirmed;

ALTER TABLE reimbursement_invoices DROP COLUMN print_selected;

ALTER TABLE reimbursement_invoices DROP COLUMN settlement_month;

ALTER TABLE reimbursement_invoices DROP COLUMN occurrence_month;

ALTER TABLE reimbursement_invoices DROP COLUMN document_kind;

ALTER TABLE reimbursement_invoices DROP COLUMN inclusion_policy;
UPDATE public.alembic_version SET version_num = 'd3e4f5a6b7c8' WHERE version_num = 'e4f5a6b7c8d9';
SELECT pg_temp.invoice_rehearsal_assert_unchanged();
COMMIT;
SELECT 'ROLLBACK_OK' AS rehearsal_status;
BEGIN;
ALTER TABLE reimbursement_invoices ADD COLUMN inclusion_policy VARCHAR(16) DEFAULT 'expense' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN document_kind VARCHAR(16) DEFAULT 'invoice' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN occurrence_month VARCHAR(7) DEFAULT '' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN settlement_month VARCHAR(7) DEFAULT '' NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN print_selected BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE reimbursement_invoices ADD COLUMN amount_confirmed BOOLEAN DEFAULT true NOT NULL;

CREATE TABLE reimbursement_audits (
    id SERIAL NOT NULL, 
    owner_type VARCHAR(8) NOT NULL, 
    owner_id VARCHAR(64) NOT NULL, 
    period_id INTEGER NOT NULL, 
    action VARCHAR(40) NOT NULL, 
    data_json TEXT NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_reimbursement_audits_period_id ON reimbursement_audits (period_id);
UPDATE public.alembic_version SET version_num = 'e4f5a6b7c8d9' WHERE version_num = 'd3e4f5a6b7c8';
DO $defaults$
BEGIN
    IF EXISTS (SELECT 1 FROM public.reimbursement_invoices WHERE
        inclusion_policy IS DISTINCT FROM 'expense' OR document_kind IS DISTINCT FROM 'invoice'
        OR occurrence_month IS DISTINCT FROM '' OR settlement_month IS DISTINCT FROM ''
        OR print_selected IS DISTINCT FROM true OR amount_confirmed IS DISTINCT FROM true) THEN
        RAISE EXCEPTION 'Historical invoice defaults were not preserved';
    END IF;
    IF to_regclass('public.reimbursement_audits') IS NULL
       OR to_regclass('public.ix_reimbursement_audits_period_id') IS NULL THEN
        RAISE EXCEPTION 'Audit schema is incomplete';
    END IF;
END
$defaults$;
SELECT pg_temp.invoice_rehearsal_assert_unchanged();
COMMIT;
SELECT 'REUPGRADE_OK' AS rehearsal_status;
SELECT version_num FROM public.alembic_version;
SELECT invoice_count, attachment_count FROM pg_temp.invoice_rehearsal_baseline;
SELECT 'MIGRATION_REHEARSAL_OK' AS rehearsal_status;
