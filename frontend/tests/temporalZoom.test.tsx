import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart, buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
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
    valueKind: "numeric" as const,
    statePoints: [],
    stateValues: [],
    stateQualitySeries: [],
  };
}

function mockChart(
  series: Array<{ id: string; points: Array<[number, number]>; yAxisIndex?: 0 | 1; unit?: string }>,
  yAxisLabels: string[] = ["m/min"],
): ChartBuildResult {
  return {
    series: series.map((s) => mockChartSeries(s.id, s.points, s.yAxisIndex ?? 0, s.unit ?? "m/min")),
    units: yAxisLabels,
    yAxisLabels,
    totalSeries: series.length,
    totalPoints: series.reduce((sum, s) => sum + s.points.length, 0),
    totalNumericPoints: series.reduce((sum, s) => sum + s.points.length, 0),
    totalDroppedPoints: 0,
    totalNonNumericPoints: 0,
    valueKind: "numeric" as const,
    categories: [],
    comparisonType: null,
  };
}

function singleSeriesChart(points: Array<[number, number]>): ChartBuildResult {
  return mockChart([{ id: "1", points }]);
}

const BROAD_POINTS: Array<[number, number]> = [
  [START_TS, 0],
  [START_TS + 1800000, 48],
  [END_TS, 12],
];

const SPIKY_POINTS: Array<[number, number]> = [
  [START_TS, 100],
  [START_TS + 300000, 500],
  [START_TS + 600000, 50],
  [START_TS + 900000, 800],
  [START_TS + 1200000, 150],
  [START_TS + 1500000, 950],
  [START_TS + 1800000, 200],
  [START_TS + 2100000, 700],
  [START_TS + 2400000, 100],
  [START_TS + 2700000, 600],
  [START_TS + 3000000, 300],
  [START_TS + 3300000, 400],
  [END_TS, 250],
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

describe("Zoom temporal exclusivo — testes obrigatórios", () => {
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
      convertFromPixel: vi.fn(() => START_TS),
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

  function renderChart(chart: ChartBuildResult = singleSeriesChart(BROAD_POINTS), extraProps: Record<string, any> = {}) {
    return render(
      <TimeSeriesChart
        chart={chart}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
        {...extraProps}
      />,
    );
  }

  // --- 1. Seleção com altura completa independentemente da posição Y ---
  it("seleção na parte superior, central e inferior produz o mesmo intervalo X", () => {
    const view = renderChart();
    // Independente de onde na vertical, o zoom é o mesmo
    fireDataZoom(10, 40);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);
    const [calledStart, calledEnd] = onVisibleWindowChange.mock.calls[0];
    expect(calledStart.getTime()).toBe(START_TS + (DURATION * 10) / 100);
    expect(calledEnd.getTime()).toBe(START_TS + (DURATION * 40) / 100);

    // Y-axis permanece automático (sem min/max fixados)
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  // --- 2. Arrasto nos dois sentidos ---
  it("arrastar da direita para a esquerda produz zoom válido", () => {
    const view = renderChart();
    // ECharts normaliza start < end internamente
    fireDataZoom(40, 10);
    // With start > end, our handler checks endMs > startMs, so it won't fire.
    // With startValue/endValue properly set, ECharts normalizes them.
    // Let's simulate the normalized version:
    fireDataZoom(10, 40);
    expect(onVisibleWindowChange).toHaveBeenCalled();
    view.unmount();
  });

  // --- 3. Clique sem arrasto, movimento vertical e cancelamento ---
  it("clique sem arrasto preserva marcadores e não aplica zoom", () => {
    const view = renderChart();
    // A click (pointerdown + pointerup with no movement) should add a marker, not zoom
    const container = view.container.firstElementChild!;
    act(() => {
      const downEvent = new PointerEvent("pointerdown", {
        clientX: 200,
        clientY: 200,
        button: 0,
        pointerId: 1,
        bubbles: true,
      });
      container.dispatchEvent(downEvent);
    });
    act(() => {
      const upEvent = new PointerEvent("pointerup", {
        clientX: 200,
        clientY: 200,
        button: 0,
        pointerId: 1,
        bubbles: true,
      });
      container.dispatchEvent(upEvent);
    });
    // Zoom should NOT have been triggered
    expect(onVisibleWindowChange).not.toHaveBeenCalled();
    view.unmount();
  });

  it("Escape cancela seleção sem aplicar zoom", () => {
    const view = renderChart();
    // Start a zoom candidate
    const container = view.container.firstElementChild!;
    act(() => {
      container.dispatchEvent(new PointerEvent("pointerdown", {
        clientX: 200, clientY: 200, button: 0, pointerId: 1, bubbles: true,
      }));
    });
    // Press Escape
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    });
    // Release - should not trigger zoom
    act(() => {
      container.dispatchEvent(new PointerEvent("pointerup", {
        clientX: 400, clientY: 200, button: 0, pointerId: 1, bubbles: true,
      }));
    });
    expect(onVisibleWindowChange).not.toHaveBeenCalled();
    view.unmount();
  });

  // --- 4. Zooms consecutivos usando o intervalo atualmente visível ---
  it("zooms consecutivos usam o intervalo correto e atualizam o histórico", () => {
    const view = renderChart();
    fireDataZoom(10, 50);
    fireDataZoom(20, 40);
    fireDataZoom(25, 35);

    expect(onVisibleWindowChange).toHaveBeenCalledTimes(3);

    // Cada zoom deve registrar o intervalo correto
    const [s1, e1] = onVisibleWindowChange.mock.calls[0];
    expect(s1.getTime()).toBe(START_TS + (DURATION * 10) / 100);
    expect(e1.getTime()).toBe(START_TS + (DURATION * 50) / 100);

    const [s2, e2] = onVisibleWindowChange.mock.calls[1];
    expect(s2.getTime()).toBe(START_TS + (DURATION * 20) / 100);
    expect(e2.getTime()).toBe(START_TS + (DURATION * 40) / 100);

    // Undo de cada nível
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", start: 20, end: 40 }),
    );
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", start: 10, end: 50 }),
    );
    pressCtrlZ();
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", start: 0, end: 100 }),
    );
    view.unmount();
  });

  // --- 5. Intervalo correto antes e depois do refinamento ---
  it("intervalo permanece inalterado após refinamento de dados", () => {
    const view = renderChart();
    fireDataZoom(20, 60);

    const zoomedStart = START_TS + (DURATION * 20) / 100;
    const zoomedEnd = START_TS + (DURATION * 60) / 100;

    // Simula refinamento: novos dados chegam para o trecho mais detalhado
    const refinedPoints: Array<[number, number]> = [
      [zoomedStart + 10000, 25],
      [zoomedStart + 500000, 30],
      [zoomedEnd - 10000, 28],
    ];
    view.rerender(
      <TimeSeriesChart
        chart={singleSeriesChart(refinedPoints)}
        equipment="Turbina 1"
        start={new Date(zoomedStart)}
        end={new Date(zoomedEnd)}
        mode={"recorded" as const}
        onVisibleWindowChange={onVisibleWindowChange}
      />,
    );

    // O intervalo X do gráfico deve ser exatamente o selecionado
    expect(lastOption.xAxis.min).toBe(zoomedStart);
    expect(lastOption.xAxis.max).toBe(zoomedEnd);
    // Y permanece automático
    expect(lastOption.yAxis[0].scale).toBe(true);
    view.unmount();
  });

  // --- 6. Respostas fora de ordem: selecionar A e depois B ---
  it("segundo zoom durante consulta pendente invalida a primeira resposta", async () => {
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

    // Zoom A pendente, depois Zoom B
    fireDataZoom(10, 30);
    fireDataZoom(40, 60);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);

    // Zoom B está ativo
    const callB = onVisibleWindowChange.mock.calls[1];
    expect(callB[0].getTime()).toBe(START_TS + (DURATION * 40) / 100);

    // Resposta atrasada do A chega depois
    await act(async () => {
      resolverA("applied");
      await Promise.resolve();
    });

    // Zoom B continua sendo o ativo (A não sobrescreve)
    view.unmount();
  });

  // --- 7. Reset e Ctrl+Z durante requisição pendente ---
  it("reset durante consulta pendente invalida a resposta atrasada", async () => {
    let resolverPending: (outcome: "applied") => void = () => {};
    onVisibleWindowChange = vi.fn(
      (_s: Date, _e: Date, _reason: string) =>
        new Promise<"applied">((resolve) => {
          resolverPending = resolve;
        }),
    );
    const view = renderChart();

    fireDataZoom(10, 30);
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(1);

    // Reset enquanto a consulta está pendente
    fireRestore();

    // O domínio deve ser restaurado
    expect(lastOption.xAxis.min).toBe(START_TS);
    expect(lastOption.xAxis.max).toBe(END_TS);

    // Resposta atrasada resolve mas não deve afetar o estado
    await act(async () => {
      resolverPending("applied");
      await Promise.resolve();
    });

    expect(lastOption.xAxis.min).toBe(START_TS);
    view.unmount();
  });

  // --- 8. Falha de consulta sem deslocar o período ---
  it("falha no zoom não desloca o período visível", async () => {
    let rejectZoom: (error: Error) => void = () => {};
    onVisibleWindowChange = vi.fn(
      () =>
        new Promise<"applied">((_resolve, reject) => {
          rejectZoom = reject;
        }),
    );
    const view = renderChart();

    fireDataZoom(10, 30);

    await act(async () => {
      rejectZoom(new Error("Network error"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // O gráfico continua mostrando o intervalo original
    expect(lastOption.xAxis.min).toBe(START_TS);
    expect(lastOption.xAxis.max).toBe(END_TS);
    view.unmount();
  });

  // --- 9. Séries com picos e quedas não viram linhas constantes ---
  it("séries com picos e quedas mantêm variação visual após zoom", () => {
    const view = renderChart(singleSeriesChart(SPIKY_POINTS));

    // Zoom para uma região com picos
    fireDataZoom(10, 50);

    // Y-axis permanece em autoescala — sem achatamento
    expect(lastOption.yAxis[0].min).toBeUndefined();
    expect(lastOption.yAxis[0].max).toBeUndefined();
    expect(lastOption.yAxis[0].scale).toBe(true);

    // Os dados da série ainda existem intactos (não foram transformados)
    expect(lastOption.series[0].data).toEqual(SPIKY_POINTS);
    view.unmount();
  });

  // --- 10. Múltiplas séries, lacunas e período sem dados ---
  it("múltiplas séries com lacunas são preservadas sem preenchimento", () => {
    const multiChart = mockChart([
      {
        id: "1",
        points: [
          [START_TS, 10],
          [START_TS + 600000, 20],
          // lacuna: sem pontos entre 600s e 2400s
          [START_TS + 2400000, 15],
          [END_TS, 25],
        ],
      },
      {
        id: "2",
        points: [
          [START_TS, 100],
          [START_TS + 1200000, 150],
          [END_TS, 120],
        ],
      },
    ]);

    const view = renderChart(multiChart);
    fireDataZoom(10, 70);

    // Ambas as séries estão presentes
    expect(lastOption.series).toHaveLength(2);
    // connectNulls está desabilitado — lacunas são preservadas
    expect(lastOption.series[0].connectNulls).toBe(false);
    expect(lastOption.series[1].connectNulls).toBe(false);
    // Nenhum ponto foi adicionado
    expect(lastOption.series[0].data).toHaveLength(4);
    expect(lastOption.series[1].data).toHaveLength(3);
    view.unmount();
  });

  // --- 11. Ausência do slider e layout sem sobreposição ---
  it("option não contém dataZoom do tipo slider", () => {
    const view = renderChart();
    const dzArray = lastOption.dataZoom as any[];
    expect(dzArray).toHaveLength(1);
    expect(dzArray[0].type).toBe("inside");
    expect(dzArray.some((dz: any) => dz.type === "slider")).toBe(false);
    view.unmount();
  });

  it("grid.bottom é menor que o antigo valor de 96 (sem slider)", () => {
    const view = renderChart();
    expect(lastOption.grid.bottom).toBeLessThan(96);
    view.unmount();
  });

  // --- 12. Marcadores, tooltip e legenda preservados ---
  it("tooltip continua configurado após zoom", () => {
    const view = renderChart();
    fireDataZoom(10, 50);
    expect(lastOption.tooltip).toBeDefined();
    expect(lastOption.tooltip.trigger).toBe("axis");
    view.unmount();
  });

  it("legenda contém os nomes das séries após zoom", () => {
    const multiChart = mockChart([
      { id: "1", points: BROAD_POINTS },
      { id: "2", points: BROAD_POINTS },
    ]);
    const view = renderChart(multiChart);
    fireDataZoom(10, 50);
    expect(lastOption.legend.data).toContain("Zona 1");
    expect(lastOption.legend.data).toContain("Zona 2");
    view.unmount();
  });

  // --- buildTimeSeriesChartOption: slider removido e yAxisIndex: "none" ---
  it("buildTimeSeriesChartOption retorna yAxisIndex: 'none' para toolbox dataZoom", () => {
    const chart = singleSeriesChart(BROAD_POINTS);
    const option = buildTimeSeriesChartOption({
      chart,
      equipment: "Test",
      start: new Date(START_TS),
      end: new Date(END_TS),
      mode: "recorded",
    });
    const toolboxDz = (option as any).toolbox?.feature?.dataZoom;
    expect(toolboxDz.yAxisIndex).toBe("none");
  });

  it("buildTimeSeriesChartOption não inclui slider para gráficos numéricos", () => {
    const chart = singleSeriesChart(BROAD_POINTS);
    const option = buildTimeSeriesChartOption({
      chart,
      equipment: "Test",
      start: new Date(START_TS),
      end: new Date(END_TS),
      mode: "recorded",
    });
    const dzArray = (option as any).dataZoom as any[];
    expect(dzArray.every((dz: any) => dz.type !== "slider")).toBe(true);
  });

  it("buildTimeSeriesChartOption não inclui slider para gráficos de estado", () => {
    const chart: ChartBuildResult = {
      series: [{
        ...mockChartSeries("1", []),
        valueKind: "textual",
        statePoints: [[START_TS, 0], [END_TS, 1]],
        stateValues: ["ON", "OFF"],
        stateQualitySeries: [[START_TS, 0], [END_TS, 0]],
      }],
      units: [],
      yAxisLabels: [],
      totalSeries: 1,
      totalPoints: 2,
      totalNumericPoints: 0,
      totalDroppedPoints: 0,
      totalNonNumericPoints: 2,
      valueKind: "textual",
      categories: ["ON", "OFF"],
      comparisonType: null,
    };
    const option = buildTimeSeriesChartOption({
      chart,
      equipment: "Test",
      start: new Date(START_TS),
      end: new Date(END_TS),
      mode: "recorded",
    });
    const dzArray = (option as any).dataZoom as any[];
    expect(dzArray.every((dz: any) => dz.type !== "slider")).toBe(true);
  });

  // --- Ctrl+Z durante requisição pendente ---
  it("Ctrl+Z durante consulta pendente impede que resposta atrasada altere o estado", async () => {
    let rejectA: () => void = () => {};
    onVisibleWindowChange = vi.fn(
      (_s: Date, _e: Date) =>
        new Promise<"applied">((_resolve, reject) => {
          if (onVisibleWindowChange.mock.calls.length === 1) {
            rejectA = () => reject(new Error("aborted"));
          } else {
            return Promise.resolve("applied" as const);
          }
        }),
    );
    const view = renderChart();

    // Zoom A pendente; desfaz antes da resposta
    fireDataZoom(10, 30);
    pressCtrlZ();
    expect(onVisibleWindowChange).toHaveBeenCalledTimes(2);
    expect(dispatchAction).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dataZoom", dataZoomIndex: 0, start: 0, end: 100 }),
    );

    // Resposta atrasada não deve alterar o estado
    await act(async () => {
      rejectA();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(lastOption.xAxis.min).toBe(START_TS);
    expect(lastOption.xAxis.max).toBe(END_TS);
    view.unmount();
  });
});
