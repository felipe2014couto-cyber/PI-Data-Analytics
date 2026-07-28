import { describe, expect, it } from "vitest";

import type { TimePeriod, TimePreset } from "../src/types";
import {
  APPLICATION_TIMEZONE,
  formatResolvedTimePeriod,
  resolveTimePeriod,
  timePeriodError,
} from "../src/utils/timePeriod";

const NOW = new Date("2026-07-17T15:00:00.000Z");

describe("advanced time period resolver", () => {
  it.each<[TimePreset, number]>([
    ["PT15M", 15 * 60_000],
    ["PT1H", 60 * 60_000],
    ["PT8H", 8 * 60 * 60_000],
    ["P1D", 24 * 60 * 60_000],
    ["P7D", 7 * 24 * 60 * 60_000],
  ])("resolves preset %s with its exact duration", (preset, duration) => {
    const result = resolveTimePeriod({ kind: "preset", preset }, NOW);
    expect(Date.parse(result.endTime) - Date.parse(result.startTime)).toBe(duration);
    expect(result.endTime).toBe(NOW.toISOString());
  });

  it("uses the supplied clock exactly once as the preset reference", () => {
    const result = resolveTimePeriod({ kind: "preset", preset: "PT1H" }, NOW);
    expect(result.referenceTime).toBe(NOW.toISOString());
  });

  it("uses America/Sao_Paulo in the resolved contract", () => {
    expect(resolveTimePeriod({ kind: "preset", preset: "PT1H" }, NOW).timezone)
      .toBe(APPLICATION_TIMEZONE);
  });

  it("interprets an absolute July wall time explicitly in Sao Paulo", () => {
    const result = resolveTimePeriod({
      kind: "absolute", start: "2026-07-17T10:30", end: "2026-07-17T11:45",
      timezone: APPLICATION_TIMEZONE,
    }, NOW);
    expect(result.startTime).toBe("2026-07-17T13:30:00.000Z");
    expect(result.endTime).toBe("2026-07-17T14:45:00.000Z");
  });

  it("accepts seconds in absolute input", () => {
    const result = resolveTimePeriod({ kind: "absolute", start: "2026-01-10T08:00:30", end: "2026-01-10T08:01:31", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(result.startTime).toBe("2026-01-10T11:00:30.000Z");
  });

  it.each<[string, string]>([
    ["", "Informe a data e hora inicial"],
    ["2026-02-30T10:00", "não existe"],
    ["2026-13-01T10:00", "não existe"],
    ["2026-01-01T25:00", "não existe"],
    ["texto", "não existe"],
  ])("rejects invalid absolute start %s", (start, message) => {
    expect(() => resolveTimePeriod({ kind: "absolute", start, end: "2026-07-18T10:00", timezone: APPLICATION_TIMEZONE }, NOW)).toThrow(message);
  });

  it("rejects an empty absolute end", () => {
    expect(timePeriodError({ kind: "absolute", start: "2026-07-17T10:00", end: "", timezone: APPLICATION_TIMEZONE }, NOW)).toContain("final");
  });

  it("rejects equal absolute boundaries", () => {
    expect(timePeriodError({ kind: "absolute", start: "2026-07-17T10:00", end: "2026-07-17T10:00", timezone: APPLICATION_TIMEZONE }, NOW)).toContain("posterior");
  });

  it("rejects an absolute end before start", () => {
    expect(timePeriodError({ kind: "absolute", start: "2026-07-17T11:00", end: "2026-07-17T10:00", timezone: APPLICATION_TIMEZONE }, NOW)).toContain("posterior");
  });

  it("rejects a nonexistent Sao Paulo wall time during DST transition", () => {
    expect(timePeriodError({ kind: "absolute", start: "2018-11-04T00:30", end: "2018-11-04T02:00", timezone: APPLICATION_TIMEZONE }, NOW)).toContain("não existe");
  });

  it.each<[number, string]>([[0, "inteira"], [-1, "inteira"], [1.5, "inteira"], [Number.NaN, "inteira"]])(
    "rejects invalid relative amount %s", (amount, message) => {
      const period = { kind: "relative", amount, unit: "hour", reference: "now", timezone: APPLICATION_TIMEZONE } as TimePeriod;
      expect(timePeriodError(period, NOW)).toContain(message);
    },
  );

  it.each<["minute" | "hour", number, string]>([
    ["minute", 30, "2026-07-17T14:30:00.000Z"],
    ["hour", 2, "2026-07-17T13:00:00.000Z"],
  ])("resolves relative %s from now", (unit, amount, expectedStart) => {
    const result = resolveTimePeriod({ kind: "relative", amount, unit, reference: "now", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(result.startTime).toBe(expectedStart);
    expect(result.endTime).toBe(NOW.toISOString());
  });

  it("uses local start of day as the relative end reference", () => {
    const result = resolveTimePeriod({ kind: "relative", amount: 1, unit: "hour", reference: "startOfDay", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(result.endTime).toBe("2026-07-17T03:00:00.000Z");
    expect(result.startTime).toBe("2026-07-17T02:00:00.000Z");
  });

  it("uses local end of day as the relative end reference", () => {
    const result = resolveTimePeriod({ kind: "relative", amount: 1, unit: "hour", reference: "endOfDay", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(result.endTime).toBe("2026-07-18T02:59:59.999Z");
  });

  it("subtracts relative days by calendar across Sao Paulo DST", () => {
    const result = resolveTimePeriod({ kind: "relative", amount: 1, unit: "day", reference: "now", timezone: APPLICATION_TIMEZONE }, new Date("2018-11-04T14:00:00.000Z"));
    expect(result.startTime).toBe("2018-11-03T15:00:00.000Z");
    expect(Date.parse(result.endTime) - Date.parse(result.startTime)).toBe(23 * 60 * 60_000);
  });

  it("subtracts a week as seven local calendar days", () => {
    const result = resolveTimePeriod({ kind: "relative", amount: 1, unit: "week", reference: "now", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(result.startTime).toBe("2026-07-10T15:00:00.000Z");
  });

  it("formats the resolved range in the official timezone", () => {
    const text = formatResolvedTimePeriod(resolveTimePeriod({ kind: "preset", preset: "PT1H" }, NOW));
    expect(text).toContain("17/07/2026");
    expect(text).toContain("11:00:00");
    expect(text).toContain("12:00:00");
  });

  it("does not mutate the supplied clock", () => {
    const before = NOW.toISOString();
    resolveTimePeriod({ kind: "relative", amount: 1, unit: "day", reference: "now", timezone: APPLICATION_TIMEZONE }, NOW);
    expect(NOW.toISOString()).toBe(before);
  });

  it("reports an invalid reference instant", () => {
    expect(() => resolveTimePeriod({ kind: "preset", preset: "PT1H" }, new Date(Number.NaN))).toThrow("referência inválido");
  });
});
