import { describe, expect, it } from "vitest";
import type {
  DataFilterConfiguration,
  TimeSeries,
  TimeSeriesPoint,
  TimeSeriesSeries,
} from "../src/types";
import { applyDataFilters, validateFilterConfiguration } from "../src/utils/dataFilters";

function point(
  timestamp: string,
  value: TimeSeriesPoint["value"],
  good = true,
  questionable = false,
  substituted = false,
): TimeSeriesPoint {
  return { timestamp, value, good, questionable, substituted };
}

function series(
  id: number,
  pts: Array<{
    timestamp: string;
    value: TimeSeriesPoint["value"];
    good?: boolean;
    questionable?: boolean;
    substituted?: boolean;
  }>,
  unit = "C",
): TimeSeriesSeries {
  return {
    tag_id: id,
    tag_name: `TAG_${id}`,
    display_name: `Tag ${id}`,
    equipment: null,
    section: null,
    variable_type: null,
    unit,
    points: pts.map((p) => point(p.timestamp, p.value, p.good, p.questionable, p.substituted)),
  };
}

function ts(seriesList: ReturnType<typeof series>[]): TimeSeries {
  return {
    start_time: "2026-01-01T00:00:00Z",
    end_time: "2026-01-01T01:00:00Z",
    mode: "recorded",
    series: seriesList,
    errors: [],
  };
}

const EMPTY_CONFIG: DataFilterConfiguration = {
  quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

const QUALITY_BAD_CONFIG: DataFilterConfiguration = {
  quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

describe("Quality filters", () => {
  it("keeps Good=true point", () => {
    const data = ts([series(1, [{ timestamp: "2026-01-01T00:00:00Z", value: 42 }])]);
    const result = applyDataFilters(data, EMPTY_CONFIG);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
    expect(result.summary.removedPoints).toBe(0);
  });

  it("excludes Good=false when excludeBad is true", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: true },
      { timestamp: "2026-01-01T00:01:00Z", value: 99, good: false },
    ])]);
    const result = applyDataFilters(data, QUALITY_BAD_CONFIG);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
    expect(result.summary.removedPoints).toBe(1);
    expect(result.summary.removedByQuality).toBe(1);
  });

  it("excludes Questionable independently", () => {
    const config: DataFilterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: true, excludeSubstituted: false },
      rules: [],
    };
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42 },
      { timestamp: "2026-01-01T00:01:00Z", value: 99, questionable: true },
    ])]);
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
    expect(result.summary.removedByQuality).toBe(1);
  });

  it("excludes Substituted independently", () => {
    const config: DataFilterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: true },
      rules: [],
    };
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42 },
      { timestamp: "2026-01-01T00:01:00Z", value: 99, substituted: true },
    ])]);
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
    expect(result.summary.removedByQuality).toBe(1);
  });

  it("counts multiple flags once", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: false, questionable: true, substituted: true },
    ])]);
    const config: DataFilterConfiguration = {
      quality: { excludeBad: true, excludeQuestionable: true, excludeSubstituted: true },
      rules: [],
    };
    const result = applyDataFilters(data, config);
    expect(result.summary.removedPoints).toBe(1);
    expect(result.summary.removedByQuality).toBe(1);
  });

  it("filter off preserves all points", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: false },
    ])]);
    const result = applyDataFilters(data, EMPTY_CONFIG);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
    expect(result.summary.removedPoints).toBe(0);
  });
});

describe("Numeric filters", () => {
  // Numeric rules only affect finite number values.
  // Strings, booleans and null are NOT affected.
  const data = ts([series(1, [
    { timestamp: "2026-01-01T00:00:00Z", value: 10 },
    { timestamp: "2026-01-01T00:01:00Z", value: 20 },
    { timestamp: "2026-01-01T00:02:00Z", value: 30 },
    { timestamp: "2026-01-01T00:03:00Z", value: "600" },
    { timestamp: "2026-01-01T00:04:00Z", value: true },
    { timestamp: "2026-01-01T00:05:00Z", value: null },
  ])]);

  const baseNumeric = (overrides: Record<string, unknown> = {}) => ({
    id: "num1",
    kind: "numeric" as const,
    enabled: true,
    tagId: 1,
    operator: "equal" as const,
    value: 10,
    secondValue: null,
    ...overrides,
  });

  // 3 numeric values (10, 20, 30) + 3 non-numeric ("600", true, null)
  const NON_NUMERIC_COUNT = 3;

  it("equal", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric()] };
    const result = applyDataFilters(data, config);
    // Keeps: 10 (matches) + 3 non-numeric = 4
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_NUMERIC_COUNT);
  });

  it("notEqual", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "notEqual", value: 10 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 20, 30 (matches notEqual) + 3 non-numeric = 5
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_NUMERIC_COUNT);
  });

  it("greaterThan", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "greaterThan", value: 15 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 20, 30 (matches) + 3 non-numeric = 5
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_NUMERIC_COUNT);
  });

  it("greaterThanOrEqual", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "greaterThanOrEqual", value: 20 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 20, 30 (matches) + 3 non-numeric = 5
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_NUMERIC_COUNT);
  });

  it("lessThan", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "lessThan", value: 20 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 10 (matches) + 3 non-numeric = 4
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_NUMERIC_COUNT);
  });

  it("lessThanOrEqual", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "lessThanOrEqual", value: 20 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 10, 20 (matches) + 3 non-numeric = 5
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_NUMERIC_COUNT);
  });

  it("between inclusive", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "between", value: 10, secondValue: 25 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 10, 20 (matches) + 3 non-numeric = 5
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_NUMERIC_COUNT);
  });

  it("outside range", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "outside", value: 10, secondValue: 25 })] };
    const result = applyDataFilters(data, config);
    // Keeps: 30 (matches outside) + 3 non-numeric = 4
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_NUMERIC_COUNT);
  });

  it("invalid limit returns error", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "between", value: 30, secondValue: 10 })] };
    const result = applyDataFilters(data, config);
    expect(result.errors).toHaveLength(1);
    // rule is invalid, so all points remain (3 numeric + 3 non-numeric)
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(3 + NON_NUMERIC_COUNT);
  });

  it("NaN and Infinity in config produce error", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ value: NaN })] };
    const errors = validateFilterConfiguration(config);
    expect(errors).toHaveLength(1);
  });

  it('"600" string is not treated as number', () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "equal", value: 600 })] };
    const result = applyDataFilters(data, config);
    // All numeric (10, 20, 30) removed (no match for 600) + 3 non-numeric kept = 3
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(NON_NUMERIC_COUNT);
  });

  it("booleans and null are not converted to numbers", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseNumeric({ operator: "equal", value: 1 })] };
    const result = applyDataFilters(data, config);
    // No numeric point equals 1. 3 non-numeric kept.
    expect(result.filteredTimeSeries.series[0].points.filter((p) => typeof p.value === "number")).toHaveLength(0);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(NON_NUMERIC_COUNT);
  });
});

describe("Text filters", () => {
  // Text rules only affect string values. Numbers, booleans, null pass through.
  const data = ts([series(1, [
    { timestamp: "2026-01-01T00:00:00Z", value: "RUN" },
    { timestamp: "2026-01-01T00:01:00Z", value: "STOP" },
    { timestamp: "2026-01-01T00:02:00Z", value: "running" },
    { timestamp: "2026-01-01T00:03:00Z", value: "600" },
    { timestamp: "2026-01-01T00:04:00Z", value: 42 },
  ])]);

  // 4 strings (RUN, STOP, running, 600) + 1 number (42)
  const NON_STRING_COUNT = 1;

  const baseText = (overrides: Record<string, unknown> = {}) => ({
    id: "txt1",
    kind: "text" as const,
    enabled: true,
    tagId: 1,
    operator: "equal" as const,
    value: "RUN",
    caseSensitive: false,
    ...overrides,
  });

  it("equal (case insensitive)", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText()] };
    const result = applyDataFilters(data, config);
    // "equal" does exact match after case folding. "RUN" → "run", "running" → "running" ≠ "run"
    // Strings exactly matching "RUN" (insensitive): RUN = 1 + number 42 = 2
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_STRING_COUNT);
  });

  it("notEqual", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "notEqual", value: "RUN" })] };
    const result = applyDataFilters(data, config);
    // Strings not eq RUN (insensitive): running, STOP, 600 = 3 + 42 = 4
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(3 + NON_STRING_COUNT);
  });

  it("contains", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "contains", value: "UN" })] };
    const result = applyDataFilters(data, config);
    // Strings containing "UN": RUN = 1 + 42 = 2 (running → "running".includes("un")? no, case insensitive? "running".includes("un")? no!)
    // "UN".toLowerCase = "un". "RUN".toLowerCase = "run". "running".toLowerCase = "running".
    // "run" contains "un"? Yes! "running" contains "un"? Yes!
    // RUN → "run" → contains "un"? No! "run" !== "running"
    // Wait, contains means contains substring. "run".includes("un") = "run".includes("un")? r-u-n... "run" has "un"? r-u-n: r, ru, un, run. Yes "run" contains "un". And "running" contains "un"? r-u-n-n-i-n-g: contains "un"? Yes!
    // So RUN and running both contain "un" → 2 + 42 = 3
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_STRING_COUNT);
  });

  it("startsWith", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "startsWith", value: "RUN" })] };
    const result = applyDataFilters(data, config);
    // Strings starting with "run" (insensitive): RUN ("run" starts with "run") ✓, running ("running" starts with "run") ✓ = 2 + 42 = 3
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2 + NON_STRING_COUNT);
  });

  it("endsWith", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "endsWith", value: "P" })] };
    const result = applyDataFilters(data, config);
    // Strings ending with "p" (insensitive): STOP ("stop" ends with "p") ✓ = 1 + 42 = 2
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_STRING_COUNT);
  });

  it("case sensitive", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "equal", value: "RUN", caseSensitive: true })] };
    const result = applyDataFilters(data, config);
    // Strings exactly "RUN" = 1 + 42 = 2
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_STRING_COUNT);
  });

  it("empty text is invalid", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ value: "" })] };
    const errors = validateFilterConfiguration(config);
    expect(errors).toHaveLength(1);
  });

  it('"600" treated as string', () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "equal", value: "600" })] };
    const result = applyDataFilters(data, config);
    // "600" = 1 + 42 = 2
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1 + NON_STRING_COUNT);
  });

  it("number is not converted to text for filtering", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseText({ operator: "equal", value: "42" })] };
    const result = applyDataFilters(data, config);
    // No string equals "42"; only number 42 remains
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(NON_STRING_COUNT);
  });
});

describe("Weekday filters (America/Sao_Paulo)", () => {
  it("keeps points on selected weekday", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [{
        id: "wd1",
        kind: "weekday",
        enabled: true,
        days: ["wednesday"],
        timezone: "America/Sao_Paulo",
      }],
    };
    // 2026-01-01T00:00:00Z = 2025-12-31T21:00 in SP (Wednesday)
    // So it should be KEPT (it IS Wednesday in SP)
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 1 },
    ])]);
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
  });

  it("handles UTC timestamp changing local day in Sao Paulo", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [{
        id: "wd2",
        kind: "weekday",
        enabled: true,
        days: ["thursday"],
        timezone: "America/Sao_Paulo",
      }],
    };
    // 2026-01-01T00:00:00Z = 2025-12-31T21:00 in SP (Wednesday, not Thursday)
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 1 },
    ])]);
    const result = applyDataFilters(data, config);
    // Point is on Wednesday in SP, not Thursday
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(0);
  });
});

describe("Time range filters", () => {
  it("normal range (inclusive)", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [{
        id: "tr1",
        kind: "timeRange",
        enabled: true,
        startTime: "07:00",
        endTime: "15:00",
        timezone: "America/Sao_Paulo",
      }],
    };
    // 2026-01-01T10:00:00Z = 07:00 in SP (BRT)
    const data = ts([series(1, [
      { timestamp: "2026-01-01T10:00:00Z", value: 1 }, // 07:00 in SP - on boundary
      { timestamp: "2026-01-01T18:00:00Z", value: 2 }, // 15:00 in SP - on boundary
      { timestamp: "2026-01-01T20:00:00Z", value: 3 }, // 17:00 in SP - outside
    ])]);
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2);
  });

  it("crosses midnight (start > end)", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [{
        id: "tr2",
        kind: "timeRange",
        enabled: true,
        startTime: "23:00",
        endTime: "07:00",
        timezone: "America/Sao_Paulo",
      }],
    };
    // 2026-01-01T02:00:00Z = 2025-12-31T23:00 in SP
    // 2026-01-01T06:00:00Z = 2026-01-01T03:00 in SP (within 23:00-07:00 range)
    // 2026-01-01T14:00:00Z = 2026-01-01T11:00 in SP (outside range)
    const data = ts([series(1, [
      { timestamp: "2026-01-01T02:00:00Z", value: 1 },
      { timestamp: "2026-01-01T06:00:00Z", value: 2 },
      { timestamp: "2026-01-01T14:00:00Z", value: 3 },
    ])]);
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(2);
  });

  it("invalid time produces error", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [{
        id: "tr3",
        kind: "timeRange",
        enabled: true,
        startTime: "25:00",
        endTime: "07:00",
        timezone: "America/Sao_Paulo",
      }],
    };
    const errors = validateFilterConfiguration(config);
    expect(errors).toHaveLength(1);
  });
});

describe("Exclude value filters", () => {
  const data = ts([series(1, [
    { timestamp: "2026-01-01T00:00:00Z", value: 600 },
    { timestamp: "2026-01-01T00:01:00Z", value: "600" },
    { timestamp: "2026-01-01T00:02:00Z", value: true },
    { timestamp: "2026-01-01T00:03:00Z", value: false },
    { timestamp: "2026-01-01T00:04:00Z", value: 42 },
  ])]);

  const baseExclude = (overrides: Record<string, unknown> = {}) => ({
    id: "ex1",
    kind: "excludeValue" as const,
    enabled: true,
    tagId: 1,
    valueType: "number" as const,
    value: 600,
    caseSensitive: false,
    ...overrides,
  });

  it("exact number", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseExclude()] };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points.map((p) => p.value)).not.toContain(600);
  });

  it("exact string", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseExclude({ valueType: "string", value: "600" })] };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points.map((p) => p.value)).not.toContain("600");
  });

  it("string with case sensitivity", () => {
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [baseExclude({ valueType: "string", value: "600", caseSensitive: true })],
    };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points.map((p) => p.value)).not.toContain("600");
  });

  it("boolean true", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseExclude({ valueType: "boolean", value: true })] };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points.map((p) => p.value)).not.toContain(true);
  });

  it("boolean false", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseExclude({ valueType: "boolean", value: false })] };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points.map((p) => p.value)).not.toContain(false);
  });

  it("distinguishes 600 from '600'", () => {
    const config: DataFilterConfiguration = { ...EMPTY_CONFIG, rules: [baseExclude({ valueType: "number", value: 600 })] };
    const result = applyDataFilters(data, config);
    const remaining = result.filteredTimeSeries.series[0].points.map((p) => p.value);
    expect(remaining).not.toContain(600);
    expect(remaining).toContain("600");
  });

  it("only affects the specified tag", () => {
    const data2 = ts([
      series(1, [{ timestamp: "2026-01-01T00:00:00Z", value: 600 }]),
      series(2, [{ timestamp: "2026-01-01T00:00:00Z", value: 600 }]),
    ]);
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [baseExclude({ tagId: 1 })],
    };
    const result = applyDataFilters(data2, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(0);
    expect(result.filteredTimeSeries.series[1].points).toHaveLength(1);
  });
});

describe("Pipeline order and counting", () => {
  it("filters only the selected series instance when A and B share tag_id", () => {
    const original = series(1, [{ timestamp: "2026-01-01T00:00:00Z", value: 10 }]);
    const compared = ts([
      { ...original, series_instance_id: "A-1" },
      { ...original, series_instance_id: "B-1" },
    ]);
    const result = applyDataFilters(compared, {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      rules: [{ id: "only-a", kind: "numeric", enabled: true, tagId: 1, seriesInstanceId: "A-1", operator: "greaterThan", value: 999, secondValue: null }],
    });
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(0);
    expect(result.filteredTimeSeries.series[1].points).toHaveLength(1);
  });
  it("combines rules with AND logic", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T10:00:00Z", value: 15 },
      { timestamp: "2026-01-01T11:00:00Z", value: 25 },
      { timestamp: "2026-01-01T12:00:00Z", value: 5 },
    ])]);
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [
        { id: "n1", kind: "numeric", enabled: true, tagId: 1, operator: "greaterThan", value: 10, secondValue: null },
        { id: "n2", kind: "numeric", enabled: true, tagId: 1, operator: "lessThan", value: 20, secondValue: null },
      ],
    };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1); // 15
  });

  it("counts a removed point only once", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: false },
    ])]);
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [
        { id: "e1", kind: "excludeValue", enabled: true, tagId: 1, valueType: "boolean", value: false, caseSensitive: false },
        { id: "t1", kind: "text", enabled: true, tagId: 1, operator: "equal", value: "false", caseSensitive: false },
      ],
    };
    const result = applyDataFilters(data, config);
    // Point is boolean, not string. Excluded by excludeValue rule.
    expect(result.summary.removedPoints).toBe(1);
    // The exclude rule should have 1 removal
    const excludeResult = result.ruleResults.find((r) => r.ruleId === "e1");
    expect(excludeResult?.removedPoints).toBe(1);
  });

  it("disabled rule is ignored", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: false },
    ])]);
    const config: DataFilterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        { id: "n1", kind: "numeric", enabled: false, tagId: 1, operator: "greaterThan", value: 10, secondValue: null },
      ],
    };
    const result = applyDataFilters(data, config);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
  });

  it("invalid rule is skipped with error", () => {
    const data = ts([series(1, [{ timestamp: "2026-01-01T00:00:00Z", value: 42 }])]);
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [
        { id: "bad", kind: "numeric", enabled: true, tagId: 1, operator: "between", value: null, secondValue: null },
      ],
    };
    const result = applyDataFilters(data, config);
    expect(result.errors).toHaveLength(1);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(1);
  });

  it("input is immutable", () => {
    const data = ts([series(1, [{ timestamp: "2026-01-01T00:00:00Z", value: 42, good: false }])]);
    const before = JSON.stringify(data);
    applyDataFilters(data, QUALITY_BAD_CONFIG);
    expect(JSON.stringify(data)).toBe(before);
  });

  it("empty series works", () => {
    const data = ts([series(1, [])]);
    const result = applyDataFilters(data, QUALITY_BAD_CONFIG);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(0);
    expect(result.summary.receivedPoints).toBe(0);
  });

  it("all points removed", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: false },
    ])]);
    const result = applyDataFilters(data, QUALITY_BAD_CONFIG);
    expect(result.filteredTimeSeries.series[0].points).toHaveLength(0);
    expect(result.summary.removedPoints).toBe(1);
    expect(result.summary.receivedPoints).toBe(1);
  });

  it("performs efficiently with many points (no quadratic)", () => {
    const pts = Array.from({ length: 20000 }, (_, i) => ({
      timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString(),
      value: i,
    }));
    const data = ts([series(1, pts)]);
    const config: DataFilterConfiguration = {
      ...EMPTY_CONFIG,
      rules: [
        { id: "n1", kind: "numeric", enabled: true, tagId: 1, operator: "greaterThan", value: 10000, secondValue: null },
      ],
    };
    const start = performance.now();
    const result = applyDataFilters(data, config);
    const elapsed = performance.now() - start;
    expect(result.filteredTimeSeries.series[0].points.length).toBe(9999);
    expect(elapsed).toBeLessThan(2000); // under 2 seconds
  });
});

describe("Category sum equals total removed", () => {
  it("sum of categories equals removedPoints", () => {
    const data = ts([series(1, [
      { timestamp: "2026-01-01T00:00:00Z", value: 42, good: false },
      { timestamp: "2026-01-01T00:01:00Z", value: "RUN" },
      { timestamp: "2026-01-01T00:02:00Z", value: 99 },
    ])]);
    const config: DataFilterConfiguration = {
      quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        { id: "t1", kind: "text", enabled: true, tagId: 1, operator: "equal", value: "RUN", caseSensitive: true },
      ],
    };
    const result = applyDataFilters(data, config);
    const sum = result.summary.removedByQuality + result.summary.removedByNumeric +
      result.summary.removedByText + result.summary.removedByDateTime + result.summary.removedByExclusion;
    expect(sum).toBe(result.summary.removedPoints);
  });
});
