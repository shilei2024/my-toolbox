import type { AdminDashboard, AdminImageItem, AdminProviderItem, AdminWorkflowItem, ModerateImageCommand, UpdateProviderCommand, UpdateWorkflowCommand } from "./types.ts";

export interface AdminRepository {
  dashboard(): Promise<AdminDashboard>;
  moderateImage(imageId: string, command: ModerateImageCommand, adminUserId: number, requestId: string): Promise<AdminImageItem>;
  updateProvider(providerId: string, command: UpdateProviderCommand, adminUserId: number, requestId: string): Promise<AdminProviderItem>;
  updateWorkflow(workflowId: string, command: UpdateWorkflowCommand, adminUserId: number, requestId: string): Promise<AdminWorkflowItem>;
}
