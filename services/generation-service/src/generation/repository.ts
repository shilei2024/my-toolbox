import type { CancelGenerationResult, CreateGenerationInput, GenerationView, GenerationWorkflowView } from "./types.ts";

export interface GenerationRepository {
  listWorkflows(defaultCreditCost: string): Promise<readonly GenerationWorkflowView[]>;
  create(input: CreateGenerationInput, defaultCreditCost: string): Promise<GenerationView>;
  findForViewer(id: string, userId: number, isAdmin: boolean): Promise<GenerationView | undefined>;
  requestCancellation(id: string, userId: number, isAdmin: boolean): Promise<CancelGenerationResult | undefined>;
}
