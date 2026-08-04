import type { Pool, QueryResultRow } from "pg";
import type { JsonObject } from "../providers/types.ts";
import type { GenerationOutboxEvent, GenerationOutboxRepository } from "./outbox-dispatcher.ts";

interface OutboxRow extends QueryResultRow { id: string; aggregate_id: string; event_type: string; payload: JsonObject; attempts: number }

export class PostgresGenerationOutboxRepository implements GenerationOutboxRepository {
  readonly #pool: Pool;
  readonly #claimLeaseSeconds: number;
  constructor(pool: Pool, claimLeaseSeconds = 60) { this.#pool = pool; this.#claimLeaseSeconds = claimLeaseSeconds; }

  async claimBatch(limit: number): Promise<readonly GenerationOutboxEvent[]> {
    const result = await this.#pool.query<OutboxRow>(`WITH due AS (
        SELECT id FROM ai.outbox_events
        WHERE published_at IS NULL AND event_type = 'generation.requested' AND available_at <= now()
        ORDER BY available_at, created_at
        FOR UPDATE SKIP LOCKED LIMIT $1
      )
      UPDATE ai.outbox_events e SET attempts = e.attempts + 1,
        available_at = now() + ($2::integer * interval '1 second')
      FROM due WHERE e.id = due.id
      RETURNING e.id, e.aggregate_id, e.event_type, e.payload, e.attempts`, [limit, this.#claimLeaseSeconds]);
    return result.rows.map((row) => {
      if (row.event_type !== "generation.requested") throw new Error("Unsupported outbox event type");
      return { id: row.id, aggregateId: row.aggregate_id, eventType: "generation.requested", payload: row.payload, attempts: row.attempts - 1 };
    });
  }

  async markPublished(eventId: string, publishedAt: Date): Promise<void> {
    await this.#pool.query("UPDATE ai.outbox_events SET published_at = $2, last_error = NULL WHERE id = $1 AND published_at IS NULL", [eventId, publishedAt]);
  }

  async reschedule(eventId: string, availableAt: Date, safeError: string): Promise<void> {
    await this.#pool.query("UPDATE ai.outbox_events SET available_at = $2, last_error = $3 WHERE id = $1 AND published_at IS NULL", [eventId, availableAt, safeError.slice(0, 120)]);
  }
}
