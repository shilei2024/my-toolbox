import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

test("account data does not opt into the affected cross-request caching APIs", () => {
  const root = new URL("../", import.meta.url);
  assert.match(readFileSync(new URL("next.config.ts", root), "utf8"), /cacheComponents:\s*false/);
  function inspect(directory: string) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) inspect(path);
      else if (/\.tsx?$/.test(entry.name)) {
        const source = readFileSync(path, "utf8");
        assert.doesNotMatch(source, /["']use cache(?::[^"']*)?["']/, path);
        assert.doesNotMatch(source, /\bunstable_cache\s*\(/, path);
      }
    }
  }
  inspect(fileURLToPath(new URL("src/", root)));
});
