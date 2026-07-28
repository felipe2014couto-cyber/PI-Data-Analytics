import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { BoxPlotUnitGroup } from "../utils/statistics";
import { buildBoxPlot, numericValuesFromSeries } from "../utils/statistics";
import { formatNumericValue } from "../utils/values";

interface BoxPlotChartProps {
  group: BoxPlotUnitGroup;
}

export function buildBoxPlotChartOption(group: BoxPlotUnitGroup): EChartsOption {
  const entries = group.series
    .map((series) => ({ series, statistics: buildBoxPlot(numericValuesFromSeries(series)) }))
    .filter((entry) => entry.statistics !== null);
  const outliers = entries.flatMap((entry, index) =>
    entry.statistics?.outliers.map((value) => [index, value]) ?? [],
  );

  return {
    title: { text: `Boxplot | ${group.unit}`, left: "center" },
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as { seriesType?: string; dataIndex?: number; value?: unknown[] };
        if (entry.seriesType === "scatter") {
          const value = Array.isArray(entry.value) ? entry.value[1] : null;
          return `Outlier: ${formatNumericValue(value as number)}`;
        }
        const item = entry.dataIndex === undefined ? null : entries[entry.dataIndex];
        const stats = item?.statistics;
        if (!item || !stats) return "";
        return [
          `<strong>${item.series.displayName}</strong> (${item.series.tagName})`,
          `Unidade: ${group.unit}`,
          `Quantidade: ${stats.count}`,
          `Mínimo: ${formatNumericValue(stats.lowerWhisker)}`,
          `Q1: ${formatNumericValue(stats.q1)}`,
          `Mediana: ${formatNumericValue(stats.median)}`,
          `Q3: ${formatNumericValue(stats.q3)}`,
          `Máximo: ${formatNumericValue(stats.upperWhisker)}`,
          `Outliers: ${stats.outliers.length}`,
        ].join("<br/>");
      },
    },
    grid: { left: 72, right: 24, top: 60, bottom: 80 },
    xAxis: {
      type: "category",
      data: entries.map((entry) => entry.series.tagName),
      axisLabel: { interval: 0, rotate: entries.length > 4 ? 25 : 0 },
    },
    yAxis: { type: "value", name: group.unit, scale: true },
    toolbox: {
      right: 16,
      feature: {
        restore: { title: "Restaurar" },
        saveAsImage: { name: `boxplot-${group.unit}`, title: "Salvar imagem" },
      },
    },
    animation: false,
    series: [
      {
        name: "Distribuição",
        type: "boxplot",
        data: entries.map((entry) => {
          const stats = entry.statistics;
          return stats
            ? [stats.lowerWhisker, stats.q1, stats.median, stats.q3, stats.upperWhisker]
            : [];
        }),
      },
      {
        name: "Outliers",
        type: "scatter",
        data: outliers,
        symbolSize: 8,
      },
    ],
  };
}

export function BoxPlotChart({ group }: BoxPlotChartProps) {
  const option = useMemo(() => buildBoxPlotChartOption(group), [group]);
  return <EChartsWrapper option={option} height={400} />;
}
