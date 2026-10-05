import { describe, expect, it } from "vitest";
import type { LineSeriesOption } from "echarts";
import { buildProductionUnitTimeSeries, findProductionUnitSegment, productionUnitTooltip } from "../src/utils/productionUnitChart";
import { buildChartData, buildChartDataGroups } from "../src/utils/chartData";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { unitResponse, unitVariable, UNIT_START as T, UNIT_DURATION as D } from "./fixtures/productionUnits";
import type { ProductionUnitRule } from "../src/types";

function chart(rule: ProductionUnitRule = "MEDIA", response = unitResponse(), ids = [20]) {
  return buildChartData(buildProductionUnitTimeSeries(response, rule, ids), { ignoreBadQuality: false });
}

describe("Backend aggregates rendered by production unit", () => {
  it("resolves tooltip from the real hover time rather than the nearest ECharts boundary", () => {
    const data = chart();
    const option = buildTimeSeriesChartOption({ chart: data, equipment: "RB1", start: new Date(T), end: new Date(T + 3 * D), mode: "recorded" }, () => T + D - 1);
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const tooltip = formatter([{ axisValue: T + D, seriesId: "tag:20", value: [T + D, null] }]);
    expect(tooltip).toContain("600304J2000B");
    expect(tooltip).toContain("28,4199002965");
    expect(tooltip).not.toContain("BOB L2");
  });
  it.each([
    ["MEDIA", 28.4199002965, "Média"], ["MIN", 25.003582, "Mínimo"], ["MAXIMO", 31.1618557, "Máximo"],
  ] as const)("%s renders the backend statistic horizontally and identifies its tooltip", (rule, value, label) => {
    const data = chart(rule);
    expect(data.series[0].points.slice(0, 2)).toEqual([[T, value], [T + D, value]]);
    const option = buildTimeSeriesChartOption({ chart: data, equipment: "RB1", start: new Date(T), end: new Date(T + 3 * D), mode: "recorded" });
    const line = (option.series as LineSeriesOption[])[0];
    expect(line.step).toBe("end");
    expect(line.connectNulls).toBe(false);
    expect(line.sampling).toBeUndefined();
    expect(line.showSymbol).toBe(false);
    expect(line.data).toEqual(data.series[0].points);
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const tooltip = formatter([{ axisValue: T + 60_000, seriesId: "tag:20", seriesName: "Velocidade", value: [T, value] }]);
    expect(tooltip).toContain(`${label} da UM`);
    expect(tooltip).toContain("600304J2000B");
    expect(tooltip).toContain("Início:");
    expect(tooltip).toContain("Fim:");
    expect(tooltip).toContain("m/min");
    expect(tooltip).toContain("Amostras brutas: 2845");
    expect(tooltip).toContain("Após filtros: 1329");
    expect(tooltip).toContain("Amostras válidas: 1329");
    expect(tooltip).not.toMatch(/amostra:|último estado RECORDED|derivado entre eventos/);
  });

  it("changes value at the exact transition between two UMs", () => {
    const response = unitResponse();
    response.segments = response.segments.slice(0, 2);
    response.segments[0].variables[0].average = 20;
    response.segments[1].variables[0].average = 30;
    const series = chart("MEDIA", response).series[0];
    expect(series.points).toEqual([[T, 20], [T + D, 20], [T + D, 30], [T + 2 * D, 30]]);
    expect(findProductionUnitSegment(series.unitAggregation!.segments, T + D - 1)?.value).toBe(20);
    expect(findProductionUnitSegment(series.unitAggregation!.segments, T + D)?.value).toBe(30);
    expect(findProductionUnitSegment(series.unitAggregation!.segments, T + 2 * D)).toBeNull();
  });

  it("renders three consecutive UMs with exact horizontal boundaries", () => {
    const response = unitResponse();
    response.segments.forEach((s, i) => { s.variables[0].average = i + 1; });
    expect(chart("MEDIA", response).series[0].points).toEqual([
      [T, 1], [T + D, 1], [T + D, 2], [T + 2 * D, 2], [T + 2 * D, 3], [T + 3 * D, 3],
    ]);
  });

  it("preserves an empty filtered UM as a gap, including its counts/context", () => {
    const series = chart().series[0];
    expect(series.points).toEqual([[T, 28.4199002965], [T + D, 28.4199002965], [T + D, null], [T + 2 * D, null], [T + 2 * D, 31.0622640703], [T + 3 * D, 31.0622640703]]);
    expect(findProductionUnitSegment(series.unitAggregation!.segments, T + D + 1)?.value).toBeNull();
    const tooltip = productionUnitTooltip(series.unitAggregation!, T + D + 1, "Velocidade", "m/min");
    expect(tooltip).toContain("sem amostras válidas");
    expect(tooltip).toContain("Amostras brutas: 1743");
    expect(tooltip).toContain("Após filtros: 0");
    expect(tooltip).toContain("Amostras válidas: 0");
  });

  it.each([0, -28.5])("preserves legitimate aggregate %s", (value) => {
    const response = unitResponse([unitVariable({ average: value })]);
    const series = chart("MEDIA", response).series[0];
    expect(series.points.slice(0, 2)).toEqual([[T, value], [T + D, value]]);
    expect(findProductionUnitSegment(series.unitAggregation!.segments, T + 1)?.value).toBe(value);
  });

  it("keeps all-null numeric variables available as empty series", () => {
    const response = unitResponse([unitVariable({ average: null, sample_count: 0 })]);
    response.segments.forEach((s) => { s.variables[0].average = null; });
    const groups = buildChartDataGroups(buildProductionUnitTimeSeries(response, "MEDIA", [20]), { ignoreBadQuality: false });
    expect(groups.numeric?.series).toHaveLength(1);
    expect(groups.numeric?.series[0].points.every(([, value]) => value === null)).toBe(true);
  });

  it("renders multiple selected numeric tags, excludes UM and auxiliary filter tags", () => {
    const response = unitResponse([
      unitVariable(), unitVariable({ tag_id: 21, display_name: "Temperatura", average: 1120, unit: "°C" }),
      unitVariable({ tag_id: 22, display_name: "Pressão", average: 5.2, unit: "bar" }),
      unitVariable({ tag_id: 30, display_name: "Largura", average: 1300 }),
      unitVariable({ tag_id: 29, display_name: "UM", data_type: "NUMERIC", average: 600 }),
    ]);
    const data = chart("MEDIA", response, [20, 21, 22, 29]);
    expect(data.series.map((s) => s.tagId)).toEqual([20, 21, 22]);
    expect(data.series.map((s) => s.points.slice(0, 2))).toEqual([
      [[T, 28.4199002965], [T + D, 28.4199002965]], [[T, 1120], [T + D, 1120]], [[T, 5.2], [T + D, 5.2]],
    ]);
  });

  it("uses the filtered backend value without recomputing counts or mutating the response", () => {
    const response = unitResponse();
    const original = JSON.stringify(response);
    expect(chart("MEDIA", response).series[0].points[0][1]).toBe(28.4199002965);
    expect(JSON.stringify(response)).toBe(original);
  });

  it.each(["STRING", "DIGITAL"])("does not fabricate numeric aggregates for %s", (dataType) => {
    expect(chart("MEDIA", unitResponse([unitVariable({ data_type: dataType, first_value: "ON", last_value: "OFF" })])).series).toEqual([]);
  });

  it.each(["DEFAULT"] as const)("does not silently map unsupported rule %s to mean", (rule) => {
    expect(buildProductionUnitTimeSeries(unitResponse(), rule, [20]).series).toEqual([]);
  });

  it("clips zoom to two UMs while retaining original intervals, counts and aggregate values", () => {
    const response = unitResponse();
    const zoom = { start: new Date(T + D / 2), end: new Date(T + 3 * D / 2) };
    const series = buildProductionUnitTimeSeries(response, "MEDIA", [20], zoom);
    expect(series.series[0].points.map((p) => [Date.parse(p.timestamp), p.value])).toEqual([
      [T + D / 2, 28.4199002965], [T + D, 28.4199002965], [T + D, null], [T + 3 * D / 2, null],
    ]);
    expect(series.query_execution?.production_unit_segment_count).toBe(2);
    expect(series.series[0].unit_aggregation?.segments[0].start).toBe(T);
    expect(series.query_execution?.points_returned).toBeUndefined();
    expect(series.query_execution?.strategy).toBe("production_unit_aggregation");
  });

  it("keeps the marker constant anywhere within an UM and respects its exclusive end", () => {
    const segments = chart().series[0].unitAggregation!.segments;
    for (const ts of [T, T + 60_000, T + 120_000, T + D - 1]) expect(findProductionUnitSegment(segments, ts)?.value).toBe(28.4199002965);
    expect(findProductionUnitSegment(segments, T + D)?.value).toBeNull();
    expect(findProductionUnitSegment(segments, T - 1)).toBeNull();
    expect(findProductionUnitSegment(segments, T + 3 * D)).toBeNull();
  });

  it("does not bridge missing intervals even if the endpoint segments are discontinuous", () => {
    const response = unitResponse();
    response.segments.splice(1, 1);
    expect(chart("MEDIA", response).series[0].points.slice(2, 4)).toEqual([[T + D, null], [T + 2 * D, null]]);
  });

  it("escapes UM/variable/unit content in HTML tooltips", () => {
    const response = unitResponse();
    response.segments[0].um_value = "<script>bad</script>";
    const tip = productionUnitTooltip(chart("MEDIA", response).series[0].unitAggregation!, T + 1, "<b>Velocidade</b>", "<unit>");
    expect(tip).toContain("&lt;script&gt;");
    expect(tip).not.toContain("<script>");
    expect(tip).toContain("&lt;b&gt;Velocidade&lt;/b&gt;");
  });
});
