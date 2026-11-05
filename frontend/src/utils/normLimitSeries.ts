import type { PiTagNormLimitPoint } from "../types";

export interface NormLimitSeries {
  seriesInstanceId: string;
  tagName: string | null;
  mainDisplayName?: string | null;
  lowerTagName?: string | null;
  upperTagName?: string | null;
  yAxisIndex: number;
  lineStyle: "solid" | "dashed" | "dotted";
  width: number;
  lowerColor: string;
  upperColor: string;
  lowerPoints: Array<[number, number | null]>;
  upperPoints: Array<[number, number | null]>;
  lowerStatePoints?: NormLimitStatePoint[];
  upperStatePoints?: NormLimitStatePoint[];
  lowerCoverageGaps?: Array<[NormLimitTimestamp, NormLimitTimestamp]>;
  upperCoverageGaps?: Array<[NormLimitTimestamp, NormLimitTimestamp]>;
}

export type NormLimitTimestamp = string | number | Date;

export interface NormLimitStatePoint {
  timestamp: NormLimitTimestamp;
  value: number | null;
  good?: boolean;
  questionable?: boolean;
}

export type NormLimitCoverageGap = [NormLimitTimestamp, NormLimitTimestamp];

function timestampToUtcMs(value: NormLimitTimestamp): number | null {
  const timestamp = value instanceof Date ? value.getTime() : typeof value === "number" ? value : Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

/** The single Good/null state resolver used for both the plotted line and marker card. */
export function resolveNormLimitStateAtTimestamp(
  points: readonly NormLimitStatePoint[],
  timestamp: NormLimitTimestamp,
  coverageGaps: readonly NormLimitCoverageGap[] = [],
): number | null {
  const targetMs = timestampToUtcMs(timestamp);
  if (targetMs === null) return null;

  const gaps = coverageGaps
    .map(([start, end]) => [timestampToUtcMs(start), timestampToUtcMs(end)] as const)
    .filter((gap): gap is readonly [number, number] => gap[0] !== null && gap[1] !== null && gap[0] < gap[1]);
  const inCoverageGap = (ms: number) => gaps.some(([start, end]) => ms >= start && ms < end);

  const events: Array<{ timestamp: number; value: number | null; isGap: boolean }> = [];
  for (const point of points) {
    const pointMs = timestampToUtcMs(point.timestamp);
    if (pointMs === null || pointMs > targetMs || inCoverageGap(pointMs)) continue;
    const finiteValue = typeof point.value === "number" && Number.isFinite(point.value) ? point.value : null;
    const valid = point.good !== false && point.questionable !== true && finiteValue !== null;
    events.push({ timestamp: pointMs, value: valid ? finiteValue : null, isGap: false });
  }
  for (const [start, end] of gaps) {
    if (start <= targetMs) events.push({ timestamp: start, value: null, isGap: true });
    // A real coverage gap invalidates the retained state through its end and
    // until another Good event is observed, even if there are no samples in it.
    if (targetMs >= start && targetMs < end) events.push({ timestamp: targetMs, value: null, isGap: true });
  }

  events.sort((a, b) => a.timestamp - b.timestamp || Number(a.isGap) - Number(b.isGap));
  return events.length ? events[events.length - 1].value : null;
}

export interface BuildNormLimitInput {
  seriesInstanceId: string;
  tagName: string | null;
  mainDisplayName?: string | null;
  lowerTagName?: string | null;
  upperTagName?: string | null;
  yAxisIndex: number;
  lineStyle: "solid" | "dashed" | "dotted";
  width: number;
  lowerColor: string;
  upperColor: string;
  lowerPoints: PiTagNormLimitPoint[];
  upperPoints: PiTagNormLimitPoint[];
  lowerCoverageGaps?: NormLimitCoverageGap[];
  upperCoverageGaps?: NormLimitCoverageGap[];
  startTimeIso?: string;
  endTimeIso?: string;
}

function toChartPoints(
  points: PiTagNormLimitPoint[],
  coverageGaps: NormLimitCoverageGap[] = [],
  startTimeIso?: string,
  endTimeIso?: string,
): Array<[number, number | null]> {
  const startTs = startTimeIso ? timestampToUtcMs(startTimeIso) : null;
  const endTs = endTimeIso ? timestampToUtcMs(endTimeIso) : null;
  const eventTimes = points.map((point) => timestampToUtcMs(point.timestamp)).filter((ts): ts is number => ts !== null);
  const gapStarts = coverageGaps.map(([a]) => timestampToUtcMs(a)).filter((ts): ts is number => ts !== null);
  let current = startTs === null ? null : resolveNormLimitStateAtTimestamp(points, startTs, coverageGaps);
  const out: Array<[number, number | null]> = [];
  if (startTs !== null && endTs !== null && startTs < endTs && current !== null) out.push([startTs, current]);
  const boundaries = [...new Set([...eventTimes, ...gapStarts])]
    .filter((ts) => (startTs === null || ts > startTs) && (endTs === null || ts < endTs))
    .sort((a, b) => a - b);
  for (const ts of boundaries) {
    const next = resolveNormLimitStateAtTimestamp(points, ts, coverageGaps);
    if (next === current) continue;
    if (next === null) {
      if (current !== null) out.push([ts, current]);
      out.push([ts, null]);
    } else {
      out.push([ts, next]);
    }
    current = next;
  }
  if (endTs !== null) {
    const atEnd = resolveNormLimitStateAtTimestamp(points, endTs, coverageGaps);
    if (atEnd !== current) {
      if (atEnd === null && current !== null) out.push([endTs, current]);
      out.push([endTs, atEnd]);
      current = atEnd;
    } else if (current !== null && out[out.length - 1]?.[0] !== endTs) {
      out.push([endTs, current]);
    }
  }
  return out;
}

export function buildNormLimitSeries(input: BuildNormLimitInput): NormLimitSeries {
  return {
    seriesInstanceId: input.seriesInstanceId,
    tagName: input.tagName,
    mainDisplayName: input.mainDisplayName ?? null,
    lowerTagName: input.lowerTagName ?? null,
    upperTagName: input.upperTagName ?? null,
    yAxisIndex: input.yAxisIndex,
    lineStyle: input.lineStyle,
    width: input.width,
    lowerColor: input.lowerColor,
    upperColor: input.upperColor,
    lowerPoints: toChartPoints(input.lowerPoints, input.lowerCoverageGaps, input.startTimeIso, input.endTimeIso),
    upperPoints: toChartPoints(input.upperPoints, input.upperCoverageGaps, input.startTimeIso, input.endTimeIso),
    lowerStatePoints: input.lowerPoints,
    upperStatePoints: input.upperPoints,
    lowerCoverageGaps: input.lowerCoverageGaps ?? [],
    upperCoverageGaps: input.upperCoverageGaps ?? [],
  };
}

/** Preserve the safe API diagnosis even when an adapter did not construct ApiError. */
export function normLimitErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const body = error as { error?: { message?: unknown }; message?: unknown; name?: unknown };
    const message = body.error?.message ?? body.message;
    if (typeof message === "string" && message.trim()) {
      if (body.name === "AbortError") return `Consulta do limite cancelada: ${message}`;
      return message.trim();
    }
  }
  if (typeof error === "string" && error.trim()) return error.trim();
  return "Falha de consulta do limite: resposta sem diagnóstico técnico.";
}
