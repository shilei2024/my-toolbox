/** Idle backoff for database pollers.
 *
 * An empty outbox is still queried on every poll; exponential idle backoff
 * keeps the loop responsive when work appears while avoiding thousands of
 * no-op queries per day on a paid/limited database.
 */
export function idleBackoffDelayMs(
  pollMs: number,
  idleMaxMs: number,
  consecutiveIdle: number,
): number {
  if (consecutiveIdle <= 0) return 0;
  const exponent = Math.min(consecutiveIdle - 1, 6);
  return Math.min(idleMaxMs, pollMs * 2 ** exponent);
}
