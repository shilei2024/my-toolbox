from __future__ import annotations

import re
import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).parents[1]
    / "services"
    / "generation-service"
    / "database"
    / "migrations"
    / "0001_initial.sql"
)
GALLERY_MIGRATION = MIGRATION.with_name("0002_gallery_system.sql")
ADMIN_MIGRATION = MIGRATION.with_name("0003_admin_console.sql")
MULTI_PROVIDER_MIGRATION = MIGRATION.with_name("0004_multi_provider.sql")
REMOTE_BINDINGS_MIGRATION = MIGRATION.with_name("0007_remote_provider_bindings.sql")
GALLERY_REPOSITORY = MIGRATION.parents[2] / "src" / "gallery" / "postgres-gallery-repository.ts"


class AIImageSchemaContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.normalized = re.sub(r"\s+", " ", cls.sql.lower()).strip()

    def test_migration_is_transactional_and_uses_isolated_schema(self):
        self.assertTrue(self.normalized.startswith("begin;"))
        self.assertTrue(self.normalized.endswith("commit;"))
        self.assertIn("create schema if not exists ai", self.normalized)

    def test_all_required_domain_tables_exist(self):
        tables = set(re.findall(r"create table ai\.([a-z_]+)", self.normalized))
        required = {
            "providers",
            "workflows",
            "workflow_versions",
            "workflow_provider_bindings",
            "generation_jobs",
            "generation_attempts",
            "images",
            "image_assets",
            "tags",
            "image_tags",
            "likes",
            "favorites",
            "comments",
            "download_logs",
            "moderation_events",
            "audit_logs",
            "system_settings",
            "outbox_events",
        }
        self.assertEqual(required - tables, set())

    def test_public_job_state_contract_is_exact(self):
        self.assertIn(
            "create type ai.job_status as enum ('pending', 'running', 'completed', 'failed', 'cancelled')",
            self.normalized,
        )

    def test_provider_is_decoupled_from_workflow(self):
        self.assertIn(
            "unique (workflow_version_id, provider_id)",
            self.normalized,
        )
        self.assertIn("provider_workflow_ref varchar(255)", self.normalized)
        self.assertIn("provider_config jsonb", self.normalized)

    def test_idempotency_and_attempt_uniqueness_are_enforced(self):
        self.assertIn("uq_ai_job_user_idempotency", self.normalized)
        self.assertIn("where user_id is not null and idempotency_key is not null", self.normalized)
        self.assertIn("unique (job_id, attempt_no)", self.normalized)

    def test_privacy_moderation_and_soft_delete_gate_public_gallery(self):
        self.assertIn("visibility ai.image_visibility", self.normalized)
        self.assertIn("prompt_visibility ai.prompt_visibility", self.normalized)
        self.assertIn("moderation_status ai.moderation_status", self.normalized)
        self.assertIn(
            "where visibility = 'public' and moderation_status = 'approved' and deleted_at is null",
            self.normalized,
        )

    def test_tencent_cos_is_default_but_storage_is_adapter_based(self):
        self.assertIn(
            "storage_provider varchar(32) not null default 'tencent_cos'",
            self.normalized,
        )
        for field in ("bucket", "region", "object_key", "public_url", "sha256"):
            self.assertRegex(self.normalized, rf"\b{field}\b")

    def test_secrets_are_references_not_plaintext_credentials(self):
        self.assertIn("secret_ref varchar(255)", self.normalized)
        forbidden_columns = re.findall(
            r"^\s*(api_key|secret_key|access_key|access_key_secret)\s+",
            self.sql,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        self.assertEqual(forbidden_columns, [])

    def test_community_actions_are_unique_and_assets_are_cascade_owned(self):
        self.assertGreaterEqual(
            self.normalized.count("primary key (image_id, user_id)"), 2
        )
        self.assertIn(
            "image_id uuid not null references ai.images(id) on delete cascade",
            self.normalized,
        )
        self.assertIn("unique (storage_provider, bucket, object_key)", self.normalized)

    def test_outbox_has_recovery_index(self):
        self.assertIn("create table ai.outbox_events", self.normalized)
        self.assertIn("ix_ai_outbox_pending", self.normalized)
        self.assertIn("where published_at is null", self.normalized)

    def test_phase_6_gallery_migration_preserves_counts_and_deferred_deletion(self):
        sql = re.sub(r"\s+", " ", GALLERY_MIGRATION.read_text(encoding="utf-8").lower()).strip()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("commit;"))
        self.assertIn("create table ai.user_profiles", sql)
        self.assertIn("create table ai.asset_deletion_tasks", sql)
        repository = re.sub(r"\s+", " ", GALLERY_REPOSITORY.read_text(encoding="utf-8").lower())
        self.assertIn("for update skip locked", repository)
        self.assertIn("trg_ai_likes_counter", sql)
        self.assertIn("trg_ai_favorites_counter", sql)
        self.assertIn("trg_ai_downloads_counter", sql)
        self.assertIn("(published_at desc, id desc)", sql)

    def test_phase_8_admin_migration_adds_bounded_read_indexes(self):
        sql = re.sub(r"\s+", " ", ADMIN_MIGRATION.read_text(encoding="utf-8").lower()).strip()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("commit;"))
        self.assertIn("ix_ai_images_moderation_created", sql)
        self.assertIn("where deleted_at is null", sql)
        self.assertIn("ix_ai_audit_created", sql)

    def test_phase_9_model_registry_enforces_provider_ownership(self):
        sql = re.sub(r"\s+", " ", MULTI_PROVIDER_MIGRATION.read_text(encoding="utf-8").lower()).strip()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("commit;"))
        self.assertIn("create table ai.provider_models", sql)
        self.assertIn("uq_ai_provider_one_default_model", sql)
        self.assertIn("add column provider_model_id uuid", sql)
        self.assertIn("foreign key (provider_id, provider_model_id)", sql)
        self.assertIn("references ai.provider_models(provider_id, id)", sql)
        self.assertIn("'openai'", sql)
        self.assertIn("'gemini'", sql)
        self.assertIn("'jimeng'", sql)

    def test_phase_11_remote_provider_bindings_are_operational(self):
        sql = re.sub(r"\s+", " ", REMOTE_BINDINGS_MIGRATION.read_text(encoding="utf-8").lower()).strip()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("commit;"))
        self.assertIn("insert into ai.workflow_provider_bindings", sql)
        self.assertIn("provider_model_id", sql)
        self.assertIn("m.is_default and m.is_enabled", sql)
        self.assertIn("on conflict (workflow_version_id, provider_id) do nothing", sql)
        for code in ("'jimeng'", "'openai'", "'gemini'"):
            self.assertIn(code, sql)


if __name__ == "__main__":
    unittest.main()
