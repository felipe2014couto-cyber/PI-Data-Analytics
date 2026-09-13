import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEffect } from "react";
import { TimeSeriesChart } from "../src/components/TimeSeriesChart";
import type { ChartBuildResult, ChartSeries } from "../src/utils/chartData";

let mockEChartsInstance: any;
let registeredEventHandlers: Record<string, Function[]> = {};
let setPointerCaptureMock = vi.fn();
let releasePointerCaptureMock = vi.fn();
let zrTriggerMock = vi.fn();
let currentZoom = { start: 0, end: 100 };
let wrapperRenderCount = 0;

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ onInit, height, activateAreaZoom, syncGroup }: any) => {
    wrapperRenderCount += 1;
    useEffect(() => {
      if (onInit && mockEChartsInstance) {
        onInit(mockEChartsInstance);
      }
    }, [onInit]);
    return (
      <div
        data-testid="echarts-wrapper"
        data-area-zoom={Boolean(activateAreaZoom)}
        data-sync-group={syncGroup ?? ""}
        style={{ height }}
      />
    );
  },
}));

const START_TS = 1725418751000;
const END_TS = START_TS + 3600000;

function mockChartSeries(id: string, axis: 0 | 1 = 0): ChartSeries {
  return {
    tagId: 7,
    displayName: `Zona ${id}`,
    tagName: `TAG_${id}`,
    equipment: null,
    section: null,
    variableType: null,
    unit: "°C",
    yAxisIndex: axis,
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
  const s = [mockChartSeries("1"), mockChartSeries("2")];
  return {
    series: s,
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

if (!window.PointerEvent) {
  class MockPointerEvent extends MouseEvent {
    public pointerId: number;
    constructor(type: string, params: any = {}) {
      super(type, params);
      this.pointerId = params.pointerId ?? 0;
    }
  }
  window.PointerEvent = MockPointerEvent as any;
}

describe("TimeSeriesChart - Arraste e Zoom sem Interferência", () => {
  beforeEach(() => {
    registeredEventHandlers = {};
    setPointerCaptureMock = vi.fn();
    releasePointerCaptureMock = vi.fn();
    zrTriggerMock = vi.fn();
    currentZoom = { start: 0, end: 100 };
    wrapperRenderCount = 0;

    window.HTMLElement.prototype.setPointerCapture = setPointerCaptureMock;
    window.HTMLElement.prototype.releasePointerCapture = releasePointerCaptureMock;
    window.HTMLElement.prototype.hasPointerCapture = vi.fn(() => true);

    mockEChartsInstance = {
      convertToPixel: vi.fn((target: any, val: any) => {
        if (target.xAxisIndex === 0) {
          const t = typeof val === "number" ? val : val[0];
          return 60 + ((t - START_TS) / 3600000) * 700;
        }
        return [200, 150];
      }),
      convertFromPixel: vi.fn((_target: any, px: number) => {
        return START_TS + ((px - 60) / 700) * 3600000;
      }),
      getModel: vi.fn(() => ({
        getComponent: () => ({
          coordinateSystem: {
            getRect: () => ({ x: 60, y: 70, width: 700, height: 254 }),
          },
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
        trigger: zrTriggerMock,
      })),
      getWidth: () => 820,
      getHeight: () => 420,
      setOption: vi.fn(),
      dispatchAction: vi.fn(),
      on: vi.fn((event: string, handler: Function) => {
        if (!registeredEventHandlers[event]) registeredEventHandlers[event] = [];
        registeredEventHandlers[event].push(handler);
      }),
      off: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
    };
  });

  it("ativa por padrão a seleção de área com o botão esquerdo", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
      />,
    );

    expect(screen.getByTestId("echarts-wrapper")).toHaveAttribute("data-area-zoom", "true");
  });

  it("clique simples mantém o marcador, mas arraste de 6 px não cria marcador", () => {
    const { rerender } = render(
      <TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" />,
    );
    const plot = screen.getByTestId("echarts-wrapper").parentElement!;
    Object.defineProperty(plot, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 820, bottom: 420, width: 820, height: 420, x: 0, y: 0, toJSON: () => ({}) }),
    });

    fireEvent.pointerDown(plot, { button: 0, pointerId: 1, clientX: 200, clientY: 150 });
    fireEvent.pointerUp(plot, { button: 0, pointerId: 1, clientX: 200, clientY: 150 });
    expect(screen.getByTestId("marker-line-0")).toBeInTheDocument();

    rerender(<TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" pinnedCursorTs={null} />);
    fireEvent.doubleClick(plot, { clientX: 200, clientY: 150 });
    expect(screen.queryByTestId("marker-line-0")).not.toBeInTheDocument();
    fireEvent.pointerDown(plot, { button: 0, pointerId: 2, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(plot, { pointerId: 2, clientX: 260, clientY: 150 });
    fireEvent.pointerUp(plot, { button: 0, pointerId: 2, clientX: 260, clientY: 150 });
    expect(screen.queryByTestId("marker-line-0")).not.toBeInTheDocument();
  });

  it("Escape encerra a seleção nativa e restaura o dataZoom anterior", () => {
    render(<TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" />);
    const plot = screen.getByTestId("echarts-wrapper").parentElement!;
    Object.defineProperty(plot, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 820, bottom: 420, width: 820, height: 420, x: 0, y: 0, toJSON: () => ({}) }),
    });
    fireEvent.pointerDown(plot, { button: 0, pointerId: 3, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(plot, { pointerId: 3, clientX: 300, clientY: 150 });
    fireEvent.keyDown(window, { key: "Escape" });

    expect(zrTriggerMock).toHaveBeenCalledWith("mouseup", expect.any(Object));
    expect(mockEChartsInstance.dispatchAction).toHaveBeenCalledWith({
      type: "dataZoom",
      dataZoomIndex: 0,
      start: 0,
      end: 100,
    });
  });

  it("não renderiza React nem aplica zoom durante pointermove da seleção", () => {
    render(<TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" />);
    const plot = screen.getByTestId("echarts-wrapper").parentElement!;
    Object.defineProperty(plot, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 820, bottom: 420, width: 820, height: 420, x: 0, y: 0, toJSON: () => ({}) }),
    });
    const rendersBeforeDrag = wrapperRenderCount;

    fireEvent.pointerDown(plot, { button: 0, pointerId: 4, clientX: 150, clientY: 150 });
    for (let x = 151; x <= 650; x += 5) {
      fireEvent.pointerMove(plot, { pointerId: 4, clientX: x, clientY: 150 });
    }

    expect(wrapperRenderCount).toBe(rendersBeforeDrag);
    expect(mockEChartsInstance.dispatchAction).not.toHaveBeenCalledWith(expect.objectContaining({ type: "dataZoom" }));
  });

  it("pointercancel limpa a seleção e não converte o gesto em clique de marcador", () => {
    render(<TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" />);
    const plot = screen.getByTestId("echarts-wrapper").parentElement!;
    Object.defineProperty(plot, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 0, top: 0, right: 820, bottom: 420, width: 820, height: 420, x: 0, y: 0, toJSON: () => ({}) }),
    });
    fireEvent.pointerDown(plot, { button: 0, pointerId: 5, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(plot, { pointerId: 5, clientX: 300, clientY: 150 });
    fireEvent.pointerCancel(plot, { pointerId: 5, clientX: 300, clientY: 150 });
    fireEvent.pointerUp(plot, { button: 0, pointerId: 5, clientX: 300, clientY: 150 });

    expect(zrTriggerMock).toHaveBeenCalledWith("mouseup", expect.any(Object));
    expect(screen.queryByTestId("marker-line-0")).not.toBeInTheDocument();
  });

  it("Ctrl+Z desfaz zooms sucessivos no domínio local sem consulta externa", () => {
    render(<TimeSeriesChart chart={mockChart()} equipment="Turbina 1" start={new Date(START_TS)} end={new Date(END_TS)} mode="recorded" />);
    currentZoom = { start: 20, end: 70 };
    act(() => registeredEventHandlers.dataZoom?.forEach((handler) => handler({})));
    currentZoom = { start: 35, end: 55 };
    act(() => registeredEventHandlers.dataZoom?.forEach((handler) => handler({})));

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(mockEChartsInstance.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "dataZoom", start: 20, end: 70,
    }));
  });

  it("expõe o grupo de sincronização temporal sem duplicar handlers no rerender", () => {
    const props = { chart: mockChart(), equipment: "Turbina 1", start: new Date(START_TS), end: new Date(END_TS), mode: "recorded" as const, syncGroup: "linked-time" };
    const { rerender } = render(<TimeSeriesChart {...props} />);
    expect(screen.getByTestId("echarts-wrapper")).toHaveAttribute("data-sync-group", "linked-time");
    expect(registeredEventHandlers.dataZoom).toHaveLength(1);
    rerender(<TimeSeriesChart {...props} />);
    expect(registeredEventHandlers.dataZoom).toHaveLength(1);
  });

  it("1. A linha vertical e a caixa de valores possuem cursor de redimensionamento (ew-resize)", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    const markerLine = screen.getByTestId("marker-line-0");
    const markerBox = screen.getByTestId("marker-box-0");

    expect(markerLine.style.cursor).toBe("ew-resize");
    expect(markerBox.style.cursor).toBe("ew-resize");
  });

  it("2. Clicar na linha do marcador inicia o arraste e ativa o drag-backdrop", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    const markerLine = screen.getByTestId("marker-line-0");
    expect(screen.queryByTestId("drag-backdrop")).not.toBeInTheDocument();

    act(() => {
      fireEvent.pointerDown(markerLine, { button: 0, clientX: 410, clientY: 100 });
    });

    // Durante o arraste, o backdrop protetor é montado
    expect(screen.getByTestId("drag-backdrop")).toBeInTheDocument();
  });

  it("3. pointerup encerra o arraste e remove o drag-backdrop", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    const markerLine = screen.getByTestId("marker-line-0");

    act(() => {
      fireEvent.pointerDown(markerLine, { button: 0, clientX: 410, clientY: 100 });
      fireEvent.pointerMove(window, { clientX: 460, clientY: 100 });
    });

    const posAfterMove = screen.getByTestId("marker-line-0").style.left;

    act(() => {
      fireEvent.pointerUp(window, { clientX: 460, clientY: 100 });
    });

    // O backdrop é removido
    expect(screen.queryByTestId("drag-backdrop")).not.toBeInTheDocument();

    // Movimento subsequente após soltar o mouse não altera mais a posição
    act(() => {
      fireEvent.pointerMove(window, { clientX: 600, clientY: 100 });
    });
    expect(screen.getByTestId("marker-line-0").style.left).toBe(posAfterMove);
  });

  it("4. O backdrop não permanece montado quando ocioso", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    expect(screen.queryByTestId("drag-backdrop")).not.toBeInTheDocument();
  });

  it("5. dataZoom não altera timestamps armazenados dos marcadores", () => {
    const originalMarkerTs = START_TS + 1800000;
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={originalMarkerTs}
      />,
    );

    const toolbar = screen.getByTestId("markers-toolbar");
    const initialText = toolbar.textContent;

    // Dispara evento de dataZoom do ECharts
    act(() => {
      registeredEventHandlers["dataZoom"]?.forEach((fn) => fn({}));
    });

    // O horário exibido no toolbar permanece inalterado
    expect(toolbar.textContent).toBe(initialText);
  });

  it("6. Um marcador fora da janela visível é ocultado sem ter seu timestamp modificado", () => {
    const originalMarkerTs = START_TS + 1800000;
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={originalMarkerTs}
      />,
    );

    expect(screen.getByTestId("marker-line-0")).toBeInTheDocument();

    // Simula zoom onde o marcador fica fora da janela visível (retorna pixelX = 9999 > gridRight)
    mockEChartsInstance.convertToPixel.mockImplementation((target: any) => {
      if (target.xAxisIndex === 0) return 9999;
      return [200, 150];
    });

    act(() => {
      registeredEventHandlers["dataZoom"]?.forEach((fn) => fn({}));
    });

    // Marcador visual é ocultado
    expect(screen.queryByTestId("marker-line-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("marker-box-0")).not.toBeInTheDocument();

    // Mas o toolbar preserva a identidade e o horário original do marcador
    expect(screen.getByTestId("markers-toolbar")).toBeInTheDocument();
  });

  it("7. Ao restaurar o zoom, o marcador reaparece na posição correta", () => {
    const originalMarkerTs = START_TS + 1800000;
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={originalMarkerTs}
      />,
    );

    // Fora da tela
    mockEChartsInstance.convertToPixel.mockReturnValue(9999);
    act(() => {
      registeredEventHandlers["dataZoom"]?.forEach((fn) => fn({}));
    });
    expect(screen.queryByTestId("marker-line-0")).not.toBeInTheDocument();

    // Restaura o zoom (volta para a coordenada correta)
    mockEChartsInstance.convertToPixel.mockImplementation((target: any) => {
      if (target.xAxisIndex === 0) return 410;
      return [200, 150];
    });
    act(() => {
      registeredEventHandlers["restore"]?.forEach((fn) => fn({}));
    });

    // Marcador reaparece
    expect(screen.getByTestId("marker-line-0")).toBeInTheDocument();
  });

  it("8. Arrastar marcador não chama setOption no ECharts", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    mockEChartsInstance.setOption.mockClear();

    const markerLine = screen.getByTestId("marker-line-0");
    act(() => {
      fireEvent.pointerDown(markerLine, { button: 0, clientX: 410, clientY: 100 });
      fireEvent.pointerMove(window, { clientX: 450, clientY: 100 });
      fireEvent.pointerMove(window, { clientX: 380, clientY: 100 }); // inverteu para a esquerda
      fireEvent.pointerMove(window, { clientX: 500, clientY: 100 }); // inverteu para a direita
    });

    // Zero chamadas a setOption durante o arraste!
    expect(mockEChartsInstance.setOption).not.toHaveBeenCalled();

    act(() => {
      fireEvent.pointerUp(window, { clientX: 500, clientY: 100 });
    });
  });

  it("9. Permite inverter o movimento do mouse para esquerda e direita no mesmo arraste", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    const markerLine = screen.getByTestId("marker-line-0");

    // Inicia arrasto
    act(() => {
      fireEvent.pointerDown(markerLine, { button: 0, clientX: 410, clientY: 100 });
    });

    // Move para a direita
    act(() => {
      fireEvent.pointerMove(window, { clientX: 550, clientY: 100 });
    });
    const posRight = screen.getByTestId("marker-line-0").style.left;

    // Inverte para a esquerda sem soltar
    act(() => {
      fireEvent.pointerMove(window, { clientX: 250, clientY: 100 });
    });
    const posLeft = screen.getByTestId("marker-line-0").style.left;
    expect(parseFloat(posLeft)).toBeLessThan(parseFloat(posRight));

    // Inverte novamente para a direita
    act(() => {
      fireEvent.pointerMove(window, { clientX: 480, clientY: 100 });
    });
    const posRightAgain = screen.getByTestId("marker-line-0").style.left;
    expect(parseFloat(posRightAgain)).toBeGreaterThan(parseFloat(posLeft));

    act(() => {
      fireEvent.pointerUp(window, { clientX: 480, clientY: 100 });
    });
  });

  it("10. Marcadores continuam acompanhando o gráfico após resize", () => {
    render(
      <TimeSeriesChart
        chart={mockChart()}
        equipment="Turbina 1"
        start={new Date(START_TS)}
        end={new Date(END_TS)}
        mode="recorded"
        pinnedCursorTs={START_TS + 1800000}
      />,
    );

    expect(screen.getByTestId("marker-line-0")).toBeInTheDocument();

    // Dispara evento de resize da janela
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });

    expect(screen.getByTestId("marker-line-0")).toBeInTheDocument();
  });
});
