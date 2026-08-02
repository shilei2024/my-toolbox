import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import type { GalleryAssetRecord, GalleryAssetUrlResolver } from "../src/gallery/asset-url.ts";
import { PostgresGalleryRepository } from "../src/gallery/postgres-gallery-repository.ts";

const databaseUrl = process.env.PHASE7_TEST_DATABASE_URL;
const PUBLIC_ID = "a23e4567-e89b-42d3-a456-426614174000";
const PRIVATE_ID = "b23e4567-e89b-42d3-a456-426614174000";
const USER_ID = 62001;

class TestAssetResolver implements GalleryAssetUrlResolver {
  async resolve(asset: GalleryAssetRecord): Promise<string> { return asset.publicUrl ?? `https://assets.example.test/${asset.objectKey}`; }
}

describe("Phase 7 PostgreSQL SEO feed integration", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const repository = new PostgresGalleryRepository(pool, new TestAssetResolver());

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase7-owner@example.test') ON CONFLICT DO NOTHING", [USER_ID]);
    await pool.query(`INSERT INTO ai.images (id, creator_user_id, slug, title, prompt, negative_prompt, provider_code_snapshot, workflow_name_snapshot, width, height, visibility, prompt_visibility, moderation_status, published_at)
      VALUES ($1, $3, 'phase7-public-image', 'Public', 'secret', '', 'comfyui', 'portrait', 1024, 1024, 'public', 'hidden', 'approved', '2026-08-02T00:00:00Z'),
             ($2, $3, 'phase7-private-image', 'Private', 'secret', '', 'comfyui', 'portrait', 1024, 1024, 'private', 'hidden', 'approved', NULL)
      ON CONFLICT (id) DO NOTHING`, [PUBLIC_ID, PRIVATE_ID, USER_ID]);
    for (const [id, name] of [[PUBLIC_ID, "seo-public.webp"], [PRIVATE_ID, "seo-private.webp"]]) {
      await pool.query(`INSERT INTO ai.image_assets (image_id, variant, bucket, region, object_key, public_url, mime_type, byte_size, width, height, sha256)
        VALUES ($1, 'original', 'bucket-test', 'ap-test', $2, $3, 'image/webp', 10, 1024, 1024, repeat('b', 64)) ON CONFLICT (image_id, variant) DO NOTHING`, [id, `images/${name}`, `https://assets.example.test/${name}`]);
    }
  });

  after(async () => {
    await pool.query("DELETE FROM ai.images WHERE id = ANY($1::uuid[])", [[PUBLIC_ID, PRIVATE_ID]]);
    await pool.query("DELETE FROM public.users WHERE id = $1", [USER_ID]);
    await pool.end();
  });

  it("exports only approved public images and supports keyset continuation", async () => {
    const first = await repository.listSeoImages(undefined, 1);
    assert.deepEqual(first.items.map((item) => item.slug), ["phase7-public-image"]);
    assert.equal(first.items[0]?.assetUrl, "https://assets.example.test/seo-public.webp");
    assert.equal(first.items.some((item) => item.slug === "phase7-private-image"), false);
  });
});
