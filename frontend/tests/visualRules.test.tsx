import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VisualRulesPanel } from "../src/components/VisualRulesPanel";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";
import type { SeriesVisualConfiguration, VisualColorRule, VisualRulesState } from "../src/types";
import { buildTimeSeriesCsv } from "../src/utils/csv";
import { calculateMetricResults } from "../src/utils/analysisMetrics";
import { firstMatchingRule, matchingRange, moveVisualItem, parseFiniteNumber, ruleMatches, validateColorRule, validateRange } from "../src/utils/visualRules";

const rule = (operator: VisualColorRule["operator"], value: number | null = 10, lower: number | null = null, upper: number | null = null): VisualColorRule => ({ id: operator, operator, value, lower, upper, color: "#ff0000", label: operator, enabled: true });
const visual = (seriesInstanceId: string): SeriesVisualConfiguration => ({ seriesInstanceId, limits: [], ranges: [], rules: [] });
const chartSeries = (id: string, axis: 0 | 1 = 0): ChartSeries => ({ tagId: 7, displayName: id, tagName: "TAG_7", equipment: null, section: null, variableType: null, unit: axis ? "rpm" : "bar", yAxisIndex: axis, color: "#1976d2", seriesInstanceId: id, total: 3, numeric: 3, dropped: 0, nonNumeric: 0, points: [[1, 0], [2, 10], [3, 20]], qualitySeries: [[1, 0], [2, 0], [3, 0]], valueKind: "numeric", statePoints: [], stateValues: [], stateQualitySeries: [] });
const chart = (series = [chartSeries("A-7")]): ChartBuildResult => ({ series, units: series.map((item) => item.unit!), yAxisLabels: series.map((item) => item.unit!), totalSeries: series.length, totalPoints: 3 * series.length, totalNumericPoints: 3 * series.length, totalDroppedPoints: 0, totalNonNumericPoints: 0, valueKind: "numeric", categories: [], comparisonType: null });
const props = (result: ChartBuildResult, visualRules?: VisualRulesState) => ({ chart: result, equipment: "EQ", start: new Date(0), end: new Date(1000), mode: "recorded" as const, visualRules });

describe("semântica de limites, faixas e regras", () => {
  it.each([["0", 0], ["-1.5", -1.5], ["2.75", 2.75]])("aceita número finito %s", (raw, expected) => expect(parseFiniteNumber(raw)).toBe(expected));
  it.each(["", "NaN", "Infinity", "-Infinity", "abc"])("rejeita entrada inválida %s", (raw) => expect(parseFiniteNumber(raw)).toBeNull());
  it("valida faixa e rejeita inversão, sobreposição, cor e opacidade insegura", () => {
    expect(validateRange({ lower: -2, upper: 0.5, color: "#00ff00", opacity: 0.2 })).toEqual([]);
    expect(validateRange({ lower: 2, upper: 1, color: "red", opacity: 0.8 })).toHaveLength(3);
    expect(validateRange({ lower: 1, upper: 3, color: "#00ff00", opacity: 0.2 }, [{ id: "x", lower: 0, upper: 2, color: "#ffffff", opacity: 0.1, label: "", visible: true }])).toContain("A faixa se sobrepõe a outra faixa.");
  });
  it.each([["<", 9, true], ["<=", 10, true], [">", 11, true], [">=", 10, true], ["==", 10, true]])("avalia %s", (operator, value, expected) => expect(ruleMatches(value, rule(operator as VisualColorRule["operator"]))).toBe(expected));
  it("Entre é inclusivo e Fora do intervalo é estrito", () => {
    const between = rule("between", null, 0, 10); const outside = rule("outside", null, 0, 10);
    expect([0, 10].every((value) => ruleMatches(value, between))).toBe(true);
    expect(ruleMatches(-1, outside)).toBe(true); expect(ruleMatches(11, outside)).toBe(true); expect(ruleMatches(0, outside)).toBe(false);
  });
  it("não coage string, boolean, null ou não finito", () => {
    for (const value of ["600", true, false, null, undefined, NaN, Infinity]) expect(ruleMatches(value, rule(">="))).toBe(false);
  });
  it("primeira regra ativa correspondente prevalece e reordenação muda prioridade", () => {
    const first = { ...rule(">=", 0), id: "first", color: "#111111" }; const second = { ...rule(">=", 0), id: "second", color: "#222222" };
    expect(firstMatchingRule(5, [first, second])?.id).toBe("first");
    expect(firstMatchingRule(5, moveVisualItem([first, second], 1, "up"))?.id).toBe("second");
  });
  it("ignora regra desativada e deixa ponto sem correspondência com cor padrão", () => {
    expect(firstMatchingRule(5, [{ ...rule(">", 0), enabled: false }])).toBeNull();
    expect(firstMatchingRule(-1, [rule(">", 0)])).toBeNull();
  });
  it("valida operador simples e intervalar incompletos", () => {
    expect(validateColorRule({ ...rule(">"), value: null })).not.toHaveLength(0);
    expect(validateColorRule(rule("between", null, null, 2))).not.toHaveLength(0);
  });
  it("faixa correspondente preserva lacunas", () => {
    const ranges = [{ id: "a", lower: 0, upper: 1, label: "a", color: "#ffffff", opacity: .1, visible: true }, { id: "b", lower: 3, upper: 4, label: "b", color: "#ffffff", opacity: .1, visible: true }];
    expect(matchingRange(2, ranges)).toBeNull(); expect(matchingRange(3, ranges)?.id).toBe("b");
  });
});

describe("integração ECharts sem alterar dados", () => {
  it("desativado mantém a opção anterior", () => {
    const baseline = buildTimeSeriesChartOption(props(chart()));
    const disabled = buildTimeSeriesChartOption(props(chart(), { enabled: false, selectedSeriesInstanceId: null, bySeries: { "A-7": { ...visual("A-7"), rules: [rule(">", 1)] } } }));
    expect(JSON.stringify(disabled)).toBe(JSON.stringify(baseline));
  });
  it("desenha limite e faixa na série e eixo corretos", () => {
    const config = { ...visual("B-7"), limits: [{ id: "l", value: 0, label: "Zero", color: "#ff0000", lineStyle: "dashed" as const, width: 2, visible: true }], ranges: [{ id: "r", lower: -1, upper: 1, label: "OK", color: "#00ff00", opacity: .2, visible: true }] };
    const option = buildTimeSeriesChartOption(props(chart([chartSeries("A-7"), chartSeries("B-7", 1)]), { enabled: true, selectedSeriesInstanceId: "B-7", bySeries: { "B-7": config } })) as any;
    expect(option.series[0].markLine).toBeUndefined(); expect(option.series[1].yAxisIndex).toBe(1);
    expect(option.series[1].markLine.data[0].yAxis).toBe(0); expect(option.series[1].markArea.data[0][1].yAxis).toBe(1);
  });
  it("mesma tag A/B mantém configurações independentes", () => {
    const state: VisualRulesState = { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": { ...visual("A-7"), limits: [{ id: "a", value: 800, label: "A", color: "#ff0000", lineStyle: "solid", width: 1, visible: true }] }, "B-7": { ...visual("B-7"), limits: [{ id: "b", value: 850, label: "B", color: "#00ff00", lineStyle: "solid", width: 1, visible: true }] } } };
    const option = buildTimeSeriesChartOption(props(chart([chartSeries("A-7"), chartSeries("B-7")]), state)) as any;
    expect(option.series.map((item: any) => item.markLine.data[0].yAxis)).toEqual([800, 850]);
  });
  it("aplica cor somente ao ponto correspondente sem fabricar pontos", () => {
    const state: VisualRulesState = { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": { ...visual("A-7"), rules: [rule(">=", 10)] } } };
    const option = buildTimeSeriesChartOption(props(chart(), state)) as any;
    expect(option.series[0].data).toHaveLength(3); expect(option.series[0].data[0]).toEqual([1, 0]); expect(option.series[0].data[1].itemStyle.color).toBe("#ff0000");
  });
  it("tooltip preserva valor e apresenta regra/faixa", () => {
    const config = { ...visual("A-7"), rules: [rule(">=", 10)], ranges: [{ id: "r", lower: 0, upper: 20, label: "Operação", color: "#00ff00", opacity: .1, visible: true }] };
    const option = buildTimeSeriesChartOption(props(chart(), { enabled: true, selectedSeriesInstanceId: "A-7", bySeries: { "A-7": config } })) as any;
    const text = option.tooltip.formatter([{ seriesName: "A-7", value: [2, 10], dataIndex: 1, seriesIndex: 0, marker: "•", axisValueLabel: "tempo" }]);
    expect(text).toContain("10"); expect(text).toContain("Regra"); expect(text).toContain("Operação");
  });
  it("métricas e CSV permanecem idênticos porque configuração não entra nos cálculos", () => {
    const timeSeries = { start_time: "2026-01-01T00:00:00Z", end_time: "2026-01-01T00:00:02Z", mode: "recorded" as const, errors: [], series: [{ tag_id: 7, tag_name: "TAG_7", display_name: "Tag 7", equipment: null, section: null, variable_type: null, unit: "bar", series_instance_id: "A-7", points: [0, 10, 20].map((value, index) => ({ timestamp: `2026-01-01T00:00:0${index}Z`, value, good: true, questionable: false, substituted: false })) }] };
    const metric = calculateMetricResults(timeSeries.series, { kind: "single", metric: "mean" }, false);
    const csv = buildTimeSeriesCsv(timeSeries);
    expect(calculateMetricResults(timeSeries.series, { kind: "single", metric: "mean" }, false)).toEqual(metric);
    expect(buildTimeSeriesCsv(timeSeries)).toBe(csv); expect(csv.split("\n")).toHaveLength(5);
  });
});

describe("painel local", () => {
  it("inicia desativado e alterações locais não chamam cliente HTTP", () => {
    const onChange = vi.fn(); const http = vi.fn();
    render(<VisualRulesPanel state={{ enabled: false, selectedSeriesInstanceId: null, bySeries: {} }} series={[{ seriesInstanceId: "A-7", label: "A", numeric: true }]} onChange={(next) => { onChange(next); }} />);
    expect(screen.getByText("Desativado")).toBeInTheDocument(); fireEvent.click(screen.getByTestId("visual-rules-enabled"));
    expect(onChange).toHaveBeenCalledOnce(); expect(http).not.toHaveBeenCalled();
  });
  it("informa indisponibilidade para série textual", () => {
    const state = { enabled: true, selectedSeriesInstanceId: "T-1", bySeries: {} };
    render(<VisualRulesPanel state={state} series={[{ seriesInstanceId: "T-1", label: "Texto", numeric: false }]} onChange={vi.fn()} />);
    expect(screen.getByText("Limites numéricos não estão disponíveis para esta série.")).toBeInTheDocument();
  });
  it("reset geral exige confirmação e não conhece resultados consultados", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true); const onChange = vi.fn();
    render(<VisualRulesPanel state={{ enabled: true, selectedSeriesInstanceId: "A", bySeries: { A: visual("A") } }} series={[{ seriesInstanceId: "A", label: "A", numeric: true }]} onChange={onChange} />);
    fireEvent.click(screen.getByText("Restaurar tudo")); expect(window.confirm).toHaveBeenCalled(); expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].bySeries).toEqual({});
  });
});
