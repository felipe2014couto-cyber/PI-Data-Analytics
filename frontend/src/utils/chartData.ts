import type {
  ComparisonType,
  TimeSeries,
  TimeSeriesPoint,
  TimeSeriesSeries,
  VisualizationType,
  SeriesAssignment,
} from "../types";
import { isNumericValue } from "./values";
import { assignmentIdentity, resolveSeriesOrder } from "./seriesAssignments";

export const PALETTE = [
  "#1976d2",
  "#d32f2f",
  "#388e3c",
  "#f57c00",
  "#7b1fa2",
  "#0288d1",
  "#c2185b",
  "#5d4037",
  "#455a64",
  "#00796b",
  "#afb42b",
  "#e64a19",
];

export type ChartValueKind = "numeric" | "textual" | "mixed" | "empty";

export type ChartQuality = 0 | 1 | 2 | 3;

export interface ChartSeries {
  tagId: number;
  displayName: string;
  tagName: string;
  equipment: string | null;
  section: string | null;
  variableType: string | null;
  unit: string | null;
  yAxisIndex: 0 | 1;
  color: string;
  contextId?: "A" | "B" | null;
  seriesInstanceId?: string | null;
  comparisonType?: ComparisonType | null;
  originalTimestamps?: string[];
  total: number;
  numeric: number;
  dropped: number;
  nonNumeric: number;
  points: Array<[number, number | null]>;
  qualitySeries: Array<[number, ChartQuality]>;
  valueKind: ChartValueKind;
  statePoints: Array<[number, number]>;
  stateValues: string[];
  stateQualitySeries: Array<[number, ChartQuality]>;
}

export interface ChartBuildResult {
  series: ChartSeries[];
  units: string[];
  yAxisLabels: string[];
  totalSeries: number;
  totalPoints: number;
  totalNumericPoints: number;
  totalDroppedPoints: number;
  totalNonNumericPoints: number;
  valueKind: ChartValueKind;
  categories: string[];
  comparisonType: ComparisonType | null;
}

export interface ChartDataGroups {
  summary: ChartBuildResult;
  numeric: ChartBuildResult | null;
  textual: ChartBuildResult[];
  mixedSeries: ChartSeries[];
}

export interface VisualizationPlan {
  numeric: ChartBuildResult | null;
  textual: ChartBuildResult | null;
  incompatibleSeries: ChartSeries[];
  excessTextualSeries: ChartSeries[];
}

const NO_UNIT_KEY = "(sem unidade)";

const QUALITY_GOOD = 0;
const QUALITY_SUBSTITUTED = 1;
const QUALITY_QUESTIONABLE = 2;
const QUALITY_BAD = 3;

function classifyQuality(point: TimeSeriesPoint): ChartQuality {
  if (point.good) {
    return QUALITY_GOOD;
  }
  if (point.substituted) {
    return QUALITY_SUBSTITUTED;
  }
  if (point.questionable) {
    return QUALITY_QUESTIONABLE;
  }
  return QUALITY_BAD;
}

function classifyValue(value: TimeSeriesPoint["value"]): ChartValueKind {
  if (isNumericValue(value)) {
    return "numeric";
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return "textual";
  }
  return "empty";
}

function mergeValueKinds(current: ChartValueKind, next: ChartValueKind): ChartValueKind {
  if (next === "empty") return current;
  if (current === "empty") return next;
  if (current === next) return current;
  return "mixed";
}

function buildUnitSlot(
  unit: string | null,
  units: Array<{ key: string; display: string }>,
): 0 | 1 {
  const display = unit && unit.trim() ? unit : NO_UNIT_KEY;
  const key = display.toLowerCase();
  const index = units.findIndex((entry) => entry.key === key);
  if (index === -1) {
    units.push({ key, display });
    return units.length === 1 ? 0 : 1;
  }
  return index === 0 ? 0 : 1;
}

export interface BuildChartOptions {
  ignoreBadQuality: boolean;
}

export function buildChartData(
  timeSeries: TimeSeries,
  options: BuildChartOptions,
): ChartBuildResult {
  const units: Array<{ key: string; display: string }> = [];
  const series: ChartSeries[] = [];
  let totalPoints = 0;
  let totalNumeric = 0;
  let totalDropped = 0;
  let totalNonNumeric = 0;
  let valueKind: ChartValueKind = "empty";
  const categories: string[] = [];
  const categoryIndexes = new Map<string, number>();
  const comparisonType = timeSeries.series.find((entry) => entry.comparison_type)?.comparison_type ?? null;

  timeSeries.series.forEach((seriesEntry, index) => {
    const yAxisIndex = buildUnitSlot(seriesEntry.unit, units);
    const color = PALETTE[index % PALETTE.length];
    const points: Array<[number, number | null]> = [];
    const qualitySeries: Array<[number, ChartQuality]> = [];
    const statePoints: Array<[number, number]> = [];
    const stateValues: string[] = [];
    const stateQualitySeries: Array<[number, ChartQuality]> = [];
    const originalTimestamps: string[] = [];
    let numeric = 0;
    let dropped = 0;
    let nonNumeric = 0;
    let seriesValueKind: ChartValueKind = "empty";
    let previousState: string | null = null;

    for (const point of seriesEntry.points) {
      const absoluteTime = Date.parse(point.timestamp);
      const time: number =
        seriesEntry.comparison_type === "periods" && point.elapsed_ms != null
          ? point.elapsed_ms
          : absoluteTime;
      if (!Number.isFinite(absoluteTime) || !Number.isFinite(time)) {
        continue;
      }
      originalTimestamps.push(point.timestamp);
      totalPoints += 1;
      if (options.ignoreBadQuality && !point.good) {
        points.push([time, null]);
        qualitySeries.push([time, classifyQuality(point)]);
        dropped += 1;
        totalDropped += 1;
        continue;
      }
      const pointValueKind = classifyValue(point.value);
      seriesValueKind = mergeValueKinds(seriesValueKind, pointValueKind);
      valueKind = mergeValueKinds(valueKind, pointValueKind);
      if (isNumericValue(point.value)) {
        points.push([time, point.value]);
        qualitySeries.push([time, classifyQuality(point)]);
        numeric += 1;
        totalNumeric += 1;
      } else {
        points.push([time, null]);
        qualitySeries.push([time, classifyQuality(point)]);
        if (typeof point.value === "string" || typeof point.value === "boolean") {
          nonNumeric += 1;
          totalNonNumeric += 1;
          const state = typeof point.value === "boolean" ? String(point.value) : point.value;
          let categoryIndex = categoryIndexes.get(state);
          if (categoryIndex === undefined) {
            categoryIndex = categories.length;
            categories.push(state);
            categoryIndexes.set(state, categoryIndex);
          }
          if (state !== previousState) {
            statePoints.push([time, categoryIndex]);
            stateValues.push(state);
            stateQualitySeries.push([time, classifyQuality(point)]);
            previousState = state;
          }
        }
      }
    }

    const seriesEndTime =
      seriesEntry.comparison_type === "periods"
        ? Date.parse(seriesEntry.original_end_time ?? timeSeries.end_time) -
          Date.parse(seriesEntry.original_start_time ?? timeSeries.start_time)
        : Date.parse(timeSeries.end_time);
    if (
      statePoints.length > 0 &&
      Number.isFinite(seriesEndTime) &&
      seriesEndTime > statePoints[statePoints.length - 1][0]
    ) {
      const lastPoint = statePoints[statePoints.length - 1];
      const lastState = stateValues[stateValues.length - 1];
      const lastQuality = stateQualitySeries[stateQualitySeries.length - 1][1];
      statePoints.push([seriesEndTime, lastPoint[1]]);
      stateValues.push(lastState);
      stateQualitySeries.push([seriesEndTime, lastQuality]);
    }

    series.push({
      tagId: seriesEntry.tag_id,
      displayName: seriesEntry.display_name,
      tagName: seriesEntry.tag_name,
      equipment: seriesEntry.equipment ?? null,
      section: seriesEntry.section ?? null,
      variableType: seriesEntry.variable_type ?? null,
      unit: seriesEntry.unit ?? null,
      yAxisIndex: yAxisIndex === 0 ? 0 : 1,
      color,
      contextId: seriesEntry.context_id ?? null,
      seriesInstanceId: seriesEntry.series_instance_id ?? null,
      comparisonType: seriesEntry.comparison_type ?? null,
      originalTimestamps,
      total: seriesEntry.points.length,
      numeric,
      dropped,
      nonNumeric,
      points,
      qualitySeries,
      valueKind: seriesValueKind,
      statePoints,
      stateValues,
      stateQualitySeries,
    });
  });

  return {
    series,
    units: units.map((entry) => entry.display),
    yAxisLabels: units.map((entry) =>
      entry.display === NO_UNIT_KEY ? "Sem unidade" : entry.display,
    ),
    totalSeries: series.length,
    totalPoints,
    totalNumericPoints: totalNumeric,
    totalDroppedPoints: totalDropped,
    totalNonNumericPoints: totalNonNumeric,
    valueKind,
    categories,
    comparisonType,
  };
}

export function buildChartDataGroups(
  timeSeries: TimeSeries,
  options: BuildChartOptions,
): ChartDataGroups {
  const summary = buildChartData(timeSeries, options);
  const numericSeries = timeSeries.series.filter(
    (_, index) => summary.series[index]?.valueKind === "numeric",
  );
  const textualSeries = timeSeries.series.filter(
    (_, index) => summary.series[index]?.valueKind === "textual",
  );

  return {
    summary,
    numeric:
      numericSeries.length > 0
        ? buildChartData({ ...timeSeries, series: numericSeries }, options)
        : null,
    textual: textualSeries.map((seriesEntry) =>
      buildChartData({ ...timeSeries, series: [seriesEntry] }, options),
    ),
    mixedSeries: summary.series.filter((seriesEntry) => seriesEntry.valueKind === "mixed"),
  };
}

export function resolveVisualization(
  groups: ChartDataGroups,
  visualization: VisualizationType,
): VisualizationPlan {
  const textualSeries = groups.textual.map((chart) => chart.series[0]).filter(Boolean);

  if (visualization === "singleValue") {
    return {
      numeric: null,
      textual: null,
      incompatibleSeries: [],
      excessTextualSeries: [],
    };
  }

  if (
    visualization === "line" ||
    visualization === "histogram" ||
    visualization === "boxplot" ||
    visualization === "scatter" ||
    visualization === "bars"
  ) {
    return {
      numeric: groups.numeric,
      textual: null,
      incompatibleSeries: textualSeries,
      excessTextualSeries: [],
    };
  }

  if (visualization === "states") {
    return {
      numeric: null,
      textual: groups.textual[0] ?? null,
      incompatibleSeries: groups.numeric?.series ?? [],
      excessTextualSeries: textualSeries.slice(1),
    };
  }

  return {
    numeric: groups.numeric,
    textual: groups.textual.length === 1 ? groups.textual[0] : null,
    incompatibleSeries: [],
    excessTextualSeries: groups.textual.length > 1 ? textualSeries : [],
  };
}

export function getOriginalSeries(series: TimeSeriesSeries | undefined): TimeSeriesSeries | null {
  return series ?? null;
}

export function applyLineAssignments(
  chart: ChartBuildResult | null,
  assignments: SeriesAssignment[],
): ChartBuildResult | null {
  if (!chart) return null;
  const assignmentById = new Map(assignments.map((assignment) => [assignmentIdentity(assignment), assignment]));
  const series = resolveSeriesOrder(chart.series, assignments, (entry) => entry.tagId, (entry) => entry.seriesInstanceId ?? undefined).map((entry) => ({
    ...entry,
    yAxisIndex: assignmentById.get(entry.seriesInstanceId ?? `tag:${entry.tagId}`)?.lineAxis === "secondary" ? 1 as const : 0 as const,
  }));
  const axisLabel = (index: 0 | 1): string => {
    const entry = series.find((candidate) => candidate.yAxisIndex === index);
    if (!entry) return index === 0 ? "Eixo Y principal" : "Eixo Y secundário";
    return entry.unit?.trim() || "Sem unidade";
  };
  const hasSecondary = series.some((entry) => entry.yAxisIndex === 1);
  return {
    ...chart,
    series,
    units: hasSecondary ? [axisLabel(0), axisLabel(1)] : [axisLabel(0)],
    yAxisLabels: hasSecondary ? [axisLabel(0), axisLabel(1)] : [axisLabel(0)],
  };
}
