import { useEffect } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { EChartsOption, LineSeriesOption } from "echarts";
import { apiMock, connectedHealthFixture, equipmentFixture, mockApiModule, paginated, piTagFixture, sectionFixture, variableTypeFixture } from "./mocks/api";
import { unitResponse, unitVariable, UNIT_START as T, UNIT_DURATION as D } from "./fixtures/productionUnits";

vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/auth/AuthContext", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

const plot = vi.hoisted(() => ({ option: null as EChartsOption | null, instance: null as any, events: {} as Record<string, Array<(event: any) => void>> }));
vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ option, onInit }: any) => {
    plot.option = option;
    useEffect(() => { onInit?.(plot.instance); }, [onInit]);
    return <div data-testid="unit-echarts" />;
  },
}));

import { DataVisualizationPage } from "../src/pages/DataVisualizationPage";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import { buildChartData } from "../src/utils/chartData";
import { buildProductionUnitTimeSeries } from "../src/utils/productionUnitChart";

const numericLines = () => (plot.option?.series as LineSeriesOption[]).filter((s) => s.type === "line" && !String(s.id).startsWith("norm"));

beforeEach(() => {
  vi.clearAllMocks();
  plot.events = {};
  plot.option = null;
  const on = (event: string, fn: (event: any) => void) => { (plot.events[event] ??= []).push(fn); };
  const off = (event: string, fn: (event: any) => void) => { plot.events[event] = (plot.events[event] ?? []).filter((handler) => handler !== fn); };
  plot.instance = {
    on: vi.fn(on), off: vi.fn(off),
    getZr: () => ({ on: vi.fn(), off: vi.fn(), trigger: vi.fn() }),
    getModel: () => ({ getComponent: () => ({ coordinateSystem: { getRect: () => ({ x: 60, y: 70, width: 700, height: 254 }) } }) }),
    getOption: () => ({ dataZoom: [{ start: 0, end: 100 }], legend: [{ selected: {} }] }),
    convertToPixel: (finder: any, value: any) => finder.xAxisIndex === 0 ? 60 + ((value - T) / (3 * D)) * 700 : [200, 150],
    convertFromPixel: () => T, getWidth: () => 820, getHeight: () => 420,
    dispatchAction: vi.fn(), setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
  };
  apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
  apiMock.listSections.mockResolvedValue(paginated([{ ...sectionFixture, um_tag_id: 29, width_tag_id: 30 }]));
  apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture, { ...variableTypeFixture, id: 2, code: "UM", name: "UM", filter_data_type: "STRING" }]));
  apiMock.listPiTags.mockResolvedValue(paginated([
    { ...piTagFixture, id: 20, display_name: "Velocidade", pi_tag_name: "LFI_RB1_VEL_PROC_PV", engineering_unit: "m/min" },
    { ...piTagFixture, id: 29, variable_type_id: 2, display_name: "UM", pi_tag_name: "UM", data_type: "NON_NUMERIC", engineering_unit: null, section_id: null },
    { ...piTagFixture, id: 30, display_name: "Largura", pi_tag_name: "LARGURA", engineering_unit: "mm" },
  ]));
  apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  apiMock.visualConfigList.mockResolvedValue([]);
  apiMock.visualConfigHistory.mockResolvedValue([]);
  apiMock.productionUnitsAnalyze.mockResolvedValue(unitResponse());
});

async function preparePage(unit = true, sectionId: number | null = 1) {
  render(<MemoryRouter><DataVisualizationPage /></MemoryRouter>);
  const equipment = await screen.findByTestId("equipment-select");
  await waitFor(() => expect(within(equipment).getAllByRole("option").length).toBeGreaterThan(1));
  fireEvent.change(equipment, { target: { value: "1" } });
  await waitFor(() => expect(screen.getByTestId("section-select")).not.toBeDisabled());
  if (sectionId !== null) fireEvent.change(screen.getByTestId("section-select"), { target: { value: String(sectionId) } });
  if (unit) fireEvent.change(screen.getByTestId("analysis-model"), { target: { value: "unit" } });
  const option = await screen.findByTestId("tag-option-20");
  fireEvent.click(option);
  await waitFor(() => expect(option).toHaveAttribute("data-selected", "true"));
  fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "absolute" } });
  fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-10-02T07:00:00" } });
  fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-10-02T07:15:00" } });
}

async function submit() {
  fireEvent.click(screen.getByTestId("filters-submit"));
  await screen.findByTestId("numeric-chart");
}

describe("Base Unidade main chart integration", () => {
  it("queries the unit endpoint once and uses its response in the chart and diagnostics without the table", async () => {
    await preparePage();
    await submit();
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledTimes(1);
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledWith(expect.objectContaining({
      section_id: 1, equipment_id: 1, tag_ids: [20], start_time: "2026-10-02T10:00:00.000Z", end_time: "2026-10-02T10:15:00.000Z",
      filter_configuration: expect.objectContaining({ filtersEnabled: true }),
    }), expect.any(AbortSignal));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
    expect(numericLines()[0].data).toEqual([[T, 28.4199002965], [T + D, 28.4199002965], [T + D, null], [T + 2 * D, null], [T + 2 * D, 31.0622640703], [T + 3 * D, 31.0622640703]]);
    expect(screen.queryByText("Análise de produção por UM")).not.toBeInTheDocument();
    expect(screen.queryByTestId("um-segment")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Calcular por UM" })).not.toBeInTheDocument();
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("production_unit_aggregation");
    expect(screen.getByTestId("metric-unit-segments")).toHaveTextContent("3");
    expect(screen.getByTestId("metric-points")).toHaveTextContent("Pontos de renderização6");
    expect(screen.queryByTestId("metric-events-returned")).not.toBeInTheDocument();
  });

  it("renders a categorical strip only when the UM tag is selected", async () => {
    await preparePage();
    await submit();
    const band = () => (plot.option?.series as any[]).find(series => series.id === "production-unit-band");
    expect(band()).toBeUndefined();
    fireEvent.click(screen.getByTestId("tag-option-29"));
    await waitFor(() => expect(band()).toBeDefined());
    expect(band().type).toBe("custom");
    expect(band().data).toEqual(unitResponse().segments.map(segment => [Date.parse(segment.start_time), Date.parse(segment.end_time), segment.um_value]));
    expect(band().encode).toEqual({ x: [0, 1] });
    expect((plot.option?.yAxis as any[]).every(axis => axis.type === "value")).toBe(true);
    const rendered = band().renderItem({ dataIndex: 0, coordSys: { x: 10, y: 106, width: 100 } }, { value: (i: number) => [T, T + D, "600304J2000B"][i], coord: (value: any[]) => [value[0] === T ? 10 : 60, 0] });
    expect(rendered.children[0].shape).toEqual({ x: 10, y: 74, width: 50, height: 26 });
    expect(rendered.children[1].style.text).toBe("600304J2000B");
    fireEvent.click(screen.getByTestId("tag-option-29"));
    await waitFor(() => expect(band()).toBeUndefined());
  });

  it("allows Todas with the equipment-wide UM and sends no fictitious section", async () => {
    await preparePage(true, null);
    expect(screen.queryByText(/Selecione uma seção com tag UM configurada/i)).not.toBeInTheDocument();
    await submit();
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledWith(expect.objectContaining({
      equipment_id: 1, section_id: undefined, tag_ids: [20],
    }), expect.any(AbortSignal));
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("production_unit_aggregation");
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("reports missing equipment-wide UM clearly for Todas", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([{ ...piTagFixture, id: 20, display_name: "Velocidade" }]));
    await preparePage(true, null);
    fireEvent.click(screen.getByTestId("filters-submit"));
    expect(await screen.findByText("Não há tag UM configurada para o equipamento inteiro.")).toBeInTheDocument();
    expect(apiMock.productionUnitsAnalyze).not.toHaveBeenCalled();
  });

  it("does not use an equipment-wide UM as an implicit fallback for a section", async () => {
    apiMock.listSections.mockResolvedValue(paginated([{ ...sectionFixture, um_tag_id: null, width_tag_id: 30 }]));
    await preparePage();
    fireEvent.click(screen.getByTestId("filters-submit"));
    expect(await screen.findByText("Não há tag UM configurada para esta seção.")).toBeInTheDocument();
    expect(apiMock.productionUnitsAnalyze).not.toHaveBeenCalled();
  });

  it("switches from Todas to the selected section UM and back to the equipment UM", async () => {
    apiMock.listSections.mockResolvedValue(paginated([{ ...sectionFixture, um_tag_id: 28, width_tag_id: 30 }]));
    apiMock.listPiTags.mockResolvedValue(paginated([
      { ...piTagFixture, id: 20, display_name: "Velocidade", pi_tag_name: "LFI_RB1_VEL_PROC_PV", engineering_unit: "m/min" },
      { ...piTagFixture, id: 28, variable_type_id: 2, section_id: 1, display_name: "UM FORNO", pi_tag_name: "UM-FORNO", data_type: "NON_NUMERIC" },
      { ...piTagFixture, id: 29, variable_type_id: 2, section_id: null, display_name: "UM GLOBAL", pi_tag_name: "UM-EQUIPAMENTO", data_type: "NON_NUMERIC" },
      { ...piTagFixture, id: 30, display_name: "Largura", pi_tag_name: "LARGURA", engineering_unit: "mm" },
    ]));
    apiMock.productionUnitsAnalyze.mockImplementation(async (payload: any) => ({
      ...unitResponse(), section_id: payload.section_id ?? null,
      um_tag_id: payload.section_id === undefined ? 29 : 28,
      um_tag_name: payload.section_id === undefined ? "UM-EQUIPAMENTO" : "UM-FORNO",
      segments: unitResponse().segments.map(segment => ({ ...segment, um_value: payload.section_id === undefined ? "UM-EQUIPAMENTO" : "UM-FORNO" })),
    }));
    await preparePage(true, null);
    await submit();
    await waitFor(() => expect((plot.option?.tooltip as any).formatter([{ axisValue: T }])).toContain("UM-EQUIPAMENTO"));
    fireEvent.change(screen.getByTestId("section-select"), { target: { value: "1" } });
    fireEvent.click(screen.getByTestId("filters-submit"));
    await waitFor(() => expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledTimes(2));
    await waitFor(() => expect((plot.option?.tooltip as any).formatter([{ axisValue: T }])).toContain("UM-FORNO"));
    expect(apiMock.productionUnitsAnalyze.mock.calls[1][0]).toMatchObject({ section_id: 1, equipment_id: 1 });
    fireEvent.change(screen.getByTestId("section-select"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("filters-submit"));
    await waitFor(() => expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledTimes(3));
    await waitFor(() => expect((plot.option?.tooltip as any).formatter([{ axisValue: T }])).toContain("UM-EQUIPAMENTO"));
    expect(apiMock.productionUnitsAnalyze.mock.calls[2][0]).toMatchObject({ section_id: undefined, equipment_id: 1 });
  });

  it("changes between mean/min/max from the same backend response", async () => {
    await preparePage();
    await submit();
    fireEvent.change(screen.getByTestId("time-analysis-rule-select"), { target: { value: "MIN" } });
    await waitFor(() => expect(numericLines()[0].data?.slice(0, 2)).toEqual([[T, 25.003582], [T + D, 25.003582]]));
    fireEvent.change(screen.getByTestId("time-analysis-rule-select"), { target: { value: "MAXIMO" } });
    await waitFor(() => expect(numericLines()[0].data?.slice(0, 2)).toEqual([[T, 31.1618557], [T + D, 31.1618557]]));
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledTimes(1);
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("uses the pointer position for the tooltip even when ECharts selects the next boundary", async () => {
    await preparePage();
    await submit();
    plot.instance.convertFromPixel = () => T + D - 1;
    fireEvent.mouseMove(screen.getByTestId("unit-echarts"), { clientX: 200, clientY: 150 });
    const formatter = (plot.option?.tooltip as { formatter: (params: unknown) => string }).formatter;
    const html = formatter([{ axisValue: T + D, seriesId: "tag:20", value: [T + D, null] }]);
    expect(html).toContain("600304J2000B");
    expect(html).toContain("28,4199002965");
    expect(html).not.toContain("BOB L2");
  });

  it("sends sample filters to the backend and never filters aggregate geometry independently", async () => {
    await preparePage();
    fireEvent.click(screen.getByTestId("advanced-filters-toggle"));
    fireEvent.change(screen.getByTestId("named-filter-widthMin"), { target: { value: "1300" } });
    fireEvent.click(screen.getByTestId("named-filters-apply"));
    await submit();
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledWith(expect.objectContaining({
      tag_ids: [20], filter_configuration: expect.objectContaining({ rules: expect.arrayContaining([
        expect.objectContaining({ tagId: 30, kind: "numeric", value: 1300 }),
      ]) }),
    }), expect.any(AbortSignal));
    expect(numericLines()[0].data?.slice(0, 2)).toEqual([[T, 28.4199002965], [T + D, 28.4199002965]]);
    expect(numericLines()).toHaveLength(1);
    expect(screen.queryByTestId("filter-summary")).not.toBeInTheDocument();
    expect(screen.getByTestId("metric-points")).toHaveTextContent("Pontos de renderização6");
  });

  it("zooms by cropping UM geometry without querying temporal detail, and restores the initial window", async () => {
    await preparePage();
    await submit();
    act(() => plot.events.dataZoom.forEach((handler) => handler({ startValue: T + D / 2, endValue: T + 3 * D / 2 })));
    await waitFor(() => expect(numericLines()[0].data).toEqual([[T + D / 2, 28.4199002965], [T + D, 28.4199002965], [T + D, null], [T + 3 * D / 2, null]]));
    expect(screen.getByTestId("metric-unit-segments")).toHaveTextContent("2");
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledTimes(1);
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
    act(() => plot.events.restore.forEach((handler) => handler({})));
    await waitFor(() => expect(numericLines()[0].data).toHaveLength(6));
  });

  it("allows a sparse zoom entirely inside a single UM", async () => {
    await preparePage();
    await submit();
    act(() => plot.events.dataZoom.forEach((handler) => handler({ startValue: T + 10_000, endValue: T + 10_500 })));
    await waitFor(() => expect(numericLines()[0].data).toEqual([[T + 10_000, 28.4199002965], [T + 10_500, 28.4199002965]]));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("never renders the selected UM as an artificial Y series", async () => {
    await preparePage();
    fireEvent.click(await screen.findByTestId("tag-option-29"));
    await submit();
    expect(numericLines().map((s) => s.id)).toEqual(["tag:20"]);
    expect(JSON.stringify(plot.option?.yAxis)).not.toContain("600304J2000B");
  });

  it("renders three variables with distinct engineering units on independent scales", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([
      { ...piTagFixture, id: 20, display_name: "Velocidade", engineering_unit: "m/min" },
      { ...piTagFixture, id: 29, variable_type_id: 2, display_name: "UM", pi_tag_name: "UM", data_type: "NON_NUMERIC", section_id: null },
      { ...piTagFixture, id: 21, display_name: "Temperatura", engineering_unit: "°C" },
      { ...piTagFixture, id: 22, display_name: "Pressão", engineering_unit: "bar" },
    ]));
    const response = unitResponse([
      unitVariable({ average: 28 }),
      unitVariable({ tag_id: 21, display_name: "Temperatura", unit: "°C", average: 1120 }),
      unitVariable({ tag_id: 22, display_name: "Pressão", unit: "bar", average: 5.2 }),
    ]);
    apiMock.productionUnitsAnalyze.mockResolvedValue(response);
    await preparePage();
    fireEvent.click(await screen.findByTestId("tag-option-21"));
    fireEvent.click(await screen.findByTestId("tag-option-22"));
    await submit();
    expect(numericLines().map((series) => series.yAxisIndex)).toEqual([0, 1, 2]);
    expect(numericLines().map((series) => series.data?.slice(0, 2))).toEqual([
      [[T, 28], [T + D, 28]], [[T, 1120], [T + D, 1120]], [[T, 5.2], [T + D, 5.2]],
    ]);
    expect((plot.option?.yAxis as any[]).map((axis) => axis.name)).toEqual(["m/min", "°C", "bar"]);
    expect((plot.option?.yAxis as any[])[2].offset).toBe(60);
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("preserves the cyclic endpoint and original temporal vertices", async () => {
    const temporal = {
      start_time: new Date(T).toISOString(), end_time: new Date(T + 3 * D).toISOString(), mode: "recorded",
      series: [{ tag_id: 20, tag_name: "VEL", display_name: "Velocidade", equipment: "RB1", section: "FORNO", variable_type: "SPEED", unit: "m/min", data_type: "REAL", step: false,
        points: [28, 29, 30].map((value, i) => ({ timestamp: new Date(T + i * D).toISOString(), value, good: true, questionable: false, substituted: false })) }],
      errors: [], query_execution: { resolution_mode: "automatic", sampled: false, partial: false, strategy: "timescaledb_continuous_aggregate" },
    };
    apiMock.timeSeriesQuery.mockResolvedValue(temporal);
    await preparePage(false);
    await submit();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(apiMock.productionUnitsAnalyze).not.toHaveBeenCalled();
    expect(numericLines()[0].data).toEqual([[T, 28], [T + D, 29], [T + 2 * D, 30]]);
    expect(numericLines()[0].step).toBeUndefined();
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("timescaledb_continuous_aggregate");
  });

  it("OOC is only a Base Unidade metric and uses the existing unit endpoint and chart", async () => {
    const response = unitResponse();
    response.segments[0].variables[0] = { ...response.segments[0].variables[0], attended_percent: 96.4, eligible_sample_count: 500, attended_sample_count: 482 };
    response.segments[1].variables[0].attended_percent = null;
    response.segments[2].variables[0].attended_percent = 50;
    apiMock.productionUnitsAnalyze.mockResolvedValue(response);
    await preparePage();
    expect(within(screen.getByTestId("analysis-model")).queryByRole("option", { name: "Base OOC" })).toBeNull();
    expect(within(screen.getByTestId("time-analysis-rule-select")).getByRole("option", { name: "OOC" })).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("time-analysis-rule-select"), { target: { value: "OOC" } });
    await submit();
    expect(apiMock.productionUnitsAnalyze).toHaveBeenCalledWith(expect.objectContaining({ analysis_rule: "OOC" }), expect.any(AbortSignal));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
    expect(numericLines()[0].data).toEqual([[T, 96.4], [T + D, 96.4], [T + D, null], [T + 2 * D, null], [T + 2 * D, 50], [T + 3 * D, 50]]);
    expect((plot.option?.yAxis as any[])[0]).toMatchObject({ min: 0, max: 100 });
    expect(screen.queryByText("Análise de produção por UM")).not.toBeInTheDocument();
  });

});

describe("Production unit marker UI", () => {
  it("shows UM and exact OOC counters in the existing marker", async () => {
    const response = unitResponse();
    Object.assign(response.segments[0].variables[0], { attended_percent: 96.4, attended_sample_count:482, eligible_sample_count:500 });
    const chart = buildChartData(buildProductionUnitTimeSeries(response,"OOC",[20]),{ignoreBadQuality:false});
    render(<TimeSeriesChart chart={chart} equipment="RB1" start={new Date(T)} end={new Date(T+3*D)} mode="recorded" pinnedCursorTs={T+60_000} />);
    expect(await screen.findByTestId("marker-box-0")).toHaveTextContent("Atendido: 96,4% (482/500 amostras)");
    expect(screen.getByTestId("marker-unit")).toHaveTextContent("UM: 600304J2000B");
  });

  it("shows the constant aggregate inside the segment, the null gap and the new value at an exact transition", async () => {
    const response = unitResponse();
    const chart = buildChartData(buildProductionUnitTimeSeries(response, "MEDIA", [20]), { ignoreBadQuality: false });
    const props = { chart, equipment: "RB1", start: new Date(T), end: new Date(T + 3 * D), mode: "recorded" as const };
    const { rerender } = render(<TimeSeriesChart {...props} pinnedCursorTs={T + 60_000} />);
    expect(await screen.findByTestId("marker-box-0")).toHaveTextContent("28,4199002965 m/min");
    expect(screen.getByTestId("marker-box-0")).toHaveTextContent("Média da UM");
    expect(screen.getByTestId("marker-unit")).toHaveTextContent("UM: 600304J2000B");
    rerender(<TimeSeriesChart {...props} pinnedCursorTs={T + 240_000} />);
    await waitFor(() => expect(screen.getByTestId("marker-box-0")).toHaveTextContent("28,4199002965 m/min"));
    rerender(<TimeSeriesChart {...props} pinnedCursorTs={T + D} />);
    await waitFor(() => expect(screen.getByTestId("marker-box-0")).toHaveTextContent("sem amostras válidas"));
    rerender(<TimeSeriesChart {...props} pinnedCursorTs={T + 2 * D} />);
    await waitFor(() => expect(screen.getByTestId("marker-box-0")).toHaveTextContent("31,0622640703 m/min"));
  });
});
