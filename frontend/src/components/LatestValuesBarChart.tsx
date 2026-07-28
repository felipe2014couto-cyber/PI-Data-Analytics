import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { LatestValueGroup } from "../utils/comparison";
import { formatNumericValue, qualityFlags } from "../utils/values";

interface LatestValuesBarChartProps {
  group: LatestValueGroup;
}

export function buildLatestValuesBarChartOption(group: LatestValueGroup): EChartsOption {
  return {
    title: { text: "Barras — último valor", subtext: group.unit, left: "center" },
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const item = params as { dataIndex?: number };
        const entry = item.dataIndex === undefined ? null : group.entries[item.dataIndex];
        if (!entry) return "";
        return [
          `<strong>${entry.displayName}</strong> (${entry.tagName})`,
          `Valor: ${formatNumericValue(entry.observation.value)} ${entry.unit}`,
          `Timestamp: ${new Date(entry.observation.timestamp).toLocaleString("pt-BR")}`,
          `Qualidade: ${qualityFlags(entry.observation)}`,
        ].join("<br/>");
      },
    },
    grid: { left: 72, right: 24, top: 72, bottom: 90 },
    xAxis: {
      type: "category",
      data: group.entries.map((entry) => entry.displayName),
      axisLabel: { interval: 0, rotate: group.entries.length > 4 ? 25 : 0 },
    },
    yAxis: { type: "value", name: group.unit, scale: true },
    toolbox: {
      right: 16,
      feature: {
        restore: { title: "Restaurar" },
        saveAsImage: { name: `barras-ultimo-valor-${group.unit}`, title: "Salvar imagem" },
      },
    },
    animation: false,
    series: [
      {
        name: "Último valor",
        type: "bar",
        data: group.entries.map((entry) => entry.observation.value),
        barMaxWidth: 72,
        label: { show: true, position: "top", formatter: (params: unknown) => {
          const item = params as { value?: number };
          return formatNumericValue(item.value ?? null);
        } },
      },
    ],
  };
}

export function LatestValuesBarChart({ group }: LatestValuesBarChartProps) {
  const option = useMemo(() => buildLatestValuesBarChartOption(group), [group]);
  return <EChartsWrapper option={option} height={390} />;
}
