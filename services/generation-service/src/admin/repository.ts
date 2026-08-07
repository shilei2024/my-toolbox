import type { AdminDashboard, AdminImageItem, AdminProviderItem, AdminProviderModelItem, AdminWorkflowItem, ModerateImageCommand, UpdateProviderCommand, UpdateProviderModelCommand, UpdateWorkflowCommand } from "./types.ts";

export interface AdminRepository {
  dashboard(): Promise<AdminDashboard>;
  moderateImage(imageId: string, command: ModerateImageCommand, adminUserId: number, requestId: string): Promise<AdminImageItem>;
  updateProvider(providerId: string, command: UpdateProviderCommand, adminUserId: number, requestId: string): Promise<AdminProviderItem>;
  updateProviderModel(modelId: string, command: UpdateProviderModelCommand, adminUserId: number, requestId: string): Promise<AdminProviderModelItem>;
  updateWorkflow(workflowId: string, command: UpdateWorkflowCommand, adminUserId: number, requestId: string): Promise<AdminWorkflowItem>;
}
