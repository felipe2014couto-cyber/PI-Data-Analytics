import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SingleValueCards } from "../src/components/SingleValueCards";
import type { TimeSeriesPoint, TimeSeriesSeries } from "../src/types";
import {
  buildSingleValueEntries,
  isDisplayableValue,
  latestDisplayableValue,
  singleValueQuality,
} from "../src/utils/singleValue";

const good = { good: true, questionable: false, substituted: false };

function point(
  timestamp: string,
  value: TimeSeriesPoint["value"],
  quality = good,
): TimeSeriesPoint {
  return { timestamp, value, ...quality };
}

function series(id: number, points: TimeSeriesPoint[], unit: string | null = "°C"): TimeSeriesSeries {
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

describe("single value selection", () => {
  it("selects the displayable point with the greatest valid timestamp from an unordered array", () => {
    const result = latestDisplayableValue(series(1, [
      point("2026-07-17T10:02:00Z", 20.5),
      point("invalid", 999),
      point("2026-07-17T10:00:00Z", 10),
    ]), false);
    expect(result?.value).toBe(20.5);
    expect(result?.timestampText).toBe("2026-07-17T10:02:00Z");
  });

  it("preserves integer, decimal, strings and booleans without coercion", () => {
    const values: TimeSeriesPoint["value"][] = [600, 500.5, "P304I", "600", "500.5", true, false];
    values.forEach((value, index) => {
      const result = latestDisplayableValue(series(index, [point("2026-07-17T10:00:00Z", value)]), false);
      expect(result?.value).toBe(value);
      expect(typeof result?.value).toBe(typeof value);
    });
    const numericString = latestDisplayableValue(series(9, [point("2026-07-17T10:00:00Z", "600")]), false);
    expect(numericString?.value).toBe("600");
    expect(typeof numericString?.value).toBe("string");
  });

  it("ignores null and non-finite numbers", () => {
    expect(isDisplayableValue(null)).toBe(false);
    expect(isDisplayableValue(NaN)).toBe(false);
    expect(isDisplayableValue(Infinity)).toBe(false);
    expect(latestDisplayableValue(series(1, [
      point("2026-07-17T10:00:00Z", null),
      point("2026-07-17T10:01:00Z", NaN),
      point("2026-07-17T10:02:00Z", Infinity),
    ]), false)).toBeNull();
  });

  it("filters bad quality before selection and falls back to the prior point", () => {
    const entry = series(1, [
      point("2026-07-17T10:00:00Z", "RUN"),
      point("2026-07-17T10:01:00Z", "STOP", { good: false, questionable: false, substituted: false }),
    ]);
    expect(latestDisplayableValue(entry, false)?.value).toBe("STOP");
    expect(latestDisplayableValue(entry, true)?.value).toBe("RUN");
  });

  it("applies the documented quality priority", () => {
    const observation = latestDisplayableValue(series(1, [point("2026-07-17T10:00:00Z", 1)]), false);
    expect(singleValueQuality(observation)).toEqual({ status: "Bom", variant: "success" });
    expect(singleValueQuality(observation && { ...observation, good: false, questionable: true, substituted: true }))
      .toEqual({ status: "Ruim", variant: "danger" });
    expect(singleValueQuality(observation && { ...observation, questionable: true, substituted: true }))
      .toEqual({ status: "Questionável", variant: "warning" });
    expect(singleValueQuality(observation && { ...observation, substituted: true }))
      .toEqual({ status: "Substituído", variant: "primary" });
    expect(singleValueQuality(null)).toEqual({ status: "Sem dados", variant: "secondary" });
  });

  it("supports multiple numeric, textual, boolean and historically mixed series", () => {
    const entries = buildSingleValueEntries([
      series(1, [point("2026-07-17T10:00:00Z", 600)]),
      series(2, [point("2026-07-17T10:00:00Z", "600")]),
      series(3, [point("2026-07-17T10:00:00Z", true)]),
      series(4, [point("2026-07-17T10:00:00Z", 10), point("2026-07-17T10:01:00Z", "RUN")]),
    ], false);
    expect(entries.map((entry) => entry.observation?.value)).toEqual([600, "600", true, "RUN"]);
  });
});

describe("single value cards", () => {
  it("renders responsive cards with value, unit, timestamp, status and independent flags", () => {
    render(<SingleValueCards series={[
      series(1, [point("2026-07-17T10:00:00Z", 500.5)], "bar"),
      series(2, [point("2026-07-17T10:01:00Z", "500.5", { good: true, questionable: true, substituted: true })], null),
      series(3, [point("2026-07-17T10:02:00Z", false, { good: true, questionable: false, substituted: true })]),
    ]} ignoreBadQuality={false} />);
    expect(screen.getAllByTestId("single-value-card-column")).toHaveLength(3);
    expect(screen.getByTestId("single-value-1")).toHaveTextContent(/500,5\s*bar/);
    expect(screen.getByTestId("single-value-2")).toHaveTextContent("500.5");
    expect(screen.getByTestId("single-value-card-2")).toHaveAttribute("data-quality-status", "Questionável");
    expect(screen.getByTestId("single-value-flags-2")).toHaveTextContent("Questionable: true | Substituted: true");
    expect(screen.getByTestId("single-value-card-3")).toHaveAttribute("data-quality-status", "Substituído");
    expect(screen.getByTestId("single-value-3")).toHaveTextContent("false");
    expect(screen.getAllByText(/17\/07\/2026/)).toHaveLength(3);
  });

  it("renders bad and no-data cards with textual accessible statuses", () => {
    render(<SingleValueCards series={[
      series(1, [point("2026-07-17T10:00:00Z", "STOP", { good: false, questionable: true, substituted: true })]),
      series(2, [point("2026-07-17T10:00:00Z", null)]),
    ]} ignoreBadQuality={false} />);
    expect(screen.getByTestId("single-value-card-1")).toHaveClass("border-danger");
    expect(screen.getByTestId("single-value-card-1")).toHaveAttribute("data-quality-status", "Ruim");
    expect(screen.getByTestId("single-value-card-2")).toHaveClass("border-secondary");
    expect(screen.getByTestId("single-value-empty-2")).toHaveTextContent("Sem valor disponível");
    expect(screen.getByTestId("single-value-empty-2")).toHaveTextContent("Sem dados");
  });
});
