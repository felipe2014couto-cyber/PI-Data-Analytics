import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { ChartBuildResult, ChartSeries } from "../utils/chartData";
import type { SeriesVisualConfiguration, VisualRulesState } from "../types";
import { formatNumericValue } from "../utils/values";
import { firstMatchingRule, matchingRange } from "../utils/visualRules";

const SAMPLE_THRESHOLD = 1200;

function formatElapsed(value: number): string {
  const totalSeconds = Math.max(0, Math.round(value / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

interface TimeSeriesChartProps {
  chart: ChartBuildResult;
  equipment: string | null;
  start: Date;
  end: Date;
  mode: "recorded" | "interpolated";
  loading?: boolean;
  titleLabel?: string;
  visualRules?: VisualRulesState;
}

function buildTooltip(
  chart: ChartBuildResult,
  startLocal: string,
  endLocal: string,
  mode: "recorded" | "interpolated",
  visualRules?: VisualRulesState,
) {
  return (params: unknown) => {
    if (!Array.isArray(params) || params.length === 0) {
      return "";
    }
    const first = params[0] as { axisValueLabel?: string; value?: [number, unknown] };
    const time = first?.axisValueLabel ?? "";
    const lines: string[] = [];
    lines.push(`<div style="font-weight:600">${chart.comparisonType === "periods" && first.value ? `Decorrido ${formatElapsed(Number(first.value[0]))}` : time}</div>`);
    for (const entry of params as Array<{
      seriesName: string;
      value: [number, unknown];
      dataIndex: number;
      seriesIndex: number;
      marker: string;
    }>) {
      const series = chart.series[entry.seriesIndex];
      if (!series) continue;
      const quality = series.qualitySeries[entry.dataIndex];
      let valueText: string;
      if (entry.value && entry.value[1] === null) {
        valueText = "(lacuna)";
      } else if (entry.value && Array.isArray(entry.value) && entry.value.length >= 2) {
        valueText = formatNumericValue(entry.value[1] as number);
      } else {
        valueText = "-";
      }
      const qualityLabels: Record<number, string> = {
        0: "OK",
        1: "Substituido",
        2: "Questionavel",
        3: "Ruim",
      };
      const qualityText =
        quality !== undefined && quality !== null
          ? (qualityLabels[Number(quality)] ?? "Ruim")
          : "";
      lines.push(
        `<div>${entry.marker} <strong>${entry.seriesName}</strong> ` +
          `(${series.tagName}): ${valueText}${series.unit ? ` ${series.unit}` : ""}` +
          (qualityText ? ` - ${qualityText}` : "") +
          `</div>`,
      );
      if (chart.comparisonType === "periods") {
        const original = series.originalTimestamps?.[entry.dataIndex];
        lines.push(`<div class="text-muted small">Original: ${original ? new Date(original).toLocaleString("pt-BR") : "-"}</div>`);
      }
      const visualConfig = visualRules?.enabled ? visualRules.bySeries[series.seriesInstanceId ?? `tag:${series.tagId}`] : undefined;
      const originalValue = entry.value?.[1];
      const rule = visualConfig ? firstMatchingRule(originalValue, visualConfig.rules) : null;
      const range = visualConfig ? matchingRange(originalValue, visualConfig.ranges) : null;
      if (rule) lines.push(`<div class="small">Regra: ${rule.label || "Sem rótulo"} · ${rule.color}</div>`);
      if (range) lines.push(`<div class="small">Faixa: ${range.label || "Sem rótulo"}</div>`);
    }
    lines.push(
      `<div class="text-muted small">Periodo: ${startLocal} ate ${endLocal} | ${mode}</div>`,
    );
    return lines.join("");
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
    const qualityLabels: Record<number, string> = {
      0: "OK",
      1: "Substituido",
      2: "Questionavel",
      3: "Ruim",
    };
    return [
      `<div style="font-weight:600">${entry.axisValueLabel ?? ""}</div>`,
      `<div>${entry.marker} <strong>${entry.seriesName}</strong> (${series.tagName}): ${state}` +
        (quality !== undefined ? ` - ${qualityLabels[quality] ?? "Ruim"}` : "") +
        `</div>`,
    ].join("");
  };
}

function buildStateOption(props: TimeSeriesChartProps): EChartsOption {
  const { chart, equipment, start, end, mode } = props;
  const series = chart.series[0];
  return {
    title: {
      text: `${equipment ?? "Equipamento"} | Estados ${mode === "recorded" ? "registrados" : "interpolados"}`,
      subtext: `${start.toLocaleString("pt-BR")} ate ${end.toLocaleString("pt-BR")}`,
      left: "center",
    },
    tooltip: {
      trigger: "axis",
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
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 24 },
    ],
    animation: false,
    series: series
      ? [
          {
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
          },
        ]
      : [],
  };
}

export function buildTimeSeriesChartOption(props: TimeSeriesChartProps): EChartsOption {
  const { chart, equipment, start, end, mode } = props;
  if (chart.valueKind === "textual") {
    return buildStateOption(props);
  }
  const titleText = `${equipment ?? "Equipamento"} | ${props.titleLabel ?? (mode === "recorded" ? "Valores registrados — exatos" : "Valores interpolados")}`;
  const subtitle = `${start.toLocaleString("pt-BR")} ate ${end.toLocaleString("pt-BR")}`;
  const yAxis = chart.yAxisLabels.map((label, index) => ({
    type: "value" as const,
    name: label,
    nameTextStyle: { padding: [0, 0, 0, 24] },
    position: (index === 0 ? "left" : "right") as "left" | "right",
    alignTicks: true,
    scale: true,
  }));
  const baseShowSymbol = chart.series.every((series) => series.points.length <= SAMPLE_THRESHOLD);
  const seriesOption = chart.series.map((series) => buildSeriesOption(series, baseShowSymbol, props.visualRules)) as EChartsOption["series"];

  return {
    title: { text: titleText, subtext: subtitle, left: "center" },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", label: { backgroundColor: "#0d3b66" } },
      formatter: buildTooltip(chart, start.toLocaleString("pt-BR"), end.toLocaleString("pt-BR"), mode, props.visualRules),
    },
    legend: {
      type: "scroll",
      bottom: 64,
      data: chart.series.map((s) => s.displayName),
    },
    grid: { left: 60, right: chart.yAxisLabels.length > 1 ? 60 : 24, top: 70, bottom: 96 },
    xAxis: {
      type: "time",
      axisLabel: { color: "#1f2d3d" },
    },
    yAxis: yAxis.length > 0 ? yAxis : [{ type: "value" }],
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { yAxisIndex: "none", title: { zoom: "Zoom", back: "Restaurar" } },
        restore: { title: "Restaurar" },
        saveAsImage: { name: "pi-analytics-data-grafico-linha", title: "Salvar imagem" },
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 24 },
    ],
    animation: false,
    series: seriesOption,
  };
}

function buildSeriesOption(series: ChartSeries, baseShowSymbol: boolean, visualRules?: VisualRulesState) {
  const config: SeriesVisualConfiguration | undefined = visualRules?.enabled ? visualRules.bySeries[series.seriesInstanceId ?? `tag:${series.tagId}`] : undefined;
  const showSymbol = Boolean(config?.rules.some((rule) => rule.enabled)) || (baseShowSymbol && series.points.length <= SAMPLE_THRESHOLD);
  const data = config ? series.points.map((point) => {
    const rule = firstMatchingRule(point[1], config.rules);
    return rule ? { value: point, itemStyle: { color: rule.color } } : point;
  }) : series.points;
  return {
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
    emphasis: { focus: "series" as const },
    data,
    markLine: config ? {
      silent: true,
      symbol: ["none", "none"],
      data: config.limits.filter((limit) => limit.visible).map((limit) => ({
        name: limit.label, yAxis: limit.value,
        lineStyle: { color: limit.color, type: limit.lineStyle, width: limit.width },
        label: { show: Boolean(limit.label), formatter: limit.label, position: "insideEndTop" as const },
      })),
    } : undefined,
    markArea: config ? {
      silent: true,
      itemStyle: { borderWidth: 0 },
      data: config.ranges.filter((range) => range.visible).map((range) => [
        { name: range.label, yAxis: range.lower, itemStyle: { color: range.color, opacity: range.opacity }, label: { show: Boolean(range.label), position: "insideTop" as const } },
        { yAxis: range.upper },
      ]),
    } : undefined,
  };
}

export function TimeSeriesChart(props: TimeSeriesChartProps) {
  const { chart, equipment, start, end, mode, loading, titleLabel } = props;
  const [, setForce] = useState(0);
  const option = useMemo(
    () => buildTimeSeriesChartOption({ chart, equipment, start, end, mode, titleLabel, visualRules: props.visualRules }),
    [chart, equipment, start, end, mode, titleLabel, props.visualRules],
  );
  return (
    <EChartsWrapper
      option={option}
      loading={loading}
      height={420}
      onInit={() => setForce((value) => value + 1)}
    />
  );
}
