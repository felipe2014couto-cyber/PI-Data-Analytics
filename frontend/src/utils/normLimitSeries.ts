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
  startTimeIso?: string;
  endTimeIso?: string;
}

function toChartPoints(
  points: PiTagNormLimitPoint[],
  startTimeIso?: string,
  endTimeIso?: string,
): Array<[number, number | null]> {
  const out: Array<[number, number | null]> = [];
  for (const p of points) {
    const ts = Date.parse(p.timestamp);
    if (!Number.isFinite(ts)) continue;
    out.push([ts, typeof p.value === "number" && Number.isFinite(p.value) ? p.value : null]);
  }
  if (out.length === 1 && out[0][1] !== null) {
    const val = out[0][1];
    const pTs = out[0][0];
    const startTs = startTimeIso ? Date.parse(startTimeIso) : NaN;
    const endTs = endTimeIso ? Date.parse(endTimeIso) : NaN;
    const actualStart = Number.isFinite(startTs) ? Math.min(startTs, pTs) : pTs;
    const actualEnd = Number.isFinite(endTs) ? Math.max(endTs, pTs) : pTs;
    if (actualEnd > actualStart) {
      return [
        [actualStart, val],
        [actualEnd, val],
      ];
    }
  } else if (out.length > 1 && endTimeIso) {
    const endTs = Date.parse(endTimeIso);
    const last = out[out.length - 1];
    if (Number.isFinite(endTs) && endTs > last[0] && last[1] !== null) {
      out.push([endTs, last[1]]);
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
    lowerPoints: toChartPoints(input.lowerPoints, input.startTimeIso, input.endTimeIso),
    upperPoints: toChartPoints(input.upperPoints, input.startTimeIso, input.endTimeIso),
  };
}