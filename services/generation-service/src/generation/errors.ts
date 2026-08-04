export class GenerationError extends Error {
  readonly code: string;
  readonly statusCode: number;
  constructor(code: string, message: string, statusCode: number) {
    super(message);
    this.name = "GenerationError";
    this.code = code;
    this.statusCode = statusCode;
  }
}

export function normalizeGenerationError(error: unknown): GenerationError {
  if (error instanceof GenerationError) return error;
  const message = error instanceof Error ? error.message : "";
  if (message.includes("insufficient_credits")) return new GenerationError("insufficient_credits", "可用积分不足，请先充值或选择其他套餐。", 409);
  return new GenerationError("generation_unavailable", "创作服务暂时不可用，请稍后重试。", 503);
}
