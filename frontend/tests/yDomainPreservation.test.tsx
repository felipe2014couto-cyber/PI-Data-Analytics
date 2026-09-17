import { render, act, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";

let mockEChartsInstance: any;
let registeredEventHandlers: Record<string, Function[]> = {};
let currentZoom = { start: 0, end: 100 };
// Última option recebida pelo wrapper mockado (para inspecionar yAxis).
let lastOption: any = null;
let lastWrapperProps: any = null;

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: (props: any) => {
    const { onInit, option, height, loading } = props;
    lastWrapperProps = props;
    useEffect(() => {
      lastOption = option;
      if (onInit && mockEChartsInstance) {
        onInit(mockEChartsInstance);
      }
    }, [onInit, option]);
    return (
      <div
        data-testid="echarts-wrapper"
        data-global-loading={Boolean(loading)}
        style={{ height }}
      />
    );
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

function mockChartSeries(id: string, values: Array<[number, number]>, yAxisIndex: 0 | 1 = 0, unit = "m/min"): ChartSeries {
  return {
    tagId: Number(id) || 7,
    displayName: `Zona ${id}`,
    tagName: `TAG_${id}`,
    equipment: null,
    section: null,
    variableType: null,
    unit,
    yAxisIndex,
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

function mockMultiSeriesChart(
  seriesList: Array<{ id: string; points: Array<[number, number]>; yAxisIndex?: 0 | 1; unit?: string }>,
  yAxisLabels: string[] = ["m/min"],
): ChartBuildResult {
  return {
    series: seriesList.map((s) => mockChartSeries(s.id, s.points, s.yAxisIndex ?? 0, s.unit ?? "m/min")),
    units: yAxisLabels,
    yAxisLabels,
    totalSeries: seriesList.length,
    totalPoints: seriesList.reduce((sum, s) => sum + s.points.length, 0),
    totalNumericPoints: seriesList.reduce((sum, s) => sum + s.points.length, 0),
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
    lastWrapperProps = null;
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

  function renderChart(points: Array<[number, number]> = BROAD_POINTS, props: Record<string, any> = {}) {
    return render(
      <TimeSeriesChart
        chart={mockChart(points)}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
        {...props}
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
    // recalculada a partir dos dados da janela restaurada.
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
    // O undo restaura apenas a janela temporal; o eixo Y permanece automático.
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("reset (restore) remove o domínio Y fixado", () => {
    const view = renderChart(BROAD_POINTS);
    fireDataZoom(10, 30);
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
    expect(lastOption.yAxis[0].min).toBeUndefined();
    fireDataZoom(50, 60);
    expect(lastOption.yAxis[0].min).toBeUndefined();
    view.unmount();
  });

  // --- Testes obrigatórios de regressão reproduzindo o uso real ---

  it("1. arraste horizontal com variação vertical de 10 a 30 pixels consulta somente a janela X e mantém min/max indefinidos", () => {
    const view = renderChart(BROAD_POINTS);
    const container = view.container.querySelector('[data-testid="echarts-wrapper"]')?.parentElement;
    expect(container).toBeTruthy();

    // Simula ponteiro com deslocamento horizontal amplo e variação vertical de 25px
    fireEvent.pointerDown(container!, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(container!, { pointerId: 1, clientX: 300, clientY: 125 });
    fireEvent.pointerUp(container!, { pointerId: 1, clientX: 300, clientY: 125 });

    fireDataZoom(10, 40);

    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);
    const calledStart = onVisibleWindowChange.mock.calls[0][0];
    const calledEnd = onVisibleWindowChange.mock.calls[0][1];
    expect(calledStart.getTime()).toBe(START_TS + (DURATION * 10) / 100);
    expect(calledEnd.getTime()).toBe(START_TS + (DURATION * 40) / 100);

    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("2. série global com pontos amplos seguida de resposta com valores estreitos não fixa limites e mantém eixo automático", () => {
    const WIDE_GLOBAL_POINTS: Array<[number, number]> = [
      [START_TS, 10],
      [START_TS + 1000000, 950],
      [END_TS, 500],
    ];
    const view = renderChart(WIDE_GLOBAL_POINTS);
    fireDataZoom(20, 50);

    const NARROW_DETAIL_POINTS: Array<[number, number]> = [
      [START_TS + 800000, 20.1],
      [START_TS + 1200000, 20.4],
      [START_TS + 1600000, 20.2],
    ];
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(NARROW_DETAIL_POINTS)}
        equipment="Turbina 1"
        start={new Date(START_TS + (DURATION * 20) / 100)}
        end={new Date(START_TS + (DURATION * 50) / 100)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("3. duas séries no mesmo eixo com escalas muito diferentes continuam visíveis após o zoom", () => {
    const twoSeriesChart = mockMultiSeriesChart([
      {
        id: "1",
        points: [
          [START_TS, 18],
          [START_TS + 1800000, 22],
          [END_TS, 20],
        ],
        yAxisIndex: 0,
      },
      {
        id: "2",
        points: [
          [START_TS, 390],
          [START_TS + 1800000, 420],
          [END_TS, 405],
        ],
        yAxisIndex: 0,
      },
    ]);

    const view = render(
      <TimeSeriesChart
        chart={twoSeriesChart}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    fireDataZoom(20, 60);

    expect(lastOption.series).toHaveLength(2);
    expect(lastOption.series[0].yAxisIndex).toBe(0);
    expect(lastOption.series[1].yAxisIndex).toBe(0);
    // Ambas as séries continuam no mesmo eixo com scale: true e sem min/max fixos
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("4. séries em eixos Y diferentes permanecem válidas e automáticas", () => {
    const dualAxisChart = mockMultiSeriesChart(
      [
        {
          id: "1",
          points: [
            [START_TS, 10],
            [END_TS, 30],
          ],
          yAxisIndex: 0,
          unit: "bar",
        },
        {
          id: "2",
          points: [
            [START_TS, 80],
            [END_TS, 120],
          ],
          yAxisIndex: 1,
          unit: "°C",
        },
      ],
      ["bar", "°C"],
    );

    const view = render(
      <TimeSeriesChart
        chart={dualAxisChart}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    fireDataZoom(15, 45);

    expect(lastOption.yAxis).toHaveLength(2);
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    expect(lastOption.yAxis[1].min).toBeUndefined();
    expect(lastOption.yAxis[1].max).toBeUndefined();
    expect(lastOption.yAxis[1].scale).toBe(true);
    view.unmount();
  });

  it("5. segundo zoom enquanto o primeiro está pendente: apenas a resposta mais recente pode ser aplicada", async () => {
    let resolverFirst!: (outcome: "applied" | "superseded") => void;
    let resolverSecond!: (outcome: "applied" | "superseded") => void;
    onVisibleWindowChange = vi.fn((_start: Date, _end: Date) => {
      if (onVisibleWindowChange.mock.calls.length === 1) {
        return new Promise<"applied" | "superseded">((resolve) => {
          resolverFirst = resolve;
        });
      }
      return new Promise<"applied" | "superseded">((resolve) => {
        resolverSecond = resolve;
      });
    });

    const view = renderChart(BROAD_POINTS);

    // Primeiro zoom
    fireDataZoom(10, 30);
    // Segundo zoom antes do primeiro resolver
    fireDataZoom(40, 70);

    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);

    // Resposta atrasada do primeiro zoom chega após o segundo zoom
    await act(async () => {
      resolverFirst("superseded");
      resolverSecond("applied");
    });

    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("6. refinamento de zoom pendente mantém gráfico visível sem overlay global de carregamento", () => {
    // Durante o refinamento do zoom, o TimeSeriesChart não recebe loading=true
    const view = renderChart(BROAD_POINTS, { loading: false });

    fireDataZoom(20, 50);

    const wrapper = view.getByTestId("echarts-wrapper");
    expect(wrapper).toBeInTheDocument();
    expect(wrapper).toHaveAttribute("data-global-loading", "false");
    expect(lastWrapperProps.loading).toBe(false);
    view.unmount();
  });

  it("7. Ctrl+Z e restaurar recuperam o intervalo e não restauram limites Y obsoletos", () => {
    const view = renderChart(BROAD_POINTS);

    // Primeiro zoom
    fireDataZoom(10, 40);
    expect(lastOption.yAxis[0].min).toBeUndefined();

    // Segundo zoom
    fireDataZoom(20, 30);
    expect(lastOption.yAxis[0].min).toBeUndefined();

    // Ctrl+Z para o primeiro nível de zoom
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0 }),
    );
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);

    // Restaurar gráfico (reset completo)
    fireRestore();
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });
});