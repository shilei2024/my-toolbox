import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import { GenerationError } from "../src/generation/errors.ts";
import { PostgresGenerationRepository } from "../src/generation/postgres-generation-repository.ts";
import { PostgresGenerationJobRepository } from "../src/queue/postgres-generation-job-repository.ts";

const databaseUrl = process.env.PHASE13_TEST_DATABASE_URL;
const USER_ID = 9013;
const WORKFLOW_ID = "b13e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "b23e4567-e89b-42d3-a456-426614174000";
const JOB_ID = "b33e4567-e89b-42d3-a456-426614174000";
const ASSET_ID = "b43e4567-e89b-42d3-a456-426614174000";
const PROJECTION_JOB_ID = "b53e4567-e89b-42d3-a456-426614174000";
const PROJECTION_ATTEMPT_ID = "b63e4567-e89b-42d3-a456-426614174000";
const BINDING_ID = "b73e4567-e89b-42d3-a456-426614174000";

describe("Phase 13 PostgreSQL media generation", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });

  before(async () => {
    await pool.query("DELETE FROM ai.generation_assets WHERE job_id = $1", [JOB_ID]);
    await pool.query("DELETE FROM ai.generation_jobs WHERE id = $1", [JOB_ID]);
    await pool.query("DELETE FROM ai.workflow_versions WHERE id = $1", [VERSION_ID]);
    await pool.query("DELETE FROM ai.workflows WHERE id = $1", [WORKFLOW_ID]);
    // credit_ledger_entries 不可变且 users 被积分表 RESTRICT 引用：测试用户与
    // 积分账户均改为幂等写入，避免依赖破坏性清理，保证套件可重复运行。
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase13-media@example.test') ON CONFLICT (id) DO NOTHING", [USER_ID]);
    await pool.query(
      "INSERT INTO ai.credit_accounts (user_id, available_amount, lifetime_granted) VALUES ($1, 100, 100) ON CONFLICT (user_id) DO UPDATE SET available_amount = EXCLUDED.available_amount",
      [USER_ID],
    );
    await pool.query("UPDATE ai.providers SET status = 'active' WHERE code = 'comfyui'");
    await pool.query(
      `INSERT INTO ai.workflows (id, slug, name, category, mode, media_type, is_enabled)
       VALUES ($1, 'phase13-media-test', 'Phase 13 Media', 'test', 'workflow', 'video', true)`,
      [WORKFLOW_ID],
    );
    await pool.query(
      "INSERT INTO ai.workflow_versions (id, workflow_id, version, is_active) VALUES ($1, $2, 1, true)",
      [VERSION_ID, WORKFLOW_ID],
    );
    await pool.query(
      `INSERT INTO ai.generation_jobs (id, user_id, workflow_version_id, prompt, requested_width, requested_height, status)
       VALUES ($1, $2, $3, 'media test', 960, 544, 'completed')`,
      [JOB_ID, USER_ID, VERSION_ID],
    );
    await pool.query(
      `INSERT INTO ai.generation_assets (
         id, job_id, media_type, position, storage_provider, bucket, region,
         object_key, asset_url, mime_type, byte_size, width, height, duration_seconds, sha256
       ) VALUES (
         $1, $2, 'video', 0, 'tencent_cos', 'bucket', 'ap-guangzhou',
         'videos/9013/job/0.mp4', 'https://cdn.example/videos/9013/job/0.mp4',
         'video/mp4', 1024, 960, 544, 5, repeat('a', 64)
       )`,
      [ASSET_ID, JOB_ID],
    );
  });

  after(async () => {
    await pool.query("DELETE FROM ai.image_assets WHERE image_id IN (SELECT id FROM ai.images WHERE job_id = $1)", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.images WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_assets WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_attempts WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_jobs WHERE id = $1", [PROJECTION_JOB_ID]);
    await pool.query("UPDATE ai.providers SET status = 'disabled' WHERE code = 'comfyui'");
    await pool.end();
  });

  it("keeps media workflows fail-closed and stores durable owner-scoped video assets", async () => {
    const workflows = await pool.query<{ slug: string; media_type: string; is_enabled: boolean }>(
      `SELECT slug, media_type, is_enabled FROM ai.workflows
       WHERE slug IN ('comfyui-ltx-video-v1', 'api-ark-video-doubao-seedance-2-0-260128')
       ORDER BY slug`,
    );
    assert.deepEqual(workflows.rows, [
      { slug: "api-ark-video-doubao-seedance-2-0-260128", media_type: "video", is_enabled: false },
      { slug: "comfyui-ltx-video-v1", media_type: "video", is_enabled: false },
    ]);

    const assets = await pool.query<{
      id: string;
      media_type: string;
      object_key: string;
      url: string;
      mime_type: string;
      byte_size: string;
      width: number;
      height: number;
      duration_seconds: string;
      sha256: string;
    }>(
      `SELECT a.id, a.media_type, a.object_key, a.asset_url AS url, a.mime_type,
              a.byte_size, a.width, a.height, a.duration_seconds, a.sha256
       FROM ai.generation_assets a WHERE a.job_id = $1 ORDER BY a.position`,
      [JOB_ID],
    );
    assert.equal(assets.rows.length, 1);
    assert.equal(assets.rows[0]?.object_key, "videos/9013/job/0.mp4");
    assert.equal(assets.rows[0]?.mime_type, "video/mp4");
    assert.equal(assets.rows[0]?.byte_size, "1024");
    assert.equal(assets.rows[0]?.width, 960);
    assert.equal(assets.rows[0]?.height, 544);
    assert.equal(assets.rows[0]?.duration_seconds, "5.000");
    assert.equal(assets.rows[0]?.sha256, "a".repeat(64));
  });

  it("exposes H3 mode metadata via listWorkflows and enforces reference image rules on create", async () => {
    const repository = new PostgresGenerationRepository(pool);
    // ① 迁移 0019/0021 写入的 mode_meta 与 videoResolutions 必须透传到工作流
    //    视图：否则前端拿不到 maxImages，H3 单图/多图参考的上传入口不渲染
    //    （0.9.6 线上"无上传入口"的根因），分辨率档位也会 fallback 到默认 1080p/2K。
    const videoWorkflows = await repository.listWorkflows("0.1000", "workflow", "video");
    const byMode = new Map(videoWorkflows.filter((item) => item.category === "MiniMax H3").map((item) => [item.defaults.modeMeta?.key, item]));
    assert.equal(byMode.get("t2v")?.defaults.modeMeta?.maxImages, 0, "t2v 文生视频不要求参考图");
    assert.equal(byMode.get("t2v")?.defaults.modeMeta?.label, "文生视频");
    assert.equal(byMode.get("i2v")?.defaults.modeMeta?.maxImages, 1, "i2v 单图参考要求 1 张");
    assert.equal(byMode.get("ref")?.defaults.modeMeta?.maxImages, 3, "ref 多图参考最多 3 张");
    for (const item of byMode.values()) {
      assert.ok(Array.isArray(item.defaults.videoResolutions) && item.defaults.videoResolutions.length > 0, "H3 工作流必须透传 0021 的限档分辨率");
      assert.deepEqual(item.defaults.videoResolutions?.map((entry) => entry.key), ["480p", "720p"]);
    }
    // ② 无 mode_meta 的普通工作流：字段省略（undefined），前端 fallback 到默认 UI。
    //    listWorkflows 要求工作流至少有一个启用的 provider binding，先给装置
    //    工作流绑定 comfyui（defaults 保持为空对象，不带 mode_meta）。
    await pool.query("UPDATE ai.workflow_versions SET defaults = '{}'::jsonb WHERE id = $1", [VERSION_ID]);
    await pool.query(
      `INSERT INTO ai.workflow_provider_bindings (id, workflow_version_id, provider_id, provider_workflow_ref)
       SELECT $1, $2, p.id, 'phase13-media-test.json' FROM ai.providers p WHERE p.code = 'comfyui'
       ON CONFLICT (workflow_version_id, provider_id) DO UPDATE SET is_enabled = true`,
      [BINDING_ID, VERSION_ID],
    );
    const visible = await repository.listWorkflows("0.1000", "workflow", "video");
    const plain = visible.find((item) => item.slug === "phase13-media-test");
    assert.ok(plain);
    assert.equal(plain.defaults.modeMeta, undefined);
    assert.equal(plain.defaults.videoResolutions, undefined);

    // ③ 参考图模式的服务端强制校验：给装置工作流写入 maxImages=1 的 mode_meta
    //    后，空参考图提交必须在 create 内被 400 拒绝且任务不落库。
    await pool.query(
      `UPDATE ai.workflow_versions SET defaults = jsonb_build_object(
         'width', 960, 'height', 544, 'count', 1,
         'visibility', 'public', 'prompt_visibility', 'public', 'duration_seconds', 5,
         'mode_meta', jsonb_build_object('key', 'i2v', 'label', '单图生视频', 'maxImages', 1)
       ) WHERE id = $1`,
      [VERSION_ID],
    );
    const withModeMeta = await repository.listWorkflows("0.1000", "workflow", "video");
    assert.equal(withModeMeta.find((item) => item.slug === "phase13-media-test")?.defaults.modeMeta?.maxImages, 1, "写入 mode_meta 后立即透传");
    await assert.rejects(
      repository.create({
        userId: USER_ID, requestId: "phase13-ref-guard", idempotencyKey: "phase13-ref-guard-1",
        workflowSlug: "phase13-media-test", prompt: "需要参考图的模式", negativePrompt: "",
        width: 960, height: 544, count: 1, visibility: "public", promptVisibility: "public",
        parameters: { durationSeconds: 5 }, creditTier: "free",
      }, "0.1000"),
      (error: unknown) => error instanceof GenerationError && error.code === "invalid_request" && /参考图/.test(error.message),
    );
    const leaked = await pool.query("SELECT 1 FROM ai.generation_jobs WHERE idempotency_key = 'phase13-ref-guard-1'");
    assert.equal(leaked.rowCount, 0, "被拒绝的请求不得留下任务记录");
    // ④ 超出 maxImages 的提交同样拒绝（maxImages=1 时传 2 张由 persistInputImages 之前的
    //    数量校验兜底，此处校验 parameters 合并后的上限）。
    await assert.rejects(
      repository.create({
        userId: USER_ID, requestId: "phase13-ref-guard", idempotencyKey: "phase13-ref-guard-2",
        workflowSlug: "phase13-media-test", prompt: "超量参考图", negativePrompt: "",
        width: 960, height: 544, count: 1, visibility: "public", promptVisibility: "public",
        parameters: { durationSeconds: 5, inputImages: [{ objectKey: "a" }, { objectKey: "b" }] },
        creditTier: "free",
      }, "0.1000"),
      (error: unknown) => error instanceof GenerationError && error.code === "invalid_request",
    );
    await pool.query("DELETE FROM ai.workflow_provider_bindings WHERE id = $1", [BINDING_ID]);
    await pool.query("UPDATE ai.workflow_versions SET defaults = '{}'::jsonb WHERE id = $1", [VERSION_ID]);
  });

  it("rejects non-video media types and duplicate positions", async () => {
    // 用 PostgreSQL 错误码断言（23514=check_violation，23505=unique_violation），
    // 与服务器消息语言无关，中文/英文 locale 的数据库下行为一致。
    await assert.rejects(
      pool.query(
        `INSERT INTO ai.generation_assets (
           id, job_id, media_type, position, storage_provider, bucket, region,
           object_key, asset_url, mime_type, byte_size, width, height, duration_seconds, sha256
         ) VALUES (
           gen_random_uuid(), $1, 'image', 1, 'tencent_cos', 'bucket', 'ap-guangzhou',
           'images/x.png', 'https://cdn.example/x.png', 'image/png',
           10, 1, 1, 5, repeat('b', 64)
         )`,
        [JOB_ID],
      ),
      (error: { code?: string }) => error.code === "23514",
    );
    await assert.rejects(
      pool.query(
        `INSERT INTO ai.generation_assets (
           id, job_id, media_type, position, storage_provider, bucket, region,
           object_key, asset_url, mime_type, byte_size, width, height, duration_seconds, sha256
         ) VALUES (
           gen_random_uuid(), $1, 'video', 0, 'tencent_cos', 'bucket', 'ap-guangzhou',
           'videos/9013/job/1.mp4', 'https://cdn.example/videos/9013/job/1.mp4',
           'video/mp4', 1024, 960, 544, 5, repeat('c', 64)
         )`,
        [JOB_ID],
      ),
      (error: { code?: string }) => error.code === "23505",
    );
  });

  it("projects completed video jobs into the shared gallery media tables", async () => {
    // 清理投影测试的历史数据（图片/资产/尝试/任务按外键顺序删除）。
    await pool.query("DELETE FROM ai.image_assets WHERE image_id IN (SELECT id FROM ai.images WHERE job_id = $1)", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.images WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_assets WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_attempts WHERE job_id = $1", [PROJECTION_JOB_ID]);
    await pool.query("DELETE FROM ai.generation_jobs WHERE id = $1", [PROJECTION_JOB_ID]);
    // 公开视频任务 + running 状态：markCompleted 应同时完成资产落库与画廊投影。
    await pool.query(
      `INSERT INTO ai.generation_jobs (id, user_id, workflow_version_id, prompt, requested_width, requested_height, status, visibility, prompt_visibility)
       VALUES ($1, $2, $3, 'video gallery projection', 960, 544, 'running', 'public', 'public')`,
      [PROJECTION_JOB_ID, USER_ID, VERSION_ID],
    );
    await pool.query(
      `INSERT INTO ai.generation_attempts (id, job_id, provider_id, attempt_no, status, started_at)
       VALUES ($1, $2, (SELECT id FROM ai.providers WHERE code = 'comfyui'), 1, 'running', now())`,
      [PROJECTION_ATTEMPT_ID, PROJECTION_JOB_ID],
    );

    const repository = new PostgresGenerationJobRepository(pool);
    await repository.markCompleted(PROJECTION_JOB_ID, PROJECTION_ATTEMPT_ID, {
      externalRequestId: "ext-video-projection-1",
      providerCode: "comfyui",
      providerMetadata: { model: "minimax_h3_fl2va_int8_convrot.safetensors" },
      generationDurationMs: 1234,
      storageDurationMs: 12,
      assets: [{
        mediaType: "video",
        storageProvider: "tencent_cos",
        bucket: "bucket",
        region: "ap-guangzhou",
        objectKey: "videos/9013/projection/0.mp4",
        url: "https://cdn.example/videos/9013/projection/0.mp4",
        mimeType: "video/mp4",
        byteSize: 2048,
        width: 960,
        height: 544,
        sha256: "b".repeat(64),
        durationSeconds: 5,
      }],
    });

    // 画廊媒体表投影：视频复用图片的审核/可见性/发布链路（默认待审核，未发布）。
    const image = await pool.query<{ id: string; media_type: string; duration_seconds: number; moderation_status: string; visibility: string; published_at: Date | null }>(
      "SELECT id, media_type, duration_seconds, moderation_status, visibility, published_at FROM ai.images WHERE job_id = $1",
      [PROJECTION_JOB_ID],
    );
    assert.equal(image.rows.length, 1);
    assert.equal(image.rows[0]?.media_type, "video");
    assert.equal(image.rows[0]?.duration_seconds, 5);
    assert.equal(image.rows[0]?.moderation_status, "pending");
    assert.equal(image.rows[0]?.published_at, null);
    const asset = await pool.query<{ mime_type: string; public_url: string | null; width: number; height: number }>(
      `SELECT a.mime_type, a.public_url, a.width, a.height FROM ai.image_assets a WHERE a.image_id = $1 AND a.variant = 'original'`,
      [image.rows[0]?.id],
    );
    assert.equal(asset.rows.length, 1);
    assert.equal(asset.rows[0]?.mime_type, "video/mp4");
    assert.equal(asset.rows[0]?.public_url, "https://cdn.example/videos/9013/projection/0.mp4");
    assert.equal(asset.rows[0]?.width, 960);
    assert.equal(asset.rows[0]?.height, 544);
    // 任务终态与资产表同时就绪：任务中心与画廊共享同一份完成事实。
    const job = await pool.query<{ status: string }>("SELECT status FROM ai.generation_jobs WHERE id = $1", [PROJECTION_JOB_ID]);
    assert.equal(job.rows[0]?.status, "completed");
    const durable = await pool.query<{ object_key: string }>("SELECT object_key FROM ai.generation_assets WHERE job_id = $1", [PROJECTION_JOB_ID]);
    assert.equal(durable.rows[0]?.object_key, "videos/9013/projection/0.mp4");
  });

  it("rejects a second video job for the same user while one is active", async () => {
    const repository = new PostgresGenerationRepository(pool);
    await pool.query("UPDATE ai.workflows SET is_enabled = true WHERE slug = 'comfyui-ltx-video-v1'");
    try {
      const base = {
        userId: USER_ID,
        requestId: "00000000-0000-4000-8000-000000000099",
        workflowSlug: "comfyui-ltx-video-v1",
        prompt: "guard test",
        negativePrompt: "",
        width: 960,
        height: 544,
        count: 1,
        visibility: "private" as const,
        promptVisibility: "hidden" as const,
        parameters: { durationSeconds: 5 },
        creditTier: "free" as const,
      };
      const first = await repository.create({ ...base, idempotencyKey: "video-guard-1" }, "5.0000");
      assert.equal(first.status, "pending");
      assert.equal(first.mode, "workflow");
      await assert.rejects(
        repository.create({ ...base, idempotencyKey: "video-guard-2" }, "5.0000"),
        (error) => error instanceof GenerationError && error.code === "video_busy",
      );
    } finally {
      await pool.query("UPDATE ai.workflows SET is_enabled = false WHERE slug = 'comfyui-ltx-video-v1'");
    }
  });
});
