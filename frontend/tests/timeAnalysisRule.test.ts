import { describe, expect, it } from "vitest";
import type { TimeSeries, TimeSeriesPoint, TimeSeriesSeries } from "../src/types";
import { applyTimeAnalysisRule } from "../src/utils/timeAnalysisRule";

function makePoint(
  timestamp: string,
  value: TimeSeriesPoint["value"],
  good = true,
  filtered_out = false,
  elapsed_ms?: number,
): TimeSeriesPoint {
  return {
    timestamp,
    value,
    good,
    filtered_out,
    elapsed_ms,
    questionable: false,
    substituted: false,
  };
}

function makeSeries(
  id: number,
  pts: TimeSeriesPoint[],
  unit = "kg",
): TimeSeriesSeries {
  return {
    tag_id: id,
    tag_name: `TAG_${id}`,
    display_name: `Tag ${id}`,
    equipment: null,
    section: null,
    variable_type: null,
    unit,
    points: pts,
  };
}

function makeTs(seriesList: TimeSeriesSeries[]): TimeSeries {
  return {
    start_time: "2026-09-04T10:00:00Z",
    end_time: "2026-09-04T10:05:00Z",
    mode: "recorded",
    series: seriesList,
    errors: [],
  };
}

describe("applyTimeAnalysisRule", () => {
  it("returns original series when rule is DEFAULT", () => {
    const pts = [
      makePoint("2026-09-04T10:00:05Z", 10),
      makePoint("2026-09-04T10:00:30Z", 20),
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "DEFAULT");
    expect(result.series[0].points).toHaveLength(2);
    expect(result.series[0].points[0].value).toBe(10);
    expect(result.series[0].points[1].value).toBe(20);
  });

  it("returns original series when rule is OOC (not yet implemented)", () => {
    const pts = [
      makePoint("2026-09-04T10:00:05Z", 10),
      makePoint("2026-09-04T10:00:30Z", 20),
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "OOC");
    expect(result.series[0].points).toHaveLength(2);
    expect(result.series[0].points[0].value).toBe(10);
  });

  it("calculates MEDIA correctly per 1-minute bucket", () => {
    const pts = [
      makePoint("2026-09-04T10:00:10Z", 10),
      makePoint("2026-09-04T10:00:20Z", 20),
      makePoint("2026-09-04T10:00:30Z", 30), // minute 10:00 -> mean = 20
      makePoint("2026-09-04T10:01:05Z", 40),
      makePoint("2026-09-04T10:01:35Z", 60), // minute 10:01 -> mean = 50
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "MEDIA");

    expect(result.series[0].points).toHaveLength(2);
    expect(result.series[0].points[0].timestamp).toBe("2026-09-04T10:00:00.000Z");
    expect(result.series[0].points[0].value).toBe(20);
    expect(result.series[0].points[1].timestamp).toBe("2026-09-04T10:01:00.000Z");
    expect(result.series[0].points[1].value).toBe(50);
  });

  it("calculates MAXIMO correctly per 1-minute bucket", () => {
    const pts = [
      makePoint("2026-09-04T10:00:10Z", 10),
      makePoint("2026-09-04T10:00:20Z", 25),
      makePoint("2026-09-04T10:00:50Z", 15),
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "MAXIMO");

    expect(result.series[0].points).toHaveLength(1);
    expect(result.series[0].points[0].timestamp).toBe("2026-09-04T10:00:00.000Z");
    expect(result.series[0].points[0].value).toBe(25);
  });

  it("calculates MIN correctly per 1-minute bucket", () => {
    const pts = [
      makePoint("2026-09-04T10:00:10Z", 10),
      makePoint("2026-09-04T10:00:20Z", 25),
      makePoint("2026-09-04T10:00:50Z", 5),
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "MIN");

    expect(result.series[0].points).toHaveLength(1);
    expect(result.series[0].points[0].timestamp).toBe("2026-09-04T10:00:00.000Z");
    expect(result.series[0].points[0].value).toBe(5);
  });

  it("handles filtered_out points within a bucket", () => {
    const pts = [
      makePoint("2026-09-04T10:00:10Z", 10, true, true), // filtered out
      makePoint("2026-09-04T10:00:20Z", 30, true, false), // valid
    ];
    const ts = makeTs([makeSeries(1, pts)]);
    const result = applyTimeAnalysisRule(ts, "MEDIA");

    expect(result.series[0].points).toHaveLength(1);
    expect(result.series[0].points[0].value).toBe(30);
  });

  it("preserves non-numeric series unchanged", () => {
    const pts = [
      makePoint("2026-09-04T10:00:10Z", "RUNNING"),
      makePoint("2026-09-04T10:00:30Z", "STOPPED"),
    ];
    const ts = makeTs([makeSeries(1, pts, "")]);
    const result = applyTimeAnalysisRule(ts, "MEDIA");

    expect(result.series[0].points).toHaveLength(2);
    expect(result.series[0].points[0].value).toBe("RUNNING");
    expect(result.series[0].points[1].value).toBe("STOPPED");
  });
});
