import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "../src/gallery/asset-url.ts";
import { GalleryError } from "../src/gallery/errors.ts";
import { PostgresGalleryRepository } from "../src/gallery/postgres-gallery-repository.ts";

const databaseUrl = process.env.PHASE6_TEST_DATABASE_URL;
const PUBLIC_ID = "623e4567-e89b-42d3-a456-426614174000";
const PRIVATE_ID = "723e4567-e89b-42d3-a456-426614174000";
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
      visibility, prompt_visibility, moderation_status, published_at
    ) VALUES
      ($1, $3, 'phase6-public-image', 'Public image', '', 'hidden secret prompt', '', 'comfyui', 'portrait', 1024, 1280, 'public', 'hidden', 'approved', now()),
      ($2, $3, 'phase6-private-image', 'Private image', '', 'owner prompt', '', 'comfyui', 'portrait', 1024, 1024, 'private', 'hidden', 'approved', NULL)
    ON CONFLICT (id) DO NOTHING`, [PUBLIC_ID, PRIVATE_ID, USER_ID]);
    for (const [id, name] of [[PUBLIC_ID, "public.webp"], [PRIVATE_ID, "private.webp"]]) {
      await pool.query(`INSERT INTO ai.image_assets (
        image_id, variant, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256
      ) VALUES ($1, 'original', 'bucket-test', 'ap-test', $2, $3, 'image/webp', 10, 1024, 1024, repeat('a', 64))
      ON CONFLICT (image_id, variant) DO NOTHING`, [id, `images/${name}`, `https://assets.example.test/${name}`]);
    }
  });

  after(async () => {
    await pool.query("DELETE FROM ai.images WHERE id = ANY($1::uuid[])", [[PUBLIC_ID, PRIVATE_ID]]);
    await pool.query("DELETE FROM public.users WHERE id = ANY($1::integer[])", [[USER_ID, OTHER_USER_ID]]);
    await pool.end();
  });

  it("enforces public visibility, prompt privacy, atomic counters and owner deletion", async () => {
    const guest = { role: "guest" as const, requestId: REQUEST_ID };
    const owner = { role: "user" as const, userId: USER_ID, requestId: REQUEST_ID };
    const other = { role: "user" as const, userId: OTHER_USER_ID, requestId: REQUEST_ID };

    const feed = await repository.listPublic({}, undefined, 24, guest);
    assert.deepEqual(feed.items.map((item) => item.id), [PUBLIC_ID]);
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
});
