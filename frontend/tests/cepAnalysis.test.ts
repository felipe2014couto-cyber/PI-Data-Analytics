import { describe, expect, it } from "vitest";

import { toIsoUtc } from "../src/pages/CepAnalysisPage";
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
});
