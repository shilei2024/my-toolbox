import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { safeAuthReturnUrl } from "../src/lib/auth-return-url.ts";

describe("Gallery authentication return URLs", () => {
  it("allows relative and same-origin HTTPS returns", () => {
    assert.equal(safeAuthReturnUrl("/create", "https://gallery.example.com"), "/create");
    assert.equal(safeAuthReturnUrl("https://gallery.example.com/create", "https://gallery.example.com"), "https://gallery.example.com/create");
  });

  it("allows same-origin loopback HTTP for local development", () => {
    assert.equal(safeAuthReturnUrl("http://127.0.0.1:3000/create", "http://127.0.0.1:3000"), "http://127.0.0.1:3000/create");
  });

  it("rejects cross-origin, port-changing and non-loopback HTTP returns", () => {
    assert.equal(safeAuthReturnUrl("https://evil.example/create", "https://gallery.example.com"), undefined);
    assert.equal(safeAuthReturnUrl("http://127.0.0.1:3001/create", "http://127.0.0.1:3000"), undefined);
    assert.equal(safeAuthReturnUrl("http://gallery.example.com/create", "http://gallery.example.com"), undefined);
  });
});
