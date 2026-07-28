import { describe, expect, it } from "vitest";
import type { MetricConfiguration, TimeSeriesSeries } from "../src/types";
import { ANALYSIS_METRICS, calculateMetricResults, createMetricConfiguration, validateMetricConfiguration } from "../src/utils/analysisMetrics";

const point = (timestamp: string, value: unknown, good = true) => ({ timestamp, value: value as number, good, questionable: false, substituted: false });
const series = (id: number, values: unknown[], unit: string | null = "bar", timestamps?: string[]): TimeSeriesSeries => ({
  tag_id: id, tag_name: `TAG_${id}`, display_name: `Tag ${id}`, equipment: null, section: null, variable_type: null, unit,
  points: values.map((value, index) => point(timestamps?.[index] ?? `2026-01-01T00:00:0${index}Z`, value)),
});
const value = (configuration: MetricConfiguration, entries = [series(1, [1, 2, 3, 4, 5])]) => calculateMetricResults(entries, configuration, true)[0];

describe("catálogo e contratos de métricas", () => {
  it("expõe exatamente as vinte métricas tipadas e opção neutra separada", () => {
    expect(ANALYSIS_METRICS).toHaveLength(20);
    expect(new Set(ANALYSIS_METRICS.map((item) => item.id)).size).toBe(20);
    expect(createMetricConfiguration(null)).toEqual({ kind: "none" });
  });

  it.each([
    ["count", 5], ["total", 15], ["mean", 3], ["minimum", 1], ["maximum", 5], ["standardDeviation", Math.sqrt(2.5)],
  ] as const)("calcula %s", (metric, expected) => {
    const result = value({ kind: "single", metric });
    expect(result.status).toBe("ok"); expect(result.value).toBeCloseTo(expected);
  });

  it("calcula Cp, Cpk e percentual conforme com limites inclusivos", () => {
    const entries = [series(1, [1, 2, 3, 4, 5])];
    expect(value({ kind: "specification", metric: "cp", lowerSpecification: 0, upperSpecification: 6 }, entries).value).toBeCloseTo(6 / (6 * Math.sqrt(2.5)));
    expect(value({ kind: "specification", metric: "cpk", lowerSpecification: 0, upperSpecification: 6 }, entries).value).toBeCloseTo(3 / (3 * Math.sqrt(2.5)));
    expect(value({ kind: "specification", metric: "pc", lowerSpecification: 1, upperSpecification: 4 }, entries).value).toBe(80);
  });

  it("considera LIC e LSC inclusivos e somente valores estritamente externos como OOC", () => {
    const result = value({ kind: "control", metric: "ooc", lowerControl: 1, upperControl: 4 });
    expect(result.value).toBe(1); expect(result.oocCount).toBe(1);
  });

  it("não fabrica zero para desvio ou capacidade indefinidos", () => {
    expect(value({ kind: "single", metric: "standardDeviation" }, [series(1, [1])]).status).toBe("insufficientData");
    expect(value({ kind: "specification", metric: "cpk", lowerSpecification: 0, upperSpecification: 2 }, [series(1, [1, 1])]).value).toBeNull();
  });

  it("exclui texto, booleano, null, não finitos e qualidade ruim sem coerção", () => {
    const entry = series(1, [1, "600", true, null, NaN, Infinity, 2]);
    entry.points[6].good = false;
    const result = value({ kind: "single", metric: "count" }, [entry]);
    expect(result.value).toBe(1); expect(result.excludedCount).toBe(6);
  });

  it("calcula os sete indicadores básicos de erro em pares UTC exatos", () => {
    const actual = series(1, [2, 4, 8], "bar", ["2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z"]);
    const reference = series(2, [1, 2, 5], "bar", ["2025-12-31T21:00:00-03:00", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z"]);
    const expected: Record<string, number> = { standardDeviationError: 1, meanAbsoluteError: 2, meanSquaredError: 14 / 3, maximumError: 3, meanError: 2, minimumError: 1, rootMeanSquaredError: Math.sqrt(14 / 3) };
    for (const [metric, expectedValue] of Object.entries(expected)) {
      const result = value({ kind: "error", metric: metric as Extract<MetricConfiguration, { kind: "error" }>["metric"], actualTagId: 1, referenceTagId: 2 }, [actual, reference]);
      expect(result.status).toBe("ok"); expect(result.value).toBeCloseTo(expectedValue);
    }
  });

  it("pareia duplicatas de forma estável e ignora timestamps sem par", () => {
    const timestamps = ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z"];
    const actual = series(1, [2, 5, 99], "bar", timestamps);
    const reference = series(2, [1, 3], "bar", timestamps.slice(0, 2));
    const result = value({ kind: "error", metric: "meanError", actualTagId: 1, referenceTagId: 2 }, [actual, reference]);
    expect(result.value).toBe(1.5); expect(result.sampleCount).toBe(2);
  });

  it("calcula Cpk do erro e preserva adimensionalidade", () => {
    const entries = [series(1, [2, 4, 8]), series(2, [1, 2, 5])];
    const result = value({ kind: "errorCapability", metric: "cpkError", actualTagId: 1, referenceTagId: 2, lowerSpecification: -1, upperSpecification: 5 }, entries);
    expect(result.value).toBeCloseTo(1); expect(result.unit).toBeNull();
  });

  it("calcula MAE máximo e médio somente quando o valor real está fora de controle", () => {
    const entries = [series(1, [0, 2, 6]), series(2, [1, 1, 4])];
    const base = { actualTagId: 1, referenceTagId: 2, lowerControl: 1, upperControl: 5 } as const;
    const maximum = value({ kind: "oocError", metric: "oocMaeMaximum", ...base }, entries);
    const average = value({ kind: "oocError", metric: "oocMaeMean", ...base }, entries);
    expect(maximum.value).toBe(2); expect(average.value).toBe(1.5); expect(average.oocCount).toBe(2);
  });

  it("retorna zero válido e oocCount zero quando há pares mas nenhum OOC", () => {
    const result = value({ kind: "oocError", metric: "oocMaeMean", actualTagId: 1, referenceTagId: 2, lowerControl: 0, upperControl: 10 }, [series(1, [1, 2]), series(2, [1, 2])]);
    expect(result.status).toBe("ok"); expect(result.value).toBe(0); expect(result.oocCount).toBe(0);
  });

  it("aplica regras de unidade para valor, quadrado, percentual e índices", () => {
    expect(value({ kind: "single", metric: "mean" }).unit).toBe("bar");
    expect(value({ kind: "error", metric: "meanSquaredError", actualTagId: 1, referenceTagId: 2 }, [series(1, [2]), series(2, [1])]).unit).toBe("bar²");
    expect(value({ kind: "specification", metric: "pc", lowerSpecification: 0, upperSpecification: 6 }).unit).toBe("%");
  });

  it("valida limites, IDs diferentes, disponibilidade e unidades compatíveis", () => {
    expect(validateMetricConfiguration({ kind: "specification", metric: "cp", lowerSpecification: 2, upperSpecification: 1 }, [])).not.toHaveLength(0);
    expect(validateMetricConfiguration({ kind: "error", metric: "meanError", actualTagId: 1, referenceTagId: 1 }, [series(1, [1])])).not.toHaveLength(0);
    expect(validateMetricConfiguration({ kind: "error", metric: "meanError", actualTagId: 1, referenceTagId: 2 }, [series(1, [1], "bar"), series(2, [1], "psi")])).not.toHaveLength(0);
  });

  it("distingue métricas pareadas da mesma tag por instância A/B", () => {
    const actual = { ...series(7, [3, 5]), series_instance_id: "A-7" };
    const reference = { ...series(7, [1, 2]), series_instance_id: "B-7" };
    const result = value({ kind: "error", metric: "meanError", actualTagId: 7, referenceTagId: 7, actualSeriesInstanceId: "A-7", referenceSeriesInstanceId: "B-7" }, [actual, reference]);
    expect(result.status).toBe("ok");
    expect(result.value).toBe(2.5);
    expect(result.seriesInstanceId).toBe("A-7");
    expect(result.referenceSeriesInstanceId).toBe("B-7");
  });

  it("retorna configuração inválida e dados insuficientes sem NaN ou Infinity", () => {
    const invalid = value({ kind: "specification", metric: "cp", lowerSpecification: null, upperSpecification: null });
    const insufficient = value({ kind: "error", metric: "meanError", actualTagId: 1, referenceTagId: 2 }, [series(1, [1]), series(2, [1], "bar", ["2026-01-02T00:00:00Z"])]);
    expect(invalid.status).toBe("invalidConfiguration"); expect(invalid.value).toBeNull();
    expect(insufficient.status).toBe("insufficientData"); expect(JSON.stringify([invalid, insufficient])).not.toMatch(/NaN|Infinity/);
  });
});
