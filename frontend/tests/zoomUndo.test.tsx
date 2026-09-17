import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";

let mockEChartsInstance: any;
let registeredEventHandlers: Record<string, Function[]> = {};
let currentZoom = { start: 0, end: 100 };

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ onInit, height }: any) => {
    useEffect(() => {
      if (onInit && mockEChartsInstance) {
        onInit(mockEChartsInstance);
      }
    }, [onInit]);
    return <div data-testid="echarts-wrapper" style={{ height }} />;
  },
}));

const START_TS = 1725418751000;
const END_TS = START_TS + 3600000;
const DURATION = END_TS - START_TS;

function mockChartSeries(id: string): ChartSeries {
  return {
    tagId: 7,
    displayName: `Zona ${id}`,
    tagName: `TAG_${id}`,
    equipment: null,
    section: null,
    variableType: null,
    unit: "°C",
    yAxisIndex: 0,
    color: "#ff0000",
    seriesInstanceId: id,
    total: 3,
    numeric: 3,
    dropped: 0,
    nonNumeric: 0,
    points: [
      [START_TS, 20],
      [START_TS + 1800000, 25],
      [END_TS, 30],
    ],
    qualitySeries: [
      [START_TS, 0],
      [START_TS + 1800000, 0],
      [END_TS, 0],
    ],
    valueKind: "numeric",
    statePoints: [],
    stateValues: [],
    stateQualitySeries: [],
  };
}

function mockChart(): ChartBuildResult {
  return {
    series: [mockChartSeries("1"), mockChartSeries("2")],
    units: ["°C"],
    yAxisLabels: ["°C"],
    totalSeries: 2,
    totalPoints: 6,
    totalNumericPoints: 6,
    totalDroppedPoints: 0,
    totalNonNumericPoints: 0,
    valueKind: "numeric",
    categories: [],
    comparisonType: null,
  };
}

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

function pressCtrlZ(options: { repeat?: boolean; target?: EventTarget | null } = {}) {
  const event = new KeyboardEvent("keydown", {
    key: "z",
    ctrlKey: true,
    bubbles: true,
    cancelable: true,
  });
  Object.defineProperty(event, "repeat", { value: Boolean(options.repeat) });
  if (options.target !== undefined) {
    Object.defineProperty(event, "target", { value: options.target });
  }
  act(() => {
    window.dispatchEvent(event);
  });
  return event;
}

describe("TimeSeriesChart - Ctrl+Z do histórico de zoom", () => {
  let onVisibleWindowChange: any;
  let dispatchAction: any;

  beforeEach(() => {
    registeredEventHandlers = {};
    currentZoom = { start: 0, end: 100 };
    onVisibleWindowChange = vi.fn(() => Promise.resolve("applied"));
    dispatchAction = vi.fn();

    mockEChartsInstance = {
      convertToPixel: vi.fn(() => [200, 150]),
      convertFromPixel: vi.fn(() => START_TS),
      getModel: vi.fn(() => ({
        getComponent: () => ({
          coordinateSystem: { getRect: () => ({ x: 60, y: 70, width: 700, height: 254 }) },
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

  function renderChart() {
    return render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );
  }

  it("três zooms seguidos e três Ctrl+Z desfazem exatamente um nível por acionamento", () => {
    const { unmount } = renderChart();
    fireDataZoom(0, 50);
    fireDataZoom(0, 30);
    fireDataZoom(10, 20);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(3);

    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(4);
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 30 }),
    );

    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(5);
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 50 }),
    );

    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(6);
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 100 }),
    );

    // Histórico esgotado: nenhum efeito adicional.
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(6);
    unmount();
  });

  it("cada undo aciona exatamente uma reconsulta da janela restaurada", () => {
    renderChart();
    fireDataZoom(0, 50);
    fireDataZoom(0, 30);
    const before = onVisibleWindowChange.mock.calls.length;
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(before + 1);
    const [visibleStart, visibleEnd, reason] = onVisibleWindowChange.mock.calls.at(-1);
    expect(reason).toBe("undo");
    expect(visibleStart.getTime()).toBe(START_TS);
    expect(visibleEnd.getTime()).toBe(START_TS + (DURATION * 50) / 100);
  });

  it("event.repeat não desfaz níveis adicionais", () => {
    renderChart();
    fireDataZoom(0, 50);
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    pressCtrlZ({ repeat: true });
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
  });

  it("não captura Ctrl+Z em campos editáveis", () => {
    renderChart();
    fireDataZoom(0, 50);
    const input = document.createElement("input");
    document.body.appendChild(input);
    const event = pressCtrlZ({ target: input });
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(false);
    input.remove();
  });

  it("sem histórico não altera estado nem chama preventDefault", () => {
    renderChart();
    const event = pressCtrlZ();
    expect(onVisibleWindowChange).not.toHaveBeenCalled();
    expect(dispatchAction).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("o próprio undo não registra nova entrada no histórico (eco de dataZoom é suprimido)", () => {
    renderChart();
    fireDataZoom(0, 50);
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    // Eco do dispatchZoom do undo: não pode disparar nova consulta nem push.
    fireDataZoom(0, 50);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    // Após o eco, o histórico permanece vazio: novo Ctrl+Z é no-op.
    const event = pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    expect(event.defaultPrevented).toBe(false);
  });

  it("listener de teclado é removido no unmount", () => {
    const { unmount } = renderChart();
    fireDataZoom(0, 50);
    unmount();
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);
  });
});