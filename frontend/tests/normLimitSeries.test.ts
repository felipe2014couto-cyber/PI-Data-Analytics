import { describe, expect, it } from "vitest";
import { buildNormLimitSeries, normLimitErrorMessage, resolveNormLimitStateAtTimestamp } from "../src/utils/normLimitSeries";

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
    expect(built.lowerPoints).toEqual([[Date.parse(start), 5], [Date.parse("2026-07-01T00:20:00Z"), 5], [Date.parse("2026-07-01T00:20:00Z"), null]]);
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

describe("marker lookup for materialized norm limits", () => {
  it("mantém o último Good entre eventos e usa o novo valor depois da retomada Good", () => {
    const points = [
      { timestamp: 10, value: 5, good: true },
      { timestamp: 20, value: 7, good: true },
      { timestamp: 30, value: null, good: false },
      { timestamp: 40, value: 9, good: true },
    ];
    expect(resolveNormLimitStateAtTimestamp(points, 15)).toBe(5);
    expect(resolveNormLimitStateAtTimestamp(points, 25)).toBe(7);
    expect(resolveNormLimitStateAtTimestamp(points, 35)).toBeNull();
    expect(resolveNormLimitStateAtTimestamp(points, 45)).toBe(9);
  });

  it("retorna indisponível dentro da lacuna e retoma no próximo ponto Good", () => {
    const points = [
      { timestamp: start, value: 5, good: true },
      { timestamp: "2026-07-01T00:40:00Z", value: 8, good: true },
    ];
    const gaps: Array<[string, string]> = [["2026-07-01T00:20:00Z", "2026-07-01T00:30:00Z"]];
    expect(resolveNormLimitStateAtTimestamp(points, "2026-07-01T00:25:00Z", gaps)).toBeNull();
    expect(resolveNormLimitStateAtTimestamp(points, "2026-07-01T00:35:00Z", gaps)).toBeNull();
    expect(resolveNormLimitStateAtTimestamp(points, "2026-07-01T00:40:00Z", gaps)).toBe(8);
  });

  it("normaliza timestamps ISO, Date e número para o mesmo instante UTC", () => {
    const timestamp = "2026-07-01T00:20:00.000Z";
    const points = [{ timestamp: new Date(timestamp), value: 12, good: true }];
    const expected = Date.parse(timestamp);
    expect(resolveNormLimitStateAtTimestamp(points, timestamp)).toBe(12);
    expect(resolveNormLimitStateAtTimestamp(points, new Date(expected))).toBe(12);
    expect(resolveNormLimitStateAtTimestamp(points, expected)).toBe(12);
  });

  it("mantém o cartão consistente com a linha visível no mesmo timestamp", () => {
    const markerTs = Date.parse("2026-07-01T00:35:00Z");
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-07-01T00:00:00Z", value: 5, good: true },
      { timestamp: "2026-07-01T00:20:00Z", value: 7, good: true },
    ] });
    const markerValue = resolveNormLimitStateAtTimestamp(
      built.lowerStatePoints!,
      markerTs,
      built.lowerCoverageGaps,
    );
    const visibleLineValue = resolveNormLimitStateAtTimestamp(
      built.lowerPoints.map(([timestamp, value]) => ({ timestamp, value })),
      markerTs,
    );
    expect(markerValue).toBe(7);
    expect(visibleLineValue).toBe(markerValue);
  });

  it("preserves finite negative values and null breaks without inventing values", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-07-01T00:00:00Z", value: 5 },
      { timestamp: "2026-07-01T00:20:00Z", value: 7 },
      { timestamp: "2026-07-01T00:30:00Z", value: null, good: false },
      { timestamp: "2026-07-01T00:40:00Z", value: 8 },
    ] });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 5],
      [Date.parse("2026-07-01T00:20:00Z"), 7],
      [Date.parse("2026-07-01T00:30:00Z"), 7],
      [Date.parse("2026-07-01T00:30:00Z"), null],
      [Date.parse("2026-07-01T00:40:00Z"), 8],
      [Date.parse(end), 8],
    ]);
    expect(built.lowerPoints.filter(([, value]) => value !== null).every(([, value]) => Number.isFinite(value))).toBe(true);
  });

  it("draws a Good -999 limit and resolves the same value for the marker card", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-07-01T00:00:00Z", value: 25, good: true },
      { timestamp: "2026-07-01T00:20:00Z", value: -999, good: true },
      { timestamp: "2026-07-01T00:40:00Z", value: 30, good: true },
    ] });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 25],
      [Date.parse("2026-07-01T00:20:00Z"), -999],
      [Date.parse("2026-07-01T00:40:00Z"), 30],
      [Date.parse(end), 30],
    ]);
    const marker = resolveNormLimitStateAtTimestamp(
      built.lowerStatePoints!,
      Date.parse("2026-07-01T00:30:00Z"),
      built.lowerCoverageGaps,
    );
    const line = resolveNormLimitStateAtTimestamp(
      built.lowerPoints.map(([timestamp, value]) => ({ timestamp, value })),
      Date.parse("2026-07-01T00:30:00Z"),
    );
    expect(marker).toBe(-999);
    expect(line).toBe(marker);
  });

  it("breaks the line for -999 with Bad quality until the next Good value", () => {
    const built = buildNormLimitSeries({ ...base, lowerPoints: [
      { timestamp: "2026-07-01T00:00:00Z", value: 25, good: true },
      { timestamp: "2026-07-01T00:20:00Z", value: -999, good: false },
      { timestamp: "2026-07-01T00:40:00Z", value: 30, good: true },
    ] });
    expect(built.lowerPoints).toEqual([
      [Date.parse(start), 25],
      [Date.parse("2026-07-01T00:20:00Z"), 25],
      [Date.parse("2026-07-01T00:20:00Z"), null],
      [Date.parse("2026-07-01T00:40:00Z"), 30],
      [Date.parse(end), 30],
    ]);
    expect(resolveNormLimitStateAtTimestamp(
      built.lowerStatePoints!, Date.parse("2026-07-01T00:30:00Z"), built.lowerCoverageGaps,
    )).toBeNull();
  });
});
