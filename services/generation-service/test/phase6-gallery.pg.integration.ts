import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "../src/gallery/asset-url.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { PostgresGalleryRepository } from "../src/gallery/postgres-gallery-repository.ts";

const databaseUrl = process.env.PHASE6_TEST_DATABASE_URL;
const PUBLIC_ID = "623e4567-e89b-42d3-a456-426614174000";
const PRIVATE_ID = "723e4567-e89b-42d3-a456-426614174000";
const PUBLIC_VIDEO_ID = "653e4567-e89b-42d3-a456-426614174000";
const USER_ID = 61001;
const OTHER_USER_ID = 61002;
const REQUEST_ID = "823e4567-e89b-42d3-a456-426614174000";

class TestAssetResolver implements GalleryAssetUrlResolver {
  async resolve(asset: GalleryAssetRecord, isPublic: boolean): Promise<string> {
    return isPublic && asset.publicUrl ? asset.publicUrl : `https://signed.example.test/${asset.objectKey}`;
  }
}

describe("Phase 6 PostgreSQL Gallery integration", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const repository = new PostgresGalleryRepository(pool, new TestAssetResolver());

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'gallery-owner@example.test'), ($2, 'gallery-other@example.test') ON CONFLICT DO NOTHING", [USER_ID, OTHER_USER_ID]);
    await pool.query("INSERT INTO ai.user_profiles (user_id, display_name) VALUES ($1, 'Gallery Owner') ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name", [USER_ID]);
    await pool.query(`INSERT INTO ai.images (
      id, creator_user_id, slug, title, description, prompt, negative_prompt,
      provider_code_snapshot, workflow_name_snapshot, width, height,
      media_type, duration_seconds,
      visibility, prompt_visibility, moderation_status, published_at
    ) VALUES
      ($1, $3, 'phase6-public-image', 'Public image', '', 'hidden secret prompt', '', 'comfyui', 'portrait', 1024, 1280, 'image', NULL, 'public', 'hidden', 'approved', now()),
      ($2, $3, 'phase6-private-image', 'Private image', '', 'owner prompt', '', 'comfyui', 'portrait', 1024, 1024, 'image', NULL, 'private', 'hidden', 'approved', NULL),
      ($4, $3, 'phase6-public-video', 'Public video', '', 'video prompt', '', 'comfyui', 'MiniMax H3 文生视频', 960, 544, 'video', 5, 'public', 'public', 'approved', now())
    ON CONFLICT (id) DO NOTHING`, [PUBLIC_ID, PRIVATE_ID, USER_ID, PUBLIC_VIDEO_ID]);
    for (const [id, name] of [[PUBLIC_ID, "public.webp"], [PRIVATE_ID, "private.webp"]] as const) {
      await pool.query(`INSERT INTO ai.image_assets (
        image_id, variant, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256
      ) VALUES ($1, 'original', 'bucket-test', 'ap-test', $2, $3, 'image/webp', 10, 1024, 1024, repeat('a', 64))
      ON CONFLICT (image_id, variant) DO NOTHING`, [id, `images/${name}`, `https://assets.example.test/${name}`]);
    }
    await pool.query(`INSERT INTO ai.image_assets (
      image_id, variant, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256
    ) VALUES ($1, 'original', 'bucket-test', 'ap-test', 'videos/phase6-public.mp4', 'https://assets.example.test/phase6-public.mp4', 'video/mp4', 10, 960, 544, repeat('b', 64))
    ON CONFLICT (image_id, variant) DO NOTHING`, [PUBLIC_VIDEO_ID]);
  });

  after(async () => {
    await pool.query("DELETE FROM ai.images WHERE id = ANY($1::uuid[])", [[PUBLIC_ID, PRIVATE_ID, PUBLIC_VIDEO_ID]]);
    await pool.query("DELETE FROM public.users WHERE id = ANY($1::integer[])", [[USER_ID, OTHER_USER_ID]]);
    await pool.end();
  });

  it("enforces public visibility, prompt privacy, atomic counters and owner deletion", async () => {
    const guest = { role: "guest" as const, requestId: REQUEST_ID };
    const owner = { role: "user" as const, userId: USER_ID, requestId: REQUEST_ID };
    const other = { role: "user" as const, userId: OTHER_USER_ID, requestId: REQUEST_ID };

    const feed = await repository.listPublic({}, undefined, 24, guest);
    assert.deepEqual(feed.items.map((item) => item.id).sort(), [PUBLIC_ID, PUBLIC_VIDEO_ID].sort());
    assert.equal(feed.items[0]?.creator?.displayName, "Gallery Owner");

    const publicGuest = await repository.findBySlug("phase6-public-image", guest);
    assert.ok(publicGuest);
    assert.equal(publicGuest.prompt, undefined);
    assert.equal(await repository.findBySlug("phase6-private-image", guest), undefined);
    assert.equal((await repository.findBySlug("phase6-private-image", owner))?.prompt, "owner prompt");

    assert.deepEqual(await repository.setFavorite(PUBLIC_ID, USER_ID, true, REQUEST_ID), { active: true, count: 1 });
    assert.deepEqual(await repository.setFavorite(PUBLIC_ID, USER_ID, true, REQUEST_ID), { active: true, count: 1 });
    assert.deepEqual(await repository.setLike(PUBLIC_ID, USER_ID, true, REQUEST_ID), { active: true, count: 1 });

    await assert.rejects(repository.softDelete(PRIVATE_ID, other, 0), (error: unknown) => error instanceof GalleryError && error.code === "forbidden");
    await repository.softDelete(PRIVATE_ID, owner, 0);
    assert.equal(await repository.findBySlug("phase6-private-image", owner), undefined);
    const tasks = await repository.claimDeletionTasks(10);
    assert.equal(tasks.some((task) => task.imageId === PRIVATE_ID && task.assets.some((asset) => asset.storageProvider === "tencent_cos" && asset.objectKey === "images/private.webp")), true);
  });

  it("lists approved videos alongside images with media metadata for hover playback", async () => {
    const guest = { role: "guest" as const, requestId: REQUEST_ID };
    // 视频与图片同页展示：listPublic 必须返回视频条目并携带 mediaType/durationSeconds。
    const feed = await repository.listPublic({}, undefined, 24, guest);
    const video = feed.items.find((item) => item.id === PUBLIC_VIDEO_ID);
    assert.ok(video, "approved public video must appear in the gallery feed");
    assert.equal(video.mediaType, "video");
    assert.equal(video.durationSeconds, 5);
    assert.equal(video.asset.mimeType, "video/mp4");
    // 详情页与图片共用同一 slug 链路，视频 prompt 按可见性返回。
    const detail = await repository.findBySlug("phase6-public-video", guest);
    assert.ok(detail);
    assert.equal(detail.mediaType, "video");
    assert.equal(detail.prompt, "video prompt");
    // SEO 资产列表（og:image / sitemap）只接受图片，视频不进入。
    const seo = await repository.listSeoImages(undefined, 24);
    assert.equal(seo.items.some((entry) => entry.slug === "phase6-public-video"), false);
  });
});
