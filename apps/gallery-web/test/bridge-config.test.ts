import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { bridgeConfigChecks } from "../scripts/check-bridge-config.ts";
import { hasNamedCookie } from "../src/server/cookie-utils.ts";
import { mainSiteUrl } from "../src/lib/site-links.ts";

function productionEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    MAVIS_AUTH_INTROSPECTION_URL: "https://tools.example.com/internal/gallery/session",
    GALLERY_INTROSPECTION_SECRET: "gallery-introspection-test-secret-123456789",
    GALLERY_PUBLIC_ORIGIN: "https://gallery.example.com",
    MAVIS_AUTH_LOGIN_URL: "https://tools.example.com/login",
    MAVIS_AUTH_LOGOUT_URL: "https://tools.example.com/logout",
  };
}

describe("Gallery bridge configuration checks", () => {
  it("detects only the configured Flask session cookie", () => {
    assert.equal(hasNamedCookie("theme=dark; mytoolbox_session=signed-value", "mytoolbox_session"), true);
    assert.equal(hasNamedCookie("not_mytoolbox_session=value", "mytoolbox_session"), false);
  });
  it("passes with a complete production configuration", () => {
    const results = bridgeConfigChecks(productionEnv());
    assert.equal(results.every((result) => result.ok), true);
  });

  it("fails closed on a missing secret and never echoes its value", () => {
    const results = bridgeConfigChecks({ ...productionEnv(), GALLERY_INTROSPECTION_SECRET: "" });
    const secretCheck = results.find((result) => result.name === "GALLERY_INTROSPECTION_SECRET");
    assert.equal(secretCheck?.ok, false);
    assert.equal(JSON.stringify(results).includes("gallery-introspection-test-secret"), false);
  });

  it("rejects insecure introspection and login URLs", () => {
    const insecure = bridgeConfigChecks({
      ...productionEnv(),
      MAVIS_AUTH_INTROSPECTION_URL: "http://tools.example.com/internal/gallery/session",
    });
    assert.equal(insecure.find((result) => result.name === "MAVIS_AUTH_INTROSPECTION_URL")?.ok, false);

    const insecureLogin = bridgeConfigChecks({ ...productionEnv(), MAVIS_AUTH_LOGIN_URL: "http://tools.example.com/login" });
    assert.equal(insecureLogin.find((result) => result.name === "MAVIS_AUTH_LOGIN_URL")?.ok, false);
  });

  it("treats a missing logout URL as optional", () => {
    const results = bridgeConfigChecks({ ...productionEnv(), MAVIS_AUTH_LOGOUT_URL: "" });
    assert.equal(results.find((result) => result.name === "MAVIS_AUTH_LOGOUT_URL")?.ok, true);
  });

  it("allows loopback HTTP only for local development", () => {
    const local = bridgeConfigChecks({
      ...productionEnv(),
      MAVIS_AUTH_INTROSPECTION_URL: "http://127.0.0.1:8000/internal/gallery/session",
      MAVIS_AUTH_LOGIN_URL: "http://localhost:8000/login",
      GALLERY_PUBLIC_ORIGIN: "http://localhost:3000",
    });
    assert.equal(local.every((result) => result.ok), true);
  });

  it("derives a safe main-site origin without exposing the login path", () => {
    assert.equal(mainSiteUrl({ MAVIS_SITE_URL: "https://tools.example.com/account" } as NodeJS.ProcessEnv), "https://tools.example.com/");
    assert.equal(mainSiteUrl({ MAVIS_AUTH_LOGIN_URL: "https://fallback.example.com/login" } as NodeJS.ProcessEnv), "https://fallback.example.com/");
    assert.equal(mainSiteUrl({ MAVIS_SITE_URL: "http://tools.example.com" } as NodeJS.ProcessEnv), undefined);
  });
});
