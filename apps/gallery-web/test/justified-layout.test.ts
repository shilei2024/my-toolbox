import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildJustifiedRows } from "../src/lib/justified-layout.ts";

describe("Justified gallery layout", () => {
  it("returns no rows for an empty feed", () => {
    assert.deepEqual(buildJustifiedRows([], 1200, 280), []);
  });

  it("fills every closed row to the container width", () => {
    const items = [1.5, 0.75, 1, 0.6, 1.8, 1.2, 0.9].map((ratio, index) => ({ id: index, width: Math.round(1000 * ratio), height: 1000 }));
    const rows = buildJustifiedRows(items, 1200, 280, 16);
    assert.ok(rows.length >= 2);
    for (const row of rows.slice(0, -1)) {
      const width = row.tiles.reduce((sum, tile) => sum + row.height * tile.ratio, 0) + 16 * (row.tiles.length - 1);
      assert.ok(Math.abs(width - 1200) <= 1, `row width ${width} should fill 1200`);
      assert.ok(row.height <= 280 + 0.01);
    }
  });

  it("never stretches the trailing row beyond 1.15x target height", () => {
    const items = [{ id: 1, width: 1000, height: 1000 }];
    const [row] = buildJustifiedRows(items, 1200, 280, 16);
    assert.ok(row);
    assert.equal(row.tiles.length, 1);
    assert.ok(row.height <= 280 * 1.15 + 0.01);
  });

  it("clamps extreme aspect ratios so panoramas and strips stay in the grid", () => {
    const rows = buildJustifiedRows([{ width: 8000, height: 1000 }, { width: 300, height: 4000 }], 1200, 280, 16);
    const ratios = rows.flatMap((row) => row.tiles.map((tile) => tile.ratio));
    assert.deepEqual(ratios, [2.4, 0.45]);
  });

  it("keeps a minimum container width for narrow viewports", () => {
    const rows = buildJustifiedRows([{ width: 1000, height: 1000 }], 120, 190, 16);
    // 容器宽度被抬到 320，但最后一行仍受 1.15x 目标行高保护。
    assert.ok((rows[0]?.height ?? 0) <= 190 * 1.15 + 0.01);
  });
});
