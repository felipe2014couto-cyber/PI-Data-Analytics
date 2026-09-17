import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  connectedHealthFixture,
  equipmentFixture,
  mockApiModule,
  paginated,
  piTagFixture,
  sectionFixture,
  variableTypeFixture,
} from "./mocks/api";
import { ApiError } from "../src/api/http";
import type { TimeSeries } from "../src/types";

let latestChartProps: any = null;

vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/components/TimeSeriesChart", () => ({
  TimeSeriesChart: (props: any) => {
    latestChartProps = props;
    return (
      <div
        data-testid="deep-zoom-chart"
        data-global-loading={Boolean(props.loading)}
      />
    );
  },
}));

import App from "../src/App";

const INITIAL: TimeSeries = {
  start_time: "2026-09-06T00:00:00Z",
  end_time: "2026-09-13T00:00:00Z",
  mode: "recorded",
  series: [{
    tag_id: 1,
    tag_name: "RB3.SPEED",
    display_name: "Velocidade",
    equipment: "RB3",
    section: "FORNO",
    variable_type: "SPEED",
    unit: "m/min",
    points: [{
      timestamp: "2026-09-10T15:25:00Z",
      value: 5,
      plot_first: 5,
      plot_last: 6,
      plot_first_ts: "2026-09-10T15:27:00Z",
      plot_last_ts: "2026-09-10T15:27:10Z",
      plot_sample_count: 2,
      good: true,
      questionable: false,
      substituted: false,
    }],
  }],
  errors: [],
  query_execution: {
    resolution_mode: "automatic",
    effective_source_mode: "RECORDED",
    sampled: true,
    partial: false,
    effective_interval: "5m",
    strategy: "timescaledb_continuous_aggregate",
    source: "timescaledb",
    points_returned: 1,
  },
};

function detail(
  value: number,
  effectiveInterval = "recorded",
  strategy = "timescaledb_direct",
): TimeSeries {
  return {
    ...INITIAL,
    start_time: "2026-09-10T15:27:00Z",
    end_time: "2026-09-10T15:27:10Z",
    series: [{
      ...INITIAL.series[0],
      points: [
        { timestamp: "2026-09-10T15:27:05Z", value, good: true, questionable: false, substituted: false },
        { timestamp: "2026-09-10T15:27:06Z", value: value + 1, good: true, questionable: false, substituted: false },
      ],
    }],
    query_execution: {
      resolution_mode: "automatic",
      effective_source_mode: "RECORDED",
      sampled: false,
      partial: false,
      effective_interval: effectiveInterval,
      strategy,
      source: "timescaledb",
      points_returned: 2,
    },
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/analises/visualizacao"]}>
      <Routes><Route path="/*" element={<App />} /></Routes>
    </MemoryRouter>,
  );
}

async function loadInitialChart() {
  renderPage();
  const equipment = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
  fireEvent.change(equipment, { target: { value: "1" } });
  const tagList = await screen.findByTestId("tag-multi-select");
  fireEvent.click(await within(tagList).findByTestId("tag-option-1"));
  fireEvent.click(await screen.findByTestId("filters-submit"));
  // The full suite initializes several route-level fixtures in parallel, so
  // leave enough time for the initial query without weakening the assertion.
  await screen.findByTestId("deep-zoom-chart", undefined, { timeout: 5_000 });
  await waitFor(() => expect(latestChartProps?.onVisibleWindowChange).toBeTypeOf("function"));
}

describe("deep zoom da visualização", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.timeSeriesQuery.mockReset();
    apiMock.timeSeriesCompare.mockReset();
    latestChartProps = null;
    apiMock.authMe.mockResolvedValue({ id: "admin", username: "admin", role: "admin", is_active: true, must_change_password: false });
    apiMock.visualConfigHistory.mockResolvedValue([]);
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([{ ...piTagFixture, validation_status: "VALID" }]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("faz uma única consulta TimescaleDB para a janela concluída e mantém resolução automática", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(detail(37));
    await loadInitialChart();

    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });

    expect(outcome).toBe("applied");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
    expect(apiMock.timeSeriesQuery.mock.calls[1][0]).toMatchObject({
      start_time: "2026-09-10T15:27:00.000Z",
      end_time: "2026-09-10T15:27:10.000Z",
      resolution_mode: "automatic",
      target_points_per_tag: 1500,
      relative_period: false,
    });
    expect(screen.getByTestId("metric-points")).toHaveTextContent("2");
    expect(screen.getByTestId("metric-effective-interval")).toHaveTextContent("recorded");
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("TimescaleDB Direto");
  });

  it("mantém os dados anteriores visíveis e o gráfico desbloqueado e silencioso durante uma busca lenta", async () => {
    let resolveDetail!: (result: TimeSeries) => void;
    const slowDetail = new Promise<TimeSeries>((resolve) => { resolveDetail = resolve; });
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockReturnValueOnce(slowDetail);
    await loadInitialChart();

    let pending!: Promise<unknown>;
    act(() => {
      pending = latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("deep-zoom-chart")).toHaveAttribute("data-global-loading", "false");
    });
    expect(screen.queryByText(/Detalhando intervalo/i)).not.toBeInTheDocument();
    expect(latestChartProps.chart.series[0].points.some((point: [number, number]) => point[1] === 5)).toBe(true);

    await act(async () => {
      resolveDetail(detail(37));
      await pending;
    });

    expect(screen.getByTestId("deep-zoom-chart")).toHaveAttribute("data-global-loading", "false");
    expect(screen.queryByText(/Detalhando intervalo/i)).not.toBeInTheDocument();
  });

  it("deduplica a mesma janela e descarta uma resposta antiga após novo zoom", async () => {
    let resolveOld!: (result: TimeSeries) => void;
    let oldSignal: AbortSignal | undefined;
    const oldRequest = new Promise<TimeSeries>((resolve) => { resolveOld = resolve; });
    apiMock.timeSeriesQuery
      .mockResolvedValueOnce(INITIAL)
      .mockImplementationOnce((_params, signal) => {
        oldSignal = signal;
        return oldRequest;
      })
      .mockResolvedValueOnce(detail(42, "recorded", "zoom-new"));
    await loadInitialChart();

    let first!: Promise<unknown>;
    let duplicate!: Promise<unknown>;
    act(() => {
      first = latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"), new Date("2026-09-10T15:27:10Z"), "selection",
      );
      duplicate = latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"), new Date("2026-09-10T15:27:10Z"), "selection",
      );
    });
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
    expect(duplicate).toBe(first);

    let secondOutcome: unknown;
    await act(async () => {
      secondOutcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:04Z"), new Date("2026-09-10T15:27:06Z"), "selection",
      );
    });
    expect(oldSignal?.aborted).toBe(true);
    expect(secondOutcome).toBe("applied");
    await act(async () => {
      resolveOld(detail(11, "recorded", "zoom-old"));
      await expect(first).resolves.toBe("superseded");
    });
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("zoom-new");
  });

  it("trata 409 como falta de coverage e oferece a recarga administrativa", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockRejectedValueOnce(new ApiError(
      409,
      "HISTORICAL_DATA_NOT_LOADED",
      "Histórico não carregado.",
      {
        affected_tags: [{ tag_id: 1, intervals: [{ start: "2026-09-10T15:27:00Z", end: "2026-09-10T15:27:10Z" }] }],
        mode: "recorded",
        resolution: "recorded",
        requested_period: { start: "2026-09-10T15:27:00Z", end: "2026-09-10T15:27:10Z" },
        reload_available: true,
      },
    ));
    await loadInitialChart();

    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"), new Date("2026-09-10T15:27:10Z"), "selection",
      );
    });

    expect(outcome).toBe("rejected");
    expect(await screen.findByTestId("zoom-coverage-error")).toHaveTextContent("cobertura RECORDED completa");
    expect(screen.getByTestId("zoom-historical-reload-button")).toBeInTheDocument();
    expect(screen.getByTestId("deep-zoom-chart")).toHaveAttribute("data-global-loading", "false");
    expect(latestChartProps.chart.series[0].points.some((point: [number, number]) => point[1] === 5)).toBe(true);
  });

  it("reutiliza a resolução já carregada quando ela é suficiente para a janela", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL);
    await loadInitialChart();

    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-07T00:00:00Z"),
        new Date("2026-09-13T00:00:00Z"),
        "selection",
      );
    });

    expect(outcome).toBe("applied");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("metric-effective-interval")).toHaveTextContent("5m");
  });

  it("reutiliza RECORDED em zooms subsequentes contidos no detalhe carregado", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(detail(37));
    await loadInitialChart();
    await act(async () => {
      await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });

    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:04Z"),
        new Date("2026-09-10T15:27:06Z"),
        "selection",
      );
    });

    expect(outcome).toBe("applied");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
  });

  it("recusa zoom de milissegundos sem pontos suficientes e não dispara outra consulta", async () => {
    const tenSecondDetail = detail(37, "10s", "timescaledb_continuous_aggregate");
    tenSecondDetail.query_execution!.effective_source_mode = "INTERPOLATED_10S";
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(tenSecondDetail);
    await loadInitialChart();
    await act(async () => {
      await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });

    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:05.717Z"),
        new Date("2026-09-10T15:27:05.837Z"),
        "selection",
      );
    });

    expect(outcome).toBe("rejected");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Detalhando intervalo/i)).not.toBeInTheDocument();
    expect(latestChartProps.chart.series[0].points.length).toBeGreaterThan(0);
  });

  it("não substitui o gráfico e memoriza a janela quando o detalhe retorna pontos insuficientes", async () => {
    const emptyDetail = detail(37);
    emptyDetail.series[0].points = [];
    emptyDetail.query_execution!.points_returned = 0;
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(emptyDetail);
    await loadInitialChart();

    let firstOutcome: unknown;
    await act(async () => {
      firstOutcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });
    expect(firstOutcome).toBe("rejected");
    expect(latestChartProps.chart.series[0].points.length).toBeGreaterThan(0);

    let repeatedOutcome: unknown;
    await act(async () => {
      repeatedOutcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"),
        new Date("2026-09-10T15:27:10Z"),
        "selection",
      );
    });
    expect(repeatedOutcome).toBe("rejected");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
  });

  it("restaura o resultado inicial sem uma terceira consulta", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(detail(37));
    await loadInitialChart();
    await act(async () => {
      await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"), new Date("2026-09-10T15:27:10Z"), "selection",
      );
    });
    act(() => latestChartProps.onRestoreInitialZoom());

    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
    await waitFor(() => {
      expect(latestChartProps.chart.series[0].points.some((point: [number, number]) => point[1] === 5)).toBe(true);
    });
  });

  it("desfaz para uma janela em cache mesmo quando o detalhe atual não contém seus eventos", async () => {
    const firstWindow = detail(37);
    const secondWindow = detail(42);
    secondWindow.start_time = "2026-09-10T15:28:00Z";
    secondWindow.end_time = "2026-09-10T15:28:10Z";
    secondWindow.series[0].points = [
      { timestamp: "2026-09-10T15:28:05Z", value: 42, good: true, questionable: false, substituted: false },
      { timestamp: "2026-09-10T15:28:06Z", value: 43, good: true, questionable: false, substituted: false },
    ];
    // The first window remains coarse enough to request the next detail.
    firstWindow.query_execution!.effective_interval = "5m";
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL)
      .mockResolvedValueOnce(firstWindow).mockResolvedValueOnce(secondWindow);
    await loadInitialChart();
    let firstVertices: unknown;
    for (const minute of [27, 28]) {
      await act(async () => {
        await latestChartProps.onVisibleWindowChange(
          new Date(`2026-09-10T15:${minute}:00Z`),
          new Date(`2026-09-10T15:${minute}:10Z`), "selection",
        );
      });
      if (minute === 27) firstVertices = latestChartProps.chart.series[0].points;
    }
    let outcome: unknown;
    await act(async () => {
      outcome = await latestChartProps.onVisibleWindowChange(
        new Date("2026-09-10T15:27:00Z"), new Date("2026-09-10T15:27:10Z"), "undo",
      );
    });
    expect(outcome).toBe("applied");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(3);
    expect(latestChartProps.chart.series[0].points).toEqual(firstVertices);
  });

  it("não reaplica percentual de zoom recursivamente e isola baseStart/baseEnd da janela visível ativa", async () => {
    apiMock.timeSeriesQuery.mockResolvedValueOnce(INITIAL).mockResolvedValueOnce(detail(37));
    await loadInitialChart();

    // Estado inicial antes do zoom
    const initialStart = latestChartProps.start.toISOString();
    const initialEnd = latestChartProps.end.toISOString();
    expect(latestChartProps.isZoomed).toBe(false);
    expect(latestChartProps.baseStart.toISOString()).toBe(initialStart);
    expect(latestChartProps.baseEnd.toISOString()).toBe(initialEnd);
    expect(screen.queryByTestId("metric-zoomed-period")).not.toBeInTheDocument();

    // Aplica zoom em subjanela
    const zoomStart = new Date("2026-09-10T15:27:00Z");
    const zoomEnd = new Date("2026-09-10T15:27:10Z");
    await act(async () => {
      const outcome = await latestChartProps.onVisibleWindowChange(zoomStart, zoomEnd, "selection");
      expect(outcome).toBe("applied");
    });

    // Janela ativa passa a ser exatamente o período com zoom, preservando baseStart e baseEnd
    expect(latestChartProps.isZoomed).toBe(true);
    expect(latestChartProps.start.toISOString()).toBe("2026-09-10T15:27:00.000Z");
    expect(latestChartProps.end.toISOString()).toBe("2026-09-10T15:27:10.000Z");
    expect(latestChartProps.baseStart.toISOString()).toBe(initialStart);
    expect(latestChartProps.baseEnd.toISOString()).toBe(initialEnd);
    expect(screen.getByTestId("metric-zoomed-period")).toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);

    // Restaura o zoom inicial
    act(() => {
      latestChartProps.onRestoreInitialZoom();
    });

    // Retorna limpo ao período original sem disparar nova requisição HTTP
    expect(latestChartProps.isZoomed).toBe(false);
    expect(latestChartProps.start.toISOString()).toBe(initialStart);
    expect(latestChartProps.end.toISOString()).toBe(initialEnd);
    expect(screen.queryByTestId("metric-zoomed-period")).not.toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
  });
});
