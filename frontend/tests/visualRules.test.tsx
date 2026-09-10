import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VisualRulesPanel } from "../src/components/VisualRulesPanel";
import { buildTimeSeriesChartOption, TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";
import { buildNormLimitSeries, type NormLimitSeries } from "../src/utils/normLimitSeries";
import type { UmChartSeries } from "../src/utils/umChartSeries";
import type { SeriesVisualConfiguration, VisualRulesState } from "../src/types";
import { buildTimeSeriesCsv } from "../src/utils/csv";
import { calculateMetricResults } from "../src/utils/analysisMetrics";
import { moveVisualItem, parseFiniteNumber } from "../src/utils/visualRules";

const visual = (seriesInstanceId: string): SeriesVisualConfiguration => ({ seriesInstanceId, limits: [], normLimit: null });
const chartSeries = (id: string, axis: 0 | 1 = 0): ChartSeries => ({
  tagId: 7,
  displayName: id,
  tagName: "TAG_7",
  equipment: null,
  section: null,
  variableType: null,
  unit: axis ? "rpm" : "bar",
  yAxisIndex: axis,
  color: "#1976d2",
  seriesInstanceId: id,
  total: 3,
  numeric: 3,
  dropped: 0,
  nonNumeric: 0,
  points: [[1, 0], [2, 10], [3, 20]],
  qualitySeries: [[1, 0], [2, 0], [3, 0]],
  valueKind: "numeric",
  statePoints: [],
  stateValues: [],
  stateQualitySeries: [],
});
const chart = (series = [chartSeries("A-7")]): ChartBuildResult => ({
  series,
  units: series.map((item) => item.unit!),
  yAxisLabels: series.map((item) => item.unit!),
  totalSeries: series.length,
  totalPoints: 3 * series.length,
  totalNumericPoints: 3 * series.length,
  totalDroppedPoints: 0,
  totalNonNumericPoints: 0,
  valueKind: "numeric",
  categories: [],
  comparisonType: null,
});
const props = (
  result: ChartBuildResult,
  visualRules?: VisualRulesState,
  normLimitSeries?: NormLimitSeries[],
  umSeries?: UmChartSeries | null,
) => ({
  chart: result,
  equipment: "EQ",
  start: new Date(0),
  end: new Date(1000),
  mode: "recorded" as const,
  visualRules,
  normLimitSeries: normLimitSeries ?? [],
  umSeries: umSeries ?? null,
});

describe("semântica de limites", () => {
  it.each([["0", 0], ["-1.5", -1.5], ["2.75", 2.75]])("aceita número finito %s", (raw, expected) =>
    expect(parseFiniteNumber(raw)).toBe(expected),
  );
  it.each(["", "NaN", "Infinity", "-Infinity", "abc"])("rejeita entrada inválida %s", (raw) =>
    expect(parseFiniteNumber(raw)).toBeNull(),
  );
});

describe("integração ECharts sem alterar dados", () => {
  it("desativado mantém a opção anterior", () => {
    const baseline = buildTimeSeriesChartOption(props(chart()));
    const disabled = buildTimeSeriesChartOption(
      props(chart(), { enabled: false, selectedSeriesInstanceId: null, bySeries: { "A-7": visual("A-7") } }),
    );
    expect(JSON.stringify(disabled)).toBe(JSON.stringify(baseline));
  });
  it("desenha limite fixo via markLine", () => {
    const config: SeriesVisualConfiguration = {
      ...visual("A-7"),
      limits: [{ id: "l", value: 5, label: "Limite 5", color: "#ff0000", lineStyle: "dashed", width: 2, visible: true }],
    };
    const option = buildTimeSeriesChartOption(
      props(chart(), { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": config } }),
    ) as any;
    expect(option.series[0].markLine.data[0].yAxis).toBe(5);
    expect(option.series[0].markLine.data[0].lineStyle.color).toBe("#ff0000");
  });
  it("limite fixo não afeta os pontos da série principal", () => {
    const config: SeriesVisualConfiguration = {
      ...visual("A-7"),
      limits: [{ id: "l", value: 5, label: "Limite 5", color: "#ff0000", lineStyle: "dashed", width: 2, visible: true }],
    };
    const option = buildTimeSeriesChartOption(
      props(chart(), { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": config } }),
    ) as any;
    expect(option.series[0].data).toEqual([[1, 0], [2, 10], [3, 20]]);
  });
  it("limites fixos em séries distintas usam o eixo correto", () => {
    const state: VisualRulesState = {
      enabled: true,
      selectedSeriesInstanceId: "A-7",
      bySeries: {
        "A-7": { ...visual("A-7"), limits: [{ id: "a", value: 800, label: "A", color: "#ff0000", lineStyle: "solid", width: 1, visible: true }] },
        "B-7": { ...visual("B-7"), limits: [{ id: "b", value: 850, label: "B", color: "#00ff00", lineStyle: "solid", width: 1, visible: true }] },
      },
    };
    const option = buildTimeSeriesChartOption(props(chart([chartSeries("A-7"), chartSeries("B-7", 1)]), state)) as any;
    expect(option.series.map((item: any) => item.markLine.data[0].yAxis)).toEqual([800, 850]);
  });
  it("tooltip preserva valor e não cita faixa nem regra", () => {
    const config: SeriesVisualConfiguration = { ...visual("A-7") };
    const option = buildTimeSeriesChartOption(
      props(chart(), { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": config } }),
    ) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [2, 10], dataIndex: 1, seriesIndex: 0, marker: "•", axisValueLabel: "tempo" },
    ]);
    expect(text).toContain("10");
    expect(text).not.toContain("Regra");
    expect(text).not.toContain("Faixa");
  });
  it("limites fixos e de norma coexistem no mesmo gráfico", () => {
    const config: SeriesVisualConfiguration = {
      ...visual("A-7"),
      limits: [{ id: "fix", value: 12, label: "Fixo", color: "#0000ff", lineStyle: "solid", width: 2, visible: true }],
      normLimit: { enabled: true, lowerColor: "#d32f2f", upperColor: "#d32f2f", lineStyle: "dashed", width: 2 },
    };
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_NORM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 1]],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(props(chart(), { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": config } }, normLimitSeries)) as any;
    expect(option.series[0].markLine.data[0].yAxis).toBe(12);
    const lower = option.series.find((s: any) => s.id === `norm-lower:A-7`);
    const upper = option.series.find((s: any) => s.id === `norm-upper:A-7`);
    expect(lower).toBeDefined();
    expect(upper).toBeDefined();
    expect(lower.yAxisIndex).toBe(0);
    expect(upper.yAxisIndex).toBe(0);
  });

  function umInput(categories: string[], steps: Array<[number, string]>): UmChartSeries {
    return {
      seriesInstanceId: "A-7",
      tagId: 8,
      tagName: "UM_TAG",
      displayName: "UM",
      unit: null,
      color: "#0288d1",
      categories,
      steps: steps.map(([ts, code]) => [ts, categories.indexOf(code), code]),
      qualitySeries: [],
      total: steps.length,
    };
  }

  function maxYAxisIndex(option: any): number {
    let max = -1;
    for (const s of option.series ?? []) {
      if (typeof s.yAxisIndex === "number" && s.yAxisIndex > max) max = s.yAxisIndex;
    }
    return max;
  }

  function yAxisLen(option: any): number {
    return Array.isArray(option.yAxis) ? option.yAxis.length : 0;
  }

  it("gera exatamente 1 eixo Y numérico sem UM e sem limites", () => {
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    expect(yAxisLen(option)).toBe(1);
    expect(option.yAxis[0].type).toBe("value");
    expect(maxYAxisIndex(option)).toBe(0);
    expect(yAxisLen(option)).toBeGreaterThan(0);
  });

  it("gera 1 eixo numérico + 1 categórico da UM quando só há UM", () => {
    const um = umInput(["P304I", "P316B"], [[0, "P304I"], [1, "P316B"]]);
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, undefined, um),
    ) as any;
    expect(yAxisLen(option)).toBe(2);
    expect(yAxisLen(option)).toBeGreaterThan(0);
    const umSeries = option.series.find((s: any) => s.id === `um:A-7`);
    expect(umSeries).toBeDefined();
    expect(umSeries.yAxisIndex).toBe(1);
    expect(umSeries.yAxisIndex).toBeLessThan(yAxisLen(option));
    expect(umSeries.step).toBe("end");
  });

  it("gera eixo numérico + UM quando há 1 eixo numérico pré-existente", () => {
    const um = umInput(["P304I"], [[0, "P304I"]]);
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, undefined, um),
    ) as any;
    expect(yAxisLen(option)).toBe(2);
    const umSeries = option.series.find((s: any) => s.id === `um:A-7`);
    expect(umSeries.yAxisIndex).toBe(1);
    expect(maxYAxisIndex(option)).toBeLessThan(yAxisLen(option));
  });

  it("gera 2 eixos numéricos + UM quando há 2 eixos numéricos pré-existentes", () => {
    const um = umInput(["P304I"], [[0, "P304I"]]);
    const option = buildTimeSeriesChartOption(
      props(chart([chartSeries("A-7"), chartSeries("B-7", 1)]), undefined, undefined, um),
    ) as any;
    expect(yAxisLen(option)).toBe(3);
    const umSeries = option.series.find((s: any) => s.id === `um:A-7`);
    expect(umSeries.yAxisIndex).toBe(2);
    expect(maxYAxisIndex(option)).toBeLessThan(yAxisLen(option));
  });

  it("limites inferiores e superiores usam yAxisIndex 0 (eixo principal)", () => {
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_NORM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 1]],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, normLimitSeries),
    ) as any;
    const lower = option.series.find((s: any) => s.id === `norm-lower:A-7`);
    const upper = option.series.find((s: any) => s.id === `norm-upper:A-7`);
    expect(lower.yAxisIndex).toBe(0);
    expect(upper.yAxisIndex).toBe(0);
    expect(maxYAxisIndex(option)).toBeLessThan(yAxisLen(option));
  });

  it("limite inferior ausente não remove a variável principal", () => {
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_NORM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, normLimitSeries),
    ) as any;
    expect(option.series[0].yAxisIndex).toBe(0);
    expect(yAxisLen(option)).toBeGreaterThan(0);
    expect(option.series.find((s: any) => s.id === "norm-lower:A-7")).toBeUndefined();
    expect(option.series.find((s: any) => s.id === "norm-upper:A-7")).toBeDefined();
  });

  it("eixo categorico da UM e completamente oculto sem grid, sem rotulos e sem ticks", () => {
    const um = umInput(["P304I", "P316B"], [[0, "P304I"], [1, "P316B"]]);
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, undefined, um),
    ) as any;
    expect(option.yAxis).toHaveLength(2);
    // Eixo 0: numérico visível
    expect(option.yAxis[0].type).toBe("value");
    expect(option.yAxis[0].show).not.toBe(false);
    // Eixo 1: UM oculto
    const umAxis = option.yAxis[1];
    expect(umAxis.type).toBe("category");
    expect(umAxis.show).toBe(false);
    expect(umAxis.axisLabel).toEqual({ show: false });
    expect(umAxis.axisTick).toEqual({ show: false });
    expect(umAxis.axisLine).toEqual({ show: false });
    expect(umAxis.splitLine).toEqual({ show: false });
    expect(umAxis.splitArea).toEqual({ show: false });
    expect(umAxis.axisPointer).toEqual({ show: false });
    // Margem lateral padrão sem offset excessivo
    expect(option.grid.left).toBe(45);
  });

  it("limites de norma herdam dinamicamente o yAxisIndex da variavel principal", () => {
    const seriesA = chartSeries("A-7", 0);
    const seriesB = chartSeries("B-7", 1);
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "B-7",
        mainDisplayName: "Escova 01",
        tagName: "TAG_B",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 5]],
        upperPoints: [[1, 15]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart([seriesA, seriesB]), undefined, normLimitSeries),
    ) as any;
    const lower = option.series.find((s: any) => s.id === "norm-lower:B-7");
    const upper = option.series.find((s: any) => s.id === "norm-upper:B-7");
    expect(lower).toBeDefined();
    expect(upper).toBeDefined();
    expect(lower.yAxisIndex).toBe(1);
    expect(upper.yAxisIndex).toBe(1);
  });

  it("limite unico (apenas inferior ou apenas superior) renderiza somente a linha cadastrada", () => {
    const onlyLower: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        mainDisplayName: "Escova 01",
        tagName: "TAG_A",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 5], [2, 5]],
        upperPoints: [],
      },
    ];
    const optLower = buildTimeSeriesChartOption(props(chart(), undefined, onlyLower)) as any;
    expect(optLower.series.find((s: any) => s.id === "norm-lower:A-7")).toBeDefined();
    expect(optLower.series.find((s: any) => s.id === "norm-upper:A-7")).toBeUndefined();
    expect(optLower.legend.data).toContain("Limite inferior — Escova 01");
    expect(optLower.legend.data).not.toContain("Limite superior — Escova 01");

    const onlyUpper: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        mainDisplayName: "Escova 01",
        tagName: "TAG_A",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [],
        upperPoints: [[1, 20], [2, 20]],
      },
    ];
    const optUpper = buildTimeSeriesChartOption(props(chart(), undefined, onlyUpper)) as any;
    expect(optUpper.series.find((s: any) => s.id === "norm-lower:A-7")).toBeUndefined();
    expect(optUpper.series.find((s: any) => s.id === "norm-upper:A-7")).toBeDefined();
    expect(optUpper.legend.data).not.toContain("Limite inferior — Escova 01");
    expect(optUpper.legend.data).toContain("Limite superior — Escova 01");
  });

  it("limite constante unico e projetado ao longo de todo o intervalo de tempo", () => {
    const startIso = "2026-01-01T00:00:00.000Z";
    const endIso = "2026-01-01T12:00:00.000Z";
    const startMs = Date.parse(startIso);
    const endMs = Date.parse(endIso);

    const built = buildNormLimitSeries({
      seriesInstanceId: "A-7",
      tagName: "LFI_RB1_COR_ESC1",
      mainDisplayName: "Escova 01",
      lowerTagName: "LIM_INF",
      upperTagName: "LIM_SUP",
      yAxisIndex: 0,
      lineStyle: "dashed",
      width: 2,
      lowerColor: "#d32f2f",
      upperColor: "#d32f2f",
      lowerPoints: [{ timestamp: "2026-01-01T06:00:00.000Z", value: 40 }],
      upperPoints: [{ timestamp: "2026-01-01T06:00:00.000Z", value: 120 }],
      startTimeIso: startIso,
      endTimeIso: endIso,
    });

    expect(built.lowerPoints).toEqual([
      [startMs, 40],
      [endMs, 40],
    ]);
    expect(built.upperPoints).toEqual([
      [startMs, 120],
      [endMs, 120],
    ]);
  });

  it("legenda e tooltip identificam os limites por variavel principal", () => {
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        mainDisplayName: "Escova 01",
        tagName: "LFI_RB1_COR_ESC1",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 5]],
        upperPoints: [[1, 25]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, normLimitSeries),
    ) as any;

    expect(option.legend.data).toContain("Limite inferior — Escova 01");
    expect(option.legend.data).toContain("Limite superior — Escova 01");

    const tooltipHtml = option.tooltip.formatter([
      { seriesId: "norm-lower:A-7", seriesName: "Limite inferior — Escova 01", value: [1, 5], dataIndex: 0, seriesIndex: 1, marker: "•", axisValueLabel: "t" },
      { seriesId: "norm-upper:A-7", seriesName: "Limite superior — Escova 01", value: [1, 25], dataIndex: 0, seriesIndex: 2, marker: "•", axisValueLabel: "t" },
    ]);

    expect(tooltipHtml).toContain("Limite inferior — Escova 01");
    expect(tooltipHtml).toContain("Limite superior — Escova 01");
    expect(tooltipHtml).toContain("5");
    expect(tooltipHtml).toContain("25");
  });

  it("UM com valores textuais, numéricos como string e -999", () => {
    const um = umInput(
      ["P304I", "P316B", "664666E08", "-999"],
      [
        [0, "P304I"],
        [1, "P316B"],
        [2, "664666E08"],
        [3, "-999"],
      ],
    );
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, undefined, um),
    ) as any;
    const umSeries = option.series.find((s: any) => s.id === `um:A-7`);
    expect(umSeries).toBeDefined();
    expect(umSeries.yAxisIndex).toBeLessThan(yAxisLen(option));
    expect(umSeries.data.map((d: [number, number]) => d[1])).toEqual([0, 1, 2, 3]);
    expect(umSeries.step).toBe("end");
    expect(umSeries.connectNulls).toBe(false);
  });

  it("nunca retorna yAxis vazio", () => {
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    expect(Array.isArray(option.yAxis)).toBe(true);
    expect(option.yAxis.length).toBeGreaterThan(0);
  });

  it("todo yAxisIndex referencia um eixo existente", () => {
    const um = umInput(["P304I", "P316B"], [[0, "P304I"], [1, "P316B"]]);
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_NORM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 1]],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart([chartSeries("A-7"), chartSeries("B-7", 1)]), undefined, normLimitSeries, um),
    ) as any;
    const totalAxes = option.yAxis.length;
    for (const s of option.series) {
      expect(s.yAxisIndex).toBeLessThan(totalAxes);
      expect(s.yAxisIndex).toBeGreaterThanOrEqual(0);
    }
  });

  it("tooltip usa seriesId, não seriesIndex, para localizar UM e limites", () => {
    const um = umInput(["P304I"], [[0, "P304I"]]);
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_LIM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 5]],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(
      props(chart(), undefined, normLimitSeries, um),
    ) as any;
    const lowerIdx = option.series.findIndex((s: any) => s.id === `norm-lower:A-7`);
    const upperIdx = option.series.findIndex((s: any) => s.id === `norm-upper:A-7`);
    const umIdx = option.series.findIndex((s: any) => s.id === `um:A-7`);
    const text = option.tooltip.formatter([
      { seriesId: "norm-lower:A-7", seriesName: "Limite inferior", value: [1, 5], dataIndex: 0, seriesIndex: lowerIdx, marker: "•", axisValueLabel: "t" },
      { seriesId: "norm-upper:A-7", seriesName: "Limite superior", value: [1, 9], dataIndex: 0, seriesIndex: upperIdx, marker: "•", axisValueLabel: "t" },
      { seriesId: "um:A-7", seriesName: "UM", value: [0, 0], dataIndex: 0, seriesIndex: umIdx, marker: "•", axisValueLabel: "t" },
    ]);
    expect(text).toContain("Limite inferior");
    expect(text).toContain("Limite superior");
    expect(text).toContain("P304I");
    expect(text).not.toContain("Regra");
  });

  it("tooltip formata cabeçalho como Data e hora: DD/MM/AAAA HH:mm:ss em America/Sao_Paulo", () => {
    const tsIso = "2026-07-01T15:30:45.000Z";
    const tsMs = Date.parse(tsIso);
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [tsMs, 52.4], dataIndex: 0, marker: "•", axisValue: tsMs },
    ]);
    expect(text).toContain("Data e hora: 01/07/2026 12:30:45");
    expect(text).toContain("52,4 bar");
  });

  it("indica timestamp da amostra quando difere do instante consultado", () => {
    const hoveredTs = Date.parse("2026-07-01T15:30:45.000Z");
    const sampleTs = Date.parse("2026-07-01T15:30:15.000Z"); // 30 segundos antes
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [sampleTs, 18.5], dataIndex: 0, marker: "•", axisValue: hoveredTs },
    ]);
    expect(text).toContain("Data e hora: 01/07/2026 12:30:45");
    expect(text).toContain("(amostra: 12:30:15)");
    expect(text).toContain("18,5 bar");
  });

  it("UM resolve o código textual ativo no instante consultado e não exibe índice", () => {
    const step1Ts = Date.parse("2026-07-01T10:00:00.000Z");
    const step2Ts = Date.parse("2026-07-01T11:00:00.000Z");
    const hoveredTs = Date.parse("2026-07-01T10:30:00.000Z");
    const um = umInput(["P304I", "P316B"], [
      [step1Ts, "P304I"],
      [step2Ts, "P316B"],
    ]);
    const option = buildTimeSeriesChartOption(props(chart(), undefined, undefined, um)) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [hoveredTs, 10], dataIndex: 0, marker: "•", axisValue: hoveredTs },
      { seriesId: "um:A-7", seriesName: "UM", value: [step1Ts, 0], dataIndex: 0, marker: "•", axisValue: hoveredTs },
    ]);
    expect(text).toContain("<strong>UM</strong>: P304I");
    expect(text).not.toContain("<strong>UM</strong>: 0");
  });

  it("dados ausentes ou nulos exibem (sem dado) sem inventar zero", () => {
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [1000, null], dataIndex: 0, marker: "•", axisValue: 1000 },
    ]);
    expect(text).toContain("(sem dado)");
    expect(text).not.toContain("0 bar");
  });

  it("qualidade não-OK exibe indicação clara no tooltip", () => {
    const ts = 1000;
    const seriesWithBadQuality: ChartSeries = {
      ...chartSeries("A-7"),
      points: [[ts, 15]],
      qualitySeries: [[ts, 3]], // 3 = Ruim
    };
    const option = buildTimeSeriesChartOption(props(chart([seriesWithBadQuality]))) as any;
    const text = option.tooltip.formatter([
      { seriesId: "A-7", seriesName: "A-7", value: [ts, 15], dataIndex: 0, marker: "•", axisValue: ts },
    ]);
    expect(text).toContain("Ruim");
  });

  it("todas as curvas possuem emphasis.focus none para manter estabilidade visual sem desfoque", () => {
    const um = umInput(["P304I"], [[0, "P304I"]]);
    const normLimitSeries: NormLimitSeries[] = [
      {
        seriesInstanceId: "A-7",
        tagName: "TAG_NORM",
        yAxisIndex: 0,
        lowerColor: "#d32f2f",
        upperColor: "#d32f2f",
        lineStyle: "dashed",
        width: 2,
        lowerPoints: [[1, 1]],
        upperPoints: [[1, 9]],
      },
    ];
    const option = buildTimeSeriesChartOption(props(chart(), undefined, normLimitSeries, um)) as any;
    for (const s of option.series) {
      expect(s.emphasis?.focus).toBe("none");
    }
  });

  it("tooltip possui pointer-events none, confine e ponteiro temporal tipo line", () => {
    const option = buildTimeSeriesChartOption(props(chart())) as any;
    expect(option.tooltip.trigger).toBe("axis");
    expect(option.tooltip.confine).toBe(true);
    expect(option.tooltip.extraCssText).toContain("pointer-events: none");
    expect(option.tooltip.axisPointer.type).toBe("line");
    // Todos os eixos Y ocultam o axisPointer para evitar marcadores redundantes
    for (const y of option.yAxis) {
      expect(y.axisPointer?.show).toBe(false);
    }
  });
  it("métricas e CSV permanecem idênticos porque configuração não entra nos cálculos", () => {
    const timeSeries = {
      start_time: "2026-01-01T00:00:00Z",
      end_time: "2026-01-01T00:00:02Z",
      mode: "recorded" as const,
      errors: [],
      series: [
        {
          tag_id: 7,
          tag_name: "TAG_7",
          display_name: "Tag 7",
          equipment: null,
          section: null,
          variable_type: null,
          unit: "bar",
          series_instance_id: "A-7",
          points: [0, 10, 20].map((value, index) => ({
            timestamp: `2026-01-01T00:00:0${index}Z`,
            value,
            good: true,
            questionable: false,
            substituted: false,
          })),
        },
      ],
    };
    const metric = calculateMetricResults(timeSeries.series, { kind: "single", metric: "mean" }, false);
    const csv = buildTimeSeriesCsv(timeSeries);
    expect(calculateMetricResults(timeSeries.series, { kind: "single", metric: "mean" }, false)).toEqual(metric);
    expect(buildTimeSeriesCsv(timeSeries)).toBe(csv);
    expect(csv.split("\n")).toHaveLength(5);
  });
});

describe("painel local", () => {
  it("inicia desativado e alterações locais não chamam cliente HTTP", () => {
    const onChange = vi.fn();
    render(
      <VisualRulesPanel
        state={{ enabled: false, selectedSeriesInstanceId: null, bySeries: {} }}
        series={[{ seriesInstanceId: "A-7", label: "A", numeric: true }]}
        onChange={(next) => {
          onChange(next);
        }}
      />,
    );
    expect(screen.getByText("Desativado")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("visual-rules-enabled"));
    expect(onChange).toHaveBeenCalledOnce();
  });
  it("informa indisponibilidade para série textual", () => {
    const state = { enabled: true, selectedSeriesInstanceId: "T-1", bySeries: {} };
    render(
      <VisualRulesPanel
        state={state}
        series={[{ seriesInstanceId: "T-1", label: "Texto", numeric: false }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Limites numéricos não estão disponíveis para esta série.")).toBeInTheDocument();
  });
  it("reset geral exige confirmação", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChange = vi.fn();
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: { A: visual("A") } }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByText("Restaurar tudo"));
    expect(window.confirm).toHaveBeenCalled();
    expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].bySeries).toEqual({});
  });
  it("título do painel é Limites", () => {
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: {} }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Limites" })).toBeInTheDocument();
  });
  it("exibe botões de limite fixo e de norma quando viável", () => {
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: {} }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
        onAddNormLimit={vi.fn()}
        selectedPiTag={{ id: 1, lowerLimitTag: "TAG_LIM_INF", upperLimitTag: "TAG_LIM_SUP" }}
      />,
    );
    expect(screen.getByTestId("add-fixed-limit")).toBeInTheDocument();
    expect(screen.getByTestId("add-norm-limit")).toBeInTheDocument();
  });
  it("não renderiza faixas nem regras", () => {
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: {} }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByText("Faixas coloridas")).toBeNull();
    expect(screen.queryByText("Regras de cores")).toBeNull();
  });
  it("não permite adicionar a norma duas vezes para a mesma série", () => {
    const onAdd = vi.fn();
    render(
      <VisualRulesPanel
        state={{
          enabled: true,
          selectedSeriesInstanceId: "A",
          bySeries: { A: { ...visual("A"), normLimit: { enabled: true, lowerColor: "#d32f2f", upperColor: "#d32f2f", lineStyle: "dashed", width: 2 } } },
        }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
        onAddNormLimit={onAdd}
        onRemoveNormLimit={vi.fn()}
        selectedPiTag={{ id: 1, lowerLimitTag: "L", upperLimitTag: "U" }}
      />,
    );
    expect(screen.queryByTestId("add-norm-limit")).toBeNull();
    expect(screen.getByTestId("remove-norm-limit")).toBeInTheDocument();
  });
  it("desabilita o botão de norma quando os limites não estão cadastrados", () => {
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: {} }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
        onAddNormLimit={vi.fn()}
        selectedPiTag={{ id: 1, lowerLimitTag: "L", upperLimitTag: null }}
      />,
    );
    expect(screen.getByTestId("add-norm-limit")).toBeDisabled();
    expect(screen.getByTestId("norm-limit-message")).toHaveTextContent("nao possui tags de limite cadastradas");
  });
  it("não permite norma quando a série não tem tag PI correspondente", () => {
    render(
      <VisualRulesPanel
        state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: {} }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
        onAddNormLimit={vi.fn()}
        selectedPiTag={null}
      />,
    );
    expect(screen.getByTestId("add-norm-limit")).toBeDisabled();
    expect(screen.getByTestId("norm-limit-message")).toHaveTextContent("Selecione uma serie com tag PI");
  });
  it("exibe erro de carregamento da norma sem remover o gráfico principal", async () => {
    render(
      <VisualRulesPanel
        state={{
          enabled: true,
          selectedSeriesInstanceId: "A",
          bySeries: { A: { ...visual("A"), normLimit: { enabled: true, lowerColor: "#d32f2f", upperColor: "#d32f2f", lineStyle: "dashed", width: 2 } } },
        }}
        series={[{ seriesInstanceId: "A", label: "A", numeric: true }]}
        onChange={vi.fn()}
        onAddNormLimit={vi.fn()}
        onRemoveNormLimit={vi.fn()}
        normLimits={{ A: { status: "error", error: "Falha ao consultar limites", lowerTagName: null, upperTagName: null } }}
        selectedPiTag={{ id: 1, lowerLimitTag: "L", upperLimitTag: "U" }}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("norm-limit-error")).toHaveTextContent("Falha ao consultar limites"),
    );
    expect(screen.getByTestId("remove-norm-limit")).toBeInTheDocument();
  });
  it("preserva reordenação de limites fixos", () => {
    const items = [{ id: "a", value: 1, label: "A", color: "#fff", lineStyle: "solid" as const, width: 1, visible: true }];
    const moved = moveVisualItem(items, 0, "down");
    expect(moved).toEqual(items);
  });

  describe("cursor interativo arrastável (pinned cursor)", () => {
    it("renderiza markLine vertical com timestamp e desativa pan de arrasto no dataZoom", () => {
      const cursorTs = 1725418751000; // 04/09/2026 02:59:11
      const option = buildTimeSeriesChartOption({
        ...props(chart()),
        pinnedCursorTs: cursorTs,
        onClearCursor: vi.fn(),
      }) as any;

      // dataZoom inside não deve mover no mousemove para permitir arrasto do cursor
      expect(option.dataZoom[0].type).toBe("inside");
      expect(option.dataZoom[0].moveOnMouseMove).toBe(false);
      expect(option.dataZoom[0].zoomOnMouseWheel).toBe(true);

      // tooltip mantém conteúdo ativo quando cursor está fixado
      expect(option.tooltip.alwaysShowContent).toBe(true);

      // botão myClearCursor adicionado na toolbox
      expect(option.toolbox.feature.myClearCursor).toBeDefined();
      expect(option.toolbox.feature.myClearCursor.show).toBe(true);

      // série principal possui a markLine vertical do cursor
      const mainSeries = option.series[0];
      expect(mainSeries.markLine).toBeDefined();
      const cursorLine = mainSeries.markLine.data.find((item: any) => item.name === "Cursor");
      expect(cursorLine).toBeDefined();
      expect(cursorLine.xAxis).toBe(cursorTs);
      expect(cursorLine.lineStyle.type).toBe("dashed");
      expect(cursorLine.label.position).toBe("insideEndTop");
    });

    it("quando pinnedCursorTs é nulo, não adiciona markLine de cursor nem botão myClearCursor", () => {
      const option = buildTimeSeriesChartOption({
        ...props(chart()),
        pinnedCursorTs: null,
      }) as any;

      expect(option.tooltip.alwaysShowContent).toBe(false);
      expect(option.toolbox.feature.myClearCursor).toBeUndefined();
      expect(option.series[0].markLine).toBeUndefined();
    });

    it("em gráficos textuais/estados, também renderiza markLine vertical quando pinnedCursorTs é definido", () => {
      const cursorTs = 1725418751000;
      const textualChart: ChartBuildResult = {
        ...chart(),
        valueKind: "textual",
        categories: ["A", "B"],
      };
      const option = buildTimeSeriesChartOption({
        ...props(textualChart),
        pinnedCursorTs: cursorTs,
        onClearCursor: vi.fn(),
      }) as any;

      expect(option.dataZoom[0].moveOnMouseMove).toBe(false);
      expect(option.tooltip.alwaysShowContent).toBe(true);
      expect(option.toolbox.feature.myClearCursor).toBeDefined();
      expect(option.series[0].markLine).toBeDefined();
      const cursorLine = option.series[0].markLine.data.find((item: any) => item.name === "Cursor");
      expect(cursorLine).toBeDefined();
      expect(cursorLine.xAxis).toBe(cursorTs);
    });

    it("componente TimeSeriesChart exibe o toolbar do marcador quando pinnedCursorTs é definido", () => {
      const cursorTs = 1725418751000;
      render(
        <TimeSeriesChart
          {...props(chart([
            { ...chartSeries("A-7"), displayName: "Zona 1", tagName: "TAG_COMPLEXA_PI_123" },
          ]))}
          pinnedCursorTs={cursorTs}
        />,
      );

      const toolbar = screen.getByTestId("markers-toolbar");
      expect(toolbar).toBeInTheDocument();
      expect(toolbar).toHaveTextContent("Marcador:");
    });
  });
});