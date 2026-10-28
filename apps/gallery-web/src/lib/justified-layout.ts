/**
 * Justified（逐行对齐）作品墙布局。
 *
 * 参考画廊的核心视觉是"每行图片等高、行宽填满容器"，而不是等高瀑布流：
 * 按原图宽高比累加，一旦当前行缩放到目标行高就断行，最后一行不强行拉满。
 *
 * 纯函数 + 已知宽高比 → 服务端与客户端渲染结果一致，避免首屏跳动；
 * 容器宽度由 ResizeObserver 提供，只影响断行位置。
 */

export interface LayoutSource {
  readonly width: number;
  readonly height: number;
}

export interface LayoutTile<T> {
  readonly item: T;
  readonly ratio: number;
}

export interface LayoutRow<T> {
  readonly tiles: readonly LayoutTile<T>[];
  readonly height: number;
}

export const DEFAULT_ROW_GAP = 16;

export function buildJustifiedRows<T extends LayoutSource>(
  items: readonly T[],
  containerWidth: number,
  targetHeight: number,
  gap: number = DEFAULT_ROW_GAP,
): readonly LayoutRow<T>[] {
  if (items.length === 0) return [];
  const width = Math.max(containerWidth, 320);
  const target = Math.max(targetHeight, 80);
  const spacing = Math.max(gap, 0);
  const rows: LayoutRow<T>[] = [];
  let current: LayoutTile<T>[] = [];
  let ratioSum = 0;

  for (const item of items) {
    const ratio = clamp(item.width / (item.height || 1) || 1, 0.45, 2.4);
    current.push({ item, ratio });
    ratioSum += ratio;
    const available = width - spacing * (current.length - 1);
    const height = available / ratioSum;
    if (height <= target) {
      rows.push({ tiles: current, height });
      current = [];
      ratioSum = 0;
    }
  }

  if (current.length > 0) {
    const available = width - spacing * (current.length - 1);
    // 最后一行不拉伸到满宽，否则 1–2 张图会被放大成巨幅。
    rows.push({ tiles: current, height: Math.min(available / ratioSum, target * 1.15) });
  }
  return rows;
}

export function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(Math.max(value, min), max);
}
