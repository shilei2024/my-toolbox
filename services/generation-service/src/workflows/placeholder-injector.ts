import type { JsonValue } from "../providers/types.ts";

export const WORKFLOW_PLACEHOLDERS = [
  "prompt", "negative_prompt", "seed", "steps", "cfg", "mu", "std", "sampler", "scheduler",
  "width", "height", "model", "lora", "duration_seconds", "frame_count", "fps",
] as const;
export type WorkflowPlaceholder = (typeof WORKFLOW_PLACEHOLDERS)[number];
export type PlaceholderValues = Partial<Record<WorkflowPlaceholder, JsonValue>>;

const TOKEN = /\{\{([a-z_]+)\}\}/g;
const ALLOWED = new Set<string>(WORKFLOW_PLACEHOLDERS);

export class WorkflowPlaceholderError extends Error {
  readonly placeholder: string;
  readonly reason: "missing" | "unknown";

  constructor(placeholder: string, reason: "missing" | "unknown") {
    super(`Workflow placeholder ${placeholder} is ${reason}`);
    this.name = "WorkflowPlaceholderError";
    this.placeholder = placeholder;
    this.reason = reason;
  }
}

export function injectPlaceholders(template: JsonValue, values: PlaceholderValues): JsonValue {
  if (Array.isArray(template)) return template.map((item) => injectPlaceholders(item, values));
  if (template !== null && typeof template === "object") {
    return Object.fromEntries(Object.entries(template).map(([key, value]) => [key, injectPlaceholders(value, values)]));
  }
  if (typeof template !== "string") return template;

  const exact = template.match(/^\{\{([a-z_]+)\}\}$/);
  if (exact?.[1]) return resolve(exact[1], values);
  return template.replace(TOKEN, (_token, name: string) => String(resolve(name, values)));
}

function resolve(name: string, values: PlaceholderValues): JsonValue {
  if (!ALLOWED.has(name)) throw new WorkflowPlaceholderError(name, "unknown");
  const value = values[name as WorkflowPlaceholder];
  if (value === undefined || value === null) throw new WorkflowPlaceholderError(name, "missing");
  return value;
}
