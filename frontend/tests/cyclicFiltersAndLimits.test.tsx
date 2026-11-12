import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  connectedHealthFixture,
  mockApiModule,
  paginated,
  equipmentFixture,
  piTagFixture,
  sectionFixture,
  variableTypeFixture,
} from "./mocks/api";
import type { PiTag, PiTagNormLimitsResponse, TimeSeries, VariableType, Equipment } from "../src/types";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { buildChartDataGroups } from "../src/utils/chartData";

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

describe("Base Cíclica - Filtros e Limites Vinculados às Tags", () => {
  const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB3", name: "Recozimento Contínuo 3" };
  const vtMm: VariableType = { ...variableTypeFixture, id: 10, code: "ESPESSURA", name: "Espessura", default_unit: "mm" };
  const vtAmp: VariableType = { ...variableTypeFixture, id: 20, code: "CORRENTE", name: "Corrente", default_unit: "A" };
  const vtTemp: VariableType = { ...variableTypeFixture, id: 30, code: "TEMP", name: "Temperatura", default_unit: "°C" };

  const tagEsp: PiTag = {
    ...piTagFixture,
    id: 1,
    equipment_id: 1,
    variable_type_id: 10,
    pi_tag_name: "RB3_ESP_PV",
    display_name: "ESPESSURA",
    engineering_unit: "mm",
    lower_limit_tag: "RB3_ESP_MIN",
    upper_limit_tag: "RB3_ESP_MAX",
    validation_status: "VALID",
    active: true,
  };

  const tagEsc: PiTag = {
    ...piTagFixture,
    id: 2,
    equipment_id: 1,
    variable_type_id: 20,
    pi_tag_name: "RB3_ESC04_PV",
    display_name: "Escova 04",
    engineering_unit: "A",
    lower_limit_tag: "RB3_ESC04_MIN",
    upper_limit_tag: "RB3_ESC04_MAX",
    validation_status: "VALID",
    active: true,
  };

  const tagTemp: PiTag = {
    ...piTagFixture,
    id: 3,
    equipment_id: 1,
    variable_type_id: 30,
    pi_tag_name: "RB3_TEMP_PV",
    display_name: "Temperatura Forno",
    engineering_unit: "°C",
    lower_limit_tag: null,
    upper_limit_tag: null,
    validation_status: "VALID",
    active: true,
  };

  const tagSteel: PiTag = {
    ...piTagFixture,
    id: 4,
    equipment_id: 1,
    variable_type_id: 40,
    pi_tag_name: "RB3_MODELO_ACO",
    display_name: "Modelo Aço",
    engineering_unit: "",
    lower_limit_tag: null,
    upper_limit_tag: null,
    validation_status: "VALID",
    active: true,
  };

  const normLimitEspResponse: PiTagNormLimitsResponse = {
    source_tag_id: 1,
    start_time: "2026-07-15T00:00:00Z",
    end_time: "2026-07-15T01:00:00Z",
    mode: "recorded",
    interval: null,
    lower: {
      tag_name: "RB3_ESP_MIN",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 1.2, good: true },
        { timestamp: "2026-07-15T01:00:00Z", value: 1.2, good: true },
      ],
      coverage_gaps: [],
    },
    upper: {
      tag_name: "RB3_ESP_MAX",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 1.8, good: true },
        { timestamp: "2026-07-15T01:00:00Z", value: 1.8, good: true },
      ],
      coverage_gaps: [],
    },
    errors: [],
  };

  const normLimitEscResponse: PiTagNormLimitsResponse = {
    source_tag_id: 2,
    start_time: "2026-07-15T00:00:00Z",
    end_time: "2026-07-15T01:00:00Z",
    mode: "recorded",
    interval: null,
    lower: {
      tag_name: "RB3_ESC04_MIN",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 50, good: true },
        { timestamp: "2026-07-15T01:00:00Z", value: 50, good: true },
      ],
      coverage_gaps: [],
    },
    upper: {
      tag_name: "RB3_ESC04_MAX",
      points: [
        { timestamp: "2026-07-15T00:00:00Z", value: 150, good: true },
        { timestamp: "2026-07-15T01:00:00Z", value: 150, good: true },
      ],
      coverage_gaps: [],
    },
    errors: [],
  };

  const timeSeriesMultiAxis: TimeSeries = {
    start_time: "2026-07-15T00:00:00Z",
    end_time: "2026-07-15T01:00:00Z",
    mode: "recorded",
    series: [
      {
        tag_id: 1,
        tag_name: "RB3_ESP_PV",
        display_name: "ESPESSURA",
        equipment: "RB3",
        section: "FORNO",
        variable_type: "ESPESSURA",
        unit: "mm",
        points: [
          { timestamp: "2026-07-15T00:10:00Z", value: 1.5, good: true, questionable: false, substituted: false },
          { timestamp: "2026-07-15T00:50:00Z", value: 1.6, good: true, questionable: false, substituted: false },
        ],
      },
      {
        tag_id: 2,
        tag_name: "RB3_ESC04_PV",
        display_name: "Escova 04",
        equipment: "RB3",
        section: "DECAPAGEM",
        variable_type: "CORRENTE",
        unit: "A",
        points: [
          { timestamp: "2026-07-15T00:10:00Z", value: 95, good: true, questionable: false, substituted: false },
          { timestamp: "2026-07-15T00:50:00Z", value: 105, good: true, questionable: false, substituted: false },
        ],
      },
    ],
    errors: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
    apiMock.listSections.mockResolvedValue(paginated([{ ...sectionFixture, steel_type_tag_id: 4 }]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([vtMm, vtAmp, vtTemp]));
    apiMock.listPiTags.mockResolvedValue(paginated([tagEsp, tagEsc, tagTemp, tagSteel]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.timeSeriesQuery.mockResolvedValue(timeSeriesMultiAxis);
    apiMock.getNormLimits.mockImplementation(async (tagId: number) => {
      if (tagId === 1) return normLimitEspResponse;
      if (tagId === 2) return normLimitEscResponse;
      throw new Error(`Tag ${tagId} has no limits`);
    });
  });

  it("exibe opção visível para ativar filtros na Base Cíclica e a oculta na Base Unidade", async () => {
    renderAt("/analises/visualizacao");

    // Na Base Cíclica (padrão), o switch de ativação de filtros deve estar presente
    const cyclicSwitch = await screen.findByTestId("cyclic-filters-switch");
    expect(cyclicSwitch).toBeInTheDocument();
    expect(cyclicSwitch).toBeChecked(); // default filtersEnabled: true

    // Muda para Base Unidade
    const modelSelect = screen.getByTestId("analysis-model") as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "unit" } });

    // Na Base Unidade, o switch específico da Base Cíclica não deve ser exibido
    expect(screen.queryByTestId("cyclic-filters-switch")).toBeNull();

    // Volta para Base Cíclica
    fireEvent.change(modelSelect, { target: { value: "cyclic" } });
    expect(screen.getByTestId("cyclic-filters-switch")).toBeInTheDocument();
  });

  it("abre pop-up/modal ao clicar em Configurar ou ao ativar filtros, exibindo controles de filtro existentes", async () => {
    renderAt("/analises/visualizacao");

    await screen.findByTestId("cyclic-filters-switch");

    // Com filtros habilitados, o botão Configurar deve estar visível
    const configBtn = screen.getByTestId("open-cyclic-filters-modal-btn");
    expect(configBtn).toBeInTheDocument();

    // Clica no botão Configurar para abrir o modal
    fireEvent.click(configBtn);

    // Modal deve estar aberto
    const modal = await screen.findByTestId("cyclic-filters-modal");
    expect(modal).toBeInTheDocument();
    expect(screen.getByText("Configurar Filtros e Limites — Base Cíclica")).toBeInTheDocument();

    // Seção de Filtros da Consulta presente com controles existentes
    expect(screen.getByTestId("cyclic-modal-filters-section")).toBeInTheDocument();
    expect(screen.getByTestId("named-filter-steelModel")).toBeInTheDocument();
    expect(screen.getByTestId("named-filter-umCode")).toBeInTheDocument();
    expect(screen.getByTestId("named-filter-widthMin")).toBeInTheDocument();
    expect(screen.getByTestId("named-filter-widthMax")).toBeInTheDocument();
    expect(screen.getByTestId("named-filters-apply")).toBeInTheDocument();
    expect(screen.getByTestId("filter-reset")).toBeInTheDocument();

    // Seção de Limites Vinculados presente com switch master
    expect(screen.getByTestId("cyclic-modal-limits-section")).toBeInTheDocument();
    expect(screen.getByTestId("cyclic-limits-switch")).toBeInTheDocument();

    // Fecha o modal pelo botão Fechar
    fireEvent.click(screen.getByTestId("close-cyclic-filters-modal-btn"));
    await waitFor(() => {
      expect(screen.queryByTestId("cyclic-filters-modal")).toBeNull();
    });
  });

  it("lista variáveis com limites cadastrados e identifica variáveis sem limites", async () => {
    renderAt("/analises/visualizacao");

    // Seleciona equipamento RB3
    const eqSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    await waitFor(() => expect(eqSelect.options.length).toBeGreaterThan(1));
    fireEvent.change(eqSelect, { target: { value: "1" } });

    // Seleciona tags ESPESSURA, Escova 04 e Temperatura
    const tagList = await screen.findByTestId("tag-multi-select");
    const opt1 = await within(tagList).findByTestId("tag-option-1");
    fireEvent.click(opt1);
    await waitFor(() => expect(opt1).toHaveAttribute("data-selected", "true"));

    const opt2 = await within(tagList).findByTestId("tag-option-2");
    fireEvent.click(opt2);
    await waitFor(() => expect(opt2).toHaveAttribute("data-selected", "true"));

    const opt3 = await within(tagList).findByTestId("tag-option-3");
    fireEvent.click(opt3);
    await waitFor(() => expect(opt3).toHaveAttribute("data-selected", "true"));

    // Abre o modal
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");

    // Inicialmente o switch de limites está desligado
    const limitsSwitch = screen.getByTestId("cyclic-limits-switch");
    expect(limitsSwitch).not.toBeChecked();
    expect(screen.getByTestId("cyclic-limits-disabled-note")).toBeInTheDocument();

    // Ativa o switch de limites
    fireEvent.click(limitsSwitch);
    expect(limitsSwitch).toBeChecked();

    // Lista de variáveis deve ser renderizada
    expect(screen.getByTestId("cyclic-limits-variables-list")).toBeInTheDocument();

    // ESPESSURA tem limites cadastrados
    const espRow = screen.getByTestId("cyclic-limit-row-tag:1");
    expect(espRow).toHaveTextContent("ESPESSURA");
    expect(espRow).toHaveTextContent("RB3_ESP_MIN");
    expect(espRow).toHaveTextContent("RB3_ESP_MAX");
    const espCheck = screen.getByTestId("cyclic-limit-checkbox-tag:1");
    expect(espCheck).not.toBeDisabled();

    // Escova 04 tem limites cadastrados
    const escRow = screen.getByTestId("cyclic-limit-row-tag:2");
    expect(escRow).toHaveTextContent("Escova 04");
    expect(escRow).toHaveTextContent("RB3_ESC04_MIN");
    expect(escRow).toHaveTextContent("RB3_ESC04_MAX");
    const escCheck = screen.getByTestId("cyclic-limit-checkbox-tag:2");
    expect(escCheck).not.toBeDisabled();

    // Temperatura NÃO tem limites cadastrados
    const tempRow = screen.getByTestId("cyclic-limit-row-tag:3");
    expect(tempRow).toHaveTextContent("Temperatura Forno");
    expect(tempRow).toHaveTextContent("Sem limites cadastrados");
    const tempCheck = screen.getByTestId("cyclic-limit-checkbox-tag:3");
    expect(tempCheck).toBeDisabled();
  });

  it("permite selecionar variáveis para exibir limites e os renderiza no eixo correspondente", async () => {
    renderAt("/analises/visualizacao");

    // Seleciona equipamento RB3
    const eqSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    await waitFor(() => expect(eqSelect.options.length).toBeGreaterThan(1));
    fireEvent.change(eqSelect, { target: { value: "1" } });

    // Seleciona ESPESSURA e Escova 04
    const tagList = await screen.findByTestId("tag-multi-select");
    const opt1 = await within(tagList).findByTestId("tag-option-1");
    fireEvent.click(opt1);
    await waitFor(() => expect(opt1).toHaveAttribute("data-selected", "true"));

    const opt2 = await within(tagList).findByTestId("tag-option-2");
    fireEvent.click(opt2);
    await waitFor(() => expect(opt2).toHaveAttribute("data-selected", "true"));

    // Executa a consulta
    fireEvent.click(await screen.findByTestId("filters-submit"));
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();

    // Abre o modal de filtros e limites
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");

    // Ativa exibição de limites
    fireEvent.click(screen.getByTestId("cyclic-limits-switch"));

    // Verifica que cada variável exibe seu eixo correspondente
    expect(screen.getByTestId("cyclic-limit-axis-tag:1")).toHaveTextContent("Eixo 1 (mm)");
    expect(screen.getByTestId("cyclic-limit-axis-tag:2")).toHaveTextContent("Eixo 2 (A)");

    // Seleciona apenas ESPESSURA
    fireEvent.click(screen.getByTestId("cyclic-limit-checkbox-tag:1"));
    expect(screen.getByTestId("cyclic-limit-checkbox-tag:1")).toBeChecked();
    expect(screen.getByTestId("cyclic-limit-checkbox-tag:2")).not.toBeChecked();

    // Fecha o modal
    fireEvent.click(screen.getByTestId("close-cyclic-filters-modal-btn"));

    // Aguarda a busca de limites da ESPESSURA
    await waitFor(() => {
      expect(apiMock.getNormLimits).toHaveBeenCalledWith(1, expect.anything(), expect.anything());
    });
    // Escova 04 NÃO deve ter sido consultada
    expect(apiMock.getNormLimits).not.toHaveBeenCalledWith(2, expect.anything(), expect.anything());

    // Abre o modal novamente e seleciona também Escova 04
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");
    fireEvent.click(screen.getByTestId("cyclic-limit-checkbox-tag:2"));
    expect(screen.getByTestId("cyclic-limit-checkbox-tag:2")).toBeChecked();
    fireEvent.click(screen.getByTestId("close-cyclic-filters-modal-btn"));

    // Aguarda a busca de limites da Escova 04
    await waitFor(() => {
      expect(apiMock.getNormLimits).toHaveBeenCalledWith(2, expect.anything(), expect.anything());
    });
  });

  it("desativar os limites oculta as linhas sem apagar as seleções de variáveis nem os filtros", async () => {
    renderAt("/analises/visualizacao");

    // Seleciona equipamento RB3
    const eqSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
    await waitFor(() => expect(eqSelect.options.length).toBeGreaterThan(1));
    fireEvent.change(eqSelect, { target: { value: "1" } });

    // Seleciona ESPESSURA
    const tagList = await screen.findByTestId("tag-multi-select");
    const opt1 = await within(tagList).findByTestId("tag-option-1");
    fireEvent.click(opt1);
    await waitFor(() => expect(opt1).toHaveAttribute("data-selected", "true"));

    // Consulta
    fireEvent.click(await screen.findByTestId("filters-submit"));
    expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();

    // Abre modal, configura um filtro e ativa limites
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");

    // Preenche um filtro de modelo de aço
    const steelInput = screen.getByTestId("named-filter-steelModel");
    fireEvent.change(steelInput, { target: { value: "P304A" } });
    fireEvent.click(screen.getByTestId("named-filters-apply"));

    // Ativa limites e marca ESPESSURA
    fireEvent.click(screen.getByTestId("cyclic-limits-switch"));
    fireEvent.click(screen.getByTestId("cyclic-limit-checkbox-tag:1"));

    // Fecha o modal
    fireEvent.click(screen.getByTestId("close-cyclic-filters-modal-btn"));

    // Aguarda limites carregados
    await waitFor(() => {
      expect(apiMock.getNormLimits).toHaveBeenCalledWith(1, expect.anything(), expect.anything());
    });

    // Reabre modal e desativa os limites
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");
    fireEvent.click(screen.getByTestId("cyclic-limits-switch")); // desliga limites
    fireEvent.click(screen.getByTestId("close-cyclic-filters-modal-btn"));

    // Reabre modal para conferir que a seleção anterior foi preservada
    fireEvent.click(screen.getByTestId("open-cyclic-filters-modal-btn"));
    await screen.findByTestId("cyclic-filters-modal");

    // O filtro de aço ainda está lá
    expect(screen.getByTestId("named-filter-steelModel")).toHaveValue("P304A");

    // Reativa limites: a ESPESSURA ainda deve estar marcada!
    fireEvent.click(screen.getByTestId("cyclic-limits-switch"));
    expect(screen.getByTestId("cyclic-limit-checkbox-tag:1")).toBeChecked();
  });

  it("renderiza limites no mesmo eixo da variável no ECharts e com identificação inferior/superior", () => {
    const chartGroups = buildChartDataGroups(timeSeriesMultiAxis, { ignoreBadQuality: true });
    expect(chartGroups).not.toBeNull();
    const numericChart = chartGroups.numeric;
    expect(numericChart).not.toBeNull();

    // numericChart tem 2 séries: ESPESSURA (yAxisIndex 0) e Escova 04 (yAxisIndex 1)
    expect(numericChart!.series[0].yAxisIndex).toBe(0);
    expect(numericChart!.series[1].yAxisIndex).toBe(1);

    const normSeriesEsp = {
      seriesInstanceId: "tag:1",
      tagName: "RB3_ESP_PV",
      mainDisplayName: "ESPESSURA",
      lowerTagName: "RB3_ESP_MIN",
      upperTagName: "RB3_ESP_MAX",
      yAxisIndex: 0,
      width: 2,
      lowerColor: "#2e7d32",
      upperColor: "#d32f2f",
      lowerPoints: [[Date.parse("2026-07-15T00:00:00Z"), 1.2], [Date.parse("2026-07-15T01:00:00Z"), 1.2]] as Array<[number, number]>,
      upperPoints: [[Date.parse("2026-07-15T00:00:00Z"), 1.8], [Date.parse("2026-07-15T01:00:00Z"), 1.8]] as Array<[number, number]>,
    };

    const normSeriesEsc = {
      seriesInstanceId: "tag:2",
      tagName: "RB3_ESC04_PV",
      mainDisplayName: "Escova 04",
      lowerTagName: "RB3_ESC04_MIN",
      upperTagName: "RB3_ESC04_MAX",
      yAxisIndex: 1,
      width: 2,
      lowerColor: "#388e3c",
      upperColor: "#c62828",
      lowerPoints: [[Date.parse("2026-07-15T00:00:00Z"), 50], [Date.parse("2026-07-15T01:00:00Z"), 50]] as Array<[number, number]>,
      upperPoints: [[Date.parse("2026-07-15T00:00:00Z"), 150], [Date.parse("2026-07-15T01:00:00Z"), 150]] as Array<[number, number]>,
    };

    const option = buildTimeSeriesChartOption({
      chart: numericChart!,
      start: new Date("2026-07-15T00:00:00Z"),
      end: new Date("2026-07-15T01:00:00Z"),
      baseStart: new Date("2026-07-15T00:00:00Z"),
      baseEnd: new Date("2026-07-15T01:00:00Z"),
      normLimitSeries: [normSeriesEsp, normSeriesEsc],
    });

    const series = option.series as Array<Record<string, any>>;

    // Localiza as séries de limite
    const espLower = series.find((s) => s.id === "norm-lower:tag:1");
    const espUpper = series.find((s) => s.id === "norm-upper:tag:1");
    const escLower = series.find((s) => s.id === "norm-lower:tag:2");
    const escUpper = series.find((s) => s.id === "norm-upper:tag:2");

    expect(espLower).toBeDefined();
    expect(espUpper).toBeDefined();
    expect(escLower).toBeDefined();
    expect(escUpper).toBeDefined();

    // Limites de ESPESSURA devem estar no yAxisIndex 0
    expect(espLower!.yAxisIndex).toBe(0);
    expect(espUpper!.yAxisIndex).toBe(0);
    expect(espLower!.name).toContain("Limite inferior — ESPESSURA");
    expect(espUpper!.name).toContain("Limite superior — ESPESSURA");

    // Limites de Escova 04 devem estar no yAxisIndex 1 (eixo da corrente A), NUNCA no 0
    expect(escLower!.yAxisIndex).toBe(1);
    expect(escUpper!.yAxisIndex).toBe(1);
    expect(escLower!.name).toContain("Limite inferior — Escova 04");
    expect(escUpper!.name).toContain("Limite superior — Escova 04");

    // Legenda deve conter a identificação de inferior e superior
    const legend = (option.legend as any).data as string[];
    expect(legend).toContain("Limite inferior — ESPESSURA");
    expect(legend).toContain("Limite superior — ESPESSURA");
    expect(legend).toContain("Limite inferior — Escova 04");
    expect(legend).toContain("Limite superior — Escova 04");
  });
});
