import type { Pool } from "pg";
import { BillingError } from "./errors.ts";

export class CreditService {
  readonly #pool: Pool;
  constructor(pool: Pool) { this.#pool = pool; }

  reserve(userId: number, generationJobId: string, amount: string, idempotencyKey: string): Promise<{ availableAmount: string; reservedAmount: string }> {
    return this.call("reserve_generation_credits", [userId, generationJobId, amount, idempotencyKey]);
  }

  settle(generationJobId: string, chargeAmount: string, idempotencyKey: string): Promise<{ availableAmount: string; reservedAmount: string }> {
    return this.call("settle_generation_credits", [generationJobId, chargeAmount, idempotencyKey]);
  }

  release(generationJobId: string, idempotencyKey: string): Promise<{ availableAmount: string; reservedAmount: string }> {
    return this.call("release_generation_credits", [generationJobId, idempotencyKey]);
  }

  private async call(functionName: string, values: readonly unknown[]): Promise<{ availableAmount: string; reservedAmount: string }> {
    const placeholders = values.map((_, index) => `$${index + 1}`).join(", ");
    try {
      const result = await this.#pool.query<{ available_amount: string; reserved_amount: string }>(`SELECT * FROM ai.${functionName}(${placeholders})`, [...values]);
      const row = result.rows[0];
      if (!row) throw new Error("credit_result_missing");
      return { availableAmount: row.available_amount, reservedAmount: row.reserved_amount };
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (message.includes("insufficient_credits")) throw new BillingError("insufficient_credits", "Not enough credits", 409);
      throw error;
    }
  }
}
