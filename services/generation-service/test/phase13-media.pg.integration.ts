import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";

const databaseUrl = process.env.PHASE13_TEST_DATABASE_URL;
const USER_ID = 9013;
const WORKFLOW_ID = "b13e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "b23e4567-e89b-42d3-a456-426614174000";
const JOB_ID = "b33e4567-e89b-42d3-a456-426614174000";
const ASSET_ID = "b43e4567-e89b-42d3-a456-426614174000";

describe("Phase 13 PostgreSQL media generation", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase13-media@example.test')", [USER_ID]);
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
      byte_size: number;
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
    assert.equal(assets.rows[0]?.byte_size, 1024);
    assert.equal(assets.rows[0]?.width, 960);
    assert.equal(assets.rows[0]?.height, 544);
    assert.equal(assets.rows[0]?.duration_seconds, "5.000");
    assert.equal(assets.rows[0]?.sha256, "a".repeat(64));
  });

  it("rejects non-video media types and duplicate positions", async () => {
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
      /check/,
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
      /unique/,
    );
  });
});
