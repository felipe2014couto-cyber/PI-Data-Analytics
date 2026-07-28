import { describe, expect, it } from "vitest";

import type { TimeSeriesPoint, TimeSeriesSeries } from "../src/types";
import {
  alignSeriesByTimestamp,
  groupLatestValuesByUnit,
  latestNumericValue,
  numericObservations,
  pearsonCorrelation,
} from "../src/utils/comparison";
import { buildScatterPlotChartOption } from "../src/components/ScatterPlotChart";
import { buildLatestValuesBarChartOption } from "../src/components/LatestValuesBarChart";

const good = { good: true, questionable: false, substituted: false };

function point(timestamp: string, value: TimeSeriesPoint["value"], quality = good): TimeSeriesPoint {
  return { timestamp, value, ...quality };
}

function series(
  id: number,
  points: TimeSeriesPoint[],
  unit: string | null = "°C",
): TimeSeriesSeries {
  return {
    tag_id: id,
    tag_name: `TAG.${id}`,
    display_name: `Tag ${id}`,
    equipment: "RB3",
    section: "ENTRADA",
    variable_type: "PROCESS",
    unit,
    points,
  };
}

describe("scatter comparison", () => {
  it("pairs exactly equal normalized timestamps and orders pairs by time", () => {
    const x = series(1, [
      point("2026-07-17T10:02:00Z", 2),
      point("2026-07-17T10:00:00Z", 1),
      point("2026-07-17T10:01:00Z", 999),
    ]);
    const y = series(2, [
      point("2026-07-17T07:00:00-03:00", 10),
      point("2026-07-17T10:02:00+00:00", 20),
      point("2026-07-17T10:03:00Z", 30),
    ], "bar");
    const pairs = alignSeriesByTimestamp(x, y, true);
    expect(pairs.map((pair) => [pair.timestamp, pair.x.value, pair.y.value])).toEqual([
      [Date.parse("2026-07-17T10:00:00Z"), 1, 10],
      [Date.parse("2026-07-17T10:02:00Z"), 2, 20],
    ]);
  });

  it("does not pair by array index or noncoincident timestamps", () => {
    const pairs = alignSeriesByTimestamp(
      series(1, [point("2026-07-17T10:00:00Z", 1)]),
      series(2, [point("2026-07-17T10:00:01Z", 2)]),
      true,
    );
    expect(pairs).toEqual([]);
  });

  it("pairs repeated timestamps stably up to the available count", () => {
    const timestamp = "2026-07-17T10:00:00Z";
    const pairs = alignSeriesByTimestamp(
      series(1, [point(timestamp, 1), point(timestamp, 2), point(timestamp, 3)]),
      series(2, [point(timestamp, 10), point(timestamp, 20)]),
      true,
    );
    expect(pairs.map((pair) => [pair.x.value, pair.y.value])).toEqual([[1, 10], [2, 20]]);
  });

  it("filters bad quality and excludes strings, null, booleans and non-finite numbers", () => {
    const values = numericObservations(
      series(1, [
        point("2026-07-17T10:00:00Z", 1),
        point("2026-07-17T10:01:00Z", 2, { good: false, questionable: true, substituted: false }),
        point("2026-07-17T10:02:00Z", "600"),
        point("2026-07-17T10:03:00Z", null),
        point("2026-07-17T10:04:00Z", true),
        point("2026-07-17T10:05:00Z", Infinity),
        point("2026-07-17T10:06:00Z", NaN),
      ]),
      true,
    );
    expect(values.map((entry) => entry.value)).toEqual([1]);
  });

  it("calculates positive, negative and near-zero Pearson correlations", () => {
    const makePairs = (ys: number[]) => alignSeriesByTimestamp(
      series(1, [1, 2, 3].map((value, index) => point(`2026-07-17T10:0${index}:00Z`, value))),
      series(2, ys.map((value, index) => point(`2026-07-17T10:0${index}:00Z`, value))),
      true,
    );
    expect(pearsonCorrelation(makePairs([2, 4, 6]))).toBe(1);
    expect(pearsonCorrelation(makePairs([6, 4, 2]))).toBe(-1);
    expect(pearsonCorrelation(makePairs([1, 0, 1]))).toBeCloseTo(0, 12);
  });

  it("returns unavailable for insufficient pairs or zero variance without NaN", () => {
    const one = alignSeriesByTimestamp(
      series(1, [point("2026-07-17T10:00:00Z", 1)]),
      series(2, [point("2026-07-17T10:00:00Z", 2)]),
      true,
    );
    expect(pearsonCorrelation(one)).toBeNull();
    const constantX = alignSeriesByTimestamp(
      series(1, [point("2026-07-17T10:00:00Z", 1), point("2026-07-17T10:01:00Z", 1)]),
      series(2, [point("2026-07-17T10:00:00Z", 2), point("2026-07-17T10:01:00Z", 3)]),
      true,
    );
    expect(pearsonCorrelation(constantX)).toBeNull();
    expect(pearsonCorrelation(constantX.map((pair) => ({ ...pair, x: pair.y, y: pair.x })))).toBeNull();
  });

  it("builds numeric axes and a complete scatter tooltip", () => {
    const x = series(1, [point("2026-07-17T10:00:00Z", 1), point("2026-07-17T10:01:00Z", 2)]);
    const y = series(2, [point("2026-07-17T10:00:00Z", 10), point("2026-07-17T10:01:00Z", 20)], "bar");
    const option = buildScatterPlotChartOption(x, y, true);
    expect((option.xAxis as { type: string; name: string }).type).toBe("value");
    expect((option.xAxis as { name: string }).name).toContain("°C");
    expect((option.yAxis as { name: string }).name).toContain("bar");
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const text = formatter({ dataIndex: 0 });
    expect(text).toContain("TAG.1");
    expect(text).toContain("TAG.2");
    expect(text).toContain("Qualidade X");
    expect(text).toContain("Qualidade Y");
  });
});

describe("latest value bars", () => {
  it("chooses the valid value with the greatest timestamp from an unordered array", () => {
    const latest = latestNumericValue(series(1, [
      point("2026-07-17T10:03:00Z", 3),
      point("2026-07-17T10:01:00Z", 1),
      point("2026-07-17T10:02:00Z", 2),
    ]), true);
    expect(latest?.value).toBe(3);
  });

  it("falls back when the newest point is bad and excludes invalid types", () => {
    const latest = latestNumericValue(series(1, [
      point("2026-07-17T10:00:00Z", 5),
      point("2026-07-17T10:01:00Z", "600"),
      point("2026-07-17T10:02:00Z", null),
      point("2026-07-17T10:03:00Z", true),
      point("2026-07-17T10:04:00Z", Infinity),
      point("2026-07-17T10:05:00Z", 10, { good: false, questionable: true, substituted: false }),
    ]), true);
    expect(latest?.value).toBe(5);
  });

  it("creates one entry per valid series and groups engineering units", () => {
    const groups = groupLatestValuesByUnit([
      series(1, [point("2026-07-17T10:00:00Z", 1)], "°C"),
      series(2, [point("2026-07-17T10:00:00Z", 2)], "°C"),
      series(3, [point("2026-07-17T10:00:00Z", 3)], "bar"),
      series(4, [point("2026-07-17T10:00:00Z", 4)], null),
      series(5, [point("2026-07-17T10:00:00Z", "600")], "°C"),
    ], true);
    expect(groups.map((group) => [group.unit, group.entries.length])).toEqual([
      ["°C", 2],
      ["bar", 1],
      ["Sem unidade", 1],
    ]);
  });

  it("builds a tooltip with tag, value, unit, timestamp and quality", () => {
    const group = groupLatestValuesByUnit([
      series(1, [point("2026-07-17T10:00:00Z", 12)], "bar"),
    ], true)[0];
    const option = buildLatestValuesBarChartOption(group);
    const formatter = (option.tooltip as { formatter: (params: unknown) => string }).formatter;
    const text = formatter({ dataIndex: 0 });
    expect(text).toContain("TAG.1");
    expect(text).toContain("Valor: 12 bar");
    expect(text).toContain("Timestamp");
    expect(text).toContain("Qualidade: OK");
  });
});
