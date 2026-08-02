import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import { MockImageProvider } from "../src/providers/mock.provider.ts";
import { PostgresProviderCatalog } from "../src/providers/postgres-catalog.ts";
import { ProviderRegistry } from "../src/providers/registry.ts";

const databaseUrl = process.env.PHASE9_TEST_DATABASE_URL;
const WORKFLOW_ID = "913e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "923e4567-e89b-42d3-a456-426614174000";
const BINDING_ID = "933e4567-e89b-42d3-a456-426614174000";

describe("Phase 9 PostgreSQL provider model catalog", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const catalog = new PostgresProviderCatalog(pool);

  before(async () => {
    await pool.query("UPDATE ai.providers SET status = 'disabled'");
    await pool.query("UPDATE ai.providers SET status = 'active', priority = 7 WHERE code = 'openai'");
    await pool.query(`INSERT INTO ai.workflows (id, slug, name, category, is_enabled) VALUES ($1, 'phase9-provider-routing', 'Phase 9 Routing', 'portrait', true)`, [WORKFLOW_ID]);
    await pool.query(`INSERT INTO ai.workflow_versions (id, workflow_id, version, is_active) VALUES ($1, $2, 1, true)`, [VERSION_ID, WORKFLOW_ID]);
    await pool.query(`INSERT INTO ai.workflow_provider_bindings (id, workflow_version_id, provider_id, provider_model_id, priority, estimated_cost)
      SELECT $1, $2, p.id, m.id, 5, 0.01 FROM ai.providers p JOIN ai.provider_models m ON m.provider_id = p.id
      WHERE p.code = 'openai' AND m.is_default`, [BINDING_ID, VERSION_ID]);
  });

  after(async () => {
    await pool.query("DELETE FROM ai.workflows WHERE id = $1", [WORKFLOW_ID]);
    await pool.query("UPDATE ai.providers SET status = 'disabled' WHERE code IN ('openai', 'gemini', 'jimeng')");
    await pool.end();
  });

  it("loads only active bindings with model identity and applies database routing state", async () => {
    const models = await pool.query<{ code: string; model_code: string }>(`SELECT p.code, m.model_code FROM ai.provider_models m JOIN ai.providers p ON p.id = m.provider_id ORDER BY p.code`);
    assert.deepEqual(models.rows.map((row) => row.code), ["gemini", "jimeng", "openai"]);
    const bindings = await catalog.bindingsFor(VERSION_ID);
    assert.equal(bindings.length, 1);
    assert.equal(bindings[0]?.providerCode, "openai");
    assert.equal(bindings[0]?.providerModel, "gpt-image-2-2026-04-21");

    const registry = new ProviderRegistry();
    registry.register(new MockImageProvider({ code: "openai", priority: 100 }));
    await catalog.refreshRegistry(registry);
    assert.deepEqual(registry.routing("openai"), { availability: "active", priority: 7 });
  });

  it("rejects a model that belongs to a different provider", async () => {
    const result = await pool.query<{ provider_id: string; model_id: string }>(`SELECT p.id AS provider_id, m.id AS model_id
      FROM ai.providers p CROSS JOIN ai.provider_models m JOIN ai.providers owner ON owner.id = m.provider_id
      WHERE p.code = 'gemini' AND owner.code = 'openai' LIMIT 1`);
    const row = result.rows[0]!;
    await assert.rejects(pool.query(`INSERT INTO ai.workflow_provider_bindings (workflow_version_id, provider_id, provider_model_id)
      VALUES ($1, $2, $3)`, [VERSION_ID, row.provider_id, row.model_id]), (error: unknown) => typeof error === "object" && error !== null && "code" in error && error.code === "23503");
  });
});
