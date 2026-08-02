import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { Pool } from "pg";
import { CreditService } from "../src/billing/credit-service.ts";

const databaseUrl = process.env.PHASE10_TEST_DATABASE_URL;
const USER_ID = 9010;
const WORKFLOW_ID = "a13e4567-e89b-42d3-a456-426614174000";
const VERSION_ID = "a23e4567-e89b-42d3-a456-426614174000";
const JOB_ID = "a33e4567-e89b-42d3-a456-426614174000";

describe("Phase 10 PostgreSQL credit ledger", { skip: !databaseUrl }, () => {
  const pool = new Pool({ connectionString: databaseUrl });
  const credits = new CreditService(pool);

  before(async () => {
    await pool.query("INSERT INTO public.users (id, email) VALUES ($1, 'phase10-billing@example.test')", [USER_ID]);
    await pool.query("INSERT INTO ai.workflows (id, slug, name, category, is_enabled) VALUES ($1, 'phase10-credit-test', 'Phase 10', 'test', true)", [WORKFLOW_ID]);
    await pool.query("INSERT INTO ai.workflow_versions (id, workflow_id, version, is_active) VALUES ($1, $2, 1, true)", [VERSION_ID, WORKFLOW_ID]);
    await pool.query(`INSERT INTO ai.generation_jobs (id, user_id, workflow_version_id, prompt, requested_width, requested_height)
      VALUES ($1, $2, $3, 'credit test', 512, 512)`, [JOB_ID, USER_ID, VERSION_ID]);
    await pool.query("INSERT INTO ai.credit_accounts (user_id, available_amount, lifetime_granted) VALUES ($1, 20, 20)", [USER_ID]);
  });

  after(async () => {
    await pool.end();
  });

  it("atomically reserves and settles generation credits", async () => {
    assert.deepEqual(await credits.reserve(USER_ID, JOB_ID, "5.0000", "reserve-job-1"), { availableAmount: "15.0000", reservedAmount: "5.0000" });
    assert.deepEqual(await credits.reserve(USER_ID, JOB_ID, "5.0000", "reserve-job-1"), { availableAmount: "15.0000", reservedAmount: "5.0000" });
    assert.deepEqual(await credits.settle(JOB_ID, "4.0000", "settle-job-1"), { availableAmount: "16.0000", reservedAmount: "0.0000" });
    const account = (await pool.query<{ lifetime_spent: string }>("SELECT lifetime_spent FROM ai.credit_accounts WHERE user_id = $1", [USER_ID])).rows[0];
    assert.equal(account?.lifetime_spent, "4.0000");
  });

  it("prevents ledger mutation", async () => {
    await assert.rejects(pool.query("UPDATE ai.credit_ledger_entries SET metadata = '{}' WHERE user_id = $1", [USER_ID]), /immutable/);
  });
});
