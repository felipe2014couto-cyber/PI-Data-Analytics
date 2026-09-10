import type { SeriesVisualConfiguration, VisualNormLimitConfiguration } from "../types";

export const EMPTY_VISUAL_CONFIGURATION = (seriesInstanceId: string): SeriesVisualConfiguration => ({
  seriesInstanceId, limits: [], normLimit: null,
});

export function isValidColor(color: string): boolean {
  return /^#[0-9a-f]{6}$/i.test(color);
}

export function parseFiniteNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function moveVisualItem<T>(items: readonly T[], index: number, direction: "up" | "down"): T[] {
  const target = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function defaultNormLimitConfig(): VisualNormLimitConfiguration {
  return {
    enabled: true,
    lowerColor: "#d32f2f",
    upperColor: "#d32f2f",
    lineStyle: "dashed",
    width: 2,
  };
}