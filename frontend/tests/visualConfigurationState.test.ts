import { describe, expect, it } from "vitest";
import type { PersistablePageState } from "../src/utils/visualConfiguration";
import { buildVisualConfigurationDocument, normalizeVisualConfigurationDocument } from "../src/utils/visualConfiguration";
import { stripRetiredNamedFilterRules } from "../src/components/AdvancedFiltersPanel";
import { resolveTimePeriod } from "../src/utils/timePeriod";

const state = (): PersistablePageState => ({
  filters: {
    analysisModel: "unit",
    equipmentId: 11,
    sectionId: 22,
    variableTypeId: 33,
    timePeriod: { kind: "preset", preset: "PT1H" },
    timezone: "America/Sao_Paulo",
    mode: "recorded",
    interval: "5m",
    maxCount: 4321,
    resolutionMode: "manual",
    targetPointsPerTag: 7654,
    ignoreBadQuality: false,
    visualization: "scatter",
    filterConfiguration: {
      quality: { excludeBad: false, excludeQuestionable: true, excludeSubstituted: true },
      rules: [{ id: "rule-1", kind: "numeric", tagId: 101, seriesInstanceId: "tag:101", operator: "greaterThan", value: 10, secondValue: null, enabled: true }],
    },
  },
  selectedTagIds: [102, 101],
  seriesAssignments: [
    { tagId: 102, order: 0, lineAxis: "secondary", scatterRole: "x" },
    { tagId: 101, order: 1, lineAxis: "primary", scatterRole: "y" },
  ],
  metricConfiguration: { kind: "single", metric: "mean" },
  comparison: { type: "equipments", contextBEquipmentId: 44, contextBCategoryId: null, contextBTagIds: [202, 201], contextBStart: "", contextBEnd: "" },
  visualRules: { enabled: true, selectedSeriesInstanceId: "tag:101", bySeries: {} },
});

describe("estado persistente da configuração visual", () => {
  it("serializa e restaura todo o estado configurável sem estados temporários", () => {
    const original = state();
    const document = buildVisualConfigurationDocument(original);
    const restored = normalizeVisualConfigurationDocument(document, state(), "America/Sao_Paulo");
    expect(restored).toEqual(original);
    expect(document).not.toHaveProperty("query");
    expect(document).not.toHaveProperty("loading");
    expect(JSON.stringify(document)).not.toContain("timeSeries");
  });

  it("produz cópias seguras de arrays e objetos", () => {
    const original = state();
    const document = buildVisualConfigurationDocument(original);
    original.selectedTagIds.reverse();
    original.filters.filterConfiguration.rules[0].enabled = false;
    expect(document.sidebar_state?.selectedTagIds).toEqual([102, 101]);
    expect(document.sidebar_state?.filters.filterConfiguration.rules[0].enabled).toBe(true);
    const restored = normalizeVisualConfigurationDocument(document, state(), "America/Sao_Paulo");
    restored.selectedTagIds.push(999);
    expect(document.sidebar_state?.selectedTagIds).toEqual([102, 101]);
  });

  it("mantém preset e recalcula seu intervalo em relação ao horário de abertura", () => {
    const document = buildVisualConfigurationDocument(state());
    expect(document.sidebar_state?.filters.timePeriod).toEqual({ kind: "preset", preset: "PT1H" });
    const first = resolveTimePeriod(document.sidebar_state!.filters.timePeriod, new Date("2026-01-01T12:00:00Z"));
    const second = resolveTimePeriod(document.sidebar_state!.filters.timePeriod, new Date("2026-01-01T13:00:00Z"));
    expect(new Date(second.startTime).getTime() - new Date(first.startTime).getTime()).toBe(3_600_000);
  });

  it("preserva período absoluto e fuso horário", () => {
    const original = state();
    original.filters.timePeriod = { kind: "absolute", start: "2026-07-20T08:15", end: "2026-07-20T10:45", timezone: "America/Sao_Paulo" };
    const restored = normalizeVisualConfigurationDocument(buildVisualConfigurationDocument(original), state(), "America/Sao_Paulo");
    expect(restored.filters.timePeriod).toEqual(original.filters.timePeriod);
    expect(restored.filters.timezone).toBe("America/Sao_Paulo");
  });

  it("abre documento antigo usando padrões atuais para campos ausentes", () => {
    const defaults = state();
    const restored = normalizeVisualConfigurationDocument({ schema_version: 1, visual_rules: { enabled: false, selectedSeriesInstanceId: null, bySeries: {}, queryMode: "interpolated" } }, defaults, "America/Sao_Paulo");
    expect(restored.filters.equipmentId).toBe(defaults.filters.equipmentId);
    expect(restored.filters.mode).toBe("interpolated");
    expect(restored.selectedTagIds).toEqual(defaults.selectedTagIds);
    expect(restored.visualRules.enabled).toBe(false);
  });

  it("remove apenas regras named-filter de campos aposentados ao restaurar", () => {
    const original = state();
    original.filters.filterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        { id: "named-filter:reprocess", kind: "text", tagId: 500, seriesInstanceId: undefined, operator: "contains", value: "Sim", enabled: true, caseSensitive: false },
        { id: "named-filter:eventType", kind: "text", tagId: 501, seriesInstanceId: undefined, operator: "contains", value: "Operacional", enabled: true, caseSensitive: false },
        { id: "named-filter:lengthAbsoluteMin", kind: "numeric", tagId: 502, seriesInstanceId: undefined, operator: "greaterThanOrEqual", value: 0, secondValue: null, enabled: true },
        { id: "named-filter:shift", kind: "text", tagId: 13, seriesInstanceId: undefined, operator: "contains", value: "1º turno", enabled: true, caseSensitive: false },
        { id: "rule-generic", kind: "numeric", tagId: 999, seriesInstanceId: undefined, operator: "equal", value: 5, secondValue: null, enabled: true },
      ],
    };
    const document = buildVisualConfigurationDocument(original);
    const restored = normalizeVisualConfigurationDocument(document, state(), "America/Sao_Paulo");
    const cleanedRules = stripRetiredNamedFilterRules(restored.filters.filterConfiguration!.rules);
    const ids = cleanedRules.map((r) => r.id);
    expect(ids).not.toContain("named-filter:reprocess");
    expect(ids).not.toContain("named-filter:eventType");
    expect(ids).not.toContain("named-filter:lengthAbsoluteMin");
    expect(ids).toContain("named-filter:shift");
    expect(ids).toContain("rule-generic");
  });

  it("abre configuração antiga sem o campo de modelo aplicando Base Unidade como compatibilidade", () => {
    const defaults = state();
    const legacyDoc = buildVisualConfigurationDocument(defaults);
    // Remove o campo analysisModel simulando documento antigo
    delete (legacyDoc.sidebar_state?.filters as Record<string, unknown>).analysisModel;
    const restored = normalizeVisualConfigurationDocument(legacyDoc, defaults, "America/Sao_Paulo");
    expect(restored.filters.analysisModel).toBe("unit");
    expect(restored.filters.timeAnalysisRule).toBeUndefined();
  });

  it("restaura configuração com Base Cíclica e regra Padrão preservadas", () => {
    const custom = state();
    custom.filters.analysisModel = "cyclic";
    custom.filters.timeAnalysisRule = "DEFAULT";
    const doc = buildVisualConfigurationDocument(custom);
    const restored = normalizeVisualConfigurationDocument(doc, state(), "America/Sao_Paulo");
    expect(restored.filters.analysisModel).toBe("cyclic");
    expect(restored.filters.timeAnalysisRule).toBe("DEFAULT");
  });
});

