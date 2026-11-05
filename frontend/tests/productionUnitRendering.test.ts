// @vitest-environment node
import { describe, expect, it } from "vitest";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { buildChartData } from "../src/utils/chartData";
import { assignProductionUnitAxes, buildProductionUnitTimeSeries } from "../src/utils/productionUnitChart";
import { buildNormLimitSeries } from "../src/utils/normLimitSeries";
import type { ProductionUnitRule } from "../src/types";
import { unitResponse, UNIT_START as T, UNIT_DURATION as D } from "./fixtures/productionUnits";

echarts.use(SVGRenderer);

describe("registered ECharts renderer for the production-unit strip", () => {
  it.each(["MEDIA", "MIN", "MAXIMO"] as ProductionUnitRule[])("actually renders UM labels and %s aggregate curves", (rule) => {
    const response = unitResponse();
    const chart = assignProductionUnitAxes(buildChartData(buildProductionUnitTimeSeries(response, rule, [20]), { ignoreBadQuality: false }))!;
    const option = buildTimeSeriesChartOption({ chart, equipment: "RB1", start: new Date(T), end: new Date(T + 3 * D), mode: "recorded",
      unitBands: response.segments.map(segment => ({ start: Date.parse(segment.start_time), end: Date.parse(segment.end_time), label: segment.um_value! })) });
    // Use the same core registry as EChartsWrapper; importing the full echarts
    // package here would mask a missing CustomChart registration in the app.
    const instance = echarts.init(null, undefined, { renderer: "svg", ssr: true, width: 1400, height: 520 });
    try {
      instance.setOption(option);
      const svg = instance.renderToSVGString();
      expect(svg).toContain("600304J2000B");
      expect(svg.match(/fill="#(?:eaf3fa|d8e9f6)"/g)).toHaveLength(3);
      const band = (option.series as any[]).find(series => series.id === "production-unit-band");
      expect(band.tooltip.triggerOn).toBe("none");
      expect(band.tooltip.formatter({ value: [T, T + D, "600304J2000B"] })).toContain(`${rule === "MEDIA" ? "Média" : rule === "MIN" ? "Mínimo" : "Máximo"} da UM`);
      expect(band.tooltip.formatter({ value: [T, T + D, "600304J2000B"] })).toContain("Amostras brutas: 2845");
    } finally {
      instance.dispose();
    }
  });

  it("does not draw physical norm limits on the percentage OOC axis", () => {
    const response = unitResponse();
    const chart = assignProductionUnitAxes(buildChartData(buildProductionUnitTimeSeries(response, "OOC", [20]), { ignoreBadQuality: false }))!;
    const target = chart.series[0];
    const limits = buildNormLimitSeries({
      seriesInstanceId: target.seriesInstanceId ?? `tag:${target.tagId}`,
      tagName: target.tagName,
      lowerTagName: "LIMIT_LOW",
      upperTagName: "LIMIT_HIGH",
      yAxisIndex: target.yAxisIndex,
      lineStyle: "dashed", width: 2, lowerColor: "#d32f2f", upperColor: "#d32f2f",
      lowerPoints: [{ timestamp: new Date(T).toISOString(), value: 10 }],
      upperPoints: [{ timestamp: new Date(T).toISOString(), value: 50 }],
      startTimeIso: new Date(T).toISOString(), endTimeIso: new Date(T + 3 * D).toISOString(),
    });
    const option = buildTimeSeriesChartOption({ chart, equipment: "RB1", start: new Date(T), end: new Date(T + 3 * D), mode: "recorded", normLimitSeries: [limits] });
    expect((option.series as any[]).some(series => String(series.id).startsWith("norm-"))).toBe(false);
    expect((option.yAxis as any[])[0]).toMatchObject({ min: 0, max: 100 });
  });
});
