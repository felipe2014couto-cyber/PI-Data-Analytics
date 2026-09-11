import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption, ECharts } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { ChartBuildResult, ChartSeries } from "../utils/chartData";
import type { NormLimitSeries } from "../utils/normLimitSeries";
import type { UmChartSeries } from "../utils/umChartSeries";
import type { SeriesVisualConfiguration, VisualRulesState } from "../types";
import { formatNumericValue } from "../utils/values";

const SAMPLE_THRESHOLD = 1200;

function formatElapsed(value: number): string {
  const totalSeconds = Math.max(0, Math.round(value / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

interface TooltipSeries {
  seriesId: string;
  displayName: string;
  tagName: string;
  unit: string | null;
  /** Series principal numérica (processa value) */
  value: (point: TimeSeriesPoint) => string;
  /** Para pontos textuais (UM) */
  categoricalCode?: (point: TimeSeriesPoint, umCategories?: string[]) => string;
}

interface TimeSeriesPoint {
  timestamp: string;
  value: unknown;
  good?: boolean;
  questionable?: boolean;
  substituted?: boolean;
}

interface TooltipSeriesState {
  main: TooltipSeries[];
  limits: TooltipSeries[];
  um: TooltipSeries | null;
  umCategories: string[];
}

export interface TimeSeriesChartProps {
  chart: ChartBuildResult;
  equipment: string | null;
  start: Date;
  end: Date;
  mode: "recorded" | "interpolated";
  loading?: boolean;
  titleLabel?: string;
  visualRules?: VisualRulesState;
  limitSeries?: ChartSeries[];
  normLimitSeries?: NormLimitSeries[];
  umSeries?: UmChartSeries | null;
  pinnedCursorTs?: number | null;
  onClearCursor?: () => void;
  onPinnedCursorChange?: (ts: number | null) => void;
}

const QUALITY_LABELS: Record<number, string> = {
  1: "Substituido",
  2: "Questionavel",
  3: "Ruim",
};

function qualityText(quality: number | null | undefined): string {
  if (quality === undefined || quality === null || quality === 0) return "";
  return QUALITY_LABELS[Number(quality)] ?? "Ruim";
}

function escapeHtml(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const SAO_PAULO_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const SAO_PAULO_TIME_FORMATTER = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function formatDateTimeSaoPaulo(dateOrMs: number | Date): string {
  try {
    const date = typeof dateOrMs === "number" ? new Date(dateOrMs) : dateOrMs;
    if (Number.isNaN(date.getTime())) return "";
    const parts = SAO_PAULO_DATE_TIME_FORMATTER.formatToParts(date);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}:${get("second")}`;
  } catch {
    return "";
  }
}

function formatTimeSaoPaulo(dateOrMs: number | Date): string {
  try {
    const date = typeof dateOrMs === "number" ? new Date(dateOrMs) : dateOrMs;
    if (Number.isNaN(date.getTime())) return "";
    const parts = SAO_PAULO_TIME_FORMATTER.formatToParts(date);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("hour")}:${get("minute")}:${get("second")}`;
  } catch {
    return "";
  }
}

function findActiveUmStep(
  steps: Array<[number, number, string]>,
  timestampMs: number,
): [number, number, string] | null {
  if (steps.length === 0) return null;
  if (timestampMs < steps[0][0]) return null;
  let low = 0;
  let high = steps.length - 1;
  let result: [number, number, string] | null = null;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (steps[mid][0] <= timestampMs) {
      result = steps[mid];
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return result;
}

function buildTooltip(
  chart: ChartBuildResult,
  state: TooltipSeriesState,
  _startLocal: string,
  _endLocal: string,
  _mode: "recorded" | "interpolated",
  umSeries?: UmChartSeries | null,
) {
  const qualityBySeries = new Map<string, Map<number, number>>();
  for (const s of chart.series) {
    const id = s.seriesInstanceId ?? `tag:${s.tagId}`;
    const qMap = new Map<number, number>();
    if (Array.isArray(s.qualitySeries)) {
      for (const item of s.qualitySeries) {
        if (Array.isArray(item)) {
          qMap.set(item[0], item[1]);
        }
      }
    }
    qualityBySeries.set(id, qMap);
  }
  if (umSeries) {
    const id = `um:${umSeries.seriesInstanceId}`;
    const qMap = new Map<number, number>();
    if (Array.isArray(umSeries.qualitySeries)) {
      for (const item of umSeries.qualitySeries) {
        if (Array.isArray(item)) {
          qMap.set(item[0], item[1]);
        }
      }
    }
    qualityBySeries.set(id, qMap);
  }

  const bySeriesId = new Map<string, TooltipSeries>();
  for (const s of state.main) bySeriesId.set(s.seriesId, s);
  for (const s of state.limits) bySeriesId.set(s.seriesId, s);
  if (state.um) bySeriesId.set(state.um.seriesId, state.um);

  return (params: unknown) => {
    try {
      if (!Array.isArray(params) || params.length === 0) {
        return "";
      }
      const first = params[0] as {
        axisValue?: number | string;
        axisValueLabel?: string;
        value?: [number, unknown] | number;
      };

      let hoveredTs: number | null = null;
      if (typeof first.axisValue === "number" && Number.isFinite(first.axisValue)) {
        hoveredTs = first.axisValue;
      } else if (
        Array.isArray(first.value) &&
        typeof first.value[0] === "number" &&
        Number.isFinite(first.value[0])
      ) {
        hoveredTs = first.value[0];
      }

      const lines: string[] = [];
      if (chart.comparisonType === "periods" && hoveredTs !== null) {
        lines.push(
          `<div style="font-weight:600;margin-bottom:4px">Decorrido ${escapeHtml(formatElapsed(hoveredTs))}</div>`,
        );
      } else if (hoveredTs !== null) {
        const formattedDate = formatDateTimeSaoPaulo(hoveredTs);
        lines.push(
          `<div style="font-weight:600;margin-bottom:4px">Data e hora: ${escapeHtml(formattedDate || first.axisValueLabel || "")}</div>`,
        );
      } else {
        lines.push(
          `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(first.axisValueLabel ?? "")}</div>`,
        );
      }

      const seen = new Set<string>();
      for (const entry of params as Array<{
        seriesId?: string;
        seriesName: string;
        value?: [number, unknown] | number;
        dataIndex?: number;
        marker?: string;
      }>) {
        const seriesId = entry.seriesId ?? "";
        if (!seriesId || seen.has(seriesId)) continue;
        seen.add(seriesId);

        let series = bySeriesId.get(seriesId);
        if (!series) {
          series = Array.from(bySeriesId.values()).find((s) => s.displayName === entry.seriesName);
        }
        if (!series) continue;

        if (series.categoricalCode && umSeries) {
          let umText = "(sem dado)";
          let umQuality: number | null = null;
          if (hoveredTs !== null && Number.isFinite(hoveredTs)) {
            const activeStep = findActiveUmStep(umSeries.steps, hoveredTs);
            if (activeStep) {
              umText = activeStep[2] || "(sem dado)";
              umQuality = qualityBySeries.get(seriesId)?.get(activeStep[0]) ?? null;
            }
          } else if (Array.isArray(entry.value)) {
            const v = entry.value[1];
            if (typeof v === "number" && v >= 0 && v < state.umCategories.length) {
              umText = state.umCategories[v];
            } else if (v !== null && v !== undefined) {
              umText = String(v);
            }
          }
          const qText = qualityText(umQuality);
          const qualitySuffix = qText ? ` - ${escapeHtml(qText)}` : "";
          const marker = entry.marker ?? "";
          lines.push(
            `<div>${marker} <strong>${escapeHtml(series.displayName)}</strong>: ${escapeHtml(umText)}${qualitySuffix}</div>`,
          );
          continue;
        }

        let sampleTs: number | null = null;
        let rawVal: unknown = null;
        if (Array.isArray(entry.value)) {
          sampleTs = typeof entry.value[0] === "number" ? entry.value[0] : null;
          rawVal = entry.value[1];
        } else if (typeof entry.value === "number") {
          rawVal = entry.value;
        }

        let quality: number | null = null;
        if (sampleTs !== null) {
          const q = qualityBySeries.get(seriesId)?.get(sampleTs);
          if (typeof q === "number") quality = q;
        }

        let valueText = "(sem dado)";
        if (rawVal !== null && rawVal !== undefined && rawVal !== "") {
          if (typeof rawVal === "number") {
            valueText = Number.isFinite(rawVal) ? formatNumericValue(rawVal) : "(sem dado)";
          } else {
            valueText = formatNumericValue(String(rawVal));
          }
        }

        const unitSuffix = series.unit && valueText !== "(sem dado)" ? ` ${escapeHtml(series.unit)}` : "";
        const qText = qualityText(quality);
        const qualitySuffix = qText ? ` - ${escapeHtml(qText)}` : "";

        let sampleNotice = "";
        if (
          sampleTs !== null &&
          hoveredTs !== null &&
          Math.abs(sampleTs - hoveredTs) >= 1000 &&
          !seriesId.startsWith("norm-") &&
          !seriesId.startsWith("limit")
        ) {
          const sampleTimeStr = formatTimeSaoPaulo(sampleTs);
          if (sampleTimeStr) {
            sampleNotice = ` <span style="color:#888;font-size:0.85em">(amostra: ${escapeHtml(sampleTimeStr)})</span>`;
          }
        }

        const marker = entry.marker ?? "";
        lines.push(
          `<div>${marker} <strong>${escapeHtml(series.displayName)}</strong>: ${escapeHtml(valueText)}${unitSuffix}${sampleNotice}${qualitySuffix}</div>`,
        );
      }

      return lines.join("");
    } catch (err) {
      console.error("Erro no formatador do tooltip:", err);
      return "";
    }
  };
}

function buildStateTooltip(chart: ChartBuildResult) {
  return (params: unknown) => {
    if (!Array.isArray(params) || params.length === 0) {
      return "";
    }
    const entry = params[0] as {
      axisValueLabel?: string;
      dataIndex: number;
      marker: string;
      seriesIndex: number;
      seriesName: string;
    };
    const series = chart.series[entry.seriesIndex];
    if (!series) return "";
    const state = series.stateValues[entry.dataIndex] ?? "-";
    const quality = series.stateQualitySeries[entry.dataIndex]?.[1];
    return [
      `<div style="font-weight:600">${entry.axisValueLabel ?? ""}</div>`,
      `<div>${entry.marker} <strong>${entry.seriesName}</strong> (${series.tagName}): ${state}` +
        (quality !== undefined ? ` - ${QUALITY_LABELS[quality] ?? "Ruim"}` : "") +
        `</div>`,
    ].join("");
  };
}

function buildStateOption(props: TimeSeriesChartProps): EChartsOption {
  const { chart, equipment, start, end, mode, pinnedCursorTs, onClearCursor } = props;
  const series = chart.series[0];
  const markLine =
    pinnedCursorTs !== null && pinnedCursorTs !== undefined && Number.isFinite(pinnedCursorTs)
      ? {
          silent: true,
          symbol: ["none", "none"],
          data: [
            {
              name: "Cursor",
              xAxis: pinnedCursorTs,
              lineStyle: { color: "#0d3b66", width: 2, type: "dashed" as const },
              label: {
                show: true,
                formatter: () => formatTimeSaoPaulo(pinnedCursorTs),
                position: "insideEndTop" as const,
                backgroundColor: "#0d3b66",
                color: "#ffffff",
                borderRadius: 3,
                padding: [2, 6],
                fontSize: 11,
                fontWeight: "bold" as const,
              },
              emphasis: { disabled: true },
            },
          ],
        }
      : undefined;

  return {
    title: {
      text: `${equipment ?? "Equipamento"} | Estados ${mode === "recorded" ? "registrados" : "interpolados"}`,
      subtext: `${start.toLocaleString("pt-BR")} ate ${end.toLocaleString("pt-BR")}`,
      left: "center",
    },
    tooltip: {
      trigger: "axis",
      alwaysShowContent: Boolean(pinnedCursorTs),
      axisPointer: { type: "cross", label: { backgroundColor: "#0d3b66" } },
      formatter: buildStateTooltip(chart),
    },
    legend: {
      type: "scroll",
      bottom: 64,
      data: series ? [series.displayName] : [],
    },
    grid: { left: 100, right: 24, top: 70, bottom: 96 },
    xAxis: {
      type: "time",
      name: chart.comparisonType === "periods" ? "Tempo decorrido" : undefined,
      axisLabel: {
        color: "#1f2d3d",
        formatter: chart.comparisonType === "periods" ? (value: number) => formatElapsed(value) : undefined,
      },
    },
    yAxis: {
      type: "category",
      data: chart.categories,
      axisLabel: { color: "#1f2d3d" },
    },
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { yAxisIndex: "none", title: { zoom: "Zoom", back: "Restaurar" } },
        restore: { title: "Restaurar" },
        saveAsImage: { name: "pi-analytics-data-grafico-estados", title: "Salvar imagem" },
        ...(pinnedCursorTs !== null && pinnedCursorTs !== undefined && onClearCursor
          ? {
              myClearCursor: {
                show: true,
                title: "Limpar cursor (duplo clique)",
                icon: "path://M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
                onclick: onClearCursor,
              },
            }
          : {}),
      },
    },
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: 0,
        moveOnMouseMove: false,
        moveOnMouseWheel: false,
        zoomOnMouseWheel: true,
      },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 24 },
    ],
    animation: false,
    series: series
      ? [
          {
            id: series.seriesInstanceId ?? `tag:${series.tagId}`,
            name: series.displayName,
            type: "line",
            step: "end",
            showSymbol: series.statePoints.length <= SAMPLE_THRESHOLD,
            symbol: "circle",
            symbolSize: 6,
            connectNulls: false,
            lineStyle: { color: series.color, width: 2 },
            itemStyle: { color: series.color },
            emphasis: { focus: "series" },
            data: series.statePoints,
            markLine,
          },
        ]
      : [],
  };
}

function normLimitDisplayName(entry: NormLimitSeries, kind: "lower" | "upper"): string {
  const base = entry.mainDisplayName?.trim() || entry.tagName?.trim() || "Principal";
  return kind === "lower" ? `Limite inferior — ${base}` : `Limite superior — ${base}`;
}

export function buildTimeSeriesChartOption(props: TimeSeriesChartProps): EChartsOption {
  const { chart, equipment, start, end, mode } = props;
  if (chart.valueKind === "textual" || chart.valueKind === "categorical") {
    return buildStateOption(props);
  }
  const titleText = `${equipment ?? "Equipamento"} | ${props.titleLabel ?? (mode === "recorded" ? "Histórico 10s — base cíclica" : "Valores interpolados")}`;
  const subtitle = `${start.toLocaleString("pt-BR")} ate ${end.toLocaleString("pt-BR")}`;

  const umSeries = props.umSeries;
  const hasUm = !!umSeries && umSeries.steps.length > 0;
  const hasNumericAxes = chart.yAxisLabels.length > 0;

  let yAxis: Array<Record<string, unknown>>;
  let umYAxisIndex = -1;

  if (hasNumericAxes) {
    yAxis = chart.yAxisLabels.map((label, index) => ({
      type: "value" as const,
      name: label,
      nameTextStyle: { padding: [0, 0, 0, 24] },
      position: (index === 0 ? "left" : "right") as "left" | "right",
      alignTicks: true,
      scale: true,
      axisPointer: { show: false },
    }));
    if (hasUm && umSeries) {
      yAxis.push({
        type: "category" as const,
        data: umSeries.categories,
        show: false,
        name: "",
        axisLabel: { show: false },
        axisTick: { show: false },
        axisLine: { show: false },
        splitLine: { show: false },
        splitArea: { show: false },
        axisPointer: { show: false },
      });
      umYAxisIndex = yAxis.length - 1;
    }
  } else {
    // Caso sem séries numéricas: cria eixo categórico oculto para renderização da UM sem escala lateral
    if (hasUm && umSeries) {
      yAxis = [
        {
          type: "category" as const,
          data: umSeries.categories,
          show: false,
          name: "",
          axisLabel: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
          splitLine: { show: false },
          splitArea: { show: false },
          axisPointer: { show: false },
        },
      ];
      umYAxisIndex = 0;
    } else {
      yAxis = [{ type: "value" as const, show: false, axisPointer: { show: false } }];
    }
  }

  const tooltipState = buildTooltipState(chart, props);
  const baseShowSymbol = chart.series.every((series) => series.points.length <= SAMPLE_THRESHOLD);
  const seriesOption = chart.series.map((series, idx) =>
    buildSeriesOption(
      series,
      baseShowSymbol,
      props.visualRules,
      props.pinnedCursorTs,
      idx === 0,
    ),
  ) as EChartsOption["series"];
  const limitSeriesOption = (props.limitSeries ?? []).map((series) => buildLimitSeriesOption(series)) as EChartsOption["series"];
  const normLimitSeriesOption = (props.normLimitSeries ?? []).flatMap((entry, idx) => {
    const targetMainSeries = chart.series.find(
      (s) => (s.seriesInstanceId ?? `tag:${s.tagId}`) === entry.seriesInstanceId,
    );
    const effectiveYAxisIndex = targetMainSeries?.yAxisIndex ?? entry.yAxisIndex ?? 0;
    const seriesList: Array<Record<string, unknown>> = [];
    if (entry.lowerPoints.length > 0) {
      seriesList.push(buildNormLimitSeriesOption(entry, "lower", idx, effectiveYAxisIndex));
    }
    if (entry.upperPoints.length > 0) {
      seriesList.push(buildNormLimitSeriesOption(entry, "upper", idx, effectiveYAxisIndex));
    }
    return seriesList;
  }) as unknown as EChartsOption["series"];
  const umSeriesOption = umSeries
    ? [buildUmSeriesOption(umSeries, umYAxisIndex, chart.series.length === 0 ? props.pinnedCursorTs : null)]
    : [];

  const normLimitLegend: string[] = [];
  for (const entry of props.normLimitSeries ?? []) {
    if (entry.lowerPoints.length > 0) {
      normLimitLegend.push(normLimitDisplayName(entry, "lower"));
    }
    if (entry.upperPoints.length > 0) {
      normLimitLegend.push(normLimitDisplayName(entry, "upper"));
    }
  }

  const legendData: string[] = [
    ...chart.series.map((s) => s.displayName),
    ...(props.limitSeries ?? []).map((s) => s.displayName),
    ...normLimitLegend,
  ];
  if (umSeries) legendData.push(umSeries.displayName);

  return {
    title: { text: titleText, subtext: subtitle, left: "center" },
    tooltip: {
      trigger: "axis",
      alwaysShowContent: Boolean(props.pinnedCursorTs),
      axisPointer: {
        type: "line",
        lineStyle: { color: "#888", type: "dashed" },
        snap: true,
      },
      confine: true,
      extraCssText: "pointer-events: none;",
      formatter: buildTooltip(
        chart,
        tooltipState,
        start.toLocaleString("pt-BR"),
        end.toLocaleString("pt-BR"),
        mode,
        umSeries,
      ),
    },
    legend: { type: "scroll", bottom: 64, data: legendData },
    grid: {
      left: chart.yAxisLabels.length > 1 ? 60 : 45,
      right: chart.yAxisLabels.length > 1 ? 60 : 24,
      top: 70,
      bottom: 96,
    },
    xAxis: {
      type: "time",
      axisLabel: { color: "#1f2d3d" },
    },
    yAxis: yAxis as EChartsOption["yAxis"],
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { yAxisIndex: "none", title: { zoom: "Zoom", back: "Restaurar" } },
        restore: { title: "Restaurar" },
        saveAsImage: { name: "pi-analytics-data-grafico-linha", title: "Salvar imagem" },
        ...(props.pinnedCursorTs !== null && props.pinnedCursorTs !== undefined && props.onClearCursor
          ? {
              myClearCursor: {
                show: true,
                title: "Limpar cursor (duplo clique)",
                icon: "path://M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
                onclick: props.onClearCursor,
              },
            }
          : {}),
      },
    },
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: 0,
        moveOnMouseMove: false,
        moveOnMouseWheel: false,
        zoomOnMouseWheel: true,
      },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 24 },
    ],
    animation: false,
    series: [
      ...((seriesOption ?? []) as unknown[]),
      ...((limitSeriesOption ?? []) as unknown[]),
      ...((normLimitSeriesOption ?? []) as unknown[]),
      ...(umSeriesOption as unknown[]),
    ] as EChartsOption["series"],
  };
}

function buildTooltipState(
  chart: ChartBuildResult,
  props: TimeSeriesChartProps,
): TooltipSeriesState {
  const main: TooltipSeries[] = chart.series.map((series) => ({
    seriesId: series.seriesInstanceId ?? `tag:${series.tagId}`,
    displayName: series.displayName,
    tagName: series.tagName,
    unit: series.unit,
    value: (point) => {
      const v = point.value;
      if (v === null || v === undefined || v === "") return "(sem dado)";
      return formatNumericValue(typeof v === "number" ? v : String(v));
    },
  }));

  const limits: TooltipSeries[] = [];
  for (const s of props.limitSeries ?? []) {
    limits.push({
      seriesId: s.seriesInstanceId ?? `limit:${s.tagId}`,
      displayName: s.displayName,
      tagName: s.tagName,
      unit: s.unit,
      value: (point) => {
        const v = point.value;
        if (v === null || v === undefined || v === "") return "(sem dado)";
        return formatNumericValue(typeof v === "number" ? v : String(v));
      },
    });
  }

  for (const entry of props.normLimitSeries ?? []) {
    const mainTarget = chart.series.find(
      (s) => (s.seriesInstanceId ?? `tag:${s.tagId}`) === entry.seriesInstanceId,
    );
    const unit = mainTarget?.unit ?? null;
    if (entry.lowerPoints.length > 0) {
      limits.push({
        seriesId: `norm-lower:${entry.seriesInstanceId}`,
        displayName: normLimitDisplayName(entry, "lower"),
        tagName: entry.lowerTagName ?? entry.tagName ?? "",
        unit,
        value: (point) => {
          const v = point.value;
          if (v === null || v === undefined || v === "") return "(sem dado)";
          return formatNumericValue(typeof v === "number" ? v : String(v));
        },
      });
    }
    if (entry.upperPoints.length > 0) {
      limits.push({
        seriesId: `norm-upper:${entry.seriesInstanceId}`,
        displayName: normLimitDisplayName(entry, "upper"),
        tagName: entry.upperTagName ?? entry.tagName ?? "",
        unit,
        value: (point) => {
          const v = point.value;
          if (v === null || v === undefined || v === "") return "(sem dado)";
          return formatNumericValue(typeof v === "number" ? v : String(v));
        },
      });
    }
  }

  return {
    main,
    limits,
    um: props.umSeries
      ? {
          seriesId: `um:${props.umSeries.seriesInstanceId}`,
          displayName: props.umSeries.displayName ?? "UM",
          tagName: props.umSeries.tagName ?? "",
          unit: null,
          value: () => "",
          categoricalCode: (point, umCategories) => {
            const v = point.value;
            if (v === null || v === undefined || v === "") return "(sem dado)";
            if (typeof v === "number" && umCategories && v >= 0 && v < umCategories.length) {
              return umCategories[v];
            }
            return String(v);
          },
        }
      : null,
    umCategories: props.umSeries?.categories ?? [],
  };
}

function buildSeriesOption(
  series: ChartSeries,
  baseShowSymbol: boolean,
  visualRules?: VisualRulesState,
  pinnedCursorTs?: number | null,
  isPrimarySeries: boolean = false,
) {
  const config: SeriesVisualConfiguration | undefined = visualRules?.enabled
    ? visualRules.bySeries[series.seriesInstanceId ?? `tag:${series.tagId}`]
    : undefined;
  const showSymbol = baseShowSymbol && series.points.length <= SAMPLE_THRESHOLD;

  const markLineData: Array<Record<string, unknown>> = [];
  if (config) {
    for (const limit of config.limits) {
      if (limit.visible) {
        markLineData.push({
          name: limit.label,
          yAxis: limit.value,
          lineStyle: { color: limit.color, type: limit.lineStyle, width: limit.width },
          label: { show: Boolean(limit.label), formatter: limit.label, position: "insideEndTop" as const },
        });
      }
    }
  }

  if (
    isPrimarySeries &&
    pinnedCursorTs !== null &&
    pinnedCursorTs !== undefined &&
    Number.isFinite(pinnedCursorTs)
  ) {
    markLineData.push({
      name: "Cursor",
      xAxis: pinnedCursorTs,
      lineStyle: { color: "#0d3b66", width: 2, type: "dashed" as const },
      label: {
        show: true,
        formatter: () => formatTimeSaoPaulo(pinnedCursorTs),
        position: "insideEndTop" as const,
        backgroundColor: "#0d3b66",
        color: "#ffffff",
        borderRadius: 3,
        padding: [2, 6],
        fontSize: 11,
        fontWeight: "bold" as const,
      },
      emphasis: { disabled: true },
    });
  }

  return {
    id: series.seriesInstanceId ?? `tag:${series.tagId}`,
    name: series.displayName,
    type: "line" as const,
    yAxisIndex: series.yAxisIndex,
    showSymbol,
    symbol: "circle",
    symbolSize: 6,
    sampling: series.comparisonType ? undefined : ("lttb" as const),
    connectNulls: false,
    lineStyle: { color: series.color, width: 2, type: (series.contextId === "B" ? "dashed" : "solid") as "dashed" | "solid" },
    itemStyle: { color: series.color },
    emphasis: { focus: "none" as const },
    data: series.points,
    markLine: markLineData.length > 0
      ? {
          silent: true,
          symbol: ["none", "none"],
          data: markLineData,
        }
      : undefined,
  };
}

function buildLimitSeriesOption(series: ChartSeries) {
  return {
    id: series.seriesInstanceId ?? `limit:${series.tagId}`,
    name: series.displayName,
    type: "line" as const,
    yAxisIndex: series.yAxisIndex,
    showSymbol: false,
    symbol: "none",
    sampling: undefined,
    connectNulls: false,
    lineStyle: { color: series.color, width: 2, type: "dashed" as const, opacity: 0.85 },
    itemStyle: { color: series.color },
    emphasis: { focus: "none" as const },
    z: 5,
    data: series.points,
  };
}

function buildNormLimitSeriesOption(
  entry: NormLimitSeries,
  kind: "lower" | "upper",
  _index: number,
  effectiveYAxisIndex: number,
): Record<string, unknown> {
  const color = kind === "lower" ? entry.lowerColor : entry.upperColor;
  const seriesId = `norm-${kind}:${entry.seriesInstanceId}`;
  return {
    id: seriesId,
    name: normLimitDisplayName(entry, kind),
    type: "line" as const,
    yAxisIndex: effectiveYAxisIndex,
    showSymbol: false,
    symbol: "none",
    sampling: undefined,
    connectNulls: false,
    lineStyle: { color, width: entry.width, type: entry.lineStyle },
    itemStyle: { color },
    emphasis: { focus: "none" as const },
    z: 5,
    data: kind === "lower" ? entry.lowerPoints : entry.upperPoints,
  };
}

function buildUmSeriesOption(
  um: UmChartSeries,
  yAxisIndex: number,
  pinnedCursorTs?: number | null,
): EChartsOption["series"] {
  const seriesId = `um:${um.seriesInstanceId}`;
  // Converte pontos para pares [ts, idx] sem o code (ECharts não usa o terceiro elemento)
  const data = um.steps.map(([ts, idx]) => [ts, idx] as [number, number]);
  const markLine =
    pinnedCursorTs !== null && pinnedCursorTs !== undefined && Number.isFinite(pinnedCursorTs)
      ? {
          silent: true,
          symbol: ["none", "none"],
          data: [
            {
              name: "Cursor",
              xAxis: pinnedCursorTs,
              lineStyle: { color: "#0d3b66", width: 2, type: "dashed" as const },
              label: {
                show: true,
                formatter: () => formatTimeSaoPaulo(pinnedCursorTs),
                position: "insideEndTop" as const,
                backgroundColor: "#0d3b66",
                color: "#ffffff",
                borderRadius: 3,
                padding: [2, 6],
                fontSize: 11,
                fontWeight: "bold" as const,
              },
              emphasis: { disabled: true },
            },
          ],
        }
      : undefined;

  return {
    id: seriesId,
    name: um.displayName,
    type: "line" as const,
    yAxisIndex,
    step: "end" as const,
    showSymbol: false,
    connectNulls: false,
    lineStyle: { color: um.color, width: 2 },
    itemStyle: { color: um.color },
    emphasis: { focus: "none" as const },
    z: 4,
    data,
    markLine,
  };
}

function formatMarkerHeader(dateOrMs: number | Date): string {
  try {
    const date = typeof dateOrMs === "number" ? new Date(dateOrMs) : dateOrMs;
    if (Number.isNaN(date.getTime())) return "";
    const parts = SAO_PAULO_DATE_TIME_FORMATTER.formatToParts(date);
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("day")}/${get("month")}, ${get("hour")}:${get("minute")}:${get("second")}`;
  } catch {
    return "";
  }
}

function getSeriesValueAtTimestamp(
  points: Array<[number, unknown]>,
  timestampMs: number,
  mode: "recorded" | "interpolated",
): { value: number | null } {
  if (!points || points.length === 0) return { value: null };
  if (timestampMs <= points[0][0]) {
    const v = typeof points[0][1] === "number" ? points[0][1] : null;
    return { value: v };
  }
  if (timestampMs >= points[points.length - 1][0]) {
    const last = points[points.length - 1];
    const v = typeof last[1] === "number" ? last[1] : null;
    return { value: v };
  }

  let low = 0;
  let high = points.length - 1;
  let idx = 0;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (points[mid][0] <= timestampMs) {
      idx = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  const p1 = points[idx];
  const p2 = idx + 1 < points.length ? points[idx + 1] : null;

  if (!p2 || p1[0] === timestampMs) {
    const v = typeof p1[1] === "number" ? p1[1] : null;
    return { value: v };
  }

  if (mode === "interpolated") {
    const v1 = typeof p1[1] === "number" ? p1[1] : null;
    const v2 = typeof p2[1] === "number" ? p2[1] : null;
    if (v1 !== null && v2 !== null && Number.isFinite(v1) && Number.isFinite(v2)) {
      const fraction = (timestampMs - p1[0]) / (p2[0] - p1[0]);
      return { value: v1 + (v2 - v1) * fraction };
    }
  }

  const dist1 = Math.abs(timestampMs - p1[0]);
  const dist2 = Math.abs(p2[0] - timestampMs);
  const chosen = dist1 <= dist2 ? p1 : p2;
  const v = typeof chosen[1] === "number" ? chosen[1] : null;
  return { value: v };
}

export function TimeSeriesChart(props: TimeSeriesChartProps) {
  const { chart, equipment, start, end, mode, loading, titleLabel, umSeries } = props;

  const [markers, setMarkers] = useState<number[]>(() => {
    if (props.pinnedCursorTs !== null && props.pinnedCursorTs !== undefined) {
      return [props.pinnedCursorTs];
    }
    return [];
  });
  const [, setRenderTick] = useState(0);
  const [isDraggingState, setIsDraggingState] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [instance, setInstance] = useState<ECharts | null>(null);
  const instanceRef = useRef<ECharts | null>(null);
  const isDraggingRef = useRef(false);
  const draggingMarkerIdxRef = useRef<number | null>(null);
  const markersRef = useRef<number[]>(markers);
  markersRef.current = markers;

  // Sync external pinnedCursorTs if changed
  useEffect(() => {
    if (props.pinnedCursorTs !== undefined && props.pinnedCursorTs !== null) {
      setMarkers((prev) => (prev.length > 0 && prev[0] === props.pinnedCursorTs ? prev : [props.pinnedCursorTs!]));
    }
  }, [props.pinnedCursorTs]);

  const handleClearAllMarkers = useCallback(() => {
    setMarkers([]);
    props.onClearCursor?.();
    props.onPinnedCursorChange?.(null);
  }, [props.onClearCursor, props.onPinnedCursorChange]);

  const handleRemoveMarker = useCallback(
    (idx: number) => {
      setMarkers((prev) => {
        const next = prev.filter((_, i) => i !== idx);
        if (next.length === 0) {
          props.onClearCursor?.();
          props.onPinnedCursorChange?.(null);
        } else {
          props.onPinnedCursorChange?.(next[0]);
        }
        return next;
      });
    },
    [props.onClearCursor, props.onPinnedCursorChange],
  );

  const handleInit = useCallback((inst: ECharts) => {
    instanceRef.current = inst;
    setInstance(inst);
  }, []);

  // Compute exact plot grid bounds (including during zoom)
  const getGridBounds = useCallback(() => {
    const inst = instanceRef.current;
    if (inst) {
      const gridModel = (inst as any).getModel?.()?.getComponent?.("grid");
      const rect = gridModel?.coordinateSystem?.getRect?.();
      if (rect && typeof rect.x === "number") {
        return {
          left: rect.x,
          right: rect.x + rect.width,
          top: rect.y,
          bottom: rect.y + rect.height,
          height: rect.height,
        };
      }
    }
    const width = containerRef.current?.clientWidth ?? inst?.getWidth() ?? 800;
    const height = containerRef.current?.clientHeight ?? inst?.getHeight() ?? 420;
    const left = chart.yAxisLabels.length > 1 ? 60 : 45;
    const right = width - (chart.yAxisLabels.length > 1 ? 60 : 24);
    const top = 70;
    const bottom = height - 96;
    return { left, right, top, bottom, height: Math.max(0, bottom - top) };
  }, [chart.yAxisLabels.length]);

  const handleAddFirstMarker = useCallback(() => {
    setMarkers((prev) => {
      if (prev.length > 0) return prev;
      const centerTs = Math.round((start.getTime() + end.getTime()) / 2);
      return [centerTs];
    });
  }, [start, end]);

  const handleAddSecondMarker = useCallback(() => {
    setMarkers((prev) => {
      if (prev.length >= 2) return prev;
      const base = prev[0] ?? (start.getTime() + end.getTime()) / 2;
      const offset = (end.getTime() - start.getTime()) * 0.15;
      let secondTs = base + offset;
      if (secondTs > end.getTime()) {
        secondTs = base - offset;
      }
      secondTs = Math.max(start.getTime(), Math.min(end.getTime(), Math.round(secondTs)));
      return [base, secondTs];
    });
  }, [start, end]);

  // option DOES NOT depend on real-time dragging markers, keeping ECharts canvas completely stationary and performant
  const option = useMemo(
    () =>
      buildTimeSeriesChartOption({
        chart,
        equipment,
        start,
        end,
        mode,
        titleLabel,
        visualRules: props.visualRules,
        limitSeries: props.limitSeries,
        normLimitSeries: props.normLimitSeries,
        umSeries: props.umSeries,
        pinnedCursorTs: props.pinnedCursorTs ?? null,
        onClearCursor: props.onClearCursor,
      }),
    [
      chart,
      equipment,
      start,
      end,
      mode,
      titleLabel,
      props.visualRules,
      props.limitSeries,
      props.normLimitSeries,
      props.umSeries,
      props.pinnedCursorTs,
      props.onClearCursor,
    ],
  );

  // Listen to ECharts zoom, restore, resize to update marker pixel positions without modifying stored timestamps
  useEffect(() => {
    if (!instance) return;
    const forceUpdate = () => setRenderTick((t) => t + 1);
    instance.on("dataZoom", forceUpdate);
    instance.on("restore", forceUpdate);
    window.addEventListener("resize", forceUpdate);
    return () => {
      instance.off("dataZoom", forceUpdate);
      instance.off("restore", forceUpdate);
      window.removeEventListener("resize", forceUpdate);
    };
  }, [instance]);

  const handleGlobalPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!isDraggingRef.current || draggingMarkerIdxRef.current === null) return;
      const container = containerRef.current;
      const inst = instanceRef.current;
      if (!container || !inst) return;

      const rect = container.getBoundingClientRect();
      const offsetX = e.clientX - rect.left;
      const bounds = getGridBounds();
      const clampedX = Math.max(bounds.left, Math.min(bounds.right, offsetX));

      const rawTs = inst.convertFromPixel({ xAxisIndex: 0 }, clampedX);
      if (typeof rawTs !== "number" || !Number.isFinite(rawTs)) return;

      const targetIdx = draggingMarkerIdxRef.current;
      const clampedTs = Math.round(rawTs);

      setMarkers((prev) => {
        if (targetIdx >= prev.length) return prev;
        if (prev[targetIdx] === clampedTs) return prev;
        const next = [...prev];
        next[targetIdx] = clampedTs;
        return next;
      });
    },
    [getGridBounds],
  );

  const handleGlobalPointerUp = useCallback(() => {
    if (isDraggingRef.current) {
      isDraggingRef.current = false;
      const activeIdx = draggingMarkerIdxRef.current;
      draggingMarkerIdxRef.current = null;
      setIsDraggingState(false);
      window.removeEventListener("pointermove", handleGlobalPointerMove);
      window.removeEventListener("pointerup", handleGlobalPointerUp);
      window.removeEventListener("pointercancel", handleGlobalPointerUp);
      window.removeEventListener("blur", handleGlobalPointerUp);

      if (activeIdx !== null && activeIdx === 0 && markersRef.current.length > 0) {
        props.onPinnedCursorChange?.(markersRef.current[0]);
      }
    }
  }, [handleGlobalPointerMove, props.onPinnedCursorChange]);

  const startDrag = useCallback(
    (targetIdx: number) => {
      isDraggingRef.current = true;
      draggingMarkerIdxRef.current = targetIdx;
      setIsDraggingState(true);

      if (instanceRef.current) {
        instanceRef.current.dispatchAction({ type: "hideTip" });
      }

      window.addEventListener("pointermove", handleGlobalPointerMove);
      window.addEventListener("pointerup", handleGlobalPointerUp);
      window.addEventListener("pointercancel", handleGlobalPointerUp);
      window.addEventListener("blur", handleGlobalPointerUp);
    },
    [handleGlobalPointerMove, handleGlobalPointerUp],
  );

  useEffect(() => {
    return () => {
      window.removeEventListener("pointermove", handleGlobalPointerMove);
      window.removeEventListener("pointerup", handleGlobalPointerUp);
      window.removeEventListener("pointercancel", handleGlobalPointerUp);
      window.removeEventListener("blur", handleGlobalPointerUp);
    };
  }, [handleGlobalPointerMove, handleGlobalPointerUp]);

  const handleCanvasPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const container = containerRef.current;
    const inst = instanceRef.current;
    if (!container || !inst) return;

    const rect = container.getBoundingClientRect();
    const offsetX = e.clientX - rect.left;
    const offsetY = e.clientY - rect.top;
    const bounds = getGridBounds();
    if (
      offsetX < bounds.left ||
      offsetX > bounds.right ||
      offsetY < bounds.top ||
      offsetY > bounds.bottom
    ) {
      return;
    }

    const rawTs = inst.convertFromPixel({ xAxisIndex: 0 }, offsetX);
    if (typeof rawTs !== "number" || !Number.isFinite(rawTs)) return;
    const clickedTs = Math.round(rawTs);

    if (markers.length === 0) {
      setMarkers([clickedTs]);
      startDrag(0);
      props.onPinnedCursorChange?.(clickedTs);
    } else if (markers.length === 1) {
      setMarkers([clickedTs]);
      startDrag(0);
      props.onPinnedCursorChange?.(clickedTs);
    } else {
      // 2 markers: find visually closer marker on screen
      const px0 = inst.convertToPixel({ xAxisIndex: 0 }, markers[0]);
      const px1 = inst.convertToPixel({ xAxisIndex: 0 }, markers[1]);
      const d0 = Math.abs(offsetX - px0);
      const d1 = Math.abs(offsetX - px1);
      const targetIdx = d0 <= d1 ? 0 : 1;
      setMarkers((prev) => {
        const next = [...prev];
        next[targetIdx] = clickedTs;
        return next;
      });
      startDrag(targetIdx);
    }
  };

  const handleDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const offsetX = e.clientX - rect.left;
    const offsetY = e.clientY - rect.top;
    const bounds = getGridBounds();
    if (
      offsetX >= bounds.left &&
      offsetX <= bounds.right &&
      offsetY >= bounds.top &&
      offsetY <= bounds.bottom
    ) {
      handleClearAllMarkers();
    }
  };

  const bounds = getGridBounds();
  const gridTop = bounds.top;
  const gridHeight = bounds.height;
  const gridLeft = bounds.left;
  const gridRight = bounds.right;

  // Find UM series index in chart series list if present
  const umSeriesIndex = useMemo(() => {
    if (!umSeries) return -1;
    return chart.series.length;
  }, [umSeries, chart.series.length]);

  return (
    <div
      ref={containerRef}
      onPointerDown={handleCanvasPointerDown}
      onDoubleClick={handleDoubleClick}
      style={{
        position: "relative",
        width: "100%",
        height: 420,
        overflow: "hidden",
        userSelect: isDraggingState ? "none" : undefined,
        cursor: isDraggingState ? "ew-resize" : "crosshair",
      }}
    >
      {/* Invisible full-cover backdrop during active dragging to guarantee zero event loss */}
      {isDraggingState && (
        <div
          data-testid="drag-backdrop"
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 25,
            cursor: "ew-resize",
            backgroundColor: "transparent",
          }}
        />
      )}
      {/* Markers Toolbar */}
      {markers.length > 0 && (
        <div
          data-testid="markers-toolbar"
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            position: "absolute",
            top: 8,
            left: 16,
            zIndex: 10,
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            backgroundColor: "rgba(255, 255, 255, 0.95)",
            border: "1px solid rgba(0, 0, 0, 0.15)",
            padding: "3px 10px",
            borderRadius: 4,
            fontSize: "0.8rem",
            boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
            pointerEvents: "auto",
          }}
        >
          <span style={{ fontWeight: 600, color: "#222" }}>Marcador:</span>
          <span>{formatMarkerHeader(markers[0])}</span>
          {markers.length === 2 && (
            <>
              <span style={{ color: "#bbb" }}>|</span>
              <span style={{ fontWeight: 600, color: "#555" }}>M2:</span>
              <span>{formatMarkerHeader(markers[1])}</span>
              <span style={{ color: "#bbb" }}>|</span>
              <span style={{ fontWeight: 600, color: "#0d3b66" }}>
                Δt: {formatElapsed(Math.abs(markers[1] - markers[0]))}
              </span>
            </>
          )}
          {markers.length < 2 && (
            <button
              type="button"
              onClick={handleAddSecondMarker}
              className="btn btn-sm btn-outline-secondary py-0 px-2"
              style={{ fontSize: "0.75rem", lineHeight: 1.3 }}
              title="Adicionar segundo marcador para comparação"
            >
              + 2º Marcador
            </button>
          )}
          <button
            type="button"
            onClick={handleClearAllMarkers}
            className="btn btn-sm btn-outline-danger py-0 px-2"
            style={{ fontSize: "0.75rem", lineHeight: 1.3 }}
            title="Remover marcadores"
          >
            Limpar
          </button>
        </div>
      )}
      {markers.length === 0 && (
        <div
          data-testid="markers-toolbar-empty"
          style={{
            position: "absolute",
            top: 8,
            left: 16,
            zIndex: 10,
            pointerEvents: "auto",
          }}
        >
          <button
            type="button"
            onClick={handleAddFirstMarker}
            className="btn btn-sm btn-outline-secondary py-0 px-2"
            style={{ fontSize: "0.75rem", lineHeight: 1.3 }}
            title="Adicionar marcador temporal"
          >
            + Marcador
          </button>
        </div>
      )}

      {/* Markers Visual Elements (Line, Dots, Box, Handles) */}
      {instance &&
        markers.map((markerTs, mIdx) => {
          const pixelX = instance.convertToPixel({ xAxisIndex: 0 }, markerTs);
          if (typeof pixelX !== "number" || !Number.isFinite(pixelX)) return null;
          // When marker is outside visible zoom window, hide it without altering stored timestamp
          if (pixelX < gridLeft - 5 || pixelX > gridRight + 5) return null;

          const markerColor = mIdx === 0 ? "#222222" : "#555555";
          const boxWidth = 185;
          const boxLeft = pixelX + boxWidth + 4 > gridRight ? pixelX - boxWidth - 4 : pixelX + 4;

          // Compute values and dot positions for each series
          const seriesData = chart.series.map((s, sIdx) => {
            const { value } = getSeriesValueAtTimestamp(s.points, markerTs, mode);
            let dotY: number | null = null;
            if (value !== null && Number.isFinite(value)) {
              const pt = instance.convertToPixel({ seriesIndex: sIdx }, [markerTs, value]);
              if (pt && Number.isFinite(pt[1]) && pt[1] >= gridTop - 4 && pt[1] <= gridTop + gridHeight + 4) {
                dotY = pt[1];
              }
            }
            const valueFormatted =
              value !== null
                ? `${formatNumericValue(value)}${s.unit ? " " + s.unit : ""}`
                : "(sem dado)";
            return {
              id: s.seriesInstanceId ?? `tag:${s.tagId}`,
              displayName: s.displayName,
              color: s.color,
              valueText: valueFormatted,
              dotY,
            };
          });

          // UM Series (if selected)
          let umData: { displayName: string; color: string; valueText: string; dotY: number | null } | null = null;
          if (umSeries && umSeriesIndex !== -1) {
            const activeStep = findActiveUmStep(umSeries.steps, markerTs);
            const umCode = activeStep ? activeStep[2] : "(sem dado)";
            let dotY: number | null = null;
            if (activeStep) {
              const pt = instance.convertToPixel({ seriesIndex: umSeriesIndex }, [markerTs, activeStep[1]]);
              if (pt && Number.isFinite(pt[1]) && pt[1] >= gridTop - 4 && pt[1] <= gridTop + gridHeight + 4) {
                dotY = pt[1];
              }
            }
            umData = {
              displayName: umSeries.displayName,
              color: umSeries.color,
              valueText: umCode,
              dotY,
            };
          }

          return (
            <div key={`marker-group-${mIdx}`}>
              {/* Vertical Line with wide grab hit area */}
              <div
                data-testid={`marker-line-${mIdx}`}
                style={{
                  position: "absolute",
                  left: pixelX - 5,
                  top: gridTop,
                  height: gridHeight,
                  width: 11,
                  cursor: "ew-resize",
                  zIndex: 10,
                  display: "flex",
                  justifyContent: "center",
                }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  startDrag(mIdx);
                }}
              >
                <div
                  style={{
                    width: 1.5,
                    height: "100%",
                    backgroundColor: markerColor,
                  }}
                />
              </div>

              {/* Curve Intersection Dots */}
              {seriesData.map(
                (sd) =>
                  sd.dotY !== null && (
                    <div
                      key={`dot-${sd.id}`}
                      style={{
                        position: "absolute",
                        left: pixelX - 4,
                        top: sd.dotY - 4,
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        backgroundColor: sd.color,
                        border: "2px solid #ffffff",
                        boxShadow: "0 0 2px rgba(0,0,0,0.5)",
                        pointerEvents: "none",
                        zIndex: 4,
                      }}
                    />
                  ),
              )}
              {umData && umData.dotY !== null && (
                <div
                  key="dot-um"
                  style={{
                    position: "absolute",
                    left: pixelX - 4,
                    top: umData.dotY - 4,
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    backgroundColor: umData.color,
                    border: "2px solid #ffffff",
                    boxShadow: "0 0 2px rgba(0,0,0,0.5)",
                    pointerEvents: "none",
                    zIndex: 4,
                  }}
                />
              )}

              {/* Marker Top Box */}
              <div
                data-testid={`marker-box-${mIdx}`}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  startDrag(mIdx);
                }}
                style={{
                  position: "absolute",
                  left: boxLeft,
                  top: gridTop + 2,
                  width: boxWidth,
                  backgroundColor: "rgba(255, 255, 255, 0.92)",
                  border: "1px solid rgba(0, 0, 0, 0.18)",
                  borderRadius: 3,
                  padding: "5px 8px",
                  boxShadow: "0 2px 6px rgba(0, 0, 0, 0.12)",
                  userSelect: "none",
                  zIndex: 10,
                  cursor: "ew-resize",
                  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif',
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    color: "#111111",
                    fontSize: "11px",
                    borderBottom: "1px solid rgba(0, 0, 0, 0.1)",
                    paddingBottom: 2,
                    marginBottom: 4,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span>{formatMarkerHeader(markerTs)}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRemoveMarker(mIdx);
                    }}
                    onPointerDown={(e) => e.stopPropagation()}
                    title="Remover marcador"
                    style={{
                      background: "none",
                      border: "none",
                      color: "#888",
                      fontSize: "13px",
                      lineHeight: 1,
                      cursor: "pointer",
                      padding: "0 2px",
                    }}
                  >
                    ×
                  </button>
                </div>

                {seriesData.map((sd) => (
                  <div key={sd.id} style={{ marginBottom: 3 }}>
                    <div
                      style={{
                        color: sd.color,
                        fontWeight: 600,
                        fontSize: "10.5px",
                        lineHeight: "13px",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                      title={sd.displayName}
                    >
                      {sd.displayName}
                    </div>
                    <div
                      style={{
                        color: sd.color,
                        fontWeight: 700,
                        fontSize: "11px",
                        lineHeight: "14px",
                      }}
                    >
                      {sd.valueText}
                    </div>
                  </div>
                ))}

                {umData && (
                  <div key="um-data" style={{ marginBottom: 3 }}>
                    <div
                      style={{
                        color: umData.color,
                        fontWeight: 600,
                        fontSize: "10.5px",
                        lineHeight: "13px",
                      }}
                      title={umData.displayName}
                    >
                      {umData.displayName}
                    </div>
                    <div
                      style={{
                        color: umData.color,
                        fontWeight: 700,
                        fontSize: "11px",
                        lineHeight: "14px",
                      }}
                    >
                      {umData.valueText}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}

      <EChartsWrapper option={option} loading={loading} height={420} onInit={handleInit} />
    </div>
  );
}
