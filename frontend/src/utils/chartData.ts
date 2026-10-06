import type {
  ComparisonType,
  TimeSeries,
  TimeSeriesDataType,
  TimeSeriesPoint,
  TimeSeriesSeries,
  VisualizationType,
  SeriesAssignment,
  ProductionUnitAggregation,
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

export type ChartValueKind = "numeric" | "textual" | "categorical" | "mixed" | "empty";

export type ChartQuality = 0 | 1 | 2 | 3;

export interface ChartSeries {
  tagId: number;
  displayName: string;
  tagName: string;
  equipment: string | null;
  section: string | null;
  variableType: string | null;
  unit: string | null;
  dataType?: TimeSeriesDataType | null;
  step?: boolean | null;
  unitAggregation?: ProductionUnitAggregation;
  yAxisIndex: number;
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
  statePoints: Array<[number, number | null]>;
  stateValues: string[];
  stateQualitySeries: Array<[number, ChartQuality]>;
  isPlotSeries?: boolean;
}

export interface ChartBuildResult {
  series: ChartSeries[];
  units: string[];
  yAxisLabels: string[];
  totalSeries: number;
  totalPoints: number;
  totalNumericPoints: number;
  totalDroppedPoints: number;
  totalRenderSentinels: number;
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
  if (typeof value === "boolean") {
    return "categorical";
  }
  if (typeof value === "string") {
    return "categorical";
  }
  return "empty";
}

function mergeValueKinds(current: ChartValueKind, next: ChartValueKind): ChartValueKind {
  if (next === "empty") return current;
  if (current === "empty") return next;
  if (current === next) return current;
  return "mixed";
}

/**
 * Expand a Plot aggregate bucket into the significant RecordedValues vertices.
 *
 * PI's Plot presentation preserves the first/last event and both extrema in
 * their real temporal order.  The aggregate still travels as one API point;
 * only the chart receives the expanded vertices.
 */
export function plotVertices(
  point: TimeSeriesPoint,
  comparisonType: ComparisonType | null | undefined,
): Array<[number, number]> {
  if (point.is_gapfilled || !point.plot_sample_count) return [];

  const bucketTime = Date.parse(point.timestamp);
  if (!Number.isFinite(bucketTime)) return [];
  const candidates: Array<[string | null | undefined, number | null | undefined]> = [
    [point.plot_first_ts, point.plot_first],
    [point.plot_min_ts, point.plot_min],
    [point.plot_max_ts, point.plot_max],
    [point.plot_last_ts, point.plot_last],
  ];
  const vertices: Array<[number, number]> = [];
  const seen = new Set<string>();

  for (const [timestamp, value] of candidates) {
    if (!timestamp || !isNumericValue(value)) continue;
    const absoluteTime = Date.parse(timestamp);
    if (!Number.isFinite(absoluteTime)) continue;
    const displayTime = comparisonType === "periods" && point.elapsed_ms != null
      ? point.elapsed_ms + (absoluteTime - bucketTime)
      : absoluteTime;
    const key = `${displayTime}:${value}`;
    if (seen.has(key)) continue;
    seen.add(key);
    vertices.push([displayTime, value]);
  }

  return vertices.sort((left, right) => left[0] - right[0]);
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
  let totalRenderSentinels = 0;
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
    const statePoints: Array<[number, number | null]> = [];
    const stateValues: string[] = [];
    const stateIndexes = new Map<string, number>();
    const stateQualitySeries: Array<[number, ChartQuality]> = [];
    const originalTimestamps: string[] = [];
    let numeric = 0;
    let dropped = 0;
    let nonNumeric = 0;
    let seriesValueKind: ChartValueKind = seriesEntry.unit_aggregation ? "numeric" : "empty";
    let previousState: string | null = null;
    let isPlotSeries = false;

    for (const point of seriesEntry.points) {
      const absoluteTime = Date.parse(point.timestamp);
      const time: number =
        seriesEntry.comparison_type === "periods" && point.elapsed_ms != null
          ? point.elapsed_ms
          : absoluteTime;
      if (!Number.isFinite(absoluteTime) || !Number.isFinite(time)) {
        continue;
      }
      if (!point.is_boundary_seed) {
        originalTimestamps.push(point.timestamp);
        totalPoints += 1;
      }
      if (point.is_render_sentinel) {
        totalRenderSentinels += 1;
        points.push([time, null]);
        continue;
      }
      if (options.ignoreBadQuality && !point.good) {
        points.push([time, null]);
        qualitySeries.push([time, classifyQuality(point)]);
        if (seriesEntry.data_type === "STRING") {
          statePoints.push([time, null]);
          stateQualitySeries.push([time, classifyQuality(point)]);
          previousState = null;
        }
        dropped += 1;
        totalDropped += 1;
        continue;
      }
      const pointValueKind = classifyValue(point.value);
      seriesValueKind = mergeValueKinds(seriesValueKind, pointValueKind);
      valueKind = mergeValueKinds(valueKind, pointValueKind);
      if (pointValueKind === "empty" && point.filtered_out) {
        // Preserve gaps created by filters (and null PI samples). This keeps
        // the state chart from connecting values across rejected timestamps.
        points.push([time, null]);
        statePoints.push([time, null]);
        stateValues.push("");
        stateQualitySeries.push([time, classifyQuality(point)]);
        previousState = null;
        continue;
      }
      if (isNumericValue(point.value)) {
        const vertices = plotVertices(point, seriesEntry.comparison_type);
        if (vertices.length > 0) {
          isPlotSeries = true;
          points.push(...vertices);
          qualitySeries.push(...vertices.map(([vertexTime]) => [vertexTime, classifyQuality(point)] as [number, ChartQuality]));
        } else {
          points.push([time, point.value]);
          qualitySeries.push([time, classifyQuality(point)]);
        }
        if (!point.is_boundary_seed) {
          numeric += 1;
          totalNumeric += 1;
        }
      } else {
        points.push([time, null]);
        qualitySeries.push([time, classifyQuality(point)]);
        if (point.value == null && seriesEntry.data_type === "STRING") {
          statePoints.push([time, null]);
          stateQualitySeries.push([time, classifyQuality(point)]);
          previousState = null;
          continue;
        }
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
            let stateIndex = stateIndexes.get(state);
            if (stateIndex === undefined) {
              stateIndex = stateValues.length;
              stateIndexes.set(state, stateIndex);
              stateValues.push(state);
            }
            statePoints.push([time, stateIndex]);
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
      statePoints[statePoints.length - 1][1] !== null &&
      Number.isFinite(seriesEndTime) &&
      seriesEndTime > statePoints[statePoints.length - 1][0]
    ) {
      const lastPoint = statePoints[statePoints.length - 1];
      const lastQuality = stateQualitySeries[stateQualitySeries.length - 1][1];
      statePoints.push([seriesEndTime, lastPoint[1]]);
      stateQualitySeries.push([seriesEndTime, lastQuality]);
    }

    // Plot buckets expand to their real event timestamps. Coverage sentinels
    // can fall inside a bucket range, so sort the flattened render vertices
    // before handing them to ECharts. Nulls still break the line (connectNulls
    // remains false); this only preserves their temporal order.
    points.sort((left, right) => left[0] - right[0]);
    qualitySeries.sort((left, right) => left[0] - right[0]);

    series.push({
      tagId: seriesEntry.tag_id,
      displayName: seriesEntry.display_name,
      tagName: seriesEntry.tag_name,
      equipment: seriesEntry.equipment ?? null,
      section: seriesEntry.section ?? null,
      variableType: seriesEntry.variable_type ?? null,
      unit: seriesEntry.unit ?? null,
      dataType: seriesEntry.data_type ?? null,
      step: seriesEntry.step ?? null,
      unitAggregation: seriesEntry.unit_aggregation,
      yAxisIndex: yAxisIndex === 0 ? 0 : 1,
      color,
      contextId: seriesEntry.context_id ?? null,
      seriesInstanceId: seriesEntry.series_instance_id ?? null,
      comparisonType: seriesEntry.comparison_type ?? null,
      originalTimestamps,
      total: seriesEntry.points.filter((point) => !point.is_boundary_seed).length,
      numeric,
      dropped,
      nonNumeric,
      points,
      qualitySeries,
      valueKind: seriesValueKind,
      statePoints,
      stateValues,
      stateQualitySeries,
      isPlotSeries,
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
    totalRenderSentinels,
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
  const hasStringSeries = summary.series.some((series) => series.dataType === "STRING");
  const textualSeries = timeSeries.series.filter((_, index) => {
    const chartSeries = summary.series[index];
    if (!chartSeries) return false;
    if (chartSeries.valueKind !== "textual" && chartSeries.valueKind !== "categorical") return false;
    // STRING-typed series are rendered as categorical bands alongside numeric
    // axes instead of being segregated into a standalone state chart.
    if (chartSeries.dataType === "STRING") return false;
    if (hasStringSeries && chartSeries.dataType === "DIGITAL") return false;
    return true;
  });

  // Numeric group now also includes STRING series so they share the same X
  // axis and zoom state with REAL/DIGITAL measurements.
  const numericGroupSeries = timeSeries.series.filter((_, index) => {
    const chartSeries = summary.series[index];
    if (!chartSeries) return false;
    if (chartSeries.valueKind === "numeric") return true;
    if (chartSeries.dataType === "STRING" && (chartSeries.valueKind === "categorical" || chartSeries.valueKind === "textual")) return true;
    if (hasStringSeries && chartSeries.dataType === "DIGITAL" && (chartSeries.valueKind === "categorical" || chartSeries.valueKind === "textual")) return true;
    return false;
  });

  return {
    summary,
    numeric:
      numericGroupSeries.length > 0
        ? buildChartData({ ...timeSeries, series: numericGroupSeries }, options)
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
    // STRING-typed series travel inside groups.numeric so they can share the
    // time axis with REAL/DIGITAL measurements. Only non-STRING textual series
    // remain incompatible with statistical charts.
    return {
      numeric: groups.numeric,
      textual: null,
      incompatibleSeries: textualSeries.filter((series) => series.dataType !== "STRING"),
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
