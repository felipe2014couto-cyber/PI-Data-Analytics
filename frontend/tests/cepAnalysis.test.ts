import { describe, expect, it } from "vitest";

import { buildCepSeriesChartOption, toIsoUtc } from "../src/pages/CepAnalysisPage";
import layoutSource from "../src/layouts/MainLayout.tsx?raw";
import pageSource from "../src/pages/CepAnalysisPage.tsx?raw";

describe("CEP analysis page", () => {
  it("serializes datetime-local values using the browser timezone", () => {
    const localValue = "2026-08-04T10:30";
    expect(toIsoUtc(localValue)).toBe(new Date(localValue).toISOString());
  });

  it("uses UTF-8 text for the CEP title and sidebar label", () => {
    expect(pageSource).toContain('title="Análise CEP"');
    expect(layoutSource).toContain('label: "Análise CEP"');
    expect(pageSource).not.toMatch(/\\u[0-9a-fA-F]{4}/);
  });

  it("keeps stopped timestamps as visual gaps without cutting limits", () => {
    const option = buildCepSeriesChartOption({
      variable_id: 1,
      variable_name: "V",
      analysis_tag: "TAG_V",
      lower_limit: 5,
      upper_limit: 15,
      non_conforming_points: [],
      points: [
        { timestamp: "2026-01-01T00:00:00Z", value: 10, lower_limit: 5, upper_limit: 15 },
        { timestamp: "2026-01-01T00:05:00Z", value: -999, lower_limit: -999, upper_limit: 15 },
        { timestamp: "2026-01-01T00:10:00Z", value: 12, lower_limit: 5, upper_limit: -999 },
      ],
    });
    const chartSeries = option.series as Array<{ name: string; connectNulls: boolean; data: Array<[string, number | null]> }>;
    expect(chartSeries[0].data).toEqual([
      ["2026-01-01T00:00:00Z", 10],
      ["2026-01-01T00:05:00Z", null],
      ["2026-01-01T00:10:00Z", 12],
    ]);
    expect(chartSeries[0].connectNulls).toBe(false);
    expect(chartSeries[1].connectNulls).toBe(false);
    expect(chartSeries[2].connectNulls).toBe(false);
    expect(chartSeries[1].data).toEqual([
      ["2026-01-01T00:00:00Z", 5],
      ["2026-01-01T00:05:00Z", null],
      ["2026-01-01T00:10:00Z", 5],
    ]);
    expect(chartSeries[2].data).toEqual([
      ["2026-01-01T00:00:00Z", 15],
      ["2026-01-01T00:05:00Z", 15],
      ["2026-01-01T00:10:00Z", null],
    ]);
    expect(JSON.stringify(chartSeries)).not.toContain("-999");
  });
});
