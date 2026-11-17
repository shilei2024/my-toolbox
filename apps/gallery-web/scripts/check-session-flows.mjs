// Run after `npm run build`. Uses synthetic identities and loopback services only.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createHmac } from "node:crypto";

const secret = "isolated-flow-test-secret-at-least-32-bytes";
const requests = [];
const upstream = createServer((req, res) => {
  res.setHeader("Content-Type", "application/json");
  const reply = (body, status = 200) => { res.statusCode = status; res.end(JSON.stringify(body)); };
  if (req.url === "/session") {
    assert.equal(req.headers["x-mavis-introspection-secret"], secret);
    if (!req.headers.cookie?.includes("mytoolbox_session=")) return reply({ role: "guest" });
    return reply({ role: "user", userId: 7, authEpoch: 2, sessionRef: (req.headers.cookie.includes("expired") ? "b" : "a").repeat(64) });
  }
  const context = req.headers["x-mavis-user-context"];
  if (!context || req.headers["x-mavis-user-signature"] !== createHmac("sha256", secret).update(context).digest("base64url")) {
    return reply({ error: { code: "unauthorized" } }, 401);
  }
  const viewer = JSON.parse(Buffer.from(context, "base64url").toString());
  requests.push({ path: req.url, role: viewer.role, version: viewer.v });
  if (viewer.role !== "guest" && (viewer.v !== 2 || viewer.sessionRef !== "a".repeat(64))) {
    return reply({ error: { code: "authentication_required" } }, 401);
  }
  if (req.url.startsWith("/v1/me/") && viewer.role === "guest") return reply({ error: { code: "unauthorized" } }, 401);
  if (req.url === "/v1/gallery/facets") return reply({ total: 0, media: { image: 0, video: 0 }, workflows: [] });
  return reply({ items: [] });
});
await new Promise(resolve => upstream.listen(0, "127.0.0.1", resolve));
const serviceOrigin = `http://127.0.0.1:${upstream.address().port}`;
const port = 38971;
const origin = `http://127.0.0.1:${port}`;
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", String(port)], {
  env: { ...process.env, GALLERY_SERVICE_BASE_URL: serviceOrigin, GALLERY_INTERNAL_HMAC_SECRET: secret,
    MAVIS_AUTH_INTROSPECTION_URL: `${serviceOrigin}/session`, GALLERY_INTROSPECTION_SECRET: secret,
    MAVIS_AUTH_SESSION_COOKIE_NAME: "mytoolbox_session", GALLERY_PUBLIC_ORIGIN: origin },
  stdio: ["ignore", "pipe", "pipe"],
});
let startup = "";
child.stdout.on("data", chunk => { startup += chunk; });
child.stderr.on("data", chunk => { startup += chunk; });
try {
  let ready = false;
  for (let i = 0; i < 80; i++) {
    if (child.exitCode !== null) throw Error(`Next exited during startup: ${startup.slice(-600)}`);
    try { if ((await fetch(`${origin}/api/me/session`)).ok) { ready = true; break; } } catch { /* still starting */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert(ready, "Next did not become ready");
  for (const identity of ["", "valid", "expired"]) {
    const headers = identity ? { Cookie: `mytoolbox_session=${identity}` } : {};
    const before = requests.length;
    const publicResponse = await fetch(`${origin}/api/gallery`, { headers });
    assert.equal(publicResponse.status, 200);
    assert.deepEqual((await publicResponse.json()).items, []);
    assert.deepEqual(requests.slice(before).map(r => r.role), identity === "expired" ? ["user", "guest"] : [identity ? "user" : "guest"]);
    const personal = await fetch(`${origin}/api/me/images`, { headers });
    assert.equal(personal.status, identity === "valid" ? 200 : 401);
    const page = await fetch(`${origin}/gallery`, { headers });
    assert.equal(page.status, 200);
    assert((await page.text()).includes("完整提示词"));
    const personalPage = await fetch(`${origin}/my-images`, { headers });
    assert.equal(personalPage.status, 200);
    const html = await personalPage.text();
    assert(html.includes(identity === "expired" ? "重新登录" : identity === "valid" ? "还没有个人作品" : "登录后查看个人作品"));
  }
  assert(requests.some(r => r.role === "user" && r.version === 2));
  console.log("SESSION_FLOWS_OK: signed-v2, public, expired-public-retry, private-denial, SSR");
} finally {
  const stopped = once(child, "exit");
  child.kill();
  await Promise.race([stopped, new Promise(resolve => setTimeout(resolve, 3000))]);
  upstream.closeAllConnections();
  await new Promise(resolve => upstream.close(resolve));
}
