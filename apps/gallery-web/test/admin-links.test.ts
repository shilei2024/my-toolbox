import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { adminConsoleUrl, publicAdminConsoleUrl } from "../src/lib/admin-links.ts";

describe("Unified admin links", () => {
  it("returns the configured HTTPS admin URL", () => {
    const env = { MAVIS_ADMIN_URL: "https://mindfulpenpal.com/admin/gallery" } as unknown as NodeJS.ProcessEnv;
    assert.equal(adminConsoleUrl(env), "https://mindfulpenpal.com/admin/gallery");
  });

  it("stays hidden when unset or unsafe", () => {
    assert.equal(adminConsoleUrl({} as unknown as NodeJS.ProcessEnv), undefined);
    assert.equal(adminConsoleUrl({ MAVIS_ADMIN_URL: "http://mindfulpenpal.com/admin" } as unknown as NodeJS.ProcessEnv), undefined);
    assert.equal(adminConsoleUrl({ MAVIS_ADMIN_URL: "not a url" } as unknown as NodeJS.ProcessEnv), undefined);
  });

  it("allows loopback HTTP for local development", () => {
    const env = { MAVIS_ADMIN_URL: "http://localhost:8000/admin/gallery" } as unknown as NodeJS.ProcessEnv;
    assert.equal(adminConsoleUrl(env), "http://localhost:8000/admin/gallery");
  });

  it("reads the public variable used by the client header", () => {
    const env = { NEXT_PUBLIC_MAVIS_ADMIN_URL: "https://mindfulpenpal.com/admin/gallery" } as unknown as NodeJS.ProcessEnv;
    assert.equal(publicAdminConsoleUrl(env), "https://mindfulpenpal.com/admin/gallery");
    assert.equal(publicAdminConsoleUrl({} as unknown as NodeJS.ProcessEnv), undefined);
  });
});
