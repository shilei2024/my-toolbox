export type AdminProviderStatus = "active" | "degraded" | "disabled";
export type AdminModerationDecision = "approved" | "rejected";

export interface AdminOverview {
  readonly pendingModeration: number;
  readonly publicImages: number;
  readonly jobsLast24Hours: number;
  readonly failedJobsLast24Hours: number;
  readonly activeProviders: number;
  readonly enabledWorkflows: number;
}

export interface AdminImageItem {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly workflowName: string;
  readonly moderationStatus: "pending" | "manual_review" | "approved" | "rejected";
  readonly visibility: "public" | "private";
  readonly promptVisibility: "public" | "hidden";
  readonly thumbnailUrl: string;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface AdminProviderItem {
  readonly id: string;
  readonly code: string;
  readonly displayName: string;
  readonly adapterType: string;
  readonly status: AdminProviderStatus;
  readonly priority: number;
  readonly secretConfigured: boolean;
  readonly consecutiveFailures: number;
  readonly lastHealthAt?: string;
  readonly updatedAt: string;
  readonly models: readonly AdminProviderModelItem[];
}

export interface AdminProviderModelItem {
  readonly id: string;
  readonly providerId: string;
  readonly modelCode: string;
  readonly displayName: string;
  readonly tier: "free" | "member";
  readonly creditCost?: number;
  readonly isDefault: boolean;
  readonly isEnabled: boolean;
  readonly updatedAt: string;
}

export interface AdminWorkflowItem {
  readonly id: string;
  readonly slug: string;
  readonly name: string;
  readonly category: string;
  readonly isEnabled: boolean;
  readonly sortOrder: number;
  readonly activeVersion?: number;
  readonly bindingCount: number;
  readonly updatedAt: string;
}

export interface AdminJobItem {
  readonly id: string;
  readonly status: "pending" | "running" | "completed" | "failed" | "cancelled";
  readonly workflowName: string;
  readonly providerCode?: string;
  readonly actualCost: number;
  readonly createdAt: string;
  readonly finishedAt?: string;
}

export interface AdminAuditItem {
  readonly id: string;
  readonly actorUserId?: number;
  readonly action: string;
  readonly resourceType: string;
  readonly resourceId?: string;
  readonly createdAt: string;
}

export interface AdminDashboard {
  readonly overview: AdminOverview;
  readonly moderationQueue: readonly AdminImageItem[];
  readonly providers: readonly AdminProviderItem[];
  readonly workflows: readonly AdminWorkflowItem[];
  readonly recentJobs: readonly AdminJobItem[];
  readonly recentAudit: readonly AdminAuditItem[];
}

export interface ModerateImageCommand {
  readonly decision: AdminModerationDecision;
  readonly reasonCodes: readonly string[];
  readonly expectedUpdatedAt: string;
}

export interface UpdateProviderCommand {
  readonly status: "active" | "disabled";
  readonly priority: number;
  readonly expectedUpdatedAt: string;
}

export interface UpdateProviderModelCommand {
  readonly tier: "free" | "member";
  readonly creditCost?: number;
  readonly isDefault: boolean;
  readonly isEnabled: boolean;
  readonly expectedUpdatedAt: string;
}

export interface UpdateWorkflowCommand {
  readonly isEnabled: boolean;
  readonly sortOrder: number;
  readonly expectedUpdatedAt: string;
}
