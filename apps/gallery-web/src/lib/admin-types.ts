/**
 * Admin 控制台共享类型（镜像 Generation Service 的管理契约）。
 */

export type ModerationStatus = "pending" | "approved" | "rejected" | "manual_review";

export interface AdminImageItem {
  readonly id: string;
  readonly slug: string;
  readonly title?: string;
  readonly workflowName: string;
  readonly createdAt: string;
  readonly moderationStatus: ModerationStatus;
  /** 图片可见性：public / private / unlisted。 */
  readonly visibility: string;
  /** Prompt 可见性：public / private。 */
  readonly promptVisibility: string;
  readonly thumbnailUrl: string;
  readonly updatedAt: string;
}

export interface AdminProviderItem {
  readonly id: string;
  readonly code: string;
  readonly displayName: string;
  readonly adapterType: string;
  readonly status: string;
  readonly priority: number;
  readonly secretConfigured: boolean;
  readonly consecutiveFailures: number;
  readonly lastHealthAt?: string;
  readonly updatedAt: string;
}

export interface AdminWorkflowItem {
  readonly id: string;
  readonly name: string;
  readonly slug: string;
  readonly category: string;
  readonly isEnabled: boolean;
  readonly activeVersion?: number;
  readonly bindingCount: number;
  readonly sortOrder: number;
  readonly updatedAt: string;
}

export interface AdminRecentJob {
  readonly id: string;
  readonly workflowName: string;
  readonly providerCode?: string;
  readonly status: string;
  readonly actualCost: number;
  readonly createdAt: string;
}

export interface AdminAuditEntry {
  readonly id: string;
  readonly action: string;
  readonly resourceType: string;
  readonly resourceId?: string;
  readonly createdAt: string;
}

export interface AdminDashboard {
  readonly overview: {
    readonly pendingModeration: number;
    readonly publicImages: number;
    readonly jobsLast24Hours: number;
    readonly failedJobsLast24Hours: number;
    readonly activeProviders: number;
    readonly enabledWorkflows: number;
  };
  readonly moderationQueue: readonly AdminImageItem[];
  readonly providers: readonly AdminProviderItem[];
  readonly workflows: readonly AdminWorkflowItem[];
  readonly recentJobs: readonly AdminRecentJob[];
  readonly recentAudit: readonly AdminAuditEntry[];
}
