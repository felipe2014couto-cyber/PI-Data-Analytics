import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { apiMock, connectedHealthFixture, equipmentFixture, sectionFixture, variableTypeFixture, piTagFixture, paginated, mockApiModule } from "./mocks/api";
import type { PiTagNormLimitsResponse } from "../src/types";

const normApi = vi.hoisted(() => ({ get: vi.fn(), charts: [] as any[] }));
vi.mock("../src/api", () => {
  const module = mockApiModule();
  return { ...module, piTagsApi: { ...module.piTagsApi, getNormLimits: normApi.get } };
});
vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: (props: any) => { normApi.charts.push(props.option); return <div data-testid="echarts-norm-probe" />; },
}));
import App from "../src/App";

const start = "2026-09-28T14:22:28Z", end = "2026-10-05T14:22:28Z", watermark = "2026-10-05T14:17:00Z";
const limitResponse: PiTagNormLimitsResponse = {
  source_tag_id: 1, start_time: start, end_time: end, mode: "recorded", interval: null,
  lower: { tag_name: "LOW", points: [{ timestamp: "2026-09-28T14:20:30Z", value: 25, good: true }], coverage_gaps: [[watermark, end]], error: "Atualização RECORDED pendente após 2026-10-05T14:17:00Z" },
  upper: { tag_name: null, points: [], coverage_gaps: [], error: null },
  errors: ["LOW: atualização RECORDED pendente após 2026-10-05T14:17:00Z"],
};

async function openLimits(includeSecond = false) {
  render(<MemoryRouter initialEntries={["/analises/visualizacao"]}><App /></MemoryRouter>);
  const eq = await screen.findByTestId("equipment-select");
  await waitFor(() => expect((eq as HTMLSelectElement).options.length).toBeGreaterThan(1));
  fireEvent.change(eq, { target: { value: "1" } });
  const tag = await within(await screen.findByTestId("tag-multi-select")).findByTestId("tag-option-1");
  fireEvent.click(tag);
  if (includeSecond) fireEvent.click(await screen.findByTestId("tag-option-2"));
  fireEvent.change(screen.getByTestId("period-preset"), { target: { value: "P7D" } });
  fireEvent.click(screen.getByTestId("filters-submit"));
  await screen.findByTestId("numeric-chart");
  fireEvent.click(screen.getByTestId("visual-rules-enabled"));
  fireEvent.change(screen.getByTestId("visual-series"), { target: { value: "tag:1" } });
  fireEvent.click(screen.getByTestId("add-norm-limit"));
}

beforeEach(() => {
  vi.clearAllMocks(); normApi.charts.length = 0;
  apiMock.listEquipments.mockResolvedValue(paginated([{ ...equipmentFixture, code: "RB1", name: "RB1" }]));
  apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
  apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
  apiMock.listPiTags.mockResolvedValue(paginated([{ ...piTagFixture, display_name: "Velocidade", lower_limit_tag: "LOW", upper_limit_tag: null, validation_status: "VALID" }]));
  apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  apiMock.timeSeriesQuery.mockImplementation(async (params) => ({
    start_time: params.start_time, end_time: params.end_time, mode: "recorded", errors: [],
    series: [{ tag_id: 1, tag_name: "PV", display_name: "Velocidade", unit: "m/min", equipment: "RB1", section: "FORNO", variable_type: "SPEED", points: [
      { timestamp: params.start_time, value: 30, good: true, questionable: false, substituted: false },
      { timestamp: params.end_time, value: 31, good: true, questionable: false, substituted: false },
    ] }],
  }));
});

describe("historical limit overlay integration", () => {
  it("keeps the pending first overlay when enabling a second series in the same query", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([
      { ...piTagFixture, id: 1, display_name: "Velocidade", lower_limit_tag: "LOW", upper_limit_tag: null, validation_status: "VALID" },
      { ...piTagFixture, id: 2, display_name: "Zona 03", lower_limit_tag: "LOW2", upper_limit_tag: null, validation_status: "VALID" },
    ]));
    apiMock.timeSeriesQuery.mockImplementation(async (params) => ({
      start_time: params.start_time, end_time: params.end_time, mode: "recorded", errors: [],
      series: [1, 2].map(id => ({ tag_id: id, tag_name: `PV${id}`, display_name: id === 1 ? "Velocidade" : "Zona 03", unit: "m/min", equipment: "RB1", section: "FORNO", variable_type: "SPEED", points: [
        { timestamp: params.start_time, value: 30, good: true, questionable: false, substituted: false },
        { timestamp: params.end_time, value: 31, good: true, questionable: false, substituted: false },
      ] })),
    }));
    const pending = new Map<number, { signal: AbortSignal; resolve: (value: PiTagNormLimitsResponse) => void; params: any }>();
    normApi.get.mockImplementation((id, params, signal) => new Promise((resolve, reject) => {
      pending.set(id, { signal, resolve, params });
      signal.addEventListener("abort", () => reject(new DOMException("The operation was aborted", "AbortError")), { once: true });
    }));
    await openLimits(true);
    await waitFor(() => expect(pending.has(1)).toBe(true));
    fireEvent.change(screen.getByTestId("visual-series"), { target: { value: "tag:2" } });
    fireEvent.click(screen.getByTestId("add-norm-limit"));
    await waitFor(() => expect(pending.has(2)).toBe(true));
    expect(pending.get(1)!.signal.aborted).toBe(false);
    expect(normApi.get).toHaveBeenCalledTimes(2);
    await act(async () => {
      for (const [id, request] of pending) request.resolve({
        ...limitResponse, source_tag_id: id, start_time: request.params.start_time, end_time: request.params.end_time,
        lower: { tag_name: `LOW${id}`, points: [{ timestamp: request.params.start_time, value: 25, good: true }], coverage_gaps: [], error: null }, errors: [],
      });
    });
    await waitFor(() => expect(screen.queryByTestId("norm-limit-loading")).toBeNull());
    const option = normApi.charts[normApi.charts.length - 1];
    expect(option.series.filter((series: any) => series.id?.startsWith("norm-lower:"))).toHaveLength(2);
    expect(screen.queryByText(/Não foi possível consultar os limites de norma|Consulta do limite cancelada/)).toBeNull();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });
  it("keeps a pending limit request alive across loading renders", async () => {
    const signals: AbortSignal[] = [];
    let resolve!: (r: PiTagNormLimitsResponse) => void;
    normApi.get.mockImplementation((_id, _params, signal) => {
      signals.push(signal);
      return new Promise<PiTagNormLimitsResponse>((r, reject) => {
        resolve = r;
        signal.addEventListener("abort", () => reject(new DOMException("The operation was aborted", "AbortError")), { once: true });
      });
    });
    await openLimits();
    await waitFor(() => expect(normApi.get).toHaveBeenCalled());
    expect(signals[0].aborted).toBe(false);
    expect(normApi.get).toHaveBeenCalledTimes(1);
    await act(async () => { const params = normApi.get.mock.calls[0][1]; resolve({ ...limitResponse, start_time: params.start_time, end_time: params.end_time, lower: { ...limitResponse.lower, points: [{ timestamp: params.start_time, value: 25, good: true }], coverage_gaps: [[new Date(Date.parse(params.end_time)-328000).toISOString(), params.end_time]] } }); });
    await waitFor(() => expect(screen.queryByTestId("norm-limit-loading")).toBeNull());
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(normApi.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Não foi possível consultar os limites de norma/)).toBeNull();
    expect(screen.getAllByText(/atualização RECORDED pendente/).length).toBeGreaterThan(0);
    const option = normApi.charts.slice().reverse().find(option => option?.series?.some((s: any) => s.id === "norm-lower:tag:1"));
    const lower = option.series.find((s: any) => s.id === "norm-lower:tag:1");
    const params = normApi.get.mock.calls[0][1];
    const tail = Date.parse(params.end_time) - 328000;
    expect(lower.data.slice(-2)).toEqual([[tail, 25], [tail, null]]);
    expect(lower.connectNulls).toBe(false);
    expect(lower.step).toBe("end");
  });

  it.each([new Error("LOW: timeout RECORDED SQLSTATE 57014"), { error: { message: "LOW: timeout RECORDED SQLSTATE 57014" } }])("shows a safe technical error while the main chart stays available", async (error) => {
    normApi.get.mockRejectedValue(error);
    await openLimits();
    await screen.findAllByText(/timeout RECORDED SQLSTATE 57014/);
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(normApi.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Não foi possível consultar os limites de norma/)).toBeNull();
  });

  it("shows the not-yet-materialized diagnosis while preserving the principal chart", async () => {
    normApi.get.mockResolvedValue({
      ...limitResponse,
      lower: { tag_name: "LOW", points: [], coverage_gaps: [[start, end]], error: "Limite aguardando a próxima recarga histórica: LOW ainda não foi materializado no TimescaleDB." },
      errors: ["Limite aguardando a próxima recarga histórica: LOW ainda não foi materializado no TimescaleDB."],
    });
    await openLimits();
    expect(await screen.findAllByText(/Limite aguardando a próxima recarga histórica/)).toHaveLength(2);
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(normApi.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Não foi possível consultar os limites de norma/)).toBeNull();
  });
});
