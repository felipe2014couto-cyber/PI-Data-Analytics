import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";

let mockEChartsInstance: any;
let registeredEventHandlers: Record<string, Function[]> = {};
let currentZoom = { start: 0, end: 100 };
// Última option recebida pelo wrapper mockado (para inspecionar yAxis).
let lastOption: any = null;

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ onInit, option, height }: any) => {
    useEffect(() => {
      lastOption = option;
      if (onInit && mockEChartsInstance) {
        onInit(mockEChartsInstance);
      }
    }, [onInit, option]);
    return <div data-testid="echarts-wrapper" style={{ height }} />;
  },
}));

const START_TS = 1725418751000;
const END_TS = START_TS + 3600000;
const DURATION = END_TS - START_TS;

// Geometria do grid usada pelos mocks: top=70, bottom=324, height=254.
const GRID_TOP = 70;
const GRID_BOTTOM = 324;
const Y_MIN = 0;
const Y_MAX = 50;

function yPixelToValue(px: number): number {
  const frac = (px - GRID_TOP) / (GRID_BOTTOM - GRID_TOP);
  return Y_MAX - frac * (Y_MAX - Y_MIN);
}

function mockChartSeries(id: string, values: Array<[number, number]>): ChartSeries {
  return {
    tagId: 7,
    displayName: `Zona ${id}`,
    tagName: `TAG_${id}`,
    equipment: null,
    section: null,
    variableType: null,
    unit: "m/min",
    yAxisIndex: 0,
    color: "#ff0000",
    seriesInstanceId: id,
    total: values.length,
    numeric: values.length,
    dropped: 0,
    nonNumeric: 0,
    points: values,
    qualitySeries: values.map((p) => [p[0], 0]),
    valueKind: "numeric",
    statePoints: [],
    stateValues: [],
    stateQualitySeries: [],
  };
}

function mockChart(points: Array<[number, number]>): ChartBuildResult {
  return {
    series: [mockChartSeries("1", points)],
    units: ["m/min"],
    yAxisLabels: ["m/min"],
    totalSeries: 1,
    totalPoints: points.length,
    totalNumericPoints: points.length,
    totalDroppedPoints: 0,
    totalNonNumericPoints: 0,
    valueKind: "numeric",
    categories: [],
    comparisonType: null,
  };
}

const BROAD_POINTS: Array<[number, number]> = [
  [START_TS, 0],
  [START_TS + 1800000, 48],
  [END_TS, 12],
];

// Dados detalhados estreitos retornados pela reconsulta do zoom.
const NARROW_POINTS: Array<[number, number]> = [
  [START_TS + 600000, 24.95],
  [START_TS + 1200000, 25.1],
  [START_TS + 1800000, 25.2],
];

function fireDataZoom(startPct: number, endPct: number) {
  const handlers = registeredEventHandlers["dataZoom"] ?? [];
  for (const handler of handlers) {
    act(() => {
      handler({
        start: startPct,
        end: endPct,
        startValue: START_TS + (DURATION * startPct) / 100,
        endValue: START_TS + (DURATION * endPct) / 100,
      });
    });
  }
}

function pressCtrlZ() {
  act(() => {
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "z",
        ctrlKey: true,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
}

function fireRestore() {
  const handlers = registeredEventHandlers["restore"] ?? [];
  for (const handler of handlers) {
    act(() => {
      handler();
    });
  }
}

describe("TimeSeriesChart - preservação do domínio Y no zoom", () => {
  let onVisibleWindowChange: any;
  let dispatchAction: any;

  beforeEach(() => {
    registeredEventHandlers = {};
    currentZoom = { start: 0, end: 100 };
    lastOption = null;
    onVisibleWindowChange = vi.fn(() => Promise.resolve("applied"));
    dispatchAction = vi.fn();

    mockEChartsInstance = {
      convertToPixel: vi.fn(() => [200, 150]),
      convertFromPixel: vi.fn((finder: any, input: any) => {
        if (finder && finder.yAxisIndex !== undefined) {
          return yPixelToValue(typeof input === "number" ? input : input[1]);
        }
        return START_TS;
      }),
      getModel: vi.fn(() => ({
        getComponent: () => ({
          coordinateSystem: { getRect: () => ({ x: 60, y: GRID_TOP, width: 700, height: GRID_BOTTOM - GRID_TOP }) },
        }),
      })),
      getOption: vi.fn(() => ({
        dataZoom: [{ ...currentZoom }],
        legend: [{ selected: {} }],
      })),
      getZr: vi.fn(() => ({
        on: vi.fn((event: string, handler: Function) => {
          if (!registeredEventHandlers[event]) registeredEventHandlers[event] = [];
          registeredEventHandlers[event].push(handler);
        }),
        off: vi.fn(),
        trigger: vi.fn(),
      })),
      getWidth: () => 820,
      getHeight: () => 420,
      setOption: vi.fn(),
      dispatchAction,
      on: vi.fn((event: string, handler: Function) => {
        if (!registeredEventHandlers[event]) registeredEventHandlers[event] = [];
        registeredEventHandlers[event].push(handler);
      }),
      off: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
    };
  });

  function renderChart(points: Array<[number, number]> = BROAD_POINTS) {
    return render(
      <TimeSeriesChart
        chart={mockChart(points)}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
  }

  it("zoom horizontal auto-ajusta a escala Y aos pontos detalhados", async () => {
    const view = renderChart(BROAD_POINTS);
    expect(lastOption.yAxis[0].min).toBeUndefined();

    fireDataZoom(10, 30);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);

    // Reconsulta devolve dados estreitos (24,95–25,20) e a página rerenderiza
    // a mesma janela com os pontos detalhados.
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(NARROW_POINTS)}
        equipment="Turbina 1"
        start={new Date(START_TS + (DURATION * 10) / 100)}
        end={new Date(START_TS + (DURATION * 30) / 100)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    // Zoom temporal: a escala Y se auto-ajusta aos pontos detalhados.
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("reconsulta rejeitada restaura o domínio Y anterior", async () => {
    let outcome: "applied" | "rejected" = "applied";
    onVisibleWindowChange = vi.fn(() => Promise.resolve(outcome));
    const view = renderChart(BROAD_POINTS);

    fireDataZoom(10, 30);
    outcome = "rejected";
    fireDataZoom(40, 60);
    await act(async () => {
      await Promise.resolve();
    });

    // O rollback limpa o domínio fixado: a escala volta ao automático,
    // recalcu­lada a partir dos dados da janela restaurada.
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("Ctrl+Z restaura X e Y do nível anterior", () => {
    const view = renderChart(BROAD_POINTS);
    fireDataZoom(0, 50);
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(NARROW_POINTS)}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(START_TS + DURATION / 2)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
    expect(lastOption.yAxis[0].min).toBeUndefined();

    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 100 }),
    );
    // O undo restaura o domínio Y visível do nível anterior (0–50),
    // lido da área plotável no momento do zoom.
    expect(lastOption.yAxis[0].min).toBeCloseTo(Y_MIN, 6);
    expect(lastOption.yAxis[0].max).toBeCloseTo(Y_MAX, 6);
    expect(lastOption.yAxis[0].scale).toBe(false);
    view.unmount();
  });

  it("reset (restore) remove o domínio Y fixado", () => {
    const view = renderChart(BROAD_POINTS);
    fireDataZoom(10, 30);
    // O zoom horizontal já não fixa o domínio.
    expect(lastOption.yAxis[0].min).toBeUndefined();

    fireRestore();
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("troca de variável (novo contexto) invalida o domínio Y herdado", () => {
    const view = renderChart(BROAD_POINTS);
    fireDataZoom(10, 30);
    expect(lastOption.yAxis[0].min).toBeUndefined();

    // Nova consulta com outra tag/unidade: recalcula o Y inicial.
    const otherChart = mockChart(NARROW_POINTS);
    otherChart.series[0] = { ...otherChart.series[0], tagId: 99, seriesInstanceId: "2" };
    view.rerender(
      <TimeSeriesChart
        chart={otherChart}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
    expect(lastOption.yAxis[0].min).toBeUndefined();
    view.unmount();
  });

  it("respostas fora de ordem não restauram escala antiga (undo superseded não sobrescreve)", async () => {
    const view = renderChart(BROAD_POINTS);
    fireDataZoom(10, 30);
    fireDataZoom(40, 60);
    // Zooms horizontais limpam o domínio: a escala permanece automática.
    expect(lastOption.yAxis[0].min).toBeUndefined();
    // O domínio visível foi lido do mesmo grid em ambos os zooms; a segunda
    // entrada do histórico não pode reverter o estado atual do primeiro eco.
    fireDataZoom(50, 60);
    expect(lastOption.yAxis[0].min).toBeUndefined();
    view.unmount();
  });
});