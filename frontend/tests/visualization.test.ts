import { describe, expect, it } from "vitest";

import {
  buildChartData,
  buildChartDataGroups,
  applyLineAssignments,
  resolveVisualization,
} from "../src/utils/chartData";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { buildBoxPlot, buildHistogram, numericValuesFromSeries } from "../src/utils/statistics";
import { buildTimeSeriesCsv, buildCsvFilename } from "../src/utils/csv";
import { formatNumericValue, isNumericValue, qualityFlags } from "../src/utils/values";
import {
  computePeriodRange,
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
  toUtcIsoString,
  isValidRange,
  getPresetOptions,
  type PeriodPreset,
} from "../src/utils/period";
import type { TimeSeries } from "../src/types";

describe("period utilities", () => {
  it("returns fixed range for preset P1D ending at now", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const range = computePeriodRange("P1D", now);
    expect(range.end.toISOString()).toBe("2026-07-15T12:00:00.000Z");
    expect(range.start.toISOString()).toBe("2026-07-14T12:00:00.000Z");
  });

  it("converts local datetime to UTC ISO", () => {
    const local = new Date(2026, 6, 15, 8, 0, 0);
    const utc = toUtcIsoString(local);
    expect(utc).toBe(new Date(local.getTime()).toISOString());
  });

  it("round-trips datetime-local values", () => {
    const date = new Date(2026, 6, 15, 8, 30);
    const text = toDatetimeLocalValue(date);
    expect(text).toBe("2026-07-15T08:30");
    const back = fromDatetimeLocalValue(text);
    expect(back?.getTime()).toBe(date.getTime());
  });

  it("validates ranges", () => {
    const a = new Date("2026-07-15T00:00:00Z");
    const b = new Date("2026-07-15T01:00:00Z");
    expect(isValidRange(a, b)).toBe(true);
    expect(isValidRange(b, a)).toBe(false);
  });

  it("exposes all presets", () => {
    const options = getPresetOptions();
    expect(options.map((o) => o.value)).toEqual<PeriodPreset[]>([
      "PT15M",
      "PT1H",
      "PT8H",
      "P1D",
      "P7D",
      "CUSTOM",
    ]);
  });
});

describe("value formatters", () => {
  it("formats numbers in pt-BR with up to 3 decimals", () => {
    expect(formatNumericValue(1.5)).toBe("1,5");
    expect(formatNumericValue(1234.5678)).toBe("1.234,568");
    expect(formatNumericValue(0)).toBe("0");
  });

  it("preserves strings and booleans", () => {
    expect(formatNumericValue("RUN")).toBe("RUN");
    expect(formatNumericValue(true)).toBe("true");
  });

  it("returns dash for nullish", () => {
    expect(formatNumericValue(null)).toBe("-");
    expect(formatNumericValue(undefined)).toBe("-");
  });

  it("detects numeric values", () => {
    expect(isNumericValue(1)).toBe(true);
    expect(isNumericValue(1.5)).toBe(true);
    expect(isNumericValue("1")).toBe(false);
    expect(isNumericValue(NaN)).toBe(false);
  });

  it("classifies quality flags", () => {
    expect(qualityFlags({ good: true })).toBe("OK");
    expect(qualityFlags({ good: false, substituted: true })).toBe("Substituido");
    expect(qualityFlags({ good: false, questionable: true })).toBe("Questionavel");
    expect(qualityFlags({ good: false })).toBe("Ruim");
  });
});

const sampleTimeSeries: TimeSeries = {
  start_time: "2026-07-15T00:00:00Z",
  end_time: "2026-07-15T01:00:00Z",
  mode: "recorded",
  series: [
    {
      tag_id: 1,
      tag_name: "RB3.TEMP",
      display_name: "Temperatura",
      equipment: "RB3",
      section: "ENTRADA",
      variable_type: "TEMPERATURE",
      unit: "C",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 1.5, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: "RUN", good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:02:00Z", value: 2.5, good: false, questionable: true, substituted: false },
        { timestamp: "2026-07-15T00:03:00Z", value: null, good: false, questionable: true, substituted: false },
        { timestamp: "2026-07-15T00:04:00Z", value: 3.5, good: true, questionable: false, substituted: false },
      ],
    },
    {
      tag_id: 2,
      tag_name: "RB3.PRESS",
      display_name: "Pressao",
      equipment: "RB3",
      section: "ENTRADA",
      variable_type: "PRESSURE",
      unit: "bar",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 10.1, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: 10.3, good: true, questionable: false, substituted: false },
      ],
    },
  ],
  errors: [],
};

describe("chart data builder", () => {
  it("sums internal points across three independent series", () => {
    const thirdSeries = {
      ...sampleTimeSeries.series[1],
      tag_id: 3,
      tag_name: "RB3.STATE",
      display_name: "Estado",
      unit: null,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: true, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:02:00Z", value: null, good: true, questionable: false, substituted: false },
      ],
    };
    const chart = buildChartData(
      { ...sampleTimeSeries, series: [...sampleTimeSeries.series, thirdSeries] },
      { ignoreBadQuality: false },
    );

    expect(chart.totalSeries).toBe(3);
    expect(chart.totalPoints).toBe(10);
    expect(chart.totalNumericPoints).toBe(5);
    expect(chart.totalNonNumericPoints).toBe(3);
    expect(chart.series.map((series) => series.tagId)).toEqual([1, 2, 3]);
    expect(chart.series.map((series) => series.total)).toEqual([5, 2, 3]);
  });

  it("applies explicit primary and secondary axes without mutating source data", () => {
    const chart = buildChartData({ ...sampleTimeSeries, series: [sampleTimeSeries.series[0], sampleTimeSeries.series[1]] }, { ignoreBadQuality: false });
    const assigned = applyLineAssignments(chart, [
      { tagId: 1, order: 1, lineAxis: "secondary", scatterRole: "none" },
      { tagId: 2, order: 0, lineAxis: "primary", scatterRole: "none" },
    ]);
    expect(assigned?.series.map((series) => series.tagId)).toEqual([2, 1]);
    expect(assigned?.series.map((series) => series.yAxisIndex)).toEqual([0, 1]);
    expect(assigned?.yAxisLabels).toEqual(["bar", "C"]);
    expect(chart.series.map((series) => series.tagId)).toEqual([1, 2]);
  });

  it("separates numeric from non-numeric values", () => {
    const chart = buildChartData(sampleTimeSeries, { ignoreBadQuality: false });
    const temp = chart.series.find((s) => s.tagId === 1);
    expect(temp).toBeTruthy();
    expect(temp?.numeric).toBe(3);
    expect(temp?.nonNumeric).toBe(1); // "RUN"; null is absence
    expect(temp?.points.find((p) => Number.isFinite(p[1] as number))).toBeTruthy();
    expect(chart.valueKind).toBe("mixed");
  });

  it("drops bad quality when ignoreBadQuality is true", () => {
    const chart = buildChartData(sampleTimeSeries, { ignoreBadQuality: true });
    const temp = chart.series.find((s) => s.tagId === 1);
    expect(temp?.dropped).toBe(2); // 2.5 (questionable) + null (bad quality)
    expect(temp?.numeric).toBe(2); // remaining two good points
  });

  it("produces one y-axis label per distinct unit", () => {
    const chart = buildChartData(sampleTimeSeries, { ignoreBadQuality: false });
    // Labels preserve the original casing as received from the catalog.
    expect(chart.yAxisLabels).toEqual(["C", "bar"]);
  });

  it("keeps yAxisIndex consistent with unit slot", () => {
    const chart = buildChartData(sampleTimeSeries, { ignoreBadQuality: false });
    const temp = chart.series.find((s) => s.tagId === 1);
    const press = chart.series.find((s) => s.tagId === 2);
    expect(temp?.yAxisIndex).toBe(0);
    expect(press?.yAxisIndex).toBe(1);
  });

  it("ignores timestamps that cannot be parsed", () => {
    const ts: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "not-a-date", value: 1.0, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:00:00Z", value: 2.0, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };
    const chart = buildChartData(ts, { ignoreBadQuality: false });
    expect(chart.totalPoints).toBe(1);
  });

  it("keeps an exclusively numeric series on the existing numeric path", () => {
    const numeric: TimeSeries = {
      ...sampleTimeSeries,
      series: [{ ...sampleTimeSeries.series[1] }],
    };

    const chart = buildChartData(numeric, { ignoreBadQuality: false });

    expect(chart.valueKind).toBe("numeric");
    expect(chart.series[0].valueKind).toBe("numeric");
    expect(chart.series[0].points).toEqual([
      [Date.parse("2026-07-15T00:00:00Z"), 10.1],
      [Date.parse("2026-07-15T00:01:00Z"), 10.3],
    ]);
  });

  it("builds textual states without coercing numeric-looking strings", () => {
    const textual: TimeSeries = {
      ...sampleTimeSeries,
      end_time: "2026-07-15T00:10:00Z",
      series: [
        {
          ...sampleTimeSeries.series[0],
          unit: null,
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "P304I", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: "P304I", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:02:00Z", value: "P316B", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:03:00Z", value: "600", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:04:00Z", value: "500.5", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:05:00Z", value: true, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:06:00Z", value: null, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const chart = buildChartData(textual, { ignoreBadQuality: false });
    const value = chart.series[0].stateValues[2];

    expect(chart.valueKind).toBe("textual");
    expect(chart.categories).toEqual(["P304I", "P316B", "600", "500.5", "true"]);
    expect(value).toBe("600");
    expect(typeof value).toBe("string");
    expect(chart.series[0].stateValues).not.toContain("null");
    expect(chart.series[0].statePoints).toHaveLength(6); // 5 changes + end of period
    expect(chart.series[0].statePoints[chart.series[0].statePoints.length - 1]?.[0]).toBe(
      Date.parse(textual.end_time),
    );
    expect(chart.series[0].stateValues[chart.series[0].stateValues.length - 1]).toBe("true");
  });

  it("keeps categories in first-occurrence order and compacts repeated states", () => {
    const textual: TimeSeries = {
      ...sampleTimeSeries,
      end_time: "2026-07-15T00:03:00Z",
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "B", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: "B", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:02:00Z", value: "A", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const chart = buildChartData(textual, { ignoreBadQuality: false });

    expect(chart.categories).toEqual(["B", "A"]);
    expect(chart.series[0].stateValues).toEqual(["B", "A", "A"]);
  });

  it("keeps filtered timestamps as gaps in textual state charts", () => {
    const textual: TimeSeries = {
      ...sampleTimeSeries,
      end_time: "2026-07-15T00:03:00Z",
      series: [{
        ...sampleTimeSeries.series[0],
        points: [
          { timestamp: "2026-07-15T00:00:00Z", value: "A", good: true, questionable: false, substituted: false },
          { timestamp: "2026-07-15T00:01:00Z", value: null, filtered_out: true, good: true, questionable: false, substituted: false },
          { timestamp: "2026-07-15T00:02:00Z", value: "B", good: true, questionable: false, substituted: false },
        ],
      }],
    };

    const chart = buildChartData(textual, { ignoreBadQuality: false });

    expect(chart.series[0].statePoints).toContainEqual([Date.parse("2026-07-15T00:01:00Z"), null]);
  });

  it("applies the bad-quality filter to states and counts discarded points", () => {
    const textual: TimeSeries = {
      ...sampleTimeSeries,
      end_time: "2026-07-15T00:03:00Z",
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "RUN", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: "BAD", good: false, questionable: true, substituted: false },
            { timestamp: "2026-07-15T00:02:00Z", value: "STOP", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const filtered = buildChartData(textual, { ignoreBadQuality: true });
    const unfiltered = buildChartData(textual, { ignoreBadQuality: false });

    expect(filtered.totalDroppedPoints).toBe(1);
    expect(filtered.series[0].dropped).toBe(1);
    expect(filtered.categories).toEqual(["RUN", "STOP"]);
    expect(filtered.series[0].stateValues[0]).toBe("RUN");
    expect(unfiltered.totalDroppedPoints).toBe(0);
    expect(unfiltered.categories).toEqual(["RUN", "BAD", "STOP"]);
  });

  it("identifies mixed number and text payloads without coercion", () => {
    const mixed = buildChartData(sampleTimeSeries, { ignoreBadQuality: false });
    const state = mixed.series[0].stateValues[0];

    expect(mixed.valueKind).toBe("mixed");
    expect(mixed.series[0].points[0][1]).toBe(1.5);
    expect(state).toBe("RUN");
    expect(typeof state).toBe("string");
  });

  it("separates numeric and textual tags into independent chart groups", () => {
    const numericSeries = { ...sampleTimeSeries.series[1] };
    const textualSeries = {
      ...sampleTimeSeries.series[0],
      tag_id: 3,
      tag_name: "RB3.STATE",
      display_name: "Estado",
      unit: null,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: "P304I", good: true, questionable: false, substituted: false },
      ],
    };
    const groups = buildChartDataGroups(
      { ...sampleTimeSeries, series: [numericSeries, textualSeries] },
      { ignoreBadQuality: false },
    );
    const state = groups.textual[0].series[0].stateValues[0];

    expect(groups.summary.valueKind).toBe("mixed");
    expect(groups.numeric?.series.map((series) => series.tagId)).toEqual([2]);
    expect(groups.textual).toHaveLength(1);
    expect(groups.textual[0].series.map((series) => series.tagId)).toEqual([3]);
    expect(groups.mixedSeries).toHaveLength(0);
    expect(state).toBe("600");
    expect(typeof state).toBe("string");
  });

  it("keeps multiple numeric tags in the same numeric chart", () => {
    const secondNumeric = {
      ...sampleTimeSeries.series[1],
      tag_id: 4,
      tag_name: "RB3.SPEED",
      display_name: "Velocidade",
      unit: "m/s",
    };

    const groups = buildChartDataGroups(
      { ...sampleTimeSeries, series: [sampleTimeSeries.series[1], secondNumeric] },
      { ignoreBadQuality: false },
    );

    expect(groups.numeric?.series.map((series) => series.tagId)).toEqual([2, 4]);
    expect(groups.textual).toHaveLength(0);
  });

  it("keeps textual tags separate so the page can enforce one state chart", () => {
    const firstTextual = {
      ...sampleTimeSeries.series[0],
      tag_id: 5,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "RUN", good: true, questionable: false, substituted: false },
      ],
    };
    const secondTextual = {
      ...firstTextual,
      tag_id: 6,
      tag_name: "RB3.MODE",
      display_name: "Modo",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "AUTO", good: true, questionable: false, substituted: false },
      ],
    };

    const groups = buildChartDataGroups(
      { ...sampleTimeSeries, series: [sampleTimeSeries.series[1], firstTextual, secondTextual] },
      { ignoreBadQuality: false },
    );

    expect(groups.numeric?.series.map((series) => series.tagId)).toEqual([2]);
    expect(groups.textual).toHaveLength(2);
    expect(groups.textual[0].series).toHaveLength(1);
    expect(groups.textual[1].series).toHaveLength(1);
  });

  it("excludes an individually mixed tag without blocking valid tags", () => {
    const groups = buildChartDataGroups(sampleTimeSeries, { ignoreBadQuality: false });

    expect(groups.mixedSeries.map((series) => series.tagName)).toEqual(["RB3.TEMP"]);
    expect(groups.numeric?.series.map((series) => series.tagName)).toEqual(["RB3.PRESS"]);
    expect(groups.textual).toHaveLength(0);
  });

  it("applies quality filtering per group while preserving global counters", () => {
    const numericSeries = {
      ...sampleTimeSeries.series[1],
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: 11, good: false, questionable: true, substituted: false },
      ],
    };
    const textualSeries = {
      ...sampleTimeSeries.series[0],
      tag_id: 7,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "RUN", good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: "STOP", good: false, questionable: true, substituted: false },
      ],
    };

    const groups = buildChartDataGroups(
      { ...sampleTimeSeries, series: [numericSeries, textualSeries] },
      { ignoreBadQuality: true },
    );

    expect(groups.summary.totalSeries).toBe(2);
    expect(groups.summary.totalPoints).toBe(4);
    expect(groups.summary.totalNumericPoints).toBe(1);
    expect(groups.summary.totalNonNumericPoints).toBe(1);
    expect(groups.summary.totalDroppedPoints).toBe(2);
    expect(groups.numeric?.series[0].dropped).toBe(1);
    expect(groups.textual[0].series[0].dropped).toBe(1);
    expect(groups.textual[0].categories).toEqual(["RUN"]);
  });

  it("classifies a numeric series after discarding a bad textual value", () => {
    const numericWithBadText: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-16T10:00:00Z", value: 750, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:01:00Z", value: "Shutdown", good: false, questionable: true, substituted: false },
            { timestamp: "2026-07-16T10:02:00Z", value: 752, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const groups = buildChartDataGroups(numericWithBadText, { ignoreBadQuality: true });
    const series = groups.summary.series[0];

    expect(series.valueKind).toBe("numeric");
    expect(series.numeric).toBe(2);
    expect(series.dropped).toBe(1);
    expect(series.nonNumeric).toBe(0);
    expect(groups.summary.totalPoints).toBe(3);
    expect(groups.summary.totalNumericPoints).toBe(2);
    expect(groups.summary.totalNonNumericPoints).toBe(0);
    expect(groups.summary.totalDroppedPoints).toBe(1);
    expect(groups.numeric?.series).toHaveLength(1);
    expect(groups.mixedSeries).toHaveLength(0);
  });

  it("classifies a textual series after discarding a bad numeric value", () => {
    const textualWithBadNumber: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-16T10:00:00Z", value: "P304I", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:01:00Z", value: 500, good: false, questionable: true, substituted: false },
            { timestamp: "2026-07-16T10:02:00Z", value: "P316B", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:03:00Z", value: null, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:04:00Z", value: "600", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const groups = buildChartDataGroups(textualWithBadNumber, { ignoreBadQuality: true });
    const series = groups.summary.series[0];
    const numericString = groups.textual[0].series[0].stateValues[2];

    expect(series.valueKind).toBe("textual");
    expect(series.numeric).toBe(0);
    expect(series.nonNumeric).toBe(3);
    expect(series.dropped).toBe(1);
    expect(groups.textual[0].categories).toEqual(["P304I", "P316B", "600"]);
    expect(groups.mixedSeries).toHaveLength(0);
    expect(numericString).toBe("600");
    expect(typeof numericString).toBe("string");
  });

  it("keeps a series mixed when valid numeric and textual values remain", () => {
    const trulyMixed: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-16T10:00:00Z", value: 700, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:01:00Z", value: "Manual", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const groups = buildChartDataGroups(trulyMixed, { ignoreBadQuality: true });

    expect(groups.summary.series[0].valueKind).toBe("mixed");
    expect(groups.mixedSeries).toHaveLength(1);
    expect(groups.numeric).toBeNull();
    expect(groups.textual).toHaveLength(0);
  });

  it("handles the real 1997 numeric plus 3 discarded textual case", () => {
    const baseTime = Date.parse("2026-07-01T00:00:00Z");
    const points = Array.from({ length: 2000 }, (_, index) => ({
      timestamp: new Date(baseTime + index * 60_000).toISOString(),
      value: index < 1997 ? 700 + index / 10 : `Bad state ${index}`,
      good: index < 1997,
      questionable: index >= 1997,
      substituted: false,
    }));
    const realCase: TimeSeries = {
      ...sampleTimeSeries,
      series: [{ ...sampleTimeSeries.series[0], points }],
    };

    const groups = buildChartDataGroups(realCase, { ignoreBadQuality: true });
    const series = groups.summary.series[0];

    expect(series.valueKind).toBe("numeric");
    expect(series.total).toBe(2000);
    expect(series.numeric).toBe(1997);
    expect(series.dropped).toBe(3);
    expect(series.nonNumeric).toBe(0);
    expect(groups.summary.totalPoints).toBe(2000);
    expect(groups.summary.totalNumericPoints).toBe(1997);
    expect(groups.summary.totalDroppedPoints).toBe(3);
    expect(groups.summary.totalNonNumericPoints).toBe(0);
    expect(groups.numeric?.series).toHaveLength(1);
    expect(groups.mixedSeries).toHaveLength(0);
  });

  it("resolves automatic, line and states without changing the summary", () => {
    const numericSeries = {
      ...sampleTimeSeries.series[0],
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
      ],
    };
    const textualSeries = {
      ...sampleTimeSeries.series[0],
      tag_id: 2,
      tag_name: "RB3.STATE",
      display_name: "Estado",
      unit: null,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
      ],
    };
    const groups = buildChartDataGroups(
      { ...sampleTimeSeries, series: [numericSeries, textualSeries] },
      { ignoreBadQuality: true },
    );

    const automatic = resolveVisualization(groups, "automatic");
    expect(automatic.numeric?.series).toHaveLength(1);
    expect(automatic.textual?.series[0].stateValues[0]).toBe("600");
    expect(typeof automatic.textual?.series[0].stateValues[0]).toBe("string");
    expect(automatic.incompatibleSeries).toHaveLength(0);

    const line = resolveVisualization(groups, "line");
    expect(line.numeric?.series).toHaveLength(1);
    expect(line.textual).toBeNull();
    expect(line.incompatibleSeries.map((series) => series.displayName)).toEqual(["Estado"]);

    for (const type of ["histogram", "boxplot", "scatter", "bars"] as const) {
      const statistical = resolveVisualization(groups, type);
      expect(statistical.numeric?.series).toHaveLength(1);
      expect(statistical.textual).toBeNull();
      expect(statistical.incompatibleSeries.map((series) => series.displayName)).toEqual([
        "Estado",
      ]);
    }

    const singleValue = resolveVisualization(groups, "singleValue");
    expect(singleValue.numeric).toBeNull();
    expect(singleValue.textual).toBeNull();
    expect(singleValue.incompatibleSeries).toEqual([]);
    expect(singleValue.excessTextualSeries).toEqual([]);

    const states = resolveVisualization(groups, "states");
    expect(states.numeric).toBeNull();
    expect(states.textual?.series[0].displayName).toBe("Estado");
    expect(states.incompatibleSeries.map((series) => series.displayName)).toEqual([
      numericSeries.display_name,
    ]);
    expect(groups.summary.totalSeries).toBe(2);
  });

  it("identifies excess textual series for automatic and states", () => {
    const textual = {
      ...sampleTimeSeries.series[0],
      unit: null,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "RUN", good: true, questionable: false, substituted: false },
      ],
    };
    const groups = buildChartDataGroups(
      {
        ...sampleTimeSeries,
        series: [
          { ...textual, tag_id: 2, display_name: "Estado" },
          { ...textual, tag_id: 3, display_name: "Modo" },
        ],
      },
      { ignoreBadQuality: true },
    );

    const automatic = resolveVisualization(groups, "automatic");
    expect(automatic.textual).toBeNull();
    expect(automatic.excessTextualSeries.map((series) => series.displayName)).toEqual([
      "Estado",
      "Modo",
    ]);

    const states = resolveVisualization(groups, "states");
    expect(states.textual?.series[0].displayName).toBe("Estado");
    expect(states.excessTextualSeries.map((series) => series.displayName)).toEqual(["Modo"]);
  });

  it("uses quality-filtered finite numbers for histogram and boxplot statistics", () => {
    const input: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: 100, good: false, questionable: true, substituted: false },
            { timestamp: "2026-07-15T00:02:00Z", value: 20, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };
    const groups = buildChartDataGroups(input, { ignoreBadQuality: true });
    const series = groups.numeric?.series[0];
    expect(series).toBeDefined();
    const values = numericValuesFromSeries(series!);
    expect(values).toEqual([10, 20]);
    expect(buildHistogram(values).count).toBe(2);
    expect(buildBoxPlot(values)?.count).toBe(2);
    expect(groups.summary.totalDroppedPoints).toBe(1);
  });

  it("configures a categorical step chart for textual states", () => {
    const textual: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };
    const chart = buildChartData(textual, { ignoreBadQuality: false });

    const option = buildTimeSeriesChartOption({
      chart,
      equipment: "RB3",
      start: new Date(textual.start_time),
      end: new Date(textual.end_time),
      mode: "recorded",
    });
    const renderedSeries = option.series as Array<{ step?: string }>;
    const yAxis = option.yAxis as { type?: string; data?: string[] };

    expect(renderedSeries[0].step).toBe("end");
    expect(yAxis.type).toBe("category");
    expect(yAxis.data).toEqual(["600"]);
  });

  it("keeps the numeric chart configuration as a normal value-axis line", () => {
    const numeric: TimeSeries = {
      ...sampleTimeSeries,
      series: [{ ...sampleTimeSeries.series[1] }],
    };
    const chart = buildChartData(numeric, { ignoreBadQuality: false });

    const option = buildTimeSeriesChartOption({
      chart,
      equipment: "RB3",
      start: new Date(numeric.start_time),
      end: new Date(numeric.end_time),
      mode: "recorded",
    });
    const renderedSeries = option.series as Array<{ step?: string; type?: string }>;
    const yAxis = option.yAxis as Array<{ type?: string }>;

    expect(renderedSeries[0].type).toBe("line");
    expect(renderedSeries[0].step).toBeUndefined();
    expect(yAxis[0].type).toBe("value");
  });
});

describe("CSV exporter", () => {
  it("emits the expected header and rows in long format", () => {
    const csv = buildTimeSeriesCsv(sampleTimeSeries);
    const lines = csv.replace(/^\ufeff/, "").split(/\r\n/).filter(Boolean);
    expect(lines[0]).toBe(
      "timestamp_utc;timestamp_local;tag_id;tag_name;display_name;equipment;section;variable_type;unit;value;value_type;good;questionable;substituted",
    );
    // 5 points + 2 points = 7 rows after header
    expect(lines).toHaveLength(8);
    // Contains string "RUN" properly preserved
    expect(csv).toContain("RUN");
    expect(csv).toContain("RB3.TEMP");
  });

  it("escapes values containing the separator, quotes, or newlines", () => {
    const ts: TimeSeries = {
      ...sampleTimeSeries,
      series: [
        {
          ...sampleTimeSeries.series[0],
          points: [
            {
              timestamp: "2026-07-15T00:00:00Z",
              value: 'has; "quote" and\nnewline',
              good: true,
              questionable: false,
              substituted: false,
            },
          ],
        },
      ],
    };
    const csv = buildTimeSeriesCsv(ts);
    expect(csv).toContain('"has; ""quote"" and\nnewline"');
  });

  it("includes UTF-8 BOM", () => {
    const csv = buildTimeSeriesCsv(sampleTimeSeries);
    expect(csv.charCodeAt(0)).toBe(0xfeff);
  });

  it("builds safe filenames", () => {
    const filename = buildCsvFilename(sampleTimeSeries, "fallback");
    expect(filename).toMatch(/^pi-analytics-data_RB3_\d{8}_\d{6}\.csv$/);
  });
});
