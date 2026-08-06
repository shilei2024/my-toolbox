import assert from "node:assert/strict";
import test from "node:test";

import { idleBackoffDelayMs } from "../src/queue/idle-backoff.ts";

test("idle backoff starts at the poll interval and doubles up to the cap", () => {
  assert.equal(idleBackoffDelayMs(1000, 30_000, 1), 1000);
  assert.equal(idleBackoffDelayMs(1000, 30_000, 2), 2000);
  assert.equal(idleBackoffDelayMs(1000, 30_000, 5), 16_000);
  assert.equal(idleBackoffDelayMs(1000, 30_000, 6), 30_000);
  assert.equal(idleBackoffDelayMs(1000, 30_000, 20), 30_000);
});

test("idle backoff respects a custom poll interval", () => {
  assert.equal(idleBackoffDelayMs(5000, 30_000, 3), 20_000);
  assert.equal(idleBackoffDelayMs(10_000, 30_000, 4), 30_000);
});

test("idle backoff returns zero when the queue is not idle", () => {
  assert.equal(idleBackoffDelayMs(1000, 30_000, 0), 0);
});
