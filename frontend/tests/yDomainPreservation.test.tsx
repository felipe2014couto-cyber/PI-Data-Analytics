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

function fireZrMouse(type: "mousedown" | "mousemove" | "mouseup", offsetX: number, offsetY: number) {
  const handlers = registeredEventHandlers[type] ?? [];
  for (const handler of handlers) {
    act(() => {
      handler({ offsetX, offsetY });
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
      off: vi.fn((event: string, handler?: Function) => {
        if (!registeredEventHandlers[event]) return;
        if (handler) {
          registeredEventHandlers[event] = registeredEventHandlers[event].filter((h) => h !== handler);
        } else {
          registeredEventHandlers[event] = [];
        }
      }),
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
    fireZrMouse("mousedown", 130, 150);
    fireZrMouse("mousemove", 340, 160);
    fireZrMouse("mouseup", 340, 160);

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

  // --- Testes obrigatórios da especificação do Zoom Híbrido Bidimensional (Seção 18) ---

  it("A. seleção bidimensional define domínio Y explícito para cada eixo numérico", () => {
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        return py <= 150 ? 1050 : 920;
      }
      if (finder && finder.xAxisIndex !== undefined) {
        const px = typeof input === "number" ? input : input[0];
        return Math.round(START_TS + ((px - 60) / 700) * DURATION);
      }
      return START_TS;
    });

    const view = renderChart(BROAD_POINTS);
    const container = view.container.querySelector('[data-testid="echarts-wrapper"]')?.parentElement;
    expect(container).toBeTruthy();

    // Seleção com altura de 120px (>= 30px threshold)
    fireZrMouse("mousedown", 130, 100);
    fireZrMouse("mousemove", 340, 220);
    fireZrMouse("mouseup", 340, 220);

    fireDataZoom(10, 40);

    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);
    expect(lastOption.yAxis[0].scale).toBe(false);
    view.unmount();
  });

  it("B. refinamento assíncrono com chegada de novos pontos mantém exatamente o domínio Y selecionado", () => {
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        return py <= 150 ? 1050 : 920;
      }
      if (finder && finder.xAxisIndex !== undefined) {
        const px = typeof input === "number" ? input : input[0];
        return Math.round(START_TS + ((px - 60) / 700) * DURATION);
      }
      return START_TS;
    });

    const view = renderChart(BROAD_POINTS);

    fireZrMouse("mousedown", 130, 100);
    fireZrMouse("mousemove", 340, 220);
    fireZrMouse("mouseup", 340, 220);
    fireDataZoom(10, 40);

    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);

    // Simula chegada de novos dados refinados (pontos estreitos)
    const refinedPoints: Array<[number, number]> = [
      [START_TS + 400000, 935],
      [START_TS + 800000, 960],
      [START_TS + 1200000, 1005],
      [START_TS + 1400000, 1040],
    ];
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(refinedPoints)}
        equipment="Turbina 1"
        start={new Date(START_TS + (DURATION * 10) / 100)}
        end={new Date(START_TS + (DURATION * 40) / 100)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    // O domínio Y selecionado pelo usuário permanece estritamente fixado
    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);
    expect(lastOption.yAxis[0].scale).toBe(false);
    view.unmount();
  });

  it("C. pequeno jitter vertical (< 30px) trata como zoom puramente temporal e não fixa limites Y artificiais", () => {
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        return yPixelToValue(py);
      }
      return START_TS;
    });

    const view = renderChart(BROAD_POINTS);

    // Movimento com 15px de variação vertical (< 30px)
    fireZrMouse("mousedown", 100, 100);
    fireZrMouse("mousemove", 300, 115);
    fireZrMouse("mouseup", 300, 115);
    fireDataZoom(10, 40);

    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("D. Ctrl+Z restaura simultaneamente o intervalo X e o domínio Y anterior", () => {
    let callCount = 0;
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        if (callCount <= 2) {
          // Zoom 1: 920 - 1050
          return py <= 150 ? 1050 : 920;
        } else {
          // Zoom 2: 950 - 1000
          return py <= 150 ? 1000 : 950;
        }
      }
      return START_TS;
    });

    const view = renderChart(BROAD_POINTS);

    // Zoom 1: Y = 920..1050
    callCount = 1;
    fireZrMouse("mousedown", 100, 100);
    fireZrMouse("mousemove", 300, 220);
    fireZrMouse("mouseup", 300, 220);
    fireDataZoom(10, 50);

    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);

    // Zoom 2: Y = 950..1000
    callCount = 3;
    fireZrMouse("mousedown", 150, 100);
    fireZrMouse("mousemove", 250, 220);
    fireZrMouse("mouseup", 250, 220);
    fireDataZoom(20, 40);

    expect(lastOption.yAxis[0].min).toBe(950);
    expect(lastOption.yAxis[0].max).toBe(1000);

    // Primeiro Ctrl+Z: restaura Zoom 1 (X=10..50%, Y=920..1050)
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", start: 10, end: 50 }),
    );
    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);
    expect(lastOption.yAxis[0].scale).toBe(false);

    // Segundo Ctrl+Z: restaura viewport inicial (X=0..100%, Y automático)
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", start: 0, end: 100 }),
    );
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("E. restauração completa remove domínios Y manuais e volta eixos para autoescala", () => {
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        return py <= 150 ? 1050 : 920;
      }
      return START_TS;
    });

    const onRestoreInitialZoom = vi.fn();
    const view = renderChart(BROAD_POINTS, { onRestoreInitialZoom });

    fireZrMouse("mousedown", 100, 100);
    fireZrMouse("mousemove", 300, 220);
    fireZrMouse("mouseup", 300, 220);
    fireDataZoom(10, 50);

    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);

    // Restaurar
    fireRestore();
    expect(onRestoreInitialZoom).toHaveBeenCalledTimes(1);
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  it("F. eixo categórico de UM nunca recebe min/max numéricos do zoom", () => {
    mockEChartsInstance.convertFromPixel.mockImplementation((finder: any, input: any) => {
      if (finder && finder.yAxisIndex !== undefined) {
        const py = typeof input === "number" ? input : input[1];
        return py <= 150 ? 1050 : 920;
      }
      return START_TS;
    });

    const umChart = mockChart(BROAD_POINTS);
    const view = renderChart(BROAD_POINTS, {
      chart: umChart,
      umSeries: {
        categories: ["A", "B", "C"],
        steps: [[START_TS, "A"], [END_TS, "B"]],
      },
    });

    fireZrMouse("mousedown", 100, 100);
    fireZrMouse("mousemove", 300, 220);
    fireZrMouse("mouseup", 300, 220);
    fireDataZoom(10, 50);

    // Eixo numérico 0 recebe o domínio selecionado
    expect(lastOption.yAxis[0].min).toBe(920);
    expect(lastOption.yAxis[0].max).toBe(1050);
    expect(lastOption.yAxis[0].scale).toBe(false);

    // Eixo da UM (índice 1, categórico) NÃO recebe min/max
    expect(lastOption.yAxis[1].type).toBe("category");
    expect(lastOption.yAxis[1].min).toBeUndefined();
    expect(lastOption.yAxis[1].max).toBeUndefined();
    view.unmount();
  });
});