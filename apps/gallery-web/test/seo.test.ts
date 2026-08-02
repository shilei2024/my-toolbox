import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { GalleryImageDetail } from "../src/lib/gallery-types.ts";
import { buildArtworkJsonLd, buildArtworkSeo, resolvePublicOrigin, serializeJsonLd } from "../src/lib/seo.ts";

const image: GalleryImageDetail = {
  id: "c23e4567-e89b-42d3-a456-426614174000",
  slug: "quiet-blue-portrait-c23e4567",
  title: "  Quiet   Blue Portrait  ",
  description: "A calm portrait.",
  width: 1024,
  height: 1280,
  workflowName: "portrait",
  publishedAt: "2026-08-02T00:00:00.000Z",
  asset: { url: "https://assets.example.test/image.webp", width: 1024, height: 1280, mimeType: "image/webp", variant: "original" },
  creator: { displayName: "Mavis Creator" },
  tags: ["portrait", "blue"],
  likeCount: 2,
  favoriteCount: 1,
  viewerHasLiked: false,
  viewerHasFavorited: false,
  prompt: "private-looking prompt that must not be serialized",
  providerCode: "comfyui",
  createdAt: "2026-08-02T00:00:00.000Z",
  downloadCount: 3,
  canDelete: false,
  isOwner: false,
};

describe("Phase 7 artwork SEO", () => {
  it("builds canonical metadata without exposing prompts or provider routing", () => {
    const seo = buildArtworkSeo(image, new URL("https://www.mindfulpenpal.com"));
    assert.equal(seo.title, "Quiet Blue Portrait");
    assert.equal(seo.canonicalUrl, "https://www.mindfulpenpal.com/gallery/quiet-blue-portrait-c23e4567");
    const serialized = serializeJsonLd(buildArtworkJsonLd(image));
    assert.equal(serialized.includes("private-looking prompt"), false);
    assert.equal(serialized.includes("comfyui"), false);
    assert.match(serialized, /ImageObject/);
  });

  it("escapes JSON-LD markup and rejects unsafe public origins", () => {
    assert.equal(serializeJsonLd({ value: "</script><script>" }).includes("<"), false);
    assert.equal(resolvePublicOrigin("http://evil.example").origin, "https://www.mindfulpenpal.com");
    assert.equal(resolvePublicOrigin("http://127.0.0.1:3104").origin, "http://127.0.0.1:3104");
  });
});
