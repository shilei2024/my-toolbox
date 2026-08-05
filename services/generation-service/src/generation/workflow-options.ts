export interface IntegerBounds {
  readonly min: number;
  readonly max: number;
}

export interface WorkflowInputBounds {
  readonly width: IntegerBounds;
  readonly height: IntegerBounds;
  readonly count: IntegerBounds;
}

export interface WorkflowSizePreset {
  readonly width: number;
  readonly height: number;
}

const DEFAULT_BOUNDS: WorkflowInputBounds = {
  width: { min: 64, max: 8192 },
  height: { min: 64, max: 8192 },
  count: { min: 1, max: 8 },
};

export const WORKFLOW_SIZE_PRESETS: readonly WorkflowSizePreset[] = [
  { width: 1024, height: 1024 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 768, height: 1344 },
  { width: 1344, height: 768 },
  { width: 832, height: 1248 },
  { width: 1248, height: 832 },
];

export function workflowBounds(inputSchema: unknown): WorkflowInputBounds {
  const properties = isRecord(inputSchema) && isRecord(inputSchema.properties) ? inputSchema.properties : undefined;
  return {
    width: boundsOf(properties?.width, DEFAULT_BOUNDS.width),
    height: boundsOf(properties?.height, DEFAULT_BOUNDS.height),
    count: boundsOf(properties?.count, DEFAULT_BOUNDS.count),
  };
}

export function workflowSizePresets(bounds: WorkflowInputBounds, defaults: { readonly width: number; readonly height: number }): readonly WorkflowSizePreset[] {
  const merged = new Map<string, WorkflowSizePreset>();
  for (const preset of WORKFLOW_SIZE_PRESETS) {
    if (inBounds(preset.width, bounds.width) && inBounds(preset.height, bounds.height)) {
      merged.set(`${preset.width}x${preset.height}`, preset);
    }
  }
  const fallback = { width: defaults.width, height: defaults.height };
  if (!merged.has(`${fallback.width}x${fallback.height}`) && inBounds(fallback.width, bounds.width) && inBounds(fallback.height, bounds.height)) {
    merged.set(`${fallback.width}x${fallback.height}`, fallback);
  }
  return [...merged.values()].slice(0, 12);
}

export function clampToBounds(value: number, bounds: IntegerBounds): number {
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

function boundsOf(schema: unknown, fallback: IntegerBounds): IntegerBounds {
  if (!isRecord(schema)) return fallback;
  const minimum = integerOf(schema.minimum);
  const maximum = integerOf(schema.maximum);
  const min = minimum ?? fallback.min;
  const max = maximum ?? fallback.max;
  return { min: Math.min(min, max), max: Math.max(min, max) };
}

function integerOf(value: unknown): number | undefined {
  return Number.isSafeInteger(value) ? Number(value) : undefined;
}

function inBounds(value: number, bounds: IntegerBounds): boolean {
  return value >= bounds.min && value <= bounds.max;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
