import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
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
import type { PiTag, TimeSeries, VariableType, Equipment } from "../src/types";
import { buildTagOption } from "../src/components/TagMultiSelect";
import { createInitialAssignments, reconcileAssignments } from "../src/utils/seriesAssignments";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { buildChartData } from "../src/utils/chartData";
import { VisualConfigurationsPanel } from "../src/components/VisualConfigurationsPanel";
import { buildNormLimitSeries } from "../src/utils/normLimitSeries";

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

describe("Visualização de Dados - Correções dos 8 Bugs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Bug 1 & Bug 5: Invalidação de parâmetros e persistência de título anterior", () => {
    it("exibe aviso de resultado desatualizado e preserva título da máquina consultada ao trocar parâmetros", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const eq2: Equipment = { ...equipmentFixture, id: 2, code: "RB3", name: "RB3" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1, eq2]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      const timeSeriesResult: TimeSeries = {
        start_time: "2026-07-15T00:00:00Z",
        end_time: "2026-07-15T01:00:00Z",
        mode: "recorded",
        series: [
          {
            tag_id: 1,
            tag_name: "TAG_RB1",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [{ timestamp: "2026-07-15T00:30:00Z", value: 30, good: true, questionable: false, substituted: false }],
          },
        ],
        errors: [],
      };
      apiMock.timeSeriesQuery.mockResolvedValue(timeSeriesResult);

      renderAt("/analises/visualizacao");

      // Seleciona RB1
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });

      // Seleciona Tag 1
      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);
      await waitFor(() => expect(option).toHaveAttribute("data-selected", "true"));

      // Submete consulta
      fireEvent.click(await screen.findByTestId("filters-submit"));
      expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
      expect(screen.queryByTestId("outdated-result-warning")).toBeNull();

      // Troca equipamento para RB3 sem consultar novamente
      fireEvent.change(equipmentSelect, { target: { value: "2" } });

      // O gráfico permanece, mas com aviso explícito de resultado desatualizado pertencente à RB1
      expect(await screen.findByTestId("outdated-result-warning")).toBeInTheDocument();
      expect(screen.getByTestId("outdated-result-warning")).toHaveTextContent("RB1");

      // Se tentar consultar sem tags selecionadas, validação bloqueia e mantém aviso de desatualizado
      fireEvent.click(screen.getByTestId("filters-submit"));
      expect(await screen.findByTestId("tag-selection-error")).toBeInTheDocument();
      expect(screen.getByTestId("outdated-result-warning")).toBeInTheDocument();
    });

    it("cartão Período exibe o intervalo efetivo e diferencia do solicitado quando limitado pelo backend", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      // Reprodução: filtro solicitado 10:04:54–10:19:54 (13:04:54Z–13:19:54Z)
      // Backend limitou aos dados disponíveis em 10:19:00 (13:19:00Z)
      const adjustedTimeSeries: TimeSeries = {
        start_time: "2026-11-11T13:04:54.000Z",
        end_time: "2026-11-11T13:19:00.000Z",
        mode: "recorded",
        series: [
          {
            tag_id: 1,
            tag_name: "TAG_VEL",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [{ timestamp: "2026-11-11T13:10:00.000Z", value: 30, good: true, questionable: false, substituted: false }],
          },
        ],
        errors: [],
        query_execution: {
          requested_start: "2026-11-11T13:04:54.000Z",
          requested_end: "2026-11-11T13:19:54.000Z",
          effective_start: "2026-11-11T13:04:54.000Z",
          effective_end: "2026-11-11T13:19:00.000Z",
          data_available_until: "2026-11-11T13:19:00.000Z",
          sampled: false,
          partial: false,
        },
      };
      apiMock.timeSeriesQuery.mockResolvedValue(adjustedTimeSeries);

      renderAt("/analises/visualizacao");

      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });

      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);

      fireEvent.click(await screen.findByTestId("filters-submit"));

      // Alerta de dados disponíveis deve estar visível com o intervalo efetivo
      const alert = await screen.findByTestId("data-available-until");
      expect(alert).toHaveTextContent("10:19:00");
      expect(alert).toHaveTextContent("10:04:54");

      // Cartão Período deve exibir o intervalo efetivo (10:19:00) e não o solicitado (10:19:54)
      const periodMetric = await screen.findByTestId("metric-period");
      expect(periodMetric).toHaveTextContent("10:19:00");
      expect(periodMetric).toHaveTextContent("Efetivo");
      expect(periodMetric).toHaveTextContent("Solicitado");
      expect(periodMetric).toHaveTextContent("10:19:54");
    });

    it("invalida resultado após alteração de filtros (qualidade, período, tags) e limpa aviso após nova consulta bem-sucedida", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      const timeSeriesResult: TimeSeries = {
        start_time: "2026-07-15T00:00:00Z",
        end_time: "2026-07-15T01:00:00Z",
        mode: "recorded",
        series: [
          {
            tag_id: 1,
            tag_name: "TAG_RB1",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [{ timestamp: "2026-07-15T00:30:00Z", value: 30, good: true, questionable: false, substituted: false }],
          },
        ],
        errors: [],
      };
      apiMock.timeSeriesQuery.mockResolvedValue(timeSeriesResult);

      renderAt("/analises/visualizacao");

      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });

      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);

      fireEvent.click(await screen.findByTestId("filters-submit"));
      expect(await screen.findByTestId("numeric-chart")).toBeInTheDocument();
      expect(screen.queryByTestId("outdated-result-warning")).toBeNull();

      // Altera o período (troca preset de PT1H para PT15M)
      const presetSelect = screen.getByTestId("period-preset");
      fireEvent.change(presetSelect, { target: { value: "PT15M" } });

      // Deve alertar que o resultado é da consulta anterior e identificar o contexto
      expect(await screen.findByTestId("outdated-result-warning")).toBeInTheDocument();
      expect(screen.getByTestId("outdated-result-warning")).toHaveTextContent("RB1");
      expect(screen.getByTestId("outdated-result-warning")).toHaveTextContent("Clique em Consultar para atualizar");

      // Nova consulta bem-sucedida deve remover o aviso
      fireEvent.click(screen.getByTestId("filters-submit"));
      await waitFor(() => {
        expect(screen.queryByTestId("outdated-result-warning")).toBeNull();
      });
    });
  });

  describe("Bug 6: Validação e acessibilidade de seleção de tags", () => {
    it("destaca TagMultiSelect com atributos de acessibilidade ao tentar consultar sem tags", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      renderAt("/analises/visualizacao");

      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });

      // Tenta submeter sem selecionar nenhuma tag
      fireEvent.click(await screen.findByTestId("filters-submit"));

      // Alerta de erro presente e TagMultiSelect com aria-invalid
      const tagSelectContainer = screen.getByTestId("tag-multi-select");
      expect(tagSelectContainer).toHaveAttribute("aria-invalid", "true");
      expect(tagSelectContainer).toHaveAttribute("aria-describedby", "tag-selection-error");

      const errorMessage = screen.getByTestId("tag-selection-error");
      expect(errorMessage).toHaveTextContent("Selecione ao menos uma tag");
    });
  });

  describe("Bug 3: Unidades padrão do tipo de variável e separação de eixos", () => {
    it("herda default_unit quando engineering_unit é nulo e separa eixos para grandezas distintas", () => {
      const vtSpeed: VariableType = { ...variableTypeFixture, id: 1, code: "VEL", default_unit: "m/min" };
      const vtTemp: VariableType = { ...variableTypeFixture, id: 2, code: "TEMP", default_unit: "°C" };

      const tagSpeed: PiTag = {
        ...piTagFixture,
        id: 20,
        variable_type_id: 1,
        engineering_unit: null,
        display_name: "Velocidade",
      };
      const tagTemp: PiTag = {
        ...piTagFixture,
        id: 23,
        variable_type_id: 2,
        engineering_unit: null,
        display_name: "Zona 03",
      };

      const optSpeed = buildTagOption(tagSpeed, { code: "RB1" }, { code: "FORNO" }, vtSpeed);
      const optTemp = buildTagOption(tagTemp, { code: "RB1" }, { code: "FORNO" }, vtTemp);

      expect(optSpeed.unit).toBe("m/min");
      expect(optTemp.unit).toBe("°C");

      const assignments = createInitialAssignments([
        { tagId: 20, unit: optSpeed.unit, numeric: true },
        { tagId: 23, unit: optTemp.unit, numeric: true },
      ]);

      expect(assignments[0].lineAxis).toBe("primary");
      expect(assignments[1].lineAxis).toBe("secondary");
    });
  });

  describe("Bug 4: Limites de norma pertencem apenas à série correspondente", () => {
    it("não renderiza limites de norma se a série pai não estiver presente no gráfico", () => {
      const timeSeries: TimeSeries = {
        start_time: "2026-07-15T00:00:00Z",
        end_time: "2026-07-15T01:00:00Z",
        mode: "recorded",
        series: [
          {
            tag_id: 10,
            tag_name: "ESPESSURA",
            display_name: "Espessura",
            equipment: "RB3",
            section: "FORNO",
            variable_type: "THICKNESS",
            unit: "mm",
            points: [[Date.parse("2026-07-15T00:30:00Z"), 2.5] as any],
          },
        ],
      };

      const chart = buildChartData(timeSeries, { ignoreBadQuality: false });

      // Limite órfão da tag 20 (Velocidade de RB1)
      const orphanNormLimit = buildNormLimitSeries({
        seriesInstanceId: "tag:20",
        tagName: "VELOCIDADE",
        mainDisplayName: "Velocidade",
        lowerTagName: "VEL_LIM_INF",
        upperTagName: "VEL_LIM_SUP",
        yAxisIndex: 0,
        lineStyle: "solid",
        width: 1,
        lowerColor: "#ff0000",
        upperColor: "#0000ff",
        lowerPoints: [{ timestamp: "2026-07-15T00:00:00Z", value: 10, good: true }],
        upperPoints: [{ timestamp: "2026-07-15T00:00:00Z", value: 50, good: true }],
      });

      const option = buildTimeSeriesChartOption({
        chart,
        equipment: "RB3",
        start: new Date("2026-07-15T00:00:00Z"),
        end: new Date("2026-07-15T01:00:00Z"),
        normLimitSeries: [orphanNormLimit],
      });

      const seriesList = option.series as Array<{ name?: string }>;
      const legend = option.legend as { data?: string[] };

      // Apenas a Espessura deve estar presente no gráfico e na legenda
      expect(seriesList.some((s) => s.name?.includes("Velocidade"))).toBe(false);
      expect(legend.data?.some((name) => name.includes("Velocidade"))).toBe(false);
      expect(legend.data).toContain("Espessura");
    });
  });

  describe("Bug 2 & Bug 8: Cobertura parcial e formatação do sentinela -999", () => {
    it("indica cobertura parcial na legenda e formata sentinela -999 como Sem limite ativo / Parada", () => {
      const timeSeries: TimeSeries = {
        start_time: "2026-07-15T00:00:00Z",
        end_time: "2026-07-15T01:00:00Z",
        mode: "recorded",
        series: [
          {
            tag_id: 20,
            tag_name: "VELOCIDADE",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [[Date.parse("2026-07-15T00:30:00Z"), 30] as any],
          },
        ],
      };

      const chart = buildChartData(timeSeries, { ignoreBadQuality: false });

      const normLimit = buildNormLimitSeries({
        seriesInstanceId: "tag:20",
        tagName: "VELOCIDADE",
        mainDisplayName: "Velocidade",
        lowerTagName: "VEL_LIM_INF",
        upperTagName: "VEL_LIM_SUP",
        yAxisIndex: 0,
        lineStyle: "solid",
        width: 1,
        lowerColor: "#ff0000",
        upperColor: "#0000ff",
        lowerPoints: [{ timestamp: "2026-07-15T00:00:00Z", value: -999, good: true }],
        upperPoints: [{ timestamp: "2026-07-15T00:00:00Z", value: 50, good: true }],
        lowerCoverageGaps: [["2026-07-15T00:45:00Z", "2026-07-15T01:00:00Z"]],
      });

      const option = buildTimeSeriesChartOption({
        chart,
        equipment: "RB1",
        start: new Date("2026-07-15T00:00:00Z"),
        end: new Date("2026-07-15T01:00:00Z"),
        normLimitSeries: [normLimit],
      });

      const legend = option.legend as { data?: string[] };
      // Limite inferior com gaps indica cobertura parcial
      expect(legend.data?.some((name) => name.includes("cobertura parcial"))).toBe(true);

      // Tooltip formata -999 como sentinela de parada
      const tooltipFormatter = (option.tooltip as any)?.formatter;
      expect(typeof tooltipFormatter).toBe("function");
      const tooltipHtml = tooltipFormatter([
        { seriesIndex: 0, seriesName: "Velocidade", axisValue: Date.parse("2026-07-15T00:30:00Z"), value: [Date.parse("2026-07-15T00:30:00Z"), 30] },
        { seriesIndex: 1, seriesName: "Limite inferior — Velocidade (cobertura parcial)", axisValue: Date.parse("2026-07-15T00:30:00Z"), value: [Date.parse("2026-07-15T00:30:00Z"), -999] },
      ]);
      expect(tooltipHtml).toContain("Sem limite ativo / Parada");
    });
  });

  describe("Bug 7: Clareza do estado da configuração visual", () => {
    it("exibe badge de rascunho não salvo quando nenhuma configuração está aberta", () => {
      render(
        <VisualConfigurationsPanel
          document={{ version: 1, filters: {} as any, seriesAssignments: [], metricConfiguration: {} as any, comparison: {} as any, visualRules: {} as any }}
          onOpen={vi.fn()}
        />,
      );
      const statusBadge = screen.getByTestId("visual-config-current-status");
      expect(statusBadge).toHaveTextContent("Rascunho atual (não salvo)");
    });
  });

  describe("Validação do período absoluto, envio de instantes e exibição do período efetivo", () => {
    it("reconhece datas inicial e final preenchidas, remove a validação e habilita Consultar com step de segundos", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      renderAt("/analises/visualizacao");

      // Seleciona tag
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });
      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);

      // Troca para período absoluto
      fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "absolute" } });

      const startInput = screen.getByTestId("absolute-start");
      const endInput = screen.getByTestId("absolute-end");
      const submitBtn = screen.getByTestId("filters-submit");

      // Possuem atributo step="1" para aceitar segundos
      expect(startInput).toHaveAttribute("step", "1");
      expect(endInput).toHaveAttribute("step", "1");

      // Inicialmente vazio: mostra mensagem de erro e botão Consultar desabilitado
      expect(screen.getByTestId("time-period-error")).toHaveTextContent("Informe a data e hora inicial");
      expect(submitBtn).toBeDisabled();

      // Preenche início solicitado: 11/11/2026 10:04:54
      fireEvent.change(startInput, { target: { value: "2026-11-11T10:04:54" } });
      // Ainda sem fim: mostra erro de data final
      expect(screen.getByTestId("time-period-error")).toHaveTextContent("Informe a data e hora final");
      expect(submitBtn).toBeDisabled();

      // Preenche fim solicitado: 11/11/2026 10:19:54
      fireEvent.change(endInput, { target: { value: "2026-11-11T10:19:54" } });

      // Mensagem de validação removida e Consultar habilitado
      expect(screen.queryByTestId("time-period-error")).toBeNull();
      expect(submitBtn).not.toBeDisabled();
    });

    it("aceita colar formato brasileiro (DD/MM/YYYY HH:mm:ss) e normaliza para ISO nos campos", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      renderAt("/analises/visualizacao");

      fireEvent.change(await screen.findByTestId("period-kind"), { target: { value: "absolute" } });
      const startInput = screen.getByTestId("absolute-start");
      const endInput = screen.getByTestId("absolute-end");

      // Simula colar texto em formato brasileiro
      fireEvent.paste(startInput, {
        clipboardData: { getData: () => "11/11/2026 10:04:54" },
      });
      fireEvent.paste(endInput, {
        clipboardData: { getData: () => "11/11/2026 10:19:54" },
      });

      expect(startInput.value).toContain("2026-11-11T10:04:54");
      expect(endInput.value).toContain("2026-11-11T10:19:54");
      expect(screen.queryByTestId("time-period-error")).toBeNull();
    });

    it("envia a consulta com os instantes UTC corretos respeitando America/Sao_Paulo sem perda de segundos e exibe badge/nota de período efetivo ajustado", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      // Simula backend limitando o fim efetivo a 11/11/2026 10:19:00 (13:19:00 UTC) ao watermark
      const timeSeriesAdjusted: TimeSeries = {
        start_time: "2026-11-11T13:04:54.000Z",
        end_time: "2026-11-11T13:19:00.000Z",
        mode: "recorded",
        series: [
          {
            tag_id: 1,
            tag_name: "TAG_RB1",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [
              { timestamp: "2026-11-11T13:05:00.000Z", value: 30, good: true, questionable: false, substituted: false },
              { timestamp: "2026-11-11T13:18:50.000Z", value: 32, good: true, questionable: false, substituted: false },
            ],
          },
        ],
        query_execution: {
          requested_start: "2026-11-11T13:04:54.000Z",
          requested_end: "2026-11-11T13:19:54.000Z",
          effective_start: "2026-11-11T13:04:54.000Z",
          effective_end: "2026-11-11T13:19:00.000Z",
          data_available_until: "2026-11-11T13:19:00.000Z",
          resolution_mode: "automatic",
          sampled: false,
          partial: false,
        },
        errors: [],
      };
      apiMock.timeSeriesQuery.mockResolvedValue(timeSeriesAdjusted);

      renderAt("/analises/visualizacao");

      // Seleciona RB1 e Tag 1
      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });
      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);

      // Define período absoluto: 11/11/2026 10:04:54 até 11/11/2026 10:19:54
      fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "absolute" } });
      const startInput = screen.getByTestId("absolute-start");
      const endInput = screen.getByTestId("absolute-end");
      fireEvent.change(startInput, { target: { value: "2026-11-11T10:04:54" } });
      fireEvent.change(endInput, { target: { value: "2026-11-11T10:19:54" } });

      // Submete consulta
      fireEvent.click(screen.getByTestId("filters-submit"));

      // 1. Verifica os instantes enviados ao backend respeitando America/Sao_Paulo (UTC-3) sem perda de :54
      await waitFor(() => expect(apiMock.timeSeriesQuery).toHaveBeenCalledTimes(1));
      expect(apiMock.timeSeriesQuery).toHaveBeenCalledWith(
        expect.objectContaining({
          start_time: "2026-11-11T13:04:54.000Z",
          end_time: "2026-11-11T13:19:54.000Z",
        }),
        expect.anything(),
      );

      // 2. Verifica o cartão Período com intervalo efetivo, badge e nota de solicitado
      const periodCard = await screen.findByTestId("metric-period");
      expect(periodCard).toHaveTextContent("11/11/2026, 10:04:54 -> 11/11/2026, 10:19:00");
      expect(within(periodCard).getByText("Efetivo")).toBeInTheDocument();
      const periodNote = screen.getByTestId("metric-period-note");
      expect(periodNote).toHaveTextContent("Solicitado: 11/11/2026, 10:04:54 -> 11/11/2026, 10:19:54");

      // 3. Os controles de filtro continuam exibindo o período solicitado pelo operador
      expect(startInput.value).toContain("2026-11-11T10:04:54");
      expect(endInput.value).toContain("2026-11-11T10:19:54");
    });

    it("se não houver ajuste do backend, o cartão mostra o período normalmente, sem badge ou nota", async () => {
      const eq1: Equipment = { ...equipmentFixture, id: 1, code: "RB1", name: "RB1" };
      const tag1: PiTag = { ...piTagFixture, id: 1, equipment_id: 1, validation_status: "VALID" };

      apiMock.listEquipments.mockResolvedValue(paginated([eq1]));
      apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
      apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
      apiMock.listPiTags.mockResolvedValue(paginated([tag1]));
      apiMock.piHealth.mockResolvedValue(connectedHealthFixture);

      const timeSeriesUnadjusted: TimeSeries = {
        start_time: "2026-11-11T13:04:54.000Z",
        end_time: "2026-11-11T13:19:54.000Z",
        mode: "recorded",
        series: [
          {
            tag_id: 1,
            tag_name: "TAG_RB1",
            display_name: "Velocidade",
            equipment: "RB1",
            section: "FORNO",
            variable_type: "SPEED",
            unit: "m/min",
            points: [{ timestamp: "2026-11-11T13:10:00.000Z", value: 30, good: true, questionable: false, substituted: false }],
          },
        ],
        query_execution: {
          requested_start: "2026-11-11T13:04:54.000Z",
          requested_end: "2026-11-11T13:19:54.000Z",
          effective_start: "2026-11-11T13:04:54.000Z",
          effective_end: "2026-11-11T13:19:54.000Z",
          resolution_mode: "automatic",
          sampled: false,
          partial: false,
        },
        errors: [],
      };
      apiMock.timeSeriesQuery.mockResolvedValue(timeSeriesUnadjusted);

      renderAt("/analises/visualizacao");

      const equipmentSelect = (await screen.findByTestId("equipment-select")) as HTMLSelectElement;
      await waitFor(() => expect(equipmentSelect.options.length).toBeGreaterThan(1));
      fireEvent.change(equipmentSelect, { target: { value: "1" } });
      const tagList = await screen.findByTestId("tag-multi-select");
      const option = await within(tagList).findByTestId("tag-option-1");
      fireEvent.click(option);

      fireEvent.change(screen.getByTestId("period-kind"), { target: { value: "absolute" } });
      fireEvent.change(screen.getByTestId("absolute-start"), { target: { value: "2026-11-11T10:04:54" } });
      fireEvent.change(screen.getByTestId("absolute-end"), { target: { value: "2026-11-11T10:19:54" } });

      fireEvent.click(screen.getByTestId("filters-submit"));

      const periodCard = await screen.findByTestId("metric-period");
      expect(periodCard).toHaveTextContent("11/11/2026, 10:04:54 -> 11/11/2026, 10:19:54");
      expect(within(periodCard).queryByText("Efetivo")).toBeNull();
      expect(screen.queryByTestId("metric-period-note")).toBeNull();
    });
  });
});
