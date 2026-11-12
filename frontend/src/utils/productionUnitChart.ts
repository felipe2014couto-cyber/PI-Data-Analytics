import type { ProductionUnitAnalysisResponse } from "../api";
import type { ChartBuildResult } from "./chartData";
import type {
  AnalysisMetric,
  MetricConfiguration,
  ProductionUnitAggregateInterval,
  ProductionUnitAggregation,
  ProductionUnitLegacyRule,
  ProductionUnitRule,
  TimeAnalysisRule,
  TimeSeries,
  TimeSeriesPoint,
} from "../types";
import { alignSeriesByTimestamp, numericObservations } from "./comparison";
import {
  calculateErrorMetricValue,
  individualValue,
  isErrorOrPairMetric,
  METRIC_BY_ID,
  unitFor,
} from "./analysisMetrics";

export function isLegacyProductionUnitRule(rule: TimeAnalysisRule): rule is ProductionUnitLegacyRule {
  return rule === "MEDIA" || rule === "MIN" || rule === "MAXIMO" || rule === "OOC";
}

export function isProductionUnitRule(rule: string): rule is ProductionUnitRule {
  return (
    rule === "MEDIA" ||
    rule === "MIN" ||
    rule === "MAXIMO" ||
    rule === "OOC" ||
    rule === "mean" ||
    rule === "maximum" ||
    rule === "minimum" ||
    rule === "count" ||
    rule === "total" ||
    rule === "standardDeviation" ||
    rule === "cp" ||
    rule === "cpk" ||
    rule === "pc" ||
    rule === "ooc" ||
    rule === "meanError" ||
    rule === "minimumError" ||
    rule === "maximumError" ||
    rule === "standardDeviationError" ||
    rule === "meanAbsoluteError" ||
    rule === "meanSquaredError" ||
    rule === "rootMeanSquaredError" ||
    rule === "cpkError" ||
    rule === "oocMaeMaximum" ||
    rule === "oocMaeMean"
  );
}

export function productionUnitRuleLabel(rule: ProductionUnitRule | string): string {
  switch (rule) {
    case "OOC":
      return "Atendido";
    case "MIN":
    case "minimum":
      return "Mínimo";
    case "MAXIMO":
    case "maximum":
      return "Máximo";
    case "MEDIA":
    case "mean":
      return "Média";
    case "count":
      return "Contagem";
    case "total":
      return "Total";
    case "standardDeviation":
      return "Desvio-padrão";
    case "cp":
      return "Cp";
    case "cpk":
      return "Cpk";
    case "pc":
      return "Percentual conforme";
    case "ooc":
      return "Fora de controle";
    case "meanError":
      return "Erro médio";
    case "minimumError":
      return "Erro mínimo";
    case "maximumError":
      return "Erro máximo";
    case "standardDeviationError":
      return "Desvio-padrão do erro";
    case "meanAbsoluteError":
      return "Erro absoluto médio";
    case "meanSquaredError":
      return "Erro quadrático médio";
    case "rootMeanSquaredError":
      return "Raiz do erro quadrático médio";
    case "cpkError":
      return "Cpk do erro";
    case "oocMaeMaximum":
      return "Erro absoluto máximo fora de controle";
    case "oocMaeMean":
      return "Erro absoluto médio fora de controle";
    default:
      return rule;
  }
}

/** Each engineering unit keeps its own scale in the unit analysis chart. */
export function assignProductionUnitAxes(chart: ChartBuildResult | null): ChartBuildResult | null {
  if (!chart) return null;
  const labels: string[] = [];
  const series = chart.series.map((entry) => {
    const label = entry.unit?.trim() || "Sem unidade";
    let index = labels.findIndex((candidate) => candidate.toLowerCase() === label.toLowerCase());
    if (index === -1) {
      index = labels.length;
      labels.push(label);
    }
    return { ...entry, yAxisIndex: index };
  });
  return { ...chart, series, units: labels, yAxisLabels: labels };
}

/** Resolve [start, end), including exact transitions and empty UMs. */
export function findProductionUnitSegment(
  segments: ProductionUnitAggregateInterval[],
  timestamp: number,
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

/** Adapt backend statistics or calculate per-UM metrics to visual vertices. */
export function buildProductionUnitTimeSeries(
  response: ProductionUnitAnalysisResponse,
  rule: TimeAnalysisRule,
  selectedTagIds: number[],
  window?: { start: Date; end: Date } | null,
  rawTimeSeries?: TimeSeries | null,
  metricConfiguration?: MetricConfiguration,
  ignoreBadQuality: boolean = false,
): TimeSeries {
  const normalizedRule: ProductionUnitRule =
    (rule as string) === "mean" ? "MEDIA" : (rule as string) === "maximum" ? "MAXIMO" : (rule as string) === "minimum" ? "MIN" : (rule as ProductionUnitRule);

  const start = window?.start.getTime() ?? Date.parse(response.start_time);
  const end = window?.end.getTime() ?? Date.parse(response.end_time);
  const segments = [...response.segments].sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time));
  const series: TimeSeries["series"] = [];

  const vertex = (timestamp: number, value: number | null): TimeSeriesPoint => ({
    timestamp: new Date(timestamp).toISOString(),
    value,
    good: true,
    questionable: false,
    substituted: false,
  });

  const buildVertices = (intervals: ProductionUnitAggregateInterval[]): TimeSeriesPoint[] => {
    const points: TimeSeriesPoint[] = [];
    let previousEnd: number | null = null;
    for (const interval of intervals) {
      const left = Math.max(start, interval.start);
      const right = Math.min(end, interval.end);
      if (left >= right) continue;
      if (previousEnd !== null && left > previousEnd) {
        points.push(vertex(previousEnd, null), vertex(left, null));
      }
      points.push(vertex(left, interval.value), vertex(right, interval.value));
      previousEnd = right;
    }
    return points;
  };

  if (isLegacyProductionUnitRule(normalizedRule)) {
    const field =
      normalizedRule === "OOC"
        ? "attended_percent"
        : normalizedRule === "MIN"
          ? "minimum"
          : normalizedRule === "MAXIMO"
            ? "maximum"
            : "average";

    for (const tagId of selectedTagIds) {
      if (tagId === response.um_tag_id) continue;
      const variable = segments.flatMap((segment) => segment.variables).find((item) => item.tag_id === tagId);
      if (!variable || variable.data_type !== "NUMERIC") continue;
      const intervals: ProductionUnitAggregateInterval[] = segments.map((segment) => {
        const item = segment.variables.find((candidate) => candidate.tag_id === tagId);
        const value = item?.data_type === "NUMERIC" ? item[field] : null;
        return {
          start: Date.parse(segment.start_time),
          end: Date.parse(segment.end_time),
          um: segment.um_value,
          value: typeof value === "number" && Number.isFinite(value) ? value : null,
          rawSampleCount: item?.raw_sample_count ?? 0,
          filteredSampleCount: item?.filtered_sample_count ?? 0,
          sampleCount: item?.sample_count ?? 0,
          ...(normalizedRule === "OOC"
            ? {
                eligibleSampleCount: item?.eligible_sample_count ?? 0,
                attendedSampleCount: item?.attended_sample_count ?? 0,
              }
            : {}),
        };
      });
      const points = buildVertices(intervals);
      series.push({
        tag_id: tagId,
        tag_name: variable.tag_name,
        display_name: variable.display_name,
        unit: normalizedRule === "OOC" ? "%" : variable.unit,
        equipment: null,
        section: null,
        variable_type: null,
        data_type: "REAL",
        step: true,
        points,
        unit_aggregation: { rule: normalizedRule, segments: intervals },
      });
    }
  } else if (isProductionUnitRule(normalizedRule)) {
    if (isErrorOrPairMetric(normalizedRule)) {
      // Dual-series error metrics
      const actualTagId =
        metricConfiguration && "actualTagId" in metricConfiguration ? metricConfiguration.actualTagId : null;
      const referenceTagId =
        metricConfiguration && "referenceTagId" in metricConfiguration ? metricConfiguration.referenceTagId : null;

      const actualSeries = rawTimeSeries?.series.find((s) => s.tag_id === actualTagId);
      const referenceSeries = rawTimeSeries?.series.find((s) => s.tag_id === referenceTagId);

      const actualVar = segments.flatMap((s) => s.variables).find((v) => v.tag_id === actualTagId);
      const refVar = segments.flatMap((s) => s.variables).find((v) => v.tag_id === referenceTagId);

      const actualDisplayName =
        actualSeries?.display_name ?? actualVar?.display_name ?? (actualTagId ? `Tag ${actualTagId}` : "Série real");
      const actualTagName = actualSeries?.tag_name ?? actualVar?.tag_name ?? String(actualTagId ?? "");
      const refDisplayName =
        referenceSeries?.display_name ??
        refVar?.display_name ??
        (referenceTagId ? `Tag ${referenceTagId}` : "Referência");
      const refTagName = referenceSeries?.tag_name ?? refVar?.tag_name ?? String(referenceTagId ?? "");
      const unit = unitFor(normalizedRule, actualSeries?.unit ?? actualVar?.unit ?? null);

      const intervals: ProductionUnitAggregateInterval[] = segments.map((segment) => {
        const segStart = Date.parse(segment.start_time);
        const segEnd = Date.parse(segment.end_time);

        if (!actualSeries || !referenceSeries || actualTagId === referenceTagId) {
          return {
            start: segStart,
            end: segEnd,
            um: segment.um_value,
            value: null,
            rawSampleCount: 0,
            filteredSampleCount: 0,
            sampleCount: 0,
          };
        }

        const actualPts = actualSeries.points.filter((p) => {
          if (p.filtered_out || (p as any).filtered_out) return false;
          const ts = Date.parse(p.timestamp);
          return ts >= segStart && ts < segEnd;
        });
        const refPts = referenceSeries.points.filter((p) => {
          if (p.filtered_out || (p as any).filtered_out) return false;
          const ts = Date.parse(p.timestamp);
          return ts >= segStart && ts < segEnd;
        });

        const pairs = alignSeriesByTimestamp(
          { ...actualSeries, points: actualPts },
          { ...referenceSeries, points: refPts },
          ignoreBadQuality,
        );

        const errors = pairs.map((pair) => pair.x.value - pair.y.value);
        let oocValues: number[] | undefined = undefined;
        let oocCount: number | undefined = undefined;

        if (normalizedRule === "oocMaeMaximum" || normalizedRule === "oocMaeMean") {
          const lower = (metricConfiguration as any)?.lowerControl;
          const upper = (metricConfiguration as any)?.upperControl;
          if (lower != null && upper != null && Number.isFinite(lower) && Number.isFinite(upper) && lower < upper) {
            const oocPairs = pairs.filter((pair) => pair.x.value < lower || pair.x.value > upper);
            oocValues = oocPairs.map((pair) => Math.abs(pair.x.value - pair.y.value));
            oocCount = oocPairs.length;
          }
        }

        const lowerSpec = (metricConfiguration as any)?.lowerSpecification;
        const upperSpec = (metricConfiguration as any)?.upperSpecification;

        const value = calculateErrorMetricValue(
          normalizedRule,
          errors,
          oocValues,
          lowerSpec,
          upperSpec,
        );

        return {
          start: segStart,
          end: segEnd,
          um: segment.um_value,
          value: typeof value === "number" && Number.isFinite(value) ? value : null,
          rawSampleCount: actualPts.length + refPts.length,
          filteredSampleCount: pairs.length * 2,
          sampleCount: pairs.length,
          ...(oocCount !== undefined ? { oocCount } : {}),
        };
      });

      const points = buildVertices(intervals);
      series.push({
        tag_id: actualTagId ?? -1,
        tag_name: `${actualTagName} - ${refTagName}`,
        display_name: `${productionUnitRuleLabel(normalizedRule)} (${actualDisplayName} - ${refDisplayName})`,
        unit,
        equipment: null,
        section: null,
        variable_type: null,
        data_type: "REAL",
        step: true,
        points,
        unit_aggregation: { rule: normalizedRule, segments: intervals },
      });
    } else {
      // Single-series metrics (count, total, standardDeviation, cp, cpk, pc, ooc)
      for (const tagId of selectedTagIds) {
        if (tagId === response.um_tag_id) continue;
        const variable = segments.flatMap((segment) => segment.variables).find((item) => item.tag_id === tagId);
        const rawSeries = rawTimeSeries?.series.find((s) => s.tag_id === tagId);
        if (!variable && !rawSeries) continue;
        if (variable && variable.data_type !== "NUMERIC") continue;

        const displayName = variable?.display_name ?? rawSeries?.display_name ?? `Tag ${tagId}`;
        const tagName = variable?.tag_name ?? rawSeries?.tag_name ?? String(tagId);
        const unit = unitFor(normalizedRule, variable?.unit ?? rawSeries?.unit ?? null);

        const intervals: ProductionUnitAggregateInterval[] = segments.map((segment) => {
          const segStart = Date.parse(segment.start_time);
          const segEnd = Date.parse(segment.end_time);
          const segVar = segment.variables.find((v) => v.tag_id === tagId);

          if (!rawSeries) {
            // Fallback for count if raw points were not provided
            if (normalizedRule === "count" && segVar && segVar.sample_count > 0) {
              return {
                start: segStart,
                end: segEnd,
                um: segment.um_value,
                value: segVar.sample_count,
                rawSampleCount: segVar.raw_sample_count,
                filteredSampleCount: segVar.filtered_sample_count,
                sampleCount: segVar.sample_count,
              };
            }
            return {
              start: segStart,
              end: segEnd,
              um: segment.um_value,
              value: null,
              rawSampleCount: segVar?.raw_sample_count ?? 0,
              filteredSampleCount: segVar?.filtered_sample_count ?? 0,
              sampleCount: segVar?.sample_count ?? 0,
            };
          }

          const pts = rawSeries.points.filter((p) => {
            if (p.filtered_out || (p as any).filtered_out) return false;
            const ts = Date.parse(p.timestamp);
            return ts >= segStart && ts < segEnd;
          });

          const observations = numericObservations({ ...rawSeries, points: pts }, ignoreBadQuality);
          const values = observations.map((o) => o.value);

          const lower =
            normalizedRule === "cp" || normalizedRule === "cpk" || normalizedRule === "pc"
              ? (metricConfiguration as any)?.lowerSpecification
              : (metricConfiguration as any)?.lowerControl;
          const upper =
            normalizedRule === "cp" || normalizedRule === "cpk" || normalizedRule === "pc"
              ? (metricConfiguration as any)?.upperSpecification
              : (metricConfiguration as any)?.upperControl;

          let value: number | null = null;
          const definition = METRIC_BY_ID.get(normalizedRule as AnalysisMetric);
          const minimum = definition?.minimumPoints ?? 1;

          if (values.length >= minimum) {
            if (definition?.requiresSpecificationLimits && (lower == null || upper == null || lower >= upper)) {
              value = null;
            } else if (definition?.requiresControlLimits && (lower == null || upper == null || lower >= upper)) {
              value = null;
            } else {
              value = individualValue(normalizedRule as AnalysisMetric, values, lower, upper);
            }
          }

          const oocCount = normalizedRule === "ooc" && typeof value === "number" ? value : undefined;

          return {
            start: segStart,
            end: segEnd,
            um: segment.um_value,
            value: typeof value === "number" && Number.isFinite(value) ? value : null,
            rawSampleCount: segVar?.raw_sample_count ?? pts.length,
            filteredSampleCount: segVar?.filtered_sample_count ?? pts.length,
            sampleCount: values.length,
            ...(oocCount !== undefined ? { oocCount } : {}),
          };
        });

        const points = buildVertices(intervals);
        series.push({
          tag_id: tagId,
          tag_name: tagName,
          display_name: displayName,
          unit,
          equipment: null,
          section: null,
          variable_type: null,
          data_type: "REAL",
          step: true,
          points,
          unit_aggregation: { rule: normalizedRule, segments: intervals },
        });
      }
    }
  }

  return {
    start_time: new Date(start).toISOString(),
    end_time: new Date(end).toISOString(),
    mode: "recorded",
    series,
    errors: [],
    query_execution: {
      source: "timescaledb",
      effective_source_mode: "RECORDED",
      strategy: response.strategy ?? "production_unit_aggregation",
      resolution_mode: "production_unit",
      sampled: false,
      partial: false,
      complete: true,
      production_unit_segment_count: segments.filter(
        (s) => Date.parse(s.start_time) < end && Date.parse(s.end_time) > start,
      ).length,
      visual_total_points: series.reduce((sum, s) => sum + s.points.length, 0),
    },
  };
}

export function formatProductionUnitValue(value: number | null): string {
  return value === null
    ? "(sem amostras válidas)"
    : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 10 }).format(value);
}

export function productionUnitTooltip(
  aggregation: ProductionUnitAggregation,
  timestamp: number,
  variable: string,
  unit: string | null,
): string {
  const segment = findProductionUnitSegment(aggregation.segments, timestamp);
  if (!segment) return "";
  const escape = (value: string) =>
    value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;").replace(/'/g, "&#39;");
  const date = (value: number) => new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  const label = productionUnitRuleLabel(aggregation.rule);
  if (aggregation.rule === "OOC") {
    return (
      `<div><strong>UM:</strong> ${escape(segment.um ?? "Sem UM atribuída")}</div>` +
      `<div>Início: ${date(segment.start)}</div><div>Fim: ${date(segment.end)} (exclusivo)</div>` +
      `<div>Variável: ${escape(variable)}</div><div>Atendido: ${formatOocValue(segment)}</div>`
    );
  }
  const value = formatProductionUnitValue(segment.value) + (segment.value !== null && unit ? ` ${unit}` : "");
  const isDual = isErrorOrPairMetric(aggregation.rule);
  return (
    `<div><strong>UM:</strong> ${escape(segment.um ?? "Sem UM atribuída")}</div>` +
    `<div>Início: ${date(segment.start)}</div><div>Fim: ${date(segment.end)} (exclusivo)</div>` +
    `<div>Variável: ${escape(variable)}</div><div>Regra: ${label}</div>` +
    `<div><strong>${label} da UM:</strong> ${escape(value)}</div>` +
    (isDual
      ? `<div>Pares avaliados: ${segment.sampleCount}</div>` +
        (segment.oocCount !== undefined ? `<div>Pares fora de controle: ${segment.oocCount}</div>` : "")
      : `<div>Amostras brutas: ${segment.rawSampleCount}</div>` +
        `<div>Após filtros: ${segment.filteredSampleCount}</div>` +
        `<div>Amostras válidas: ${segment.sampleCount}</div>` +
        (aggregation.rule === "ooc" && segment.oocCount !== undefined
          ? `<div>Fora de controle: ${segment.oocCount}</div>`
          : ""))
  );
}

export function formatOocValue(segment: ProductionUnitAggregateInterval | null): string {
  if (!segment || segment.value === null) return "sem amostras elegíveis";
  return `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 }).format(segment.value)}% (${segment.attendedSampleCount ?? 0}/${segment.eligibleSampleCount ?? 0} amostras)`;
}
