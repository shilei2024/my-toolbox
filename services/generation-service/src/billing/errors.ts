export class BillingError extends Error {
  readonly code: string;
  readonly statusCode: number;
  constructor(
    code: string,
    message: string,
    statusCode: number,
  ) {
    super(message);
    this.name = "BillingError";
    this.code = code;
    this.statusCode = statusCode;
  }
}

export function normalizeBillingError(error: unknown): BillingError {
  if (error instanceof BillingError) return error;
  return new BillingError("billing_unavailable", "Billing is temporarily unavailable", 503);
}
