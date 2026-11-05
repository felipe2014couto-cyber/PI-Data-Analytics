import { useEffect } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiMock, connectedHealthFixture, equipmentFixture, mockApiModule, paginated, piTagFixture, sectionFixture, variableTypeFixture } from "./mocks/api";

vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/auth/AuthContext", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

const chartProbe = vi.hoisted(() => ({
  option: null as any,
  events: {} as Record<string, Array<(event: any) => void>>,
  instance: null as any,
}));

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ option, onInit }: any) => {
    chartProbe.option = option;
    useEffect(() => { onInit?.(chartProbe.instance); }, [onInit]);
    return <div data-testid="zoom-snapshot-echarts" />;
  },
}));

import { DataVisualizationPage } from "../src/pages/DataVisualizationPage";

const START = Date.parse("2026-10-01T00:00:00Z");
const END = Date.parse("2026-10-08T00:00:00Z");

function response(points: Array<[number, number]>) {
  return {
    start_time: new Date(points[0][0]).toISOString(),
    end_time: new Date(points[points.length - 1][0]).toISOString(),
    mode: "recorded",
    series: [{
      tag_id: 1,
      tag_name: "RB1.SPEED",
      display_name: "Velocidade",
      equipment: "RB1",
      section: "FORNO",
      variable_type: "SPEED",
      unit: "m/min",
      points: points.map(([timestamp, value]) => ({
        timestamp: new Date(timestamp).toISOString(), value, good: true,
        questionable: false, substituted: false,
      })),
    }],
    errors: [],
    query_execution: {
      resolution_mode: "automatic", sampled: true, partial: false,
      strategy: "timescaledb_continuous_aggregate", effective_interval: "1m",
      points_returned: points.length,
    },
  };
}

function mainSeriesData() {
  return (chartProbe.option?.series ?? []).find((item: any) => item.id === "tag:1")?.data ?? [];
}

function zoomTo(start: number, end: number) {
  act(() => {
    for (const handler of chartProbe.events.dataZoom ?? []) {
      handler({ start: 20, end: 60, startValue: start, endValue: end });
    }
  });
}

async function setupAndZoom(undo: "button" | "keyboard") {
  apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
  apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
  apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
  apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
  apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  apiMock.visualConfigList.mockResolvedValue([]);
  apiMock.visualConfigHistory.mockResolvedValue([]);
  apiMock.timeSeriesQuery
    .mockResolvedValueOnce(response([[START, 10], [START + 3_600_000, 20], [END, 30]]))
    .mockResolvedValueOnce(response([
      [START + 1_800_000, 15], [START + 2_000_000, 16], [START + 2_200_000, 17],
      [START + 2_400_000, 18], [START + 2_600_000, 19],
    ]))
    .mockResolvedValueOnce(response([[START + 86_400_000, 91], [START + 172_800_000, 92]]));

  render(<MemoryRouter><DataVisualizationPage /></MemoryRouter>);
  const equipment = await screen.findByTestId("equipment-select");
  await waitFor(() => expect(within(equipment).getAllByRole("option").length).toBeGreaterThan(1));
  fireEvent.change(equipment, { target: { value: "1" } });
  await waitFor(() => expect(screen.getByTestId("section-select")).not.toBeDisabled());
  const tag = await screen.findByTestId("tag-option-1");
  fireEvent.click(tag);
  fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "absolute" } });
  fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-10-01T00:00:00" } });
  fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-10-08T00:00:00" } });
  fireEvent.click(screen.getByTestId("filters-submit"));
  await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(mainSeriesData()).toHaveLength(3));

  zoomTo(START + 1_800_000, START + 2_600_000);
  await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(mainSeriesData()).toHaveLength(5));

  const undoZoom = () => {
    if (undo === "button") {
      act(() => chartProbe.option.toolbox.feature.myZoomBack.onclick());
    } else {
      act(() => window.dispatchEvent(new KeyboardEvent("keydown", {
        key: "z", ctrlKey: true, bubbles: true, cancelable: true,
      })));
    }
  };
  return { undoZoom, tag };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.timeSeriesQuery.mockReset();
  chartProbe.option = null;
  chartProbe.events = {};
  chartProbe.instance = {
    on: (event: string, handler: (event: any) => void) => { (chartProbe.events[event] ??= []).push(handler); },
    off: vi.fn(),
    getZr: () => ({ on: vi.fn(), off: vi.fn(), trigger: vi.fn() }),
    getModel: () => ({ getComponent: () => ({ coordinateSystem: { getRect: () => ({ x: 60, y: 70, width: 700, height: 254 }) } }) }),
    getOption: () => ({ dataZoom: [{ start: 0, end: 100 }], legend: [{ selected: {} }] }),
    convertToPixel: () => [200, 150], convertFromPixel: () => START,
    getWidth: () => 820, getHeight: () => 420,
    dispatchAction: vi.fn(), setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
  };
});

describe("undo restores the chart dataset snapshot", () => {
  it.each(["button", "keyboard"] as const)("restaura a janela completa pelo %s sem consultar novamente", async (undo) => {
    const { undoZoom, tag } = await setupAndZoom(undo);
    expect(mainSeriesData()).toHaveLength(5);

    undoZoom();

    await waitFor(() => expect(mainSeriesData()).toHaveLength(3));
    expect(mainSeriesData()).toEqual([[START, 10], [START + 3_600_000, 20], [END, 30]]);
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(2);
    expect(tag).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("period-kind")).toHaveValue("absolute");
  });

  it("descarta snapshots após uma nova consulta-base e não restaura seus dados ou período", async () => {
    await setupAndZoom("keyboard");
    expect(mainSeriesData()).toHaveLength(5);

    fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-10-02T00:00:00" } });
    fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-10-09T00:00:00" } });
    fireEvent.click(screen.getByTestId("filters-submit"));
    await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(mainSeriesData()).toEqual([[START + 86_400_000, 91], [START + 172_800_000, 92]]));

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", {
      key: "z", ctrlKey: true, bubbles: true, cancelable: true,
    })));

    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(3);
    expect(mainSeriesData()).toEqual([[START + 86_400_000, 91], [START + 172_800_000, 92]]);
    expect(screen.getByTestId("absolute-start")).toHaveValue("2026-10-02T00:00");
  });
});
