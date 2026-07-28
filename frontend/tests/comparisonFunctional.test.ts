import { describe, expect, it } from "vitest";

import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { buildChartData } from "../src/utils/chartData";
import { buildTimeSeriesCsv } from "../src/utils/csv";
import type { TimeSeries } from "../src/types";

const compared: TimeSeries = {
  start_time: "2026-01-01T00:00:00Z",
  end_time: "2026-01-01T01:00:00Z",
  mode: "recorded",
  errors: [],
  series: ["A", "B"].map((context, index) => ({
    tag_id: 7,
    original_tag_id: 7,
    tag_name: "TAG.7",
    display_name: `Temperatura — Contexto ${context}`,
    equipment: "RB3",
    section: "ENTRADA",
    variable_type: "TEMPERATURE",
    unit: "C",
    points: [{ timestamp: index === 0 ? "2026-01-01T00:10:00Z" : "2026-02-01T00:10:00Z", elapsed_ms: 600000, value: index + 1, good: true, questionable: false, substituted: false }],
    context_id: context as "A" | "B",
    context_label: `Contexto ${context}`,
    comparison_type: "periods" as const,
    series_instance_id: `${context}-7`,
    category: "TEMPERATURE",
    original_start_time: index === 0 ? "2026-01-01T00:00:00Z" : "2026-02-01T00:00:00Z",
    original_end_time: index === 0 ? "2026-01-01T01:00:00Z" : "2026-02-01T01:00:00Z",
  })),
};

describe("functional comparison", () => {
  it("overlays periods by elapsed time while retaining original timestamps", () => {
    const chart = buildChartData(compared, { ignoreBadQuality: false });
    expect(chart.series.map((series) => series.points[0][0])).toEqual([600000, 600000]);
    expect(chart.series.map((series) => series.seriesInstanceId)).toEqual(["A-7", "B-7"]);
    expect(chart.series.map((series) => series.originalTimestamps?.[0])).toEqual([
      "2026-01-01T00:10:00Z",
      "2026-02-01T00:10:00Z",
    ]);
    const option = buildTimeSeriesChartOption({ chart, equipment: null, start: new Date(compared.start_time), end: new Date(compared.end_time), mode: "recorded" });
    const plotted = option.series as Array<{ sampling?: string; lineStyle: { type: string } }>;
    expect(plotted[0].sampling).toBeUndefined();
    expect(plotted[1].lineStyle.type).toBe("dashed");
  });

  it("exports comparison identity and the real tag id without changing timestamps", () => {
    const csv = buildTimeSeriesCsv(compared);
    expect(csv).toContain("comparison_type;context_id;context_label;series_instance_id;category;elapsed_ms");
    expect(csv).toContain("2026-02-01T00:10:00Z");
    expect(csv).toContain(";7;TAG.7;");
    expect(csv).not.toContain(";-7;TAG.7;");
  });
});
