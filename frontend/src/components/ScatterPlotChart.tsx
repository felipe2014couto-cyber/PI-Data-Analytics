import { useMemo } from "react";
import type { EChartsOption } from "echarts";

import { EChartsWrapper } from "./EChartsWrapper";
import type { TimeSeriesSeries } from "../types";
import { alignSeriesByTimestamp, pearsonCorrelation } from "../utils/comparison";
import { formatNumericValue, qualityFlags } from "../utils/values";

interface ScatterPlotChartProps {
  xSeries: TimeSeriesSeries;
  ySeries: TimeSeriesSeries;
  ignoreBadQuality: boolean;
}

function axisName(series: TimeSeriesSeries): string {
  return `${series.display_name}${series.unit?.trim() ? ` (${series.unit.trim()})` : ""}`;
}

export function buildScatterPlotChartOption(
  xSeries: TimeSeriesSeries,
  ySeries: TimeSeriesSeries,
  ignoreBadQuality: boolean,
): EChartsOption {
  const pairs = alignSeriesByTimestamp(xSeries, ySeries, ignoreBadQuality);
  return {
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const entry = params as { dataIndex?: number };
        const pair = entry.dataIndex === undefined ? null : pairs[entry.dataIndex];
        if (!pair) return "";
        return [
          `<strong>${new Date(pair.timestamp).toLocaleString("pt-BR")}</strong>`,
          `Eixo X — ${xSeries.display_name} (${xSeries.tag_name}): ${formatNumericValue(pair.x.value)}${xSeries.unit ? ` ${xSeries.unit}` : ""}`,
          `Qualidade X: ${qualityFlags(pair.x)}`,
          `Eixo Y — ${ySeries.display_name} (${ySeries.tag_name}): ${formatNumericValue(pair.y.value)}${ySeries.unit ? ` ${ySeries.unit}` : ""}`,
          `Qualidade Y: ${qualityFlags(pair.y)}`,
        ].join("<br/>");
      },
    },
    grid: { left: 80, right: 40, top: 28, bottom: 80 },
    xAxis: { type: "value", name: axisName(xSeries), scale: true, nameLocation: "middle", nameGap: 45 },
    yAxis: { type: "value", name: axisName(ySeries), scale: true, nameLocation: "middle", nameGap: 58 },
    toolbox: {
      right: 16,
      feature: {
        dataZoom: { title: { zoom: "Zoom", back: "Restaurar zoom" } },
        restore: { title: "Restaurar" },
        saveAsImage: { name: `dispersao-${xSeries.tag_name}-${ySeries.tag_name}`, title: "Salvar imagem" },
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, yAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 22 },
    ],
    animation: false,
    series: [
      {
        name: `${xSeries.display_name} × ${ySeries.display_name}`,
        type: "scatter",
        symbolSize: 9,
        data: pairs.map((pair) => [pair.x.value, pair.y.value]),
      },
    ],
  };
}

export function ScatterPlotChart(props: ScatterPlotChartProps) {
  const { xSeries, ySeries, ignoreBadQuality } = props;
  const pairs = useMemo(
    () => alignSeriesByTimestamp(xSeries, ySeries, ignoreBadQuality),
    [xSeries, ySeries, ignoreBadQuality],
  );
  const correlation = useMemo(() => pearsonCorrelation(pairs), [pairs]);
  const option = useMemo(
    () => buildScatterPlotChartOption(xSeries, ySeries, ignoreBadQuality),
    [xSeries, ySeries, ignoreBadQuality],
  );
  return (
    <div>
      <div className="small mb-2" data-testid="scatter-summary">
        <strong>Eixo X:</strong> {axisName(xSeries)} | <strong>Eixo Y:</strong>{" "}
        {axisName(ySeries)} | <strong>Pares:</strong> {pairs.length} |{" "}
        <strong>Correlação:</strong>{" "}
        {correlation === null
          ? "indisponível"
          : correlation.toLocaleString("pt-BR", {
              minimumFractionDigits: 4,
              maximumFractionDigits: 4,
            })}
      </div>
      <EChartsWrapper option={option} height={430} />
    </div>
  );
}
