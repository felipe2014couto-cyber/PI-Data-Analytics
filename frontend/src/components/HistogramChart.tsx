import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { ChartSeries } from "../utils/chartData";
import { buildHistogram, numericValuesFromSeries } from "../utils/statistics";
import { formatNumericValue } from "../utils/values";

interface HistogramChartProps {
  series: ChartSeries;
}

function intervalLabel(lower: number, upper: number, includesUpper: boolean): string {
  return `${includesUpper ? "[" : "["}${formatNumericValue(lower)}, ${formatNumericValue(upper)}${includesUpper ? "]" : ")"}`;
}

export function buildHistogramChartOption(series: ChartSeries): EChartsOption {
  const histogram = buildHistogram(numericValuesFromSeries(series));
  const labels = histogram.bins.map((bin) => intervalLabel(bin.lower, bin.upper, bin.includesUpper));
  return {
    title: {
      text: series.displayName,
      subtext: `${series.tagName} | ${series.unit?.trim() || "Sem unidade"} | n=${histogram.count}`,
      left: "center",
    },
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const entry = Array.isArray(params) ? params[0] as { dataIndex?: number } : null;
        const bin = entry?.dataIndex === undefined ? null : histogram.bins[entry.dataIndex];
        if (!bin) return "";
        return [
          `<strong>${series.displayName}</strong> (${series.tagName})`,
          `Intervalo: ${intervalLabel(bin.lower, bin.upper, bin.includesUpper)}`,
          `Frequência: ${bin.frequency}`,
          `Percentual: ${bin.percentage.toFixed(2)}%`,
        ].join("<br/>");
      },
    },
    grid: { left: 60, right: 24, top: 72, bottom: 90 },
    xAxis: {
      type: "category",
      name: `Intervalos (${series.unit?.trim() || "Sem unidade"})`,
      data: labels,
      axisLabel: { rotate: labels.length > 8 ? 35 : 0, hideOverlap: true },
    },
    yAxis: { type: "value", name: "Frequência", minInterval: 1 },
    toolbox: {
      right: 16,
      feature: {
        restore: { title: "Restaurar" },
        saveAsImage: { name: `histograma-${series.tagName}`, title: "Salvar imagem" },
      },
    },
    animation: false,
    series: [
      {
        name: series.displayName,
        type: "bar",
        data: histogram.bins.map((bin) => bin.frequency),
        itemStyle: { color: series.color },
        barMaxWidth: 72,
      },
    ],
  };
}

export function HistogramChart({ series }: HistogramChartProps) {
  const option = useMemo(() => buildHistogramChartOption(series), [series]);
  return <EChartsWrapper option={option} height={380} />;
}
