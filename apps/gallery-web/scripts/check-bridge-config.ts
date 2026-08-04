/**
 * Read-only Gallery Web to Flask bridge configuration audit.
 *
 * Prints only PASS/FAIL states and safe metadata; never prints secret values.
 * Exit code 0 means every required variable is present and valid.
 *
 * Usage:
 *   node --experimental-strip-types scripts/check-bridge-config.ts
 */
import { Buffer } from "node:buffer";
import { pathToFileURL } from "node:url";

export interface BridgeCheck {
  readonly name: string;
  readonly ok: boolean;
  readonly required: boolean;
  readonly message: string;
}

const URL_CHECKS = [
  { name: "MAVIS_AUTH_INTROSPECTION_URL", required: true },
  { name: "GALLERY_PUBLIC_ORIGIN", required: true },
  { name: "MAVIS_AUTH_LOGIN_URL", required: true },
  { name: "MAVIS_AUTH_LOGOUT_URL", required: false },
] as const;

export function bridgeConfigChecks(env: NodeJS.ProcessEnv = process.env): BridgeCheck[] {
  const checks: BridgeCheck[] = [];

  for (const item of URL_CHECKS) {
    const raw = env[item.name]?.trim() ?? "";
    if (!raw) {
      checks.push({
        name: item.name,
        ok: !item.required,
        required: item.required,
        message: item.required ? "missing" : "missing (optional; entry hidden)",
      });
      continue;
    }
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      checks.push({ name: item.name, ok: false, required: item.required, message: "must be an absolute URL" });
      continue;
    }
    const ok = url.protocol === "https:" || (url.protocol === "http:" && isLoopback(url.hostname));
    checks.push({
      name: item.name,
      ok,
      required: item.required,
      message: ok ? "absolute HTTPS URL" : "must use HTTPS (HTTP only on loopback)",
    });
  }

  const secret = env.GALLERY_INTROSPECTION_SECRET?.trim() ?? "";
  const secretOk = Buffer.byteLength(secret, "utf8") >= 32;
  checks.push({
    name: "GALLERY_INTROSPECTION_SECRET",
    ok: secretOk,
    required: true,
    message: secretOk ? "present and at least 32 UTF-8 bytes" : "must be present with at least 32 UTF-8 bytes",
  });

  return checks;
}

export function isLoopback(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1" || hostname === "[::1]";
}

function main(): void {
  const checks = bridgeConfigChecks();
  for (const check of checks) {
    console.log(`[${check.ok ? "PASS" : "FAIL"}] ${check.name}: ${check.message}`);
  }
  if (checks.some((check) => check.required && !check.ok)) {
    console.error("Bridge configuration is not ready; no secret values were printed.");
    process.exit(1);
  }
  console.log("Bridge configuration is ready; no secret values were printed.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
