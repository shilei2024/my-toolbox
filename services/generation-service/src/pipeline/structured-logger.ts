import type { JsonValue } from "../providers/types.ts";
export interface StructuredLogger { info(event: string, fields: Readonly<Record<string, JsonValue>>): void; error(event: string, fields: Readonly<Record<string, JsonValue>>): void }
export class ConsoleStructuredLogger implements StructuredLogger {
  info(event: string, fields: Readonly<Record<string, JsonValue>>): void { console.info(JSON.stringify({ level: "info", event, ...fields })); }
  error(event: string, fields: Readonly<Record<string, JsonValue>>): void { console.error(JSON.stringify({ level: "error", event, ...fields })); }
}

