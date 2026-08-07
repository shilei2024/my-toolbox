import type { Pool, QueryResultRow } from "pg";
import type { CreditTier, JsonObject, ProviderAvailability, ProviderBinding } from "./types.ts";
import type { ProviderRegistry } from "./registry.ts";

interface ProviderRow extends QueryResultRow { code: string; status: ProviderAvailability; priority: number }
interface BindingRow extends QueryResultRow {
  id: string;
  provider_code: string;
  workflow_version_id: string;
  provider_workflow_ref: string | null;
  provider_model: string | null;
  model_tier: CreditTier | null;
  provider_config: JsonObject;
  priority: number;
  estimated_cost: string | null;
  timeout_seconds: number;
  max_attempts: number;
  is_enabled: boolean;
}

export class PostgresProviderCatalog {
  readonly #pool: Pool;
  constructor(pool: Pool) { this.#pool = pool; }

  async refreshRegistry(registry: ProviderRegistry): Promise<void> {
    const result = await this.#pool.query<ProviderRow>("SELECT code, status, priority FROM ai.providers ORDER BY code");
    for (const row of result.rows) if (registry.has(row.code)) registry.setRouting(row.code, { availability: row.status, priority: row.priority });
  }

  async bindingsFor(workflowVersionId: string): Promise<readonly ProviderBinding[]> {
    const result = await this.#pool.query<BindingRow>(`SELECT b.id, p.code AS provider_code, b.workflow_version_id,
        b.provider_workflow_ref, COALESCE(m.model_code, b.provider_model) AS provider_model,
        m.tier AS model_tier,
        (p.config || b.provider_config) AS provider_config, b.priority, b.estimated_cost,
        b.timeout_seconds, b.max_attempts, b.is_enabled
      FROM ai.workflow_provider_bindings b
      JOIN ai.providers p ON p.id = b.provider_id
      LEFT JOIN ai.provider_models m ON m.id = b.provider_model_id AND m.provider_id = p.id
      WHERE b.workflow_version_id = $1 AND b.is_enabled AND p.status <> 'disabled'
        AND (b.provider_model_id IS NULL OR m.is_enabled)
      ORDER BY b.priority, p.priority, p.code`, [workflowVersionId]);
    return result.rows.map(binding);
  }
}

function binding(row: BindingRow): ProviderBinding {
  return {
    id: row.id,
    providerCode: row.provider_code,
    workflowVersionId: row.workflow_version_id,
    ...(row.provider_workflow_ref ? { providerWorkflowRef: row.provider_workflow_ref } : {}),
    ...(row.provider_model ? { providerModel: row.provider_model } : {}),
    ...(row.model_tier === "free" || row.model_tier === "member" ? { modelTier: row.model_tier } : {}),
    providerConfig: row.provider_config,
    priority: row.priority,
    ...(row.estimated_cost === null ? {} : { estimatedCost: Number(row.estimated_cost) }),
    timeoutSeconds: row.timeout_seconds,
    maxAttempts: row.max_attempts,
    enabled: row.is_enabled,
  };
}
