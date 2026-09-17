import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";

let mockEChartsInstance: any;
let registeredEventHandlers: Record<string, Function[]> = {};
let currentZoom = { start: 0, end: 100 };
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

function mockChart(points: Array<[number, number]>, _tagId = 7, instanceId = "1"): ChartBuildResult {
  return {
    series: [mockChartSeries(instanceId, points)],
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

function flushPromises() {
  return act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("TimeSeriesChart - integridade assíncrona do zoom", () => {
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

  it("um segundo zoom durante consulta pendente invalida logicamente a primeira revisão", async () => {
    let resolverA: (outcome: "applied") => void = () => {};
    onVisibleWindowChange = vi.fn(
      (_s: Date, _e: Date) =>
        new Promise<"applied">((resolve) => {
          if (onVisibleWindowChange.mock.calls.length === 1) {
            resolverA = resolve;
          } else {
            resolve("applied");
          }
        }),
    );
    const view = renderChart();

    // Zoom A pendente, depois Zoom B.
    fireDataZoom(10, 30);
    fireDataZoom(40, 60);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);

    // Zoom B aplicado: janela B é a ativa.
    const callB = onVisibleWindowChange.mock.calls[1];
    expect(callB[0].getTime()).toBe(START_TS + (DURATION * 40) / 100);

    // Resposta atrasada do Zoom A chega depois: não pode alterar o estado.
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(BROAD_POINTS)}
        equipment="Turbina 1"
        start={new Date(START_TS + (DURATION * 40) / 100)}
        end={new Date(START_TS + (DURATION * 60) / 100)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
    await flushPromises();
    if (resolverA) resolverA("applied");
    await flushPromises();

    // Nenhuma restauração da janela A foi despachada: o domínio continua B.
    const windowStart = START_TS + (DURATION * 40) / 100;
    expect(
      dispatchAction.mock.calls.filter(
        (c: any[]) => c[0]?.type === "dataZoom" && c[0]?.startValue === undefined && c[0]?.start === 10,
      ).length,
    ).toBe(0);
    expect(lastOption.xAxis.min).toBe(windowStart);
    view.unmount();
  });

  it("Ctrl+Z durante consulta pendente impede que a resposta atrasada sobrescreva o estado restaurado", async () => {
    let rejectA: () => void = () => {};
    onVisibleWindowChange = vi.fn(
      (_s: Date, _e: Date) =>
        new Promise<"applied">((_resolve, reject) => {
          if (onVisibleWindowChange.mock.calls.length === 1) {
            rejectA = () => reject(new Error("aborted"));
          } else {
            return Promise.resolve("applied");
          }
        }),
    );
    const view = renderChart();

    // Zoom A pendente; usuário desfaz antes da resposta chegar.
    fireDataZoom(10, 30);
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 100 }),
    );

    // A resposta pendente de A chega depois (rejeitada/abortada): o estado
    // restaurado permanece.
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(BROAD_POINTS)}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
    await flushPromises();
    if (rejectA) rejectA();
    await flushPromises();

    // Domínio restaurado intacto: xAxis ainda cobre a janela completa.
    expect(lastOption.xAxis.min).toBe(START_TS);
    expect(lastOption.xAxis.max).toBe(END_TS);
    view.unmount();
  });

  it("coerência atômica: a option reconstruída nunca mistura domínio novo com janela de dados antiga", () => {
    const view = renderChart();
    fireDataZoom(10, 30);
    const zoomedStart = START_TS + (DURATION * 10) / 100;
    const zoomedEnd = START_TS + (DURATION * 30) / 100;
    view.rerender(
      <TimeSeriesChart
        chart={mockChart(BROAD_POINTS)}
        equipment="Turbina 1"
        start={new Date(zoomedStart)}
        end={new Date(zoomedEnd)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
    // Domínio X e dataZoom são da mesma revisão: janela completa da nova
    // revisão, sem vestígios da anterior.
    expect(lastOption.xAxis.min).toBe(zoomedStart);
    expect(lastOption.xAxis.max).toBe(zoomedEnd);
    expect(lastOption.dataZoom[0].start).toBe(0);
    expect(lastOption.dataZoom[0].end).toBe(100);
    view.unmount();
  });
});