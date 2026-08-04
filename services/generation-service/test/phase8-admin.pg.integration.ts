import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import { PostgresAdminRepository } from "../src/admin/postgres-admin-repository.ts";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "../src/gallery/asset-url.ts";
import { GalleryError } from "../src/gallery/errors.ts";

const databaseUrl = process.env.PHASE8_TEST_DATABASE_URL;
const USER_ID = 64001;
const PROVIDER_ID = "f13e4567-e89b-42d3-a456-426614174000";
const WORKFLOW_ID = "f23e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "f33e4567-e89b-42d3-a456-426614174000";
const BINDING_ID = "f43e4567-e89b-42d3-a456-426614174000";
const IMAGE_ID = "f53e4567-e89b-42d3-a456-426614174000";
const JOB_ID = "f63e4567-e89b-42d3-a456-426614174000";
const REQUEST_ID = "f73e4567-e89b-42d3-a456-426614174000";

class TestAssetResolver implements GalleryAssetUrlResolver {
  async resolve(asset: GalleryAssetRecord): Promise<string> { return `https://signed.example.test/${asset.objectKey}`; }
}

describe("Phase 8 PostgreSQL Admin integration", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const repository = new PostgresAdminRepository(pool, new TestAssetResolver());

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase8-admin@example.test')", [USER_ID]);
    await pool.query(`INSERT INTO ai.providers (id, code, display_name, adapter_type, status, priority, secret_ref)
      VALUES ($1, 'phase8-comfyui', 'Phase 8 ComfyUI', 'comfyui', 'disabled', 80, 'vault://phase8')`, [PROVIDER_ID]);
    await pool.query(`INSERT INTO ai.workflows (id, slug, name, category, is_enabled, sort_order, created_by_user_id)
      VALUES ($1, 'phase8-portrait', 'Phase 8 Portrait', 'portrait', false, 80, $2)`, [WORKFLOW_ID, USER_ID]);
    await pool.query(`INSERT INTO ai.workflow_versions (id, workflow_id, version, is_active, created_by_user_id)
      VALUES ($1, $2, 1, true, $3)`, [VERSION_ID, WORKFLOW_ID, USER_ID]);
    await pool.query(`INSERT INTO ai.workflow_provider_bindings (id, workflow_version_id, provider_id, provider_workflow_ref)
      VALUES ($1, $2, $3, 'phase8-workflow.json')`, [BINDING_ID, VERSION_ID, PROVIDER_ID]);
    await pool.query(`INSERT INTO ai.generation_jobs (id, user_id, workflow_version_id, status, prompt, requested_width, requested_height)
      VALUES ($1, $2, $3, 'completed', 'phase8 test prompt', 512, 512)`, [JOB_ID, USER_ID, VERSION_ID]);
    await pool.query(`INSERT INTO ai.images (id, job_id, creator_user_id, provider_id, workflow_version_id, slug, title, prompt, negative_prompt,
        provider_code_snapshot, workflow_name_snapshot, width, height, visibility, prompt_visibility, moderation_status)
      VALUES ($1, $2, $3, $4, $5, 'phase8-review-image', 'Review image', 'hidden prompt', '', 'phase8-comfyui', 'Phase 8 Portrait', 512, 512, 'public', 'hidden', 'manual_review')`, [IMAGE_ID, JOB_ID, USER_ID, PROVIDER_ID, VERSION_ID]);
    await pool.query(`INSERT INTO ai.image_assets (image_id, variant, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256)
      VALUES ($1, 'thumbnail', 'bucket-test', 'ap-test', 'images/phase8-review.webp', NULL, 'image/webp', 10, 512, 512, repeat('d', 64))`, [IMAGE_ID]);
  });

  after(async () => {
    await pool.query("DELETE FROM ai.audit_logs WHERE resource_id = ANY($1::text[])", [[IMAGE_ID, PROVIDER_ID, WORKFLOW_ID]]);
    await pool.query("DELETE FROM ai.images WHERE id = $1", [IMAGE_ID]);
    await pool.query("DELETE FROM ai.generation_jobs WHERE id = $1", [JOB_ID]);
    await pool.query("DELETE FROM ai.workflows WHERE id = $1", [WORKFLOW_ID]);
    await pool.query("DELETE FROM ai.providers WHERE id = $1", [PROVIDER_ID]);
    await pool.query("DELETE FROM public.users WHERE id = $1", [USER_ID]);
    await pool.end();
  });

  it("reads safe dashboard data and commits moderated/config changes with audit and optimistic concurrency", async () => {
    const dashboard = await repository.dashboard();
    const image = dashboard.moderationQueue.find((item) => item.id === IMAGE_ID);
    const provider = dashboard.providers.find((item) => item.id === PROVIDER_ID);
    const workflow = dashboard.workflows.find((item) => item.id === WORKFLOW_ID);
    assert.ok(image && provider && workflow);
    assert.equal(image.thumbnailUrl, "https://signed.example.test/images/phase8-review.webp");
    assert.equal(provider.secretConfigured, true);
    assert.equal("secretRef" in provider, false);

    const approved = await repository.moderateImage(IMAGE_ID, { decision: "approved", reasonCodes: ["manual_approved"], expectedUpdatedAt: image.updatedAt }, USER_ID, REQUEST_ID);
    assert.equal(approved.moderationStatus, "approved");
    const state = await pool.query<{ published_at: Date | null }>("SELECT published_at FROM ai.images WHERE id = $1", [IMAGE_ID]);
    assert.ok(state.rows[0]?.published_at);
    await assert.rejects(repository.moderateImage(IMAGE_ID, { decision: "rejected", reasonCodes: [], expectedUpdatedAt: image.updatedAt }, USER_ID, REQUEST_ID), (error: unknown) => error instanceof GalleryError && error.code === "conflict");

    const activated = await repository.updateProvider(PROVIDER_ID, { status: "active", priority: 5, expectedUpdatedAt: provider.updatedAt }, USER_ID, REQUEST_ID);
    assert.equal(activated.status, "active");
    assert.equal(activated.priority, 5);
    const enabled = await repository.updateWorkflow(WORKFLOW_ID, { isEnabled: true, sortOrder: 5, expectedUpdatedAt: workflow.updatedAt }, USER_ID, REQUEST_ID);
    assert.equal(enabled.isEnabled, true);
    assert.equal(enabled.activeVersion, 1);
    assert.equal(enabled.bindingCount, 1);

    const audit = await pool.query<{ action: string }>("SELECT action FROM ai.audit_logs WHERE actor_user_id = $1 ORDER BY id", [USER_ID]);
    assert.deepEqual(audit.rows.map((row) => row.action), ["admin.image_moderated", "admin.provider_updated", "admin.workflow_updated"]);
    const moderation = await pool.query("SELECT 1 FROM ai.moderation_events WHERE image_id = $1 AND reviewer_user_id = $2 AND decision = 'approved'", [IMAGE_ID, USER_ID]);
    assert.equal(moderation.rowCount, 1);
  });
});
