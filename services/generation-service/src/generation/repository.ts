import type { DecodedCursor } from "../gallery/cursor.ts";
import type { CancelGenerationResult, CreateGenerationInput, GenerationPageResult, GenerationStatus, GenerationView, GenerationWorkflowView } from "./types.ts";

export interface GenerationRepository {
  listWorkflows(defaultCreditCost: string): Promise<readonly GenerationWorkflowView[]>;
  create(input: CreateGenerationInput, defaultCreditCost: string): Promise<GenerationView>;
  findForViewer(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined>;
  listForViewer(userId: number, cursor: DecodedCursor | undefined, limit: number, status?: GenerationStatus): Promise<GenerationPageResult>;
  requestCancellation(id: string, userId: number, isAdmin: boolean): Promise<CancelGenerationResult | undefined>;
}
