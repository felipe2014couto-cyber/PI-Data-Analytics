import { describe, expect, it } from "vitest";

import {
  buildBoxPlot,
  buildHistogram,
  finiteNumbers,
  groupSeriesByUnit,
} from "../src/utils/statistics";
import { buildHistogramChartOption } from "../src/components/HistogramChart";
import { buildBoxPlotChartOption } from "../src/components/BoxPlotChart";
import type { ChartSeries } from "../src/utils/chartData";

function chartSeries(
  values: Array<number | string | boolean | null>,
  overrides: Partial<ChartSeries> = {},
): ChartSeries {
  return {
    tagId: 1,
    displayName: "Temperatura",
    tagName: "RB3.TEMP",
    equipment: "RB3",
    section: "ENTRADA",
    variableType: "TEMPERATURE",
    unit: "°C",
    yAxisIndex: 0,
    color: "#1976d2",
    total: values.length,
    numeric: values.filter((value) => typeof value === "number" && Number.isFinite(value)).length,
    dropped: 0,
    nonNumeric: 0,
    points: values.map((value, index) => [index, typeof value === "number" ? value : null]),
    qualitySeries: [],
    valueKind: "numeric",
    statePoints: [],
    stateValues: [],
    stateQualitySeries: [],
    ...overrides,
  };
}

describe("histogram statistics", () => {
  it("uses ceil square root classes and preserves total frequency", () => {
    const result = buildHistogram(Array.from({ length: 10 }, (_, index) => index + 1));
    expect(result.bins).toHaveLength(4);
    expect(result.bins.reduce((sum, bin) => sum + bin.frequency, 0)).toBe(10);
  });

  it("limits the histogram to 50 classes", () => {
    const result = buildHistogram(Array.from({ length: 10_000 }, (_, index) => index));
    expect(result.bins).toHaveLength(50);
  });

  it("creates one class for constant values and one observation", () => {
    expect(buildHistogram([7, 7, 7]).bins).toEqual([
      { lower: 7, upper: 7, frequency: 3, percentage: 100, includesUpper: true },
    ]);
    expect(buildHistogram([-2]).bins[0].frequency).toBe(1);
  });

  it("supports negative and decimal values and includes the maximum", () => {
    const result = buildHistogram([-2.5, -1.1, 0.2, 1.75]);
    expect(result.min).toBe(-2.5);
    expect(result.max).toBe(1.75);
    expect(result.bins[result.bins.length - 1]?.includesUpper).toBe(true);
    expect(result.bins.reduce((sum, bin) => sum + bin.frequency, 0)).toBe(4);
    expect(result.bins[result.bins.length - 1]?.frequency).toBeGreaterThan(0);
  });

  it("returns no classes for an empty numeric set", () => {
    expect(buildHistogram([])).toEqual({ count: 0, min: null, max: null, bins: [] });
  });

  it("excludes numeric strings, booleans, null and non-finite values", () => {
    expect(finiteNumbers([600, "600", "500.5", true, null, Infinity, -Infinity, NaN])).toEqual([
      600,
    ]);
  });

  it("builds a tooltip with interval, frequency and percentage", () => {
    const option = buildHistogramChartOption(chartSeries([1, 2, 3, 4]));
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const text = formatter([{ dataIndex: 0 }]);
    expect(text).toContain("Intervalo");
    expect(text).toContain("Frequência");
    expect(text).toContain("Percentual");
  });
});

describe("boxplot statistics", () => {
  it("calculates five-number statistics for [1, 2, 3, 4, 5]", () => {
    expect(buildBoxPlot([1, 2, 3, 4, 5])).toEqual({
      count: 5,
      lowerWhisker: 1,
      q1: 2,
      median: 3,
      q3: 4,
      upperWhisker: 5,
      outliers: [],
    });
  });

  it("uses linear interpolation for two and three observations", () => {
    expect(buildBoxPlot([1, 5])).toMatchObject({ q1: 2, median: 3, q3: 4 });
    expect(buildBoxPlot([1, 3, 9])).toMatchObject({ q1: 2, median: 3, q3: 6 });
  });

  it("separates outliers and uses observed inliers as whiskers", () => {
    expect(buildBoxPlot([1, 2, 3, 4, 100])).toEqual({
      count: 5,
      lowerWhisker: 1,
      q1: 2,
      median: 3,
      q3: 4,
      upperWhisker: 4,
      outliers: [100],
    });
  });

  it("supports constants, one observation and negative values", () => {
    expect(buildBoxPlot([4])).toEqual({
      count: 1,
      lowerWhisker: 4,
      q1: 4,
      median: 4,
      q3: 4,
      upperWhisker: 4,
      outliers: [],
    });
    expect(buildBoxPlot([2, 2, 2])?.outliers).toEqual([]);
    expect(buildBoxPlot([-5, -3, -1])?.median).toBe(-3);
  });

  it("returns null when no valid numeric value exists", () => {
    expect(buildBoxPlot([])).toBeNull();
    expect(buildBoxPlot(["600", true, null, Infinity])).toBeNull();
  });

  it("groups equal units together and separates distinct and missing units", () => {
    const groups = groupSeriesByUnit([
      chartSeries([1], { tagId: 1, unit: "°C" }),
      chartSeries([2], { tagId: 2, unit: "°C" }),
      chartSeries([3], { tagId: 3, unit: "bar" }),
      chartSeries([4], { tagId: 4, unit: null }),
    ]);
    expect(groups.map((group) => [group.unit, group.series.length])).toEqual([
      ["°C", 2],
      ["bar", 1],
      ["Sem unidade", 1],
    ]);
  });

  it("builds box and outlier series with complete tooltip", () => {
    const group = groupSeriesByUnit([chartSeries([1, 2, 3, 4, 100])])[0];
    const option = buildBoxPlotChartOption(group);
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const text = formatter({ seriesType: "boxplot", dataIndex: 0 });
    expect(text).toContain("Quantidade: 5");
    expect(text).toContain("Q1");
    expect(text).toContain("Mediana");
    expect(text).toContain("Outliers: 1");
    const series = option.series as Array<{ type: string; data: unknown[] }>;
    expect(series[1].type).toBe("scatter");
    expect(series[1].data).toEqual([[0, 100]]);
  });
});
