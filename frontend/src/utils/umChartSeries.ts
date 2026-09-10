import type { ChartQuality, ChartSeries } from "./chartData";

export interface UmChartSeries {
  seriesInstanceId: string;
  tagId: number;
  tagName: string;
  displayName: string;
  unit: string | null;
  color: string;
  /** Codes por índice no eixo Y: 0, 1, 2... */
  categories: string[];
  /** Pontos em degraus: [[timestamp, indexCategoria, code]] */
  steps: Array<[number, number, string]>;
  qualitySeries: Array<[number, ChartQuality]>;
  total: number;
}

function toCategoryValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return String(value);
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  return null;
}

function qualityOf(point: { good?: boolean; questionable?: boolean; substituted?: boolean }): ChartQuality {
  if (point.good) return 0;
  if (point.substituted) return 1;
  if (point.questionable) return 2;
  return 3;
}

export interface BuildUmInput {
  seriesInstanceId: string;
  tagId: number;
  tagName: string;
  displayName: string;
  unit: string | null;
  color: string;
  points: Array<{ timestamp: string; value: unknown; good?: boolean; questionable?: boolean; substituted?: boolean }>;
  endTimeIso: string;
}

export function buildUmChartSeries(input: BuildUmInput): UmChartSeries {
  const categoryMap = new Map<string, number>();
  const categories: string[] = [];
  const steps: Array<[number, number, string]> = [];
  const qualitySeries: Array<[number, ChartQuality]> = [];

  let lastCode: string | null = null;

  for (const point of input.points) {
    const ts = Date.parse(point.timestamp);
    if (!Number.isFinite(ts)) continue;
    const code = toCategoryValue(point.value);
    qualitySeries.push([ts, qualityOf(point)]);
    if (code === null) {
      lastCode = null;
      continue;
    }
    let idx = categoryMap.get(code);
    if (idx === undefined) {
      idx = categories.length;
      categories.push(code);
      categoryMap.set(code, idx);
    }
    if (code !== lastCode) {
      steps.push([ts, idx, code]);
      lastCode = code;
    }
  }

  // Estende o último estado até o fim do período, preservando continuidade
  const endTs = Date.parse(input.endTimeIso);
  if (
    steps.length > 0 &&
    Number.isFinite(endTs) &&
    endTs > steps[steps.length - 1][0]
  ) {
    const [, lastIdx, lastCode] = steps[steps.length - 1];
    steps.push([endTs, lastIdx, lastCode]);
  }

  return {
    seriesInstanceId: input.seriesInstanceId,
    tagId: input.tagId,
    tagName: input.tagName,
    displayName: input.displayName,
    unit: input.unit,
    color: input.color,
    categories,
    steps,
    qualitySeries,
    total: input.points.length,
  };
}

export function isCategoricalSeries(series: ChartSeries): boolean {
  return series.valueKind === "categorical";
}