import type { AdminCuratedImageItem, AdminDashboard, AdminImageItem, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem, CreateCuratedImageCommand, ModerateImageCommand, UpdateCuratedImageCommand, UpdateProviderCommand, UpdateProviderModelCommand, UpdateWorkflowCommand } from "./types.ts";

export interface AdminRepository {
  dashboard(): Promise<AdminDashboard>;
  moderateImage(imageId: string, command: ModerateImageCommand, adminUserId: number, requestId: string): Promise<AdminImageItem>;
  updateProvider(providerId: string, command: UpdateProviderCommand, adminUserId: number, requestId: string): Promise<AdminProviderItem>;
  updateProviderModel(modelId: string, command: UpdateProviderModelCommand, adminUserId: number, requestId: string): Promise<AdminProviderModelItem>;
  updateWorkflow(workflowId: string, command: UpdateWorkflowCommand, adminUserId: number, requestId: string): Promise<AdminWorkflowItem>;
  createCuratedImage(command: CreateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem>;
  updateCuratedImage(imageId: string, command: UpdateCuratedImageCommand, adminUserId: number, requestId: string): Promise<AdminCuratedImageItem>;
  listCuratedImages(limit: number): Promise<readonly AdminCuratedImageItem[]>;
  deleteCuratedImage(imageId: string, adminUserId: number, requestId: string, retentionSeconds: number): Promise<{ readonly slug: string }>;
}
