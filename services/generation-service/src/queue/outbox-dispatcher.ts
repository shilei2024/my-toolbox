import type { JsonObject } from "../providers/types.ts";
import type { StructuredLogger } from "../pipeline/structured-logger.ts";
import type { EnqueueGenerationInput, QueueReceipt } from "./generation-queue-service.ts";

export interface GenerationOutboxEvent {
  readonly id: string;
  readonly aggregateId: string;
  readonly eventType: "generation.requested";
  readonly payload: Readonly<JsonObject>;
  readonly attempts: number;
}

export interface GenerationOutboxRepository {
  claimBatch(limit: number): Promise<readonly GenerationOutboxEvent[]>;
  markPublished(eventId: string, publishedAt: Date): Promise<void>;
  reschedule(eventId: string, availableAt: Date, safeError: string): Promise<void>;
}

export interface GenerationQueuePublisher { enqueue(input: EnqueueGenerationInput): Promise<QueueReceipt> }
export interface OutboxDispatcherOptions { readonly batchSize: number; readonly retryBaseMs: number; readonly retryMaxMs: number }
export interface OutboxDispatchResult { readonly claimed: number; readonly published: number; readonly rescheduled: number }

export class GenerationOutboxDispatcher {
  readonly #repository: GenerationOutboxRepository;
  readonly #queue: GenerationQueuePublisher;
  readonly #options: OutboxDispatcherOptions;
  readonly #logger: StructuredLogger;
  constructor(repository: GenerationOutboxRepository, queue: GenerationQueuePublisher, options: OutboxDispatcherOptions, logger: StructuredLogger) { this.#repository = repository; this.#queue = queue; this.#options = options; this.#logger = logger; }

  async runOnce(now = new Date()): Promise<OutboxDispatchResult> {
    const events = await this.#repository.claimBatch(this.#options.batchSize);
    let published = 0;
    let rescheduled = 0;
    for (const event of events) {
      try {
        const input = toQueueInput(event);
        await this.#queue.enqueue(input);
        await this.#repository.markPublished(event.id, now);
        published += 1;
      } catch {
        const delay = Math.min(this.#options.retryMaxMs, this.#options.retryBaseMs * 2 ** Math.min(event.attempts, 20));
        await this.#repository.reschedule(event.id, new Date(now.getTime() + delay), "queue_publish_failed");
        this.#logger.error("queue.outbox_publish_failed", { eventId: event.id, generationId: event.aggregateId, attemptNumber: event.attempts + 1, retryDelayMs: delay, failureReason: "queue_publish_failed" });
        rescheduled += 1;
      }
    }
    return { claimed: events.length, published, rescheduled };
  }
}

function toQueueInput(event: GenerationOutboxEvent): EnqueueGenerationInput {
  if (event.eventType !== "generation.requested") throw new Error("Unsupported outbox event");
  const keys = Object.keys(event.payload);
  if (keys.some((key) => !new Set(["requestId", "priority"]).has(key))) throw new Error("Outbox payload contains unsupported fields");
  const requestId = event.payload.requestId;
  const priority = event.payload.priority;
  if (typeof requestId !== "string") throw new Error("Outbox request id is invalid");
  if (priority !== undefined && (typeof priority !== "number" || !Number.isSafeInteger(priority) || priority < 0)) throw new Error("Outbox priority is invalid");
  return { jobId: event.aggregateId, requestId, ...(priority === undefined ? {} : { priority }) };
}

