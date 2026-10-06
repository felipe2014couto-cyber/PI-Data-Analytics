import { describe, expect, it } from "vitest";
import { buildNormLimitSeries, normLimitErrorMessage } from "../src/utils/normLimitSeries";

const start = "2026-07-01T00:00:00Z";
const end = "2026-07-01T01:00:00Z";
const base = {
  seriesInstanceId: "tag:1", tagName: "PV", yAxisIndex: 0,
  lineStyle: "dashed" as const, width: 2, lowerColor: "#00f", upperColor: "#f00",
  lowerPoints: [], upperPoints: [], startTimeIso: start, endTimeIso: end,
};

describe("historical norm limit state", () => {
  it("holds a Good seed across an event-free requested window", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-06-30T23:30:00Z", value: 5 },
    ] });
    expect(built.lowerPoints).toEqual([[Date.parse(start), 5], [Date.parse(end), 5]]);
  });

  it("uses a Good seed before the window and holds it until the next event", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-06-30T23:30:00Z", value: 5 },
      { timestamp: "2026-07-01T00:20:00Z", value: 7 },
    ] });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 5], [Date.parse("2026-07-01T00:20:00Z"), 7], [Date.parse(end), 7],
    ]);
    expect(built.upperPoints).toEqual([]);
  });

  it("does not carry an older Good seed through a Bad or Timeout seed", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-06-30T23:30:00Z", value: 5 },
      { timestamp: "2026-06-30T23:50:00Z", value: null, good: false },
    ] });
    expect(built.lowerPoints).toEqual([]);
  });

  it("breaks validity on Bad, Timeout, invalid values and real coverage gaps", () => {
    const built = buildNormLimitSeries({ ...base,
      lowerPoints: [
        { timestamp: "2026-06-30T23:30:00Z", value: 5 },
        { timestamp: "2026-07-01T00:10:00Z", value: 6, good: false },
        { timestamp: "2026-07-01T00:20:00Z", value: 7 },
        { timestamp: "2026-07-01T00:30:00Z", value: null }, // PI Timeout/invalid state is normalized to null.
        { timestamp: "2026-07-01T00:40:00Z", value: 8 },
        { timestamp: "2026-07-01T00:50:00Z", value: 9 },
      ],
      lowerCoverageGaps: [["2026-07-01T00:45:00Z", "2026-07-01T00:48:00Z"]],
    });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 5],
      [Date.parse("2026-07-01T00:10:00Z"), 5],
      [Date.parse("2026-07-01T00:10:00Z"), null],
      [Date.parse("2026-07-01T00:20:00Z"), 7],
      [Date.parse("2026-07-01T00:30:00Z"), 7],
      [Date.parse("2026-07-01T00:30:00Z"), null],
      [Date.parse("2026-07-01T00:40:00Z"), 8],
      [Date.parse("2026-07-01T00:45:00Z"), 8],
      [Date.parse("2026-07-01T00:45:00Z"), null],
      [Date.parse("2026-07-01T00:50:00Z"), 9],
      [Date.parse(end), 9],
    ]);
  });

  it("breaks on an explicit Timeout and resumes only on a new Good event", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-06-30T23:30:00Z", value: 5 },
      { timestamp: "2026-07-01T00:10:00Z", value: null, good: false },
      { timestamp: "2026-07-01T00:40:00Z", value: 8, good: true },
    ] });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 5],
      [Date.parse("2026-07-01T00:10:00Z"), 5],
      [Date.parse("2026-07-01T00:10:00Z"), null],
      [Date.parse("2026-07-01T00:40:00Z"), 8],
      [Date.parse(end), 8],
    ]);
  });
});


describe("availability tail", () => {
  it.each([false, true])("draws a stable seed to the watermark, with an in-window change=%s", (change) => {
    const watermark = "2026-07-01T00:54:32Z";
    const points = [{ timestamp: "2026-06-30T23:30:00Z", value: 5, good: true }];
    if (change) points.push({ timestamp: "2026-07-01T00:20:00Z", value: 7, good: true });
    const built = buildNormLimitSeries({ ...base, lowerPoints: points, lowerCoverageGaps: [[watermark, end]] });
    expect(built.lowerPoints.slice(-2)).toEqual([[Date.parse(watermark), change ? 7 : 5], [Date.parse(watermark), null]]);
    expect(built.lowerPoints[0]).toEqual([Date.parse(start), 5]);
    expect(built.lowerPoints.some(([ts]) => ts > Date.parse(watermark))).toBe(false);
  });

  it("keeps a real gap broken even after coverage resumes without another Good", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [{ timestamp: "2026-06-30T23:30:00Z", value: 5 }],
      lowerCoverageGaps: [["2026-07-01T00:20:00Z", "2026-07-01T00:30:00Z"], ["2026-07-01T00:50:00Z", end]],
    });
    expect(built.lowerPoints).toEqual([[Date.parse(start), 5], [Date.parse("2026-07-01T00:20:00Z"), 5], [Date.parse("2026-07-01T00:20:00Z"), null], [Date.parse("2026-07-01T00:50:00Z"), null]]);
  });

  it("retains a Good substituted seed such as RB1 Zona 03", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [{ timestamp: "2026-06-30T23:30:00Z", value: 1120, good: true, substituted: true }] });
    expect(built.lowerPoints).toEqual([[Date.parse(start), 1120], [Date.parse(end), 1120]]);
  });

  it.each([
    new Error("LOW: atualização RECORDED pendente"),
    { message: "LOW: atualização RECORDED pendente" },
    { error: { message: "LOW: atualização RECORDED pendente" } },
  ])("preserves a known technical diagnosis without requiring ApiError", (error) => {
    expect(normLimitErrorMessage(error)).toBe("LOW: atualização RECORDED pendente");
  });
});
