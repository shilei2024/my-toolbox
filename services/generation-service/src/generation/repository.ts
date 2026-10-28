import type { DecodedCursor } from "../gallery/cursor.ts";
import type { MediaType } from "../providers/types.ts";
import type { CancelGenerationResult, CreateGenerationInput, GenerationMode, GenerationPageResult, GenerationStatus, GenerationView, GenerationWorkflowView } from "./types.ts";

export interface GenerationRepository {
  listWorkflows(defaultCreditCost: string, mode?: GenerationMode, mediaType?: MediaType): Promise<readonly GenerationWorkflowView[]>;
  create(input: CreateGenerationInput, defaultCreditCost: string): Promise<GenerationView>;
  findForViewer(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined>;
  listForViewer(userId: number, cursor: DecodedCursor | undefined, limit: number, status?: GenerationStatus): Promise<GenerationPageResult>;
  requestCancellation(id: string, userId: number, isAdmin: boolean): Promise<CancelGenerationResult | undefined>;
  finalizeCancellation(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined>;
}
