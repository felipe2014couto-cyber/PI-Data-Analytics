import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  connectedHealthFixture,
  mockApiModule,
  notConfiguredHealthFixture,
  paginated,
  equipmentFixture,
  piTagFixture,
  sectionFixture,
  variableTypeFixture,
} from "./mocks/api";
import type { PiTag, TimeSeries, VisualConfigurationDocument } from "../src/types";

vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/components/EChartsWrapper");

import App from "../src/App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setSelectValue(element: HTMLSelectElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLSelectElement.prototype,
    "value",
  )?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function submitFirstAvailableTag() {
  const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
  await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
  fireEvent.change(equipmentSelect, { target: { value: "1" } });
  await waitFor(() => expect(screen.getByTestId("section-select")).not.toBeDisabled());
  const tagList = await screen.findByTestId("tag-multi-select");
  const option = await within(tagList).findByTestId("tag-option-1");
  fireEvent.click(option);
  await waitFor(() => expect(option).toHaveAttribute("data-selected", "true"));
  fireEvent.click(await screen.findByTestId("filters-submit"));
}

const TIME_SERIES: TimeSeries = {
  start_time: "2026-07-15T00:00:00Z",
  end_time: "2026-07-15T01:00:00Z",
  mode: "recorded",
  series: [
    {
      tag_id: 1,
      tag_name: "RB3.TEMP",
      display_name: "Temperatura",
      equipment: "RB3",
      section: "ENTRADA",
      variable_type: "TEMPERATURE",
      unit: "C",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 1.5, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: 2.5, good: true, questionable: false, substituted: false },
      ],
    },
  ],
  errors: [],
};

const TEXTUAL_SERIES = {
  ...TIME_SERIES.series[0],
  tag_id: 2,
  tag_name: "RB3.STATE",
  display_name: "Estado",
  unit: null,
  points: [
    { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
    { timestamp: "2026-07-15T00:01:00Z", value: "RUN", good: true, questionable: false, substituted: false },
  ],
};

describe("Data visualization page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.visualConfigHistory.mockResolvedValue([]);
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
  });

  it("loads equipment, section and variable type lookups", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    await waitFor(() => {
      expect(apiMock.listEquipments).toHaveBeenCalled();
    });
    expect(apiMock.listSections).toHaveBeenCalled();
    expect(apiMock.listVariableTypes).toHaveBeenCalled();
    expect(apiMock.listPiTags).toHaveBeenCalled();
    expect(screen.getByTestId("data-filters-panel")).toBeInTheDocument();
  });

  it("restaura configuração completa sem efeitos dependentes apagarem as tags", async () => {
    const document: VisualConfigurationDocument = {
      schema_version: 1,
      visual_rules: { enabled: false, selectedSeriesInstanceId: null, bySeries: {} },
      sidebar_state: {
        filters: {
          analysisModel: "unit", equipmentId: 1, sectionId: 1, variableTypeId: 1,
          timePeriod: { kind: "preset", preset: "PT1H" }, timezone: "America/Sao_Paulo",
          mode: "recorded", interval: "5m", maxCount: 2000, resolutionMode: "manual",
          targetPointsPerTag: 5000, ignoreBadQuality: false, visualization: "line",
          filterConfiguration: { quality: { excludeBad: false, excludeQuestionable: true, excludeSubstituted: false }, rules: [] },
        },
        selectedTagIds: [1],
        seriesAssignments: [{ tagId: 1, order: 0, lineAxis: "secondary", scatterRole: "none" }],
        metricConfiguration: { kind: "single", metric: "mean" },
        comparison: { type: "disabled", contextBEquipmentId: null, contextBCategoryId: null, contextBTagIds: [], contextBStart: "", contextBEnd: "" },
      },
    };
    const savedConfig = { id: "complete", name: "Completa", description: null, current_version: 4, created_at: "2026-01-01", updated_at: "2026-01-01", document };
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture])); apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.visualConfigList.mockResolvedValue([savedConfig]); apiMock.visualConfigGet.mockResolvedValue(savedConfig);
    renderAt("/analises/visualizacao");
    await waitFor(() => expect(screen.getByTestId("visual-config-select")).toHaveValue(""));
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "complete" } });
    fireEvent.click(screen.getByRole("button", { name: "Ações da configuração" })); fireEvent.click(screen.getByText("Abrir"));
    await waitFor(() => expect(screen.getByTestId("equipment-select")).toHaveValue("1"));
    expect(screen.getByTestId("section-select")).toHaveValue("1");
    expect(screen.getByTestId("variable-type-select")).toHaveValue("1");
    expect(screen.getByTestId("period-kind")).toHaveValue("preset");
    expect(screen.getByTestId("period-preset")).toHaveValue("PT1H");
    expect(within(screen.getByTestId("tag-multi-select")).getByTestId("tag-option-1")).toHaveAttribute("data-selected", "true");
    expect(screen.getByText("Aberta: Completa, versão 4")).toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("keeps period and context values mounted when their sections are collapsed", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
    fireEvent.change(equipmentSelect, { target: { value: "1" } });
    await waitFor(() => expect(equipmentSelect).toHaveValue("1"));
    fireEvent.click(screen.getByRole("button", { name: "Período" }));
    fireEvent.click(screen.getByRole("button", { name: "Contexto" }));

    expect(screen.getByTestId("period-kind")).toBeInTheDocument();
    expect(screen.getByTestId("equipment-select")).toHaveValue("1");
    expect(screen.getByTestId("variable-type-select")).toBeVisible();
    expect(screen.getByTestId("tag-multi-select")).toBeVisible();
  });

  it("runs the existing query action from the top CSV toolbar", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");

    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    fireEvent.change(equipmentSelect, { target: { value: "1" } });
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(await within(tagList).findByTestId("tag-option-1"));
    fireEvent.click(screen.getByTestId("filters-submit-top"));

    await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("filters-submit")).toBeInTheDocument();
  });

  it("starts graph configuration collapsed and preserves its values independently from filters", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const graphToggle = await screen.findByTestId("graph-configuration-toggle");
    const filtersToggle = screen.getByTestId("advanced-filters-toggle");
    expect(graphToggle).toHaveAttribute("aria-expanded", "false");
    expect(filtersToggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(graphToggle);
    const visualization = screen.getByTestId("visualization-select") as HTMLSelectElement;
    fireEvent.change(visualization, { target: { value: "line" } });
    fireEvent.click(graphToggle);
    fireEvent.click(graphToggle);

    expect(visualization).toHaveValue("line");
    expect(filtersToggle).toHaveAttribute("aria-expanded", "false");
  });

  it("uses interpolated mode by default and preserves a manual change to recorded", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const interpolated = await screen.findByTestId("mode-interpolated");
    const recorded = screen.getByTestId("mode-recorded");
    expect(interpolated).toBeChecked();
    expect(recorded).not.toBeChecked();
    fireEvent.click(recorded);
    fireEvent.click(screen.getByTestId("graph-configuration-toggle"));
    expect(recorded).toBeChecked();
    expect(interpolated).not.toBeChecked();
  });

  it("defaults to automatic and exposes only implemented visualization types", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const select = (await screen.findByTestId("visualization-select")) as HTMLSelectElement;
    expect(select.value).toBe("automatic");
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      "Automática",
      "Linha temporal",
      "Estados",
      "Histograma",
      "Boxplot",
      "Dispersão",
      "Barras — último valor",
      "Valor único",
    ]);
    expect(select.labels?.[0]).toHaveTextContent("Visualização");
    expect(select.textContent).not.toMatch(/Parametrização|Comparação por períodos/i);
  });

  it("shows all original series in single value without a new query and preserves summary, CSV and dropped count", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        {
          ...TIME_SERIES.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:02:00Z", value: "600", good: false, questionable: false, substituted: false },
          ],
        },
        TEXTUAL_SERIES,
        { ...TEXTUAL_SERIES, tag_id: 3, tag_name: "RB3.ENABLED", display_name: "Habilitado", points: [
          { timestamp: "2026-07-15T00:03:00Z", value: true, good: true, questionable: false, substituted: false },
        ] },
      ],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    const summary = screen.getByTestId("query-summary").textContent;
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("1");

    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "singleValue" } });
    expect(screen.getAllByTestId("single-value-card-column")).toHaveLength(3);
    expect(screen.getByTestId("single-value-1")).toHaveTextContent("10");
    expect(screen.getByTestId("single-value-2")).toHaveTextContent("RUN");
    expect(screen.getByTestId("single-value-3")).toHaveTextContent("true");
    expect(screen.queryByTestId("chart-mixed-series")).not.toBeInTheDocument();
    expect(screen.getByTestId("query-summary").textContent).toBe(summary);
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("1");
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  }, 30_000);

  it("switches between automatic, line and states without querying again or changing summary and CSV", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [TIME_SERIES.series[0], TEXTUAL_SERIES],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(
      await screen.findByTestId("numeric-chart", {}, { timeout: 20_000 }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("textual-chart")).toBeInTheDocument();
    const summaryBefore = screen.getByTestId("query-summary").textContent;
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();

    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "line" } });
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Estado");
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Linha temporal");
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();

    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "states" } });
    expect(screen.queryByTestId("numeric-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("textual-chart")).toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Temperatura");
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Estados");
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  }, 30_000);

  it("does not render an empty chart for a visualization with no compatible series", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [TEXTUAL_SERIES] });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("textual-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "line" } });
    expect(screen.queryByTestId("numeric-chart")).not.toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent(
      "Estados” ou “Automática",
    );
    expect(screen.queryByTestId("chart-no-data")).not.toBeInTheDocument();
  });

  it("switches to separate histograms and unit-grouped boxplots without a new query", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        TIME_SERIES.series[0],
        {
          ...TIME_SERIES.series[0],
          tag_id: 3,
          tag_name: "RB3.PRESS",
          display_name: "Pressão",
          unit: "bar",
        },
        TEXTUAL_SERIES,
      ],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    const summaryBefore = screen.getByTestId("query-summary").textContent;

    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "histogram" },
    });
    expect(screen.getAllByTestId("histogram-chart")).toHaveLength(2);
    expect(screen.queryByTestId("numeric-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent(
      "Histograma",
    );
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Estado");
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();

    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "boxplot" },
    });
    expect(screen.getAllByTestId("boxplot-chart")).toHaveLength(2);
    expect(screen.queryByTestId("histogram-charts")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Boxplot");
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("orients histogram and boxplot when only textual series are available", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [TEXTUAL_SERIES] });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("textual-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "histogram" },
    });
    expect(screen.queryByTestId("histogram-charts")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Histograma");
    expect(screen.queryByTestId("chart-no-data")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "boxplot" },
    });
    expect(screen.queryByTestId("boxplot-charts")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Boxplot");
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "scatter" },
    });
    expect(screen.getByTestId("scatter-series-guidance")).toHaveTextContent("duas séries");
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "bars" },
    });
    expect(screen.queryByTestId("latest-bars-charts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart-no-data")).not.toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("switches to scatter and latest-value bars without querying or changing summary", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    const secondNumeric = {
      ...TIME_SERIES.series[0],
      tag_id: 3,
      tag_name: "RB3.PRESS",
      display_name: "Pressão",
      unit: "bar",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: 20, good: true, questionable: false, substituted: false },
      ],
    };
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [TIME_SERIES.series[0], secondNumeric, TEXTUAL_SERIES],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    const summaryBefore = screen.getByTestId("query-summary").textContent;
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "scatter" },
    });
    expect(screen.getByTestId("scatter-series-guidance")).toHaveTextContent("explicitamente");
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent("Estado");
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);

    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "bars" },
    });
    expect(screen.getAllByTestId("latest-bars-chart")).toHaveLength(2);
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent(
      "Barras — último valor",
    );
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    expect(screen.getByTestId("query-summary").textContent).toBe(summaryBefore);
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("orients scatter when only one numeric series is available", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "scatter" },
    });
    expect(screen.getByTestId("scatter-series-guidance")).toHaveTextContent("mais uma");
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
  });

  it("orients scatter for three series and insufficient coincident timestamps", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    const second = {
      ...TIME_SERIES.series[0],
      tag_id: 2,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 10, good: true, questionable: false, substituted: false },
      ],
    };
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [TIME_SERIES.series[0], second, { ...second, tag_id: 3 }],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "scatter" },
    });
    expect(screen.getByTestId("scatter-series-guidance")).toHaveTextContent("Foram encontradas 3");
  });

  it("recommends interpolated mode when two series have insufficient matching timestamps", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        { ...TIME_SERIES.series[0], points: [{ timestamp: "2026-07-15T00:00:00Z", value: 1, good: true, questionable: false, substituted: false }] },
        { ...TIME_SERIES.series[0], tag_id: 2, points: [{ timestamp: "2026-07-15T00:01:00Z", value: 2, good: true, questionable: false, substituted: false }] },
      ],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), {
      target: { value: "scatter" },
    });
    expect(screen.getByTestId("scatter-series-guidance")).toHaveTextContent("explicitamente");
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
  });

  it("shows one state series and names excess textual series", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [TEXTUAL_SERIES, { ...TEXTUAL_SERIES, tag_id: 3, display_name: "Modo" }],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("chart-multiple-textual")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "states" } });
    expect(screen.getByTestId("textual-chart")).toBeInTheDocument();
    expect(screen.getByTestId("chart-multiple-textual")).toHaveTextContent("Modo");
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
  });

  it("keeps multiple numeric series together in line mode", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        TIME_SERIES.series[0],
        { ...TIME_SERIES.series[0], tag_id: 2, display_name: "Pressão" },
      ],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "line" } });
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.getByTestId("metric-series")).toHaveTextContent("2");
    expect(screen.queryByTestId("chart-incompatible-visualization")).not.toBeInTheDocument();
  });

  it("orients states mode when only numeric series are available", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "states" } });
    expect(screen.queryByTestId("numeric-chart")).not.toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-incompatible-visualization")).toHaveTextContent(
      "Linha temporal” ou “Automática",
    );
    expect(screen.queryByTestId("chart-no-data")).not.toBeInTheDocument();
  });

  it("filters sections when the equipment changes", async () => {
    const otherEquipment = {
      id: 2,
      code: "RC4",
      name: "Outro equipamento",
      description: null,
      active: true,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    };
    const sectionForOther = {
      id: 2,
      equipment_id: 2,
      code: "FORNO2",
      name: "Forno 2",
      description: null,
      active: true,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    };
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture, otherEquipment]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture, sectionForOther]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    // Wait for sections to be loaded (we know they're in the page after the
    // loadLookups promise resolves).
    await waitFor(() => {
      expect(apiMock.listSections).toHaveBeenCalled();
    });
    setSelectValue(equipmentSelect, "2");

    await waitFor(() => {
      const sectionSelect = screen.getByTestId("section-select") as HTMLSelectElement;
      const options = Array.from(sectionSelect.options).map((o) => o.textContent);
      expect(options.some((text) => text && text.includes("FORNO2"))).toBe(true);
    });
  });

  it("blocks tags that are invalid or inactive", async () => {
    const validTag: PiTag = { ...piTagFixture, id: 1, validation_status: "VALID", active: true };
    const invalidTag: PiTag = { ...piTagFixture, id: 2, validation_status: "INVALID", active: true, pi_tag_name: "RB3.INVALID" };
    const errorTag: PiTag = { ...piTagFixture, id: 3, validation_status: "ERROR", active: true, pi_tag_name: "RB3.ERROR" };
    // The page filters active=false tags, so the inactive tag is omitted
    // from the listing. The test ensures VALID tags are selectable and the
    // others are not.
    apiMock.listPiTags.mockResolvedValue(paginated([validTag, invalidTag, errorTag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    await waitFor(() => {
      expect(screen.getByTestId("tag-option-3")).toBeInTheDocument();
    });
    const tagList = screen.getByTestId("tag-multi-select");
    const valid = within(tagList).getByTestId("tag-option-1");
    const invalid = within(tagList).getByTestId("tag-option-2");
    const error = within(tagList).getByTestId("tag-option-3");
    expect(valid.getAttribute("data-selectable")).toBe("true");
    expect(invalid.getAttribute("data-selectable")).toBe("false");
    expect(error.getAttribute("data-selectable")).toBe("false");
  });

  it("clears selected tags when the equipment filter changes", async () => {
    const otherEquipment = {
      id: 2,
      code: "RC4",
      name: "Outro equipamento",
      description: null,
      active: true,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    };
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture, otherEquipment]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    const initialSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(initialSelect, "1");
    await waitFor(() => {
      expect((screen.getByTestId("equipment-select") as HTMLSelectElement).value).toBe("1");
    });
    const tagList = await screen.findByTestId("tag-multi-select");
    const tagItem = within(tagList).getByTestId("tag-option-1");
    fireEvent.click(tagItem);
    await waitFor(() => {
      expect(within(tagList).getByTestId("tag-option-1").getAttribute("data-selected")).toBe("true");
    });
    expect(within(tagList).getByTestId("tag-option-1")).toHaveClass("tag-multi-select-item-selected");
    const updatedSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(updatedSelect, "2");
    await waitFor(() => {
      const after = (screen.getByTestId("equipment-select") as HTMLSelectElement).value;
      expect(after).toBe("2");
    });
    await waitFor(() => {
      expect(within(tagList).queryByTestId("tag-option-1")).toBeNull();
    });
  });

  it("blocks queries without a tag", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const submit = await screen.findByTestId("filters-submit");
    fireEvent.click(submit);
    expect(await screen.findByTestId("filters-error")).toHaveTextContent("Selecione ao menos uma tag");
  });

  it("requires interval when mode is interpolated", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    const tagItem = within(tagList).getByTestId("tag-option-1");
    fireEvent.click(tagItem);
    const modeInterp = await screen.findByTestId("mode-interpolated");
    fireEvent.click(modeInterp);
    const resolutionManual = await screen.findByTestId("resolution-manual");
    fireEvent.click(resolutionManual);
    const intervalSelect = await screen.findByTestId("interval-select");
    expect(intervalSelect).toBeInTheDocument();
  });

  it("builds the request with UTC ISO timestamps and sends the right URL", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

    let capturedParams: Record<string, unknown> | undefined;
    apiMock.timeSeriesQuery.mockImplementation(async (params) => {
      capturedParams = params;
      return TIME_SERIES;
    });

    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(await screen.findByTestId("filters-submit"));
    await waitFor(() => {
      expect(apiMock.timeSeriesQuery).toHaveBeenCalled();
    });
    expect(capturedParams).toBeDefined();
    expect(capturedParams?.tag_ids).toEqual([1]);
    expect(typeof capturedParams?.start_time).toBe("string");
    expect(typeof capturedParams?.end_time).toBe("string");
    expect(String(capturedParams?.start_time)).toMatch(/T.*Z$/);
    expect(String(capturedParams?.end_time)).toMatch(/T.*Z$/);
    expect(capturedParams?.mode).toBe("interpolated");
  });

  it("cancels the previous request when a new one is issued", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

    const abortSignals: AbortSignal[] = [];
    const pendingResolvers: Array<(value: TimeSeries) => void> = [];
    apiMock.timeSeriesQuery.mockImplementation(async (_params, signal) => {
      if (signal) abortSignals.push(signal);
      return new Promise<TimeSeries>((resolve) => {
        pendingResolvers.push(resolve);
      });
    });

    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    const submit = await screen.findByTestId("filters-submit");
    fireEvent.click(submit);
    // Yield to allow the first request to start
    await new Promise((r) => setTimeout(r, 0));
    expect(abortSignals.length).toBe(1);
    // Reset the button state by resolving the first request
    pendingResolvers[0](TIME_SERIES);
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);
    await waitFor(() => {
      expect(abortSignals.length).toBeGreaterThanOrEqual(2);
    });
    // The first signal should have been aborted
    expect(abortSignals[0]?.aborted).toBe(true);
  });

  it("shows error state when the backend returns an error", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockRejectedValue(
      Object.assign(new Error("Falha timeout"), {
        status: 504,
        code: "PI_TIMEOUT",
      }),
    );
    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(await screen.findByTestId("filters-submit"));
    const error = await screen.findByTestId("chart-error");
    expect(error.textContent).toContain("Falha timeout");
  });

  describe("cancelamento de consulta", () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };

    beforeEach(() => {
      vi.clearAllMocks();
      apiMock.listPiTags.mockResolvedValue(paginated([tag]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    });

    async function startQuery() {
      renderAt("/analises/visualizacao");
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      setSelectValue(equipmentSelect, "1");
      const tagList = await screen.findByTestId("tag-multi-select");
      fireEvent.click(within(tagList).getByTestId("tag-option-1"));
      fireEvent.click(await screen.findByTestId("filters-submit"));
      await new Promise((r) => setTimeout(r, 50));
      return screen.getByTestId("filters-cancel");
    }

    it("botao possui type='button'", async () => {
      apiMock.timeSeriesQuery.mockReturnValue(new Promise(() => {}));
      renderAt("/analises/visualizacao");
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      setSelectValue(equipmentSelect, "1");
      const tagList = await screen.findByTestId("tag-multi-select");
      fireEvent.click(within(tagList).getByTestId("tag-option-1"));
      fireEvent.click(await screen.findByTestId("filters-submit"));
      const cancelBtn = await screen.findByTestId("filters-cancel");
      expect(cancelBtn.getAttribute("type")).toBe("button");
    });

    it("um clique gera um POST e o botao fica desabilitado", async () => {
      apiMock.timeSeriesQuery.mockReturnValue(new Promise(() => {}));
      apiMock.cancelQuery.mockResolvedValue({ query_id: "x", cancelled: true });
      const cancelBtn = await startQuery();
      expect(cancelBtn).not.toBeDisabled();
      fireEvent.click(cancelBtn);
      await new Promise((r) => setTimeout(r, 50));
      expect(apiMock.cancelQuery).toHaveBeenCalledTimes(1);
      expect(cancelBtn).toBeDisabled();
      expect(cancelBtn.textContent).toBe("Cancelando...");
    });

    it("varios cliques rapidos geram somente um POST", async () => {
      apiMock.timeSeriesQuery.mockReturnValue(new Promise(() => {}));
      apiMock.cancelQuery.mockResolvedValue({ query_id: "x", cancelled: true });
      const cancelBtn = await startQuery();
      fireEvent.click(cancelBtn);
      fireEvent.click(cancelBtn);
      fireEvent.click(cancelBtn);
      await new Promise((r) => setTimeout(r, 50));
      expect(apiMock.cancelQuery).toHaveBeenCalledTimes(1);
    });

    it("AbortError nao gera segundo POST", async () => {
      apiMock.timeSeriesQuery.mockImplementation(
        (_params: unknown, signal?: AbortSignal) =>
          new Promise((_resolve, reject) => {
            if (signal) {
              signal.addEventListener("abort", () => {
                reject(new DOMException("Aborted", "AbortError"));
              });
            }
          }),
      );
      apiMock.cancelQuery.mockResolvedValue({ query_id: "x", cancelled: true });
      const cancelBtn = await startQuery();
      fireEvent.click(cancelBtn);
      await new Promise((r) => setTimeout(r, 100));
      expect(apiMock.cancelQuery).toHaveBeenCalledTimes(1);
      const error = await screen.findByTestId("chart-error");
      expect(error.textContent).toContain("Consulta cancelada");
    });

    it("consulta concluida nao pode ser cancelada", async () => {
      apiMock.timeSeriesQuery
        .mockResolvedValueOnce(TIME_SERIES)
        .mockReturnValueOnce(new Promise(() => {}));
      apiMock.cancelQuery.mockResolvedValue({ query_id: "x", cancelled: true });
      renderAt("/analises/visualizacao");
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      setSelectValue(equipmentSelect, "1");
      const tagList = await screen.findByTestId("tag-multi-select");
      fireEvent.click(within(tagList).getByTestId("tag-option-1"));
      fireEvent.click(await screen.findByTestId("filters-submit"));
      await waitFor(() => expect(screen.queryByTestId("filters-cancel")).toBeNull());
      expect(screen.queryByTestId("filters-cancel")).toBeNull();
      fireEvent.click(await screen.findByTestId("filters-submit"));
      const cancelBtn = await screen.findByTestId("filters-cancel");
      expect(cancelBtn).toBeTruthy();
    });

    it("cliques apos primeiro sao ignorados (sem novo POST)", async () => {
      apiMock.timeSeriesQuery.mockImplementation(
        (_params: unknown, signal?: AbortSignal) =>
          new Promise((_resolve, reject) => {
            if (signal) {
              signal.addEventListener("abort", () => {
                reject(new DOMException("Aborted", "AbortError"));
              });
            }
          }),
      );
      apiMock.cancelQuery.mockResolvedValue({ query_id: "x", cancelled: true });
      const cancelBtn = await startQuery();
      fireEvent.click(cancelBtn);
      await new Promise((r) => setTimeout(r, 100));
      expect(apiMock.cancelQuery).toHaveBeenCalledTimes(1);
      const error = await screen.findByTestId("chart-error");
      expect(error.textContent).toContain("Consulta cancelada");
    });

    it("falha no endpoint ainda aborta o fetch local e mostra consulta cancelada", async () => {
      apiMock.timeSeriesQuery.mockImplementation(
        (_params: unknown, signal?: AbortSignal) =>
          new Promise((_resolve, reject) => {
            if (signal) {
              signal.addEventListener("abort", () => {
                reject(new DOMException("Aborted", "AbortError"));
              });
            }
          }),
      );
      apiMock.cancelQuery.mockRejectedValue(new Error("Network error"));
      const cancelBtn = await startQuery();
      fireEvent.click(cancelBtn);
      await new Promise((r) => setTimeout(r, 200));
      expect(apiMock.cancelQuery).toHaveBeenCalledTimes(1);
      await waitFor(() => {
        expect(screen.getByTestId("chart-error").textContent).toContain("Consulta cancelada");
      });
    });
  });

  it("shows partial-results panel when the response has per-series errors", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      errors: [{ tag_id: 999, code: "PI_UNAVAILABLE", message: "Falha remota" }],
    });
    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(await screen.findByTestId("filters-submit"));
    const panel = await screen.findByTestId("partial-results");
    expect(panel.textContent).toContain("Resultado parcial");
  });

  it("identifies an individually mixed tag without blocking a valid numeric tag", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        {
          ...TIME_SERIES.series[0],
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: 600, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: "600", good: true, questionable: false, substituted: false },
          ],
        },
        {
          ...TIME_SERIES.series[0],
          tag_id: 2,
          tag_name: "RB3.PRESS",
          display_name: "Pressao",
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: 10.5, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    });

    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    const warning = await screen.findByTestId("chart-mixed-series");
    expect(warning).toHaveTextContent("Temperatura");
    expect(screen.queryByTestId("chart-mixed-types")).not.toBeInTheDocument();
  });

  it("does not show a mixed-series alert when the textual value is discarded", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        {
          ...TIME_SERIES.series[0],
          display_name: "Temperatura da Tira",
          points: [
            { timestamp: "2026-07-16T10:00:00Z", value: 750, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-16T10:01:00Z", value: "Shutdown", good: false, questionable: true, substituted: false },
            { timestamp: "2026-07-16T10:02:00Z", value: 752, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    });

    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("chart-mixed-series")).not.toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
  });

  it("renders separate numeric and state charts for different tag types", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        TIME_SERIES.series[0],
        {
          ...TIME_SERIES.series[0],
          tag_id: 2,
          tag_name: "RB3.STATE",
          display_name: "Estado",
          unit: null,
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-15T00:01:00Z", value: "P304I", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    });

    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.getByTestId("textual-chart")).toBeInTheDocument();
    expect(screen.getByText("Séries numéricas")).toBeInTheDocument();
    expect(screen.getByText("Estados", { selector: "h5" })).toBeInTheDocument();
    expect(screen.queryByTestId("chart-mixed-types")).not.toBeInTheDocument();
  });

  it("renders only the state chart for a single textual series", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        {
          ...TIME_SERIES.series[0],
          tag_name: "RB3.STATE",
          display_name: "Estado",
          unit: null,
          points: [
            { timestamp: "2026-07-15T00:00:00Z", value: "600", good: true, questionable: false, substituted: false },
          ],
        },
      ],
    });

    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("textual-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("numeric-chart")).not.toBeInTheDocument();
  });

  it("keeps numeric data visible when multiple textual tags exceed the limit", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    const textual = {
      ...TIME_SERIES.series[0],
      tag_id: 2,
      tag_name: "RB3.STATE",
      display_name: "Estado",
      unit: null,
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: "RUN", good: true, questionable: false, substituted: false },
      ],
    };
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [
        TIME_SERIES.series[0],
        textual,
        { ...textual, tag_id: 3, tag_name: "RB3.MODE", display_name: "Modo" },
      ],
    });

    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();

    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("chart-multiple-textual")).toHaveTextContent(
      "Selecione somente uma tag textual",
    );
  });

  it("enables the CSV download button only after a successful query", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    const csvBefore = await screen.findByTestId("download-csv");
    expect(csvBefore).toBeDisabled();
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(await screen.findByTestId("filters-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    });
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("textual-chart")).not.toBeInTheDocument();
  });

  it("shows the not configured warning when the backend reports it", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
    renderAt("/analises/visualizacao");
    expect(await screen.findByTestId("pi-not-configured-warning")).toBeInTheDocument();
  });

  it("rejects more than two distinct units", async () => {
    const tagA = { ...piTagFixture, id: 1, engineering_unit: "C", validation_status: "VALID" as const };
    const tagB = { ...piTagFixture, id: 2, engineering_unit: "bar", pi_tag_name: "RB3.PRESS", display_name: "Pressao", validation_status: "VALID" as const };
    const tagC = { ...piTagFixture, id: 3, engineering_unit: "%", pi_tag_name: "RB3.TORQUE", display_name: "Torque", validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tagA, tagB, tagC]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    setSelectValue(equipmentSelect, "1");
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(within(tagList).getByTestId("tag-option-2"));
    fireEvent.click(within(tagList).getByTestId("tag-option-3"));
    fireEvent.click(await screen.findByTestId("filters-submit"));
    expect(await screen.findByTestId("filters-error")).toHaveTextContent("unidades incompatíveis");
  });

  it("starts with the one-hour preset and exposes only preset, absolute and relative periods", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const kind = (await screen.findByTestId("period-kind")) as HTMLSelectElement;
    expect(kind.value).toBe("preset");
    expect(Array.from(kind.options).map((option) => option.textContent)).toEqual([
      "Predefinido", "Absoluto", "Relativo",
    ]);
    expect((screen.getByTestId("period-preset") as HTMLSelectElement).value).toBe("PT1H");
    expect(screen.getByTestId("time-period-timezone")).toHaveTextContent("America/Sao_Paulo");
    expect(within(screen.getByTestId("period-kind")).queryByText(/cíclic/i)).not.toBeInTheDocument();
  });

  it("sends an absolute Sao Paulo period as the correct UTC instants", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");

    fireEvent.change(await screen.findByTestId("period-kind"), { target: { value: "absolute" } });
    fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-07-17T10:30" } });
    fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-07-17T11:45" } });
    const equipment = await screen.findByTestId("equipment-select");
    fireEvent.change(equipment, { target: { value: "1" } });
    const tagList = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(tagList).getByTestId("tag-option-1"));
    fireEvent.click(screen.getByTestId("filters-submit"));

    await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1));
    expect(apiMock.timeSeriesQuery.mock.calls[0][0]).toMatchObject({
      start_time: "2026-07-17T13:30:00.000Z",
      end_time: "2026-07-17T14:45:00.000Z",
    });
    expect(await screen.findByTestId("query-summary")).toHaveTextContent("10:30:00");
    expect(screen.getByTestId("query-summary")).toHaveTextContent("11:45:00");
  });

  it("shows inline validation and disables consultation for an invalid absolute period", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    fireEvent.change(await screen.findByTestId("period-kind"), { target: { value: "absolute" } });
    fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-07-17T12:00" } });
    fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-07-17T11:00" } });
    expect(screen.getByTestId("time-period-error")).toHaveTextContent("posterior");
    expect(screen.getByTestId("absolute-start")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("filters-submit")).toBeDisabled();
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
  });

  it("edits the period without a new request or clearing the last successful result", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    const summary = screen.getByTestId("query-summary").textContent;

    fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "relative" } });
    fireEvent.change(screen.getByTestId("relative-amount"), { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("relative-unit"), { target: { value: "day" } });

    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.getByTestId("query-summary").textContent).toBe(summary);
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("uses Base Unidade by default, exposes future models disabled and maps Equipment to Máquina", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");

    const model = (await screen.findByTestId("analysis-model")) as HTMLSelectElement;
    expect(model.value).toBe("unit");
    expect(Array.from(model.options).map((option) => option.textContent)).toEqual([
      "Base Unidade",
      "Base Cíclica — Disponível em uma fase futura.",
      "Base OEE — Disponível em uma fase futura.",
      "Base Paradas — Disponível em uma fase futura.",
      "Base Qualidade — Disponível em uma fase futura.",
    ]);
    expect(Array.from(model.options).slice(1).every((option) => option.disabled)).toBe(true);
    expect(screen.getByLabelText("Máquina")).toBe(screen.getByTestId("equipment-select"));
    expect(screen.getByLabelText(/Métrica de análise/i)).toBeInTheDocument();
  });

  it("validates manual line axes by unit and accepts different units on separate axes", async () => {
    const temperature = { ...piTagFixture, id: 1, data_type: "NUMERIC" as const, engineering_unit: "°C", validation_status: "VALID" as const };
    const pressure = { ...temperature, id: 2, pi_tag_name: "RB3.PRESS", display_name: "Pressão", engineering_unit: "bar" };
    apiMock.listPiTags.mockResolvedValue(paginated([temperature, pressure]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [TIME_SERIES.series[0], { ...TIME_SERIES.series[0], tag_id: 2, tag_name: "RB3.PRESS", display_name: "Pressão", unit: "bar" }] });
    renderAt("/analises/visualizacao");
    fireEvent.change(await screen.findByTestId("equipment-select"), { target: { value: "1" } });
    const list = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    fireEvent.click(within(list).getByTestId("tag-option-2"));
    await waitFor(() => expect(screen.getByTestId("line-axis-2")).toHaveValue("secondary"));

    fireEvent.change(screen.getByTestId("line-axis-2"), { target: { value: "primary" } });
    expect(screen.getByTestId("series-assignment-errors")).toHaveTextContent("unidades incompatíveis");
    fireEvent.click(screen.getByTestId("filters-submit"));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("line-axis-2"), { target: { value: "secondary" } });
    expect(screen.queryByTestId("series-assignment-errors")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("filters-submit"));
    await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByTestId("line-axis-1"), { target: { value: "secondary" } });
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("query-summary")).toBeInTheDocument();
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
  });

  it("uses explicit scatter X and Y despite reversed API order and preserves them without a new query", async () => {
    const first = { ...piTagFixture, id: 1, data_type: "NUMERIC" as const, validation_status: "VALID" as const };
    const second = { ...first, id: 2, pi_tag_name: "RB3.PRESS", display_name: "Pressão", engineering_unit: "bar" };
    const secondSeries = { ...TIME_SERIES.series[0], tag_id: 2, tag_name: "RB3.PRESS", display_name: "Pressão", unit: "bar" };
    apiMock.listPiTags.mockResolvedValue(paginated([first, second]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [secondSeries, TIME_SERIES.series[0]] });
    renderAt("/analises/visualizacao");
    fireEvent.change(await screen.findByTestId("equipment-select"), { target: { value: "1" } });
    const list = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    fireEvent.click(within(list).getByTestId("tag-option-2"));
    fireEvent.click(screen.getByTestId("filters-submit"));
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "scatter" } });
    await waitFor(() => expect(screen.getByTestId("scatter-x")).toHaveValue("1"));
    expect(screen.getByTestId("scatter-y")).toHaveValue("2");
    expect(screen.getByTestId("scatter-summary")).toHaveTextContent("Eixo X: Temperatura");
    expect(screen.getByTestId("scatter-summary")).toHaveTextContent("Eixo Y: Pressão");

    fireEvent.change(screen.getByTestId("scatter-y"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("scatter-x"), { target: { value: "2" } });
    fireEvent.change(screen.getByTestId("scatter-y"), { target: { value: "1" } });
    expect(screen.getByTestId("scatter-summary")).toHaveTextContent("Eixo X: Pressão");
    expect(screen.getByTestId("scatter-summary")).toHaveTextContent("Eixo Y: Temperatura");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("clears a removed scatter role without silently selecting another tag", async () => {
    const first = { ...piTagFixture, id: 1, data_type: "NUMERIC" as const, validation_status: "VALID" as const };
    const second = { ...first, id: 2, pi_tag_name: "RB3.PRESS", display_name: "Pressão", engineering_unit: "bar" };
    apiMock.listPiTags.mockResolvedValue(paginated([first, second]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [TIME_SERIES.series[0], { ...TIME_SERIES.series[0], tag_id: 2, display_name: "Pressão" }] });
    renderAt("/analises/visualizacao");
    fireEvent.change(await screen.findByTestId("equipment-select"), { target: { value: "1" } });
    const list = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    fireEvent.click(within(list).getByTestId("tag-option-2"));
    fireEvent.click(screen.getByTestId("filters-submit"));
    await screen.findByTestId("numeric-chart");
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "scatter" } });
    await waitFor(() => expect(screen.getByTestId("scatter-x")).toHaveValue("1"));
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    await waitFor(() => expect(screen.getByTestId("scatter-x")).toHaveValue(""));
    expect(screen.getByTestId("scatter-y")).toHaveValue("2");
    expect(screen.queryByTestId("scatter-chart")).not.toBeInTheDocument();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("reorders single-value cards without changing API calls, summary, counters or CSV", async () => {
    const first = { ...piTagFixture, id: 1, data_type: "NUMERIC" as const, validation_status: "VALID" as const };
    const second = { ...first, id: 2, pi_tag_name: "RB3.PRESS", display_name: "Pressão" };
    apiMock.listPiTags.mockResolvedValue(paginated([first, second]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({ ...TIME_SERIES, series: [TIME_SERIES.series[0], { ...TIME_SERIES.series[0], tag_id: 2, tag_name: "RB3.PRESS", display_name: "Pressão" }] });
    renderAt("/analises/visualizacao");
    fireEvent.change(await screen.findByTestId("equipment-select"), { target: { value: "1" } });
    const list = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    fireEvent.click(within(list).getByTestId("tag-option-2"));
    fireEvent.click(screen.getByTestId("filters-submit"));
    await screen.findByTestId("numeric-chart");
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "singleValue" } });
    const summary = screen.getByTestId("query-summary").textContent;
    expect(screen.getAllByTestId("single-value-card-column")[0]).toHaveTextContent("Temperatura");
    fireEvent.click(screen.getByTestId("move-up-2"));
    expect(screen.getAllByTestId("single-value-card-column")[0]).toHaveTextContent("Pressão");
    expect(screen.getByTestId("query-summary").textContent).toBe(summary);
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("offers the neutral option and exactly twenty analysis metrics", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/analises/visualizacao");
    const select = await screen.findByTestId("analysis-metric") as HTMLSelectElement;
    expect(select.options).toHaveLength(21);
    expect(select.options[0]).toHaveTextContent("Nenhuma métrica");
    expect(select.value).toBe("");
    expect(screen.queryByTestId("metric-results")).not.toBeInTheDocument();
  });

  it("calculates cards from the last response without changing charts, CSV, summary or calling the API again", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue({
      ...TIME_SERIES,
      series: [{ ...TIME_SERIES.series[0], points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 2, good: true, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:01:00Z", value: 100, good: false, questionable: false, substituted: false },
        { timestamp: "2026-07-15T00:02:00Z", value: "600", good: false, questionable: false, substituted: false },
      ] }],
    });
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    await screen.findByTestId("numeric-chart");
    const summary = screen.getByTestId("query-summary").textContent;
    fireEvent.change(screen.getByTestId("analysis-metric"), { target: { value: "mean" } });
    expect(await screen.findByTestId("metric-results")).toBeInTheDocument();
    expect(screen.getByTestId("metric-value")).toHaveTextContent("2");
    // Bad quality points are pre-filtered by the filter pipeline; only 1 valid point remains
    expect(screen.getByTestId("metric-result-card")).toHaveTextContent("Amostras/pares: 1 · Ignorados: 0");
    expect(screen.getByTestId("numeric-chart")).toBeInTheDocument();
    expect(screen.getByTestId("query-summary").textContent).toBe(summary);
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("ignore-bad-quality"));
    expect(screen.getByTestId("metric-value")).toHaveTextContent("51");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
  });

  it("shows accessible metric validation without blocking the PI query", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    const equipment = await screen.findByTestId("equipment-select");
    fireEvent.change(equipment, { target: { value: "1" } });
    const list = await screen.findByTestId("tag-multi-select");
    fireEvent.click(within(list).getByTestId("tag-option-1"));
    fireEvent.change(screen.getByTestId("analysis-metric"), { target: { value: "cp" } });
    expect(screen.getByTestId("metric-validation")).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("filters-submit")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("filters-submit"));
    await screen.findByTestId("numeric-chart");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("metric-results")).toHaveTextContent("Informe LIE e LSE");
  });

  it("changes comparison configuration locally and calls only compare on Consultar", async () => {
    const tag = { ...piTagFixture, validation_status: "VALID" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([tag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesCompare.mockResolvedValue({
      comparison_enabled: true,
      comparison_type: "periods",
      contexts: [
        { context_id: "A", context_label: "Contexto A", start_time: TIME_SERIES.start_time, end_time: TIME_SERIES.end_time, time_series: { ...TIME_SERIES, series: [{ ...TIME_SERIES.series[0], context_id: "A", comparison_type: "periods", series_instance_id: "A-1" }] }, complete: true },
        { context_id: "B", context_label: "Contexto B", start_time: "2026-06-15T00:00:00Z", end_time: "2026-06-15T01:00:00Z", time_series: { ...TIME_SERIES, start_time: "2026-06-15T00:00:00Z", end_time: "2026-06-15T01:00:00Z", series: [{ ...TIME_SERIES.series[0], context_id: "B", comparison_type: "periods", series_instance_id: "B-1" }] }, complete: true },
      ],
      metadata: { comparison_enabled: true, comparison_type: "periods", context_count: 2, series_instance_count: 2, points_received_by_context: { A: 2, B: 2 }, points_returned_by_context: { A: 2, B: 2 }, duration_ms_by_context: { A: 1, B: 1 }, strategy_by_context: {}, cache_hit_by_context: {}, duration_ms: 2, complete: true, partial: false, query_id: "cmp-ui" },
    });
    renderAt("/analises/visualizacao");

    fireEvent.change(await screen.findByTestId("comparison-type"), { target: { value: "periods" } });
    fireEvent.change(screen.getByTestId("comparison-start-b"), { target: { value: "2026-06-15T00:00" } });
    fireEvent.change(screen.getByTestId("comparison-end-b"), { target: { value: "2026-06-15T01:00" } });
    expect(apiMock.timeSeriesCompare).not.toHaveBeenCalled();
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();

    await submitFirstAvailableTag();
    await waitFor(() => expect(apiMock.timeSeriesCompare).toHaveBeenCalledTimes(1));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled();
    const payload = apiMock.timeSeriesCompare.mock.calls[0][0];
    expect(payload.contexts).toHaveLength(2);
    expect(payload.contexts.map((context: { context_id: string }) => context.context_id)).toEqual(["A", "B"]);
  });

  it("applies and resets visual limits, ranges and colors without another API call", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([{ ...piTagFixture, validation_status: "VALID" as const }]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(TIME_SERIES);
    renderAt("/analises/visualizacao");
    await submitFirstAvailableTag();
    await screen.findByTestId("numeric-chart");
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("visual-rules-enabled"));
    fireEvent.change(screen.getByTestId("visual-series"), { target: { value: "tag:1" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar limite" }));
    fireEvent.click(screen.getByRole("button", { name: "Adicionar faixa" }));
    fireEvent.click(screen.getByRole("button", { name: "Adicionar regra" }));
    expect(screen.getByTestId("visual-limit")).toBeInTheDocument();
    expect(screen.getByTestId("visual-range")).toBeInTheDocument();
    expect(screen.getByTestId("visual-rule")).toHaveTextContent("Prioridade 1");

    fireEvent.change(screen.getByTestId("line-axis-1"), { target: { value: "secondary" } });
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "histogram" } });
    fireEvent.change(screen.getByTestId("visualization-select"), { target: { value: "line" } });
    fireEvent.click(screen.getByRole("button", { name: "Restaurar esta série" }));
    expect(screen.queryByTestId("visual-limit")).not.toBeInTheDocument();
    expect(screen.getByTestId("query-summary")).toBeInTheDocument();
    expect(screen.getByTestId("download-csv")).not.toBeDisabled();
    expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1);
    expect(apiMock.timeSeriesCompare).not.toHaveBeenCalled();
  });
});
