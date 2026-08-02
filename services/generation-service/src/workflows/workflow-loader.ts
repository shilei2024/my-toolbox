import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { Ajv, type ValidateFunction } from "ajv";
import type { JsonObject } from "../providers/types.ts";

const REF = /^([a-z0-9]+(?:-[a-z0-9]+)*)-v([1-9]\d*)$/;
const WORKFLOW_SCHEMA = {
  type: "object",
  minProperties: 1,
  additionalProperties: {
    type: "object",
    required: ["class_type", "inputs"],
    properties: { class_type: { type: "string", minLength: 1 }, inputs: { type: "object" } },
    additionalProperties: true,
  },
} as const;

export interface LoadedWorkflow {
  readonly reference: string;
  readonly workflowName: string;
  readonly workflowVersion: number;
  readonly digest: string;
  readonly template: JsonObject;
}

export class WorkflowLoadError extends Error {
  readonly code: "invalid_reference" | "not_found" | "invalid_json" | "invalid_schema";

  constructor(code: "invalid_reference" | "not_found" | "invalid_json" | "invalid_schema", message: string) {
    super(message);
    this.name = "WorkflowLoadError";
    this.code = code;
  }
}

export class WorkflowLoader {
  readonly #directory: string;
  readonly #validate: ValidateFunction;
  readonly #cache = new Map<string, { signature: string; value: LoadedWorkflow }>();

  constructor(directory: string) {
    this.#directory = path.resolve(directory);
    this.#validate = new Ajv({ allErrors: true, strict: true }).compile(WORKFLOW_SCHEMA);
  }

  async load(reference: string): Promise<LoadedWorkflow> {
    const match = REF.exec(reference);
    if (!match?.[1] || !match[2]) throw new WorkflowLoadError("invalid_reference", "Workflow reference is invalid");
    const filename = path.join(this.#directory, `${reference}.json`);
    if (path.dirname(filename) !== this.#directory) throw new WorkflowLoadError("invalid_reference", "Workflow path is invalid");
    let fileStat;
    try { fileStat = await stat(filename); } catch { throw new WorkflowLoadError("not_found", "Workflow does not exist"); }
    const signature = `${fileStat.mtimeMs}:${fileStat.size}`;
    const cached = this.#cache.get(reference);
    if (cached?.signature === signature) return structuredClone(cached.value);
    let raw: string;
    try { raw = await readFile(filename, "utf8"); } catch { throw new WorkflowLoadError("not_found", "Workflow cannot be read"); }
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { throw new WorkflowLoadError("invalid_json", "Workflow JSON is invalid"); }
    if (!this.#validate(parsed)) throw new WorkflowLoadError("invalid_schema", "Workflow JSON does not match the API workflow schema");
    const value: LoadedWorkflow = {
      reference,
      workflowName: match[1],
      workflowVersion: Number(match[2]),
      digest: createHash("sha256").update(raw).digest("hex"),
      template: parsed as JsonObject,
    };
    this.#cache.set(reference, { signature, value });
    return structuredClone(value);
  }

  clear(): void { this.#cache.clear(); }
}
