import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";

const source = readFileSync(new URL("../src/server/gallery-client.ts", import.meta.url), "utf8").replace('import "server-only";', "");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const output = { exports: {} as Record<string, (...args: unknown[]) => Promise<unknown>> };
new Function("require", "module", "exports", compiled)(createRequire(import.meta.url), output, output.exports);

test("expired identity retries public reads once without weakening private access", async () => {
  const original = globalThis.fetch;
  const base = process.env.GALLERY_SERVICE_BASE_URL, secret = process.env.GALLERY_INTERNAL_HMAC_SECRET;
  process.env.GALLERY_SERVICE_BASE_URL = "http://localhost:3101";
  process.env.GALLERY_INTERNAL_HMAC_SECRET = "test-only-secret-longer-than-thirty-two-bytes";
  try {
    for (const [path, method, status, retry] of [
      ["/v1/gallery?q=test", "GET", 401, true], ["/v1/gallery/facets", "GET", 401, true],
      ["/v1/gallery/slug", "GET", 401, true], ["/v1/me/images", "GET", 401, false],
      ["/v1/me/favorites", "GET", 401, false], ["/v1/images/id/like", "POST", 401, false],
      ["/v1/gallery", "GET", 403, false],
    ] as const) {
      const roles: string[] = [];
      globalThis.fetch = async (_url, init) => {
        const headers = init!.headers as Record<string, string>;
        roles.push(JSON.parse(Buffer.from(headers["X-Mavis-User-Context"], "base64url").toString()).role);
        return roles.length === 1 ? Response.json({ error: { code: "unauthorized" } }, { status }) : Response.json({ items: [] });
      };
      const call = output.exports.serviceRequest(path, { role: "user", userId: 1, requestId: "test" }, { method });
      if (retry) { await call; assert.deepEqual(roles, ["user", "guest"]); }
      else { await assert.rejects(call); assert.deepEqual(roles, ["user"]); }
    }
    let calls = 0;
    globalThis.fetch = async () => { calls++; return Response.json({}, { status: 401 }); };
    await assert.rejects(output.exports.serviceRequest("/v1/gallery", { role: "guest", requestId: "test" }));
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
    if (base === undefined) delete process.env.GALLERY_SERVICE_BASE_URL; else process.env.GALLERY_SERVICE_BASE_URL = base;
    if (secret === undefined) delete process.env.GALLERY_INTERNAL_HMAC_SECRET; else process.env.GALLERY_INTERNAL_HMAC_SECRET = secret;
  }
});
