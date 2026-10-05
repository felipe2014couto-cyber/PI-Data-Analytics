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
  lowerCoverageGaps?: Array<[string, string]>;
  upperCoverageGaps?: Array<[string, string]>;
  startTimeIso?: string;
  endTimeIso?: string;
}

function toChartPoints(
  points: PiTagNormLimitPoint[],
  coverageGaps: Array<[string, string]> = [],
  startTimeIso?: string,
  endTimeIso?: string,
): Array<[number, number | null]> {
  const startTs = startTimeIso ? Date.parse(startTimeIso) : NaN;
  const endTs = endTimeIso ? Date.parse(endTimeIso) : NaN;
  const events: Array<[number, number | null, boolean]> = [];
  for (const p of points) {
    const ts = Date.parse(p.timestamp);
    if (!Number.isFinite(ts)) continue;
    const good = p.good !== false && p.questionable !== true && p.substituted !== true;
    events.push([ts, good && typeof p.value === "number" && Number.isFinite(p.value) ? p.value : null, good]);
  }
  const gaps = coverageGaps.map(([a, b]) => [Date.parse(a), Date.parse(b)] as const)
    .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && a < b);
  const inGap = (ts: number) => gaps.some(([a, b]) => ts >= a && ts < b);
  events.sort((a, b) => a[0] - b[0]);
  let current: number | null = null;
  const beforeWindow = events.filter(([ts]) => !Number.isFinite(startTs) || ts <= startTs);
  const priorOperations: Array<{ ts: number; kind: "gap" | "event"; value?: number | null; good?: boolean }> = [
    ...gaps.filter(([a]) => !Number.isFinite(startTs) || a <= startTs).map(([ts]) => ({ ts, kind: "gap" as const })),
    ...beforeWindow.map(([ts, value, good]) => ({ ts, kind: "event" as const, value, good })),
  ].sort((a, b) => a.ts - b.ts || (a.kind === "gap" ? -1 : 1));
  for (const operation of priorOperations) {
    if (operation.kind === "gap") current = null;
    else if (inGap(operation.ts)) continue;
    else current = operation.good && operation.value !== null ? operation.value! : null;
  }
  if (Number.isFinite(startTs) && inGap(startTs)) current = null;
  const out: Array<[number, number | null]> = [];
  if (Number.isFinite(startTs) && Number.isFinite(endTs) && startTs < endTs && current !== null) out.push([startTs, current]);
  const timeline: Array<{ ts: number; kind: "gap" | "event"; value?: number | null; good?: boolean }> = [
    ...gaps.filter(([a]) => (!Number.isFinite(startTs) || a > startTs) && (!Number.isFinite(endTs) || a < endTs)).map(([ts]) => ({ ts, kind: "gap" as const })),
    ...events.filter(([ts]) => (!Number.isFinite(startTs) || ts > startTs) && (!Number.isFinite(endTs) || ts < endTs))
      .map(([ts, value, good]) => ({ ts, kind: "event" as const, value, good })),
  ].sort((a, b) => a.ts - b.ts || (a.kind === "gap" ? -1 : 1));
  for (const operation of timeline) {
    if (operation.kind === "gap") {
      current = null;
      out.push([operation.ts, null]);
    } else {
      if (inGap(operation.ts)) continue;
      current = operation.good && operation.value !== null ? operation.value! : null;
      out.push([operation.ts, current]);
    }
  }
  out.sort((a, b) => a[0] - b[0]);
  current = out.length ? out[out.length - 1][1] : current;
  if (Number.isFinite(endTs) && current !== null && (!out.length || out[out.length - 1][1] !== null)) out.push([endTs, current]);
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
  };
}
