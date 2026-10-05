import type { ProductionUnitAnalysisResponse } from "../api";
import type { ChartBuildResult } from "./chartData";
import type { ProductionUnitAggregateInterval, ProductionUnitAggregation, ProductionUnitRule, TimeAnalysisRule, TimeSeries, TimeSeriesPoint } from "../types";

export function isProductionUnitRule(rule: TimeAnalysisRule): rule is ProductionUnitRule {
  return rule === "MEDIA" || rule === "MIN" || rule === "MAXIMO" || rule === "OOC";
}

export function productionUnitRuleLabel(rule: ProductionUnitRule): string {
  return rule === "OOC" ? "Atendido" : rule === "MIN" ? "Mínimo" : rule === "MAXIMO" ? "Máximo" : "Média";
}

/** Each engineering unit keeps its own scale in the unit analysis chart. */
export function assignProductionUnitAxes(chart: ChartBuildResult | null): ChartBuildResult | null {
  if (!chart) return null;
  const labels: string[] = [];
  const series = chart.series.map((entry) => {
    const label = entry.unit?.trim() || "Sem unidade";
    let index = labels.findIndex((candidate) => candidate.toLowerCase() === label.toLowerCase());
    if (index === -1) { index = labels.length; labels.push(label); }
    return { ...entry, yAxisIndex: index };
  });
  return { ...chart, series, units: labels, yAxisLabels: labels };
}

/** Resolve [start, end), including exact transitions and empty UMs. */
export function findProductionUnitSegment(
  segments: ProductionUnitAggregateInterval[], timestamp: number,
): ProductionUnitAggregateInterval | null {
  let low = 0;
  let high = segments.length - 1;
  let previous = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start <= timestamp) {
      previous = mid;
      low = mid + 1;
    } else high = mid - 1;
  }
  const segment = segments[previous];
  return segment && timestamp < segment.end ? segment : null;
}

/** Adapt backend statistics to visual vertices; never recalculate or filter samples. */
export function buildProductionUnitTimeSeries(
  response: ProductionUnitAnalysisResponse,
  rule: TimeAnalysisRule,
  selectedTagIds: number[],
  window?: { start: Date; end: Date } | null,
): TimeSeries {
  const start = window?.start.getTime() ?? Date.parse(response.start_time);
  const end = window?.end.getTime() ?? Date.parse(response.end_time);
  const segments = [...response.segments].sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time));
  const field = rule === "OOC" ? "attended_percent" : rule === "MIN" ? "minimum" : rule === "MAXIMO" ? "maximum" : "average";
  const series: TimeSeries["series"] = [];
  if (isProductionUnitRule(rule)) {
    for (const tagId of selectedTagIds) {
      if (tagId === response.um_tag_id) continue;
      const variable = segments.flatMap((segment) => segment.variables).find((item) => item.tag_id === tagId);
      if (!variable || variable.data_type !== "NUMERIC") continue;
      const intervals: ProductionUnitAggregateInterval[] = segments.map((segment) => {
        const item = segment.variables.find((candidate) => candidate.tag_id === tagId);
        const value = item?.data_type === "NUMERIC" ? item[field] : null;
        return {
          start: Date.parse(segment.start_time), end: Date.parse(segment.end_time), um: segment.um_value,
          value: typeof value === "number" && Number.isFinite(value) ? value : null,
          rawSampleCount: item?.raw_sample_count ?? 0,
          filteredSampleCount: item?.filtered_sample_count ?? 0,
          sampleCount: item?.sample_count ?? 0,
          ...(rule === "OOC" ? { eligibleSampleCount: item?.eligible_sample_count ?? 0, attendedSampleCount: item?.attended_sample_count ?? 0 } : {}),
        };
      });
      const points: TimeSeriesPoint[] = [];
      let previousEnd: number | null = null;
      const vertex = (timestamp: number, value: number | null): TimeSeriesPoint => ({
        timestamp: new Date(timestamp).toISOString(), value,
        good: true, questionable: false, substituted: false,
      });
      for (const interval of intervals) {
        const left = Math.max(start, interval.start);
        const right = Math.min(end, interval.end);
        if (left >= right) continue;
        if (previousEnd !== null && left > previousEnd) {
          points.push(vertex(previousEnd, null), vertex(left, null));
        }
        // The right vertex is a visual boundary, never a new PI measurement.
        points.push(vertex(left, interval.value), vertex(right, interval.value));
        previousEnd = right;
      }
      series.push({
        tag_id: tagId, tag_name: variable.tag_name, display_name: variable.display_name,
        unit: rule === "OOC" ? "%" : variable.unit, equipment: null, section: null, variable_type: null,
        data_type: "REAL", step: true, points,
        unit_aggregation: { rule, segments: intervals },
      });
    }
  }
  return {
    start_time: new Date(start).toISOString(), end_time: new Date(end).toISOString(),
    mode: "recorded", series, errors: [],
    query_execution: {
      source: "timescaledb", effective_source_mode: "RECORDED",
      strategy: response.strategy ?? "production_unit_aggregation", resolution_mode: "production_unit",
      sampled: false, partial: false, complete: true,
      production_unit_segment_count: segments.filter((s) => Date.parse(s.start_time) < end && Date.parse(s.end_time) > start).length,
      visual_total_points: series.reduce((sum, s) => sum + s.points.length, 0),
    },
  };
}

export function formatProductionUnitValue(value: number | null): string {
  return value === null ? "(sem amostras válidas)" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 10 }).format(value);
}

export function productionUnitTooltip(
  aggregation: ProductionUnitAggregation, timestamp: number, variable: string, unit: string | null,
): string {
  const segment = findProductionUnitSegment(aggregation.segments, timestamp);
  if (!segment) return "";
  const escape = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
  const date = (value: number) => new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  const label = productionUnitRuleLabel(aggregation.rule);
  if (aggregation.rule === "OOC") {
    return `<div><strong>UM:</strong> ${escape(segment.um ?? "Sem UM atribuída")}</div>` +
      `<div>Início: ${date(segment.start)}</div><div>Fim: ${date(segment.end)} (exclusivo)</div>` +
      `<div>Variável: ${escape(variable)}</div><div>Atendido: ${formatOocValue(segment)}</div>`;
  }
  const value = formatProductionUnitValue(segment.value) + (segment.value !== null && unit ? ` ${unit}` : "");
  return `<div><strong>UM:</strong> ${escape(segment.um ?? "Sem UM atribuída")}</div>` +
    `<div>Início: ${date(segment.start)}</div><div>Fim: ${date(segment.end)} (exclusivo)</div>` +
    `<div>Variável: ${escape(variable)}</div><div>Regra: ${label}</div>` +
    `<div><strong>${label} da UM:</strong> ${escape(value)}</div>` +
    `<div>Amostras brutas: ${segment.rawSampleCount}</div>` +
    `<div>Após filtros: ${segment.filteredSampleCount}</div>` +
    `<div>Amostras válidas: ${segment.sampleCount}</div>`;
}


export function formatOocValue(segment: ProductionUnitAggregateInterval | null): string {
  if (!segment || segment.value === null) return "sem amostras elegíveis";
  return `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 }).format(segment.value)}% (${segment.attendedSampleCount ?? 0}/${segment.eligibleSampleCount ?? 0} amostras)`;
}
