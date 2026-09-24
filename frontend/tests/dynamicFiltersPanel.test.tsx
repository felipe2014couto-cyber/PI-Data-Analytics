import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiMock, mockApiModule } from "./mocks/api";

vi.mock("../src/api", () => mockApiModule());

import { AdvancedFiltersPanel, isFixedAnalysisTag } from "../src/components/AdvancedFiltersPanel";
import { applyDataFilters } from "../src/utils/dataFilters";
import type { ConflictedVariable, DataFilterConfiguration, SectionAnalysisTag, TimeSeries } from "../src/types";

const mockConfig: DataFilterConfiguration = {
  quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

const mockAnalysisTags: SectionAnalysisTag[] = [
  {
    id: 1,
    variable_type_id: 10,
    variable_type_code: "CORRENTE",
    variable_type_name: "Corrente Elétrica",
    filter_data_type: "REAL",
    filter_type: "MIN_MAX",
    pi_tag_id: 101,
    pi_tag_name: "SEC1.CURRENT",
  },
  {
    id: 2,
    variable_type_id: 11,
    variable_type_code: "VALVULA_ON",
    variable_type_name: "Status Válvula",
    filter_data_type: "DIGITAL",
    filter_type: "SELECTION",
    pi_tag_id: 102,
    pi_tag_name: "SEC1.VALVE",
  },
  {
    id: 3,
    variable_type_id: 12,
    variable_type_code: "LOTE_PROD",
    variable_type_name: "Lote de Produção",
    filter_data_type: "STRING",
    filter_type: "TEXT",
    pi_tag_id: 103,
    pi_tag_name: "SEC1.BATCH",
  },
  {
    id: 7,
    variable_type_id: 16,
    variable_type_code: "MODO_OPERACAO",
    variable_type_name: "Modo de Operação",
    filter_data_type: "STRING",
    filter_type: "SELECTION",
    pi_tag_id: 107,
    pi_tag_name: "SEC1.MODE",
  },
  // Fixed variable types that must NOT be duplicated in dynamic section
  {
    id: 4,
    variable_type_id: 13,
    variable_type_code: "LARGURA",
    variable_type_name: "Largura Bobina",
    filter_data_type: "REAL",
    filter_type: "MIN_MAX",
    pi_tag_id: 104,
    pi_tag_name: "SEC1.WIDTH",
  },
  {
    id: 5,
    variable_type_id: 14,
    variable_type_code: "UM",
    variable_type_name: "Unidade Metalúrgica",
    filter_data_type: "STRING",
    filter_type: "TEXT",
    pi_tag_id: 105,
    pi_tag_name: "SEC1.UM",
  },
  {
    id: 6,
    variable_type_id: 15,
    variable_type_code: "ESPESSURA",
    variable_type_name: "Espessura Nominal",
    filter_data_type: "REAL",
    filter_type: "MIN_MAX",
    pi_tag_id: 106,
    pi_tag_name: "SEC1.THICK",
  },
];

describe("AdvancedFiltersPanel Dynamic Filters", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getDistinctValues.mockResolvedValue(["MANUAL", "AUTOMATICO", "CALIBRACAO"]);
  });

  it("renders dynamic section for non-fixed section analysis tags", async () => {
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("named-filter-group-extra-filters")).toBeInTheDocument();
    expect(screen.getByText("Filtros extras")).toBeInTheDocument();

    // Check that non-fixed tags are rendered
    expect(screen.getAllByText(/Corrente Elétrica/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Status Válvula/)).toBeInTheDocument();
    expect(screen.getByText(/Lote de Produção/)).toBeInTheDocument();
    expect(screen.getByText(/Modo de Operação/)).toBeInTheDocument();

    // Check controls for MIN_MAX (REAL)
    expect(screen.getByTestId("dynamic-filter-min-10")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-filter-max-10")).toBeInTheDocument();

    // Check control for SELECTION (DIGITAL)
    expect(screen.getByTestId("dynamic-filter-digital-11")).toBeInTheDocument();

    // Check control for SELECTION (STRING with distinct options)
    const modeSelect = screen.getByTestId("dynamic-filter-select-16") as HTMLSelectElement;
    expect(modeSelect).toBeInTheDocument();
    await waitFor(() => {
      const opts = Array.from(modeSelect.options).map((o) => o.value);
      expect(opts).toContain("MANUAL");
      expect(opts).toContain("AUTOMATICO");
    });

    // Check control for TEXT (STRING)
    expect(screen.getByTestId("dynamic-filter-string-12")).toBeInTheDocument();
    expect(screen.getByTestId("info-popover-12")).toBeInTheDocument();

    // Fixed tags must NOT be present in dynamic section
    expect(screen.queryByTestId("dynamic-filter-min-13")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-filter-string-14")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-filter-min-15")).not.toBeInTheDocument();
  });

  it("triggers onDynamicFilterChange and onChange with numeric rule on MIN_MAX input", () => {
    const onDynamicFilterChange = vi.fn();
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={onChange}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={onDynamicFilterChange}
      />,
    );

    const minInput = screen.getByTestId("dynamic-filter-min-10");
    fireEvent.change(minInput, { target: { value: "150" } });

    expect(onDynamicFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({
        10: expect.objectContaining({
          variable_type_id: 10,
          min: 150,
        }),
      }),
    );

    // Verify section-filter rule emitted to onChange
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        rules: expect.arrayContaining([
          expect.objectContaining({
            id: "section-filter:10",
            kind: "numeric",
            operator: "greaterThanOrEqual",
            value: 150,
            secondValue: null,
            tagId: 101,
          }),
        ]),
      }),
    );
  });

  it("triggers onDynamicFilterChange and onChange on DIGITAL SELECTION select", () => {
    const onDynamicFilterChange = vi.fn();
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={onChange}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={onDynamicFilterChange}
      />,
    );

    const digitalSelect = screen.getByTestId("dynamic-filter-digital-11");
    fireEvent.change(digitalSelect, { target: { value: "ON" } });

    expect(onDynamicFilterChange).toHaveBeenCalledWith(
      expect.objectContaining({
        11: expect.objectContaining({
          variable_type_id: 11,
          value: "ON",
        }),
      }),
    );

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        rules: expect.arrayContaining([
          expect.objectContaining({
            id: "section-filter:11",
            kind: "text",
            operator: "equal",
            value: "ON",
            tagId: 102,
          }),
        ]),
      }),
    );
  });

  it("triggers onChange on distinct string SELECTION select", async () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={onChange}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    const modeSelect = screen.getByTestId("dynamic-filter-select-16");
    await waitFor(() => {
      expect(apiMock.getDistinctValues).toHaveBeenCalledWith(107);
    });

    fireEvent.change(modeSelect, { target: { value: "AUTOMATICO" } });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        rules: expect.arrayContaining([
          expect.objectContaining({
            id: "section-filter:16",
            kind: "text",
            operator: "equal",
            value: "AUTOMATICO",
            tagId: 107,
          }),
        ]),
      }),
    );
  });

  it("shows validation error on invalid STRING filter expression", () => {
    const onDynamicFilterChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={onDynamicFilterChange}
      />,
    );

    const stringInput = screen.getByTestId("dynamic-filter-string-12");
    fireEvent.change(stringInput, { target: { value: "P1:X100" } });

    expect(screen.getByText(/prefixos das duas extremidades devem ser iguais/)).toBeInTheDocument();
    expect(stringInput).toHaveClass("is-invalid");
  });

  it("clears dynamic filters when Limpar filtros is clicked", () => {
    const onDynamicFilterChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{
          10: { variable_type_id: 10, min: 100 },
          11: { variable_type_id: 11, value: "ON" },
        }}
        onDynamicFilterChange={onDynamicFilterChange}
      />,
    );

    const clearButton = screen.getByTestId("filter-reset");
    fireEvent.click(clearButton);

    expect(onDynamicFilterChange).toHaveBeenCalledWith({});
  });

  it("oculta a área Filtros extras quando analysisTags está vazio (ex: Todas as seções)", () => {
    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={[]}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("named-filter-group-extra-filters")).not.toBeInTheDocument();
    expect(screen.queryByText("Filtros extras")).not.toBeInTheDocument();
  });

  it("limpa os campos de Filtros extras ao trocar de seção mantendo os filtros principais intactos", () => {
    const { rerender } = render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={mockAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    // Fill in a main filter and an extra filter
    const umInput = screen.getByTestId("named-filter-umCode");
    fireEvent.change(umInput, { target: { value: "UM-100" } });
    expect(umInput).toHaveValue("UM-100");

    const stringInput = screen.getByTestId("dynamic-filter-string-12");
    fireEvent.change(stringInput, { target: { value: "LOTE-99" } });
    expect(stringInput).toHaveValue("LOTE-99");

    // Switch section: change analysisTags to another section's tags
    const newSectionTags: SectionAnalysisTag[] = [
      {
        id: 10,
        variable_type_id: 20,
        variable_type_code: "PRESSAO",
        variable_type_name: "Pressão Hidráulica",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 201,
        pi_tag_name: "SEC2.PRESSURE",
      },
    ];

    rerender(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={newSectionTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    // Extra filters reloaded with new section
    expect(screen.getByTestId("named-filter-group-extra-filters")).toBeInTheDocument();
    expect(screen.getAllByText(/Pressão Hidráulica/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Lote de Produção/)).not.toBeInTheDocument();

    // Main filter preserved
    expect(screen.getByTestId("named-filter-umCode")).toHaveValue("UM-100");
  });

  it("executa filtragem real de dados com sample-and-hold assíncrono para filtros extras", () => {
    // Test applyDataFilters directly with cross-series rule from extra filter
    const timeSeries: TimeSeries = {
      start_time: "2026-07-01T10:00:00Z",
      end_time: "2026-07-01T10:01:00Z",
      mode: "recorded",
      errors: [],
      series: [
        {
          tag_id: 999, // User visible series (e.g. Temperature)
          tag_name: "SEC1.TEMP",
          display_name: "Temperature",
          equipment: "EQ1",
          section: "SEC1",
          variable_type: "TEMP",
          unit: "C",
          points: [
            { timestamp: "2026-07-01T10:00:05Z", value: 100, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-01T10:00:15Z", value: 105, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-01T10:00:25Z", value: 110, good: true, questionable: false, substituted: false },
          ],
        },
        {
          tag_id: 102, // Extra section tag: Status Válvula (DIGITAL) with async timestamps
          tag_name: "SEC1.VALVE",
          display_name: "Status Válvula",
          equipment: "EQ1",
          section: "SEC1",
          variable_type: "VALVE",
          unit: "",
          points: [
            // Sample-and-hold: valve is ON starting at 10:00:00
            { timestamp: "2026-07-01T10:00:00Z", value: true, good: true, questionable: false, substituted: false },
            // valve turns OFF at 10:00:20
            { timestamp: "2026-07-01T10:00:20Z", value: false, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    // Filter rule: valve must be ON
    const config: DataFilterConfiguration = {
      quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        {
          id: "section-filter:11",
          kind: "text",
          enabled: true,
          tagId: 102,
          operator: "equal",
          value: "ON",
          caseSensitive: false,
        },
      ],
    };

    const result = applyDataFilters(timeSeries, config, {
      crossSeriesRuleIds: new Set(["section-filter:11"]),
      summarySeriesKeys: new Set(["tag:999"]),
    });

    const visibleSeries = result.filteredTimeSeries.series.find((s) => s.tag_id === 999);
    expect(visibleSeries).toBeDefined();
    // Points at 10:00:05 and 10:00:15 have valve ON (sample-and-hold from 10:00:00)
    // Point at 10:00:25 has valve OFF (from 10:00:20) and is excluded!
    expect(visibleSeries!.points.map((p) => p.timestamp)).toEqual([
      "2026-07-01T10:00:05Z",
      "2026-07-01T10:00:15Z",
    ]);
    expect(result.summary.removedPoints).toBe(1);
  });
});

describe("Filtros extras por máquina e seção (regras de negócio)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1 e 4. Deduplica variável compartilhada em 'Todas as seções' e exibe contagem de tags", () => {
    // Duas seções (FORNO e ACABAMENTO) têm a variável VELOCIDADE
    const extraAnalysisTags: SectionAnalysisTag[] = [
      {
        id: 1,
        variable_type_id: 50,
        variable_type_code: "VELOCIDADE",
        variable_type_name: "Velocidade de Linha",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 201,
        pi_tag_name: "FORNO.VEL",
        section_tag_map: { 1: 201, 2: 301 },
        pi_tag_ids: [201, 301],
      },
      {
        id: 2,
        variable_type_id: 51,
        variable_type_code: "PRESSAO",
        variable_type_name: "Pressão Hidráulica",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 202,
        pi_tag_name: "FORNO.PRESS",
        section_tag_map: { 1: 202 },
        pi_tag_ids: [202],
      },
      {
        id: 3,
        variable_type_id: 52,
        variable_type_code: "TEMPERATURA",
        variable_type_name: "Temperatura Forno",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 302,
        pi_tag_name: "ACAB.TEMP",
        section_tag_map: { 2: 302 },
        pi_tag_ids: [302],
      },
    ];

    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={extraAnalysisTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    // Deve renderizar apenas UM controle (min e max) para Velocidade de Linha
    expect(screen.queryAllByTestId("dynamic-filter-min-50").length).toBe(1);
    expect(screen.queryAllByTestId("dynamic-filter-max-50").length).toBe(1);
    expect(screen.getByText(/\(2 tags\)/)).toBeInTheDocument();
    // Exibe também os outros filtros únicos
    expect(screen.queryAllByTestId("dynamic-filter-min-51").length).toBe(1);
    expect(screen.queryAllByTestId("dynamic-filter-min-52").length).toBe(1);
  });

  it("2 e 3. Seção específica exibe apenas suas próprias tags de análise e omite tags de outras seções", () => {
    // Quando FORNO está selecionado, apenas tags de FORNO são passadas
    const fornoTags: SectionAnalysisTag[] = [
      {
        id: 1,
        variable_type_id: 50,
        variable_type_code: "VELOCIDADE",
        variable_type_name: "Velocidade de Linha",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 201,
        pi_tag_name: "FORNO.VEL",
        section_tag_map: { 1: 201 },
        pi_tag_ids: [201],
      },
      {
        id: 2,
        variable_type_id: 51,
        variable_type_code: "PRESSAO",
        variable_type_name: "Pressão Hidráulica",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 202,
        pi_tag_name: "FORNO.PRESS",
        section_tag_map: { 1: 202 },
        pi_tag_ids: [202],
      },
    ];

    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={fornoTags}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("dynamic-filter-min-50")).toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-filter-min-51")).toBeInTheDocument();
    // Não exibe (2 tags) pois só tem 1 tag
    expect(screen.queryByText(/\(2 tags\)/)).not.toBeInTheDocument();
    // Não exibe TEMPERATURA (que pertence a ACABAMENTO)
    expect(screen.queryByTestId("dynamic-filter-min-52")).not.toBeInTheDocument();
  });

  it("5 e 6. Avaliação real em 'Todas as seções': mapeia cada série à sua PI Tag e é estritamente neutra para seção sem a variável", () => {
    const timeSeries: TimeSeries = {
      start_time: "2026-07-01T10:00:00Z",
      end_time: "2026-07-01T10:01:00Z",
      mode: "recorded",
      errors: [],
      series: [
        // Série 1: Visível, pertence à Seção 1 (FORNO)
        {
          tag_id: 1000,
          tag_name: "SEC1.CORRENTE",
          display_name: "Corrente Forno",
          equipment: "RB1",
          section: "FORNO",
          variable_type: "CORRENTE",
          unit: "A",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 10, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-01T10:00:20Z", value: 20, good: true, questionable: false, substituted: false },
          ],
        },
        // Série 2: Visível, pertence à Seção 2 (ACABAMENTO)
        {
          tag_id: 2000,
          tag_name: "SEC2.CORRENTE",
          display_name: "Corrente Acabamento",
          equipment: "RB1",
          section: "ACABAMENTO",
          variable_type: "CORRENTE",
          unit: "A",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 30, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-01T10:00:20Z", value: 40, good: true, questionable: false, substituted: false },
          ],
        },
        // Série 3: Visível, pertence à Seção 3 (DECAPAGEM - SEM variável VELOCIDADE)
        {
          tag_id: 3000,
          tag_name: "SEC3.NIVEL",
          display_name: "Nível Tanque",
          equipment: "RB1",
          section: "DECAPAGEM",
          variable_type: "NIVEL",
          unit: "m",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 5, good: true, questionable: false, substituted: false },
            { timestamp: "2026-07-01T10:00:20Z", value: 5, good: true, questionable: false, substituted: false },
          ],
        },
        // Tag de contexto: VELOCIDADE FORNO (Tag 201)
        {
          tag_id: 201,
          tag_name: "LFI_RB1_VEL_FORNO",
          display_name: "Velocidade Forno",
          equipment: "RB1",
          section: "FORNO",
          variable_type: "VELOCIDADE",
          unit: "m/min",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 50, good: true, questionable: false, substituted: false }, // < 100
            { timestamp: "2026-07-01T10:00:20Z", value: 150, good: true, questionable: false, substituted: false }, // >= 100
          ],
        },
        // Tag de contexto: VELOCIDADE ACABAMENTO (Tag 301)
        {
          tag_id: 301,
          tag_name: "LFI_RB1_VEL_ACAB",
          display_name: "Velocidade Acabamento",
          equipment: "RB1",
          section: "ACABAMENTO",
          variable_type: "VELOCIDADE",
          unit: "m/min",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 150, good: true, questionable: false, substituted: false }, // >= 100
            { timestamp: "2026-07-01T10:00:20Z", value: 50, good: true, questionable: false, substituted: false }, // < 100
          ],
        },
      ],
    };

    // Regra: VELOCIDADE >= 100
    const config: DataFilterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        {
          id: "section-filter:50",
          kind: "numeric",
          enabled: true,
          tagId: 201, // Tag de referência
          operator: "greaterThanOrEqual",
          value: 100,
          secondValue: null,
          sectionTagMap: { 1: 201, 2: 301 }, // Seção 1 -> Tag 201, Seção 2 -> Tag 301 (Seção 3 NÃO mapeada)
        },
      ],
    };

    const seriesSectionMap = new Map<string, number>([
      ["tag:1000", 1], // FORNO
      ["tag:2000", 2], // ACABAMENTO
      ["tag:3000", 3], // DECAPAGEM (sem a variável)
    ]);

    const result = applyDataFilters(timeSeries, config, {
      crossSeriesRuleIds: new Set(["section-filter:50"]),
      summarySeriesKeys: new Set(["tag:1000", "tag:2000", "tag:3000"]),
      seriesSectionMap,
    });

    const series1 = result.filteredTimeSeries.series.find((s) => s.tag_id === 1000);
    const series2 = result.filteredTimeSeries.series.find((s) => s.tag_id === 2000);
    const series3 = result.filteredTimeSeries.series.find((s) => s.tag_id === 3000);

    // Série 1 (FORNO): em 10:00:10 Tag 201 é 50 (<100) -> filtrado! Em 10:00:20 é 150 -> mantido.
    expect(series1!.points.map((p) => p.timestamp)).toEqual(["2026-07-01T10:00:20Z"]);

    // Série 2 (ACABAMENTO): em 10:00:10 Tag 301 é 150 (>=100) -> mantido! Em 10:00:20 é 50 -> filtrado.
    expect(series2!.points.map((p) => p.timestamp)).toEqual(["2026-07-01T10:00:10Z"]);

    // Série 3 (DECAPAGEM): Seção sem a variável -> regra é estritamente NEUTRA. Ambos os pontos são mantidos!
    expect(series3!.points.map((p) => p.timestamp)).toEqual([
      "2026-07-01T10:00:10Z",
      "2026-07-01T10:00:20Z",
    ]);

    // Total de pontos removidos = 1 (da Série 1) + 1 (da Série 2) + 0 (da Série 3) = 2
    expect(result.summary.removedPoints).toBe(2);
  });

  it("7. Evita colisões utilizando series_instance_id como chave de série", () => {
    // Mesma tag_id em instâncias de série distintas
    const timeSeries: TimeSeries = {
      start_time: "2026-07-01T10:00:00Z",
      end_time: "2026-07-01T10:01:00Z",
      mode: "recorded",
      errors: [],
      series: [
        {
          tag_id: 1000,
          series_instance_id: "inst-forno",
          tag_name: "SEC.CORRENTE",
          display_name: "Corrente",
          equipment: "RB1",
          section: "FORNO",
          variable_type: "CORRENTE",
          unit: "A",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 10, good: true, questionable: false, substituted: false },
          ],
        },
        {
          tag_id: 1000,
          series_instance_id: "inst-acabamento",
          tag_name: "SEC.CORRENTE",
          display_name: "Corrente",
          equipment: "RB1",
          section: "ACABAMENTO",
          variable_type: "CORRENTE",
          unit: "A",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 10, good: true, questionable: false, substituted: false },
          ],
        },
        {
          tag_id: 201,
          tag_name: "LFI_RB1_VEL_FORNO",
          display_name: "Velocidade Forno",
          equipment: "RB1",
          section: "FORNO",
          variable_type: "VELOCIDADE",
          unit: "m/min",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 50, good: true, questionable: false, substituted: false },
          ],
        },
        {
          tag_id: 301,
          tag_name: "LFI_RB1_VEL_ACAB",
          display_name: "Velocidade Acabamento",
          equipment: "RB1",
          section: "ACABAMENTO",
          variable_type: "VELOCIDADE",
          unit: "m/min",
          points: [
            { timestamp: "2026-07-01T10:00:10Z", value: 150, good: true, questionable: false, substituted: false },
          ],
        },
      ],
    };

    const config: DataFilterConfiguration = {
      quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      rules: [
        {
          id: "section-filter:50",
          kind: "numeric",
          enabled: true,
          tagId: 201,
          operator: "greaterThanOrEqual",
          value: 100,
          secondValue: null,
          sectionTagMap: { 1: 201, 2: 301 },
        },
      ],
    };

    const seriesSectionMap = new Map<string, number>([
      ["inst-forno", 1],
      ["inst-acabamento", 2],
    ]);

    const result = applyDataFilters(timeSeries, config, {
      crossSeriesRuleIds: new Set(["section-filter:50"]),
      summarySeriesKeys: new Set(["inst-forno", "inst-acabamento"]),
      seriesSectionMap,
    });

    const fornoInst = result.filteredTimeSeries.series.find((s) => s.series_instance_id === "inst-forno");
    const acabInst = result.filteredTimeSeries.series.find((s) => s.series_instance_id === "inst-acabamento");

    expect(fornoInst!.points.length).toBe(0); // 50 < 100, filtrado
    expect(acabInst!.points.length).toBe(1); // 150 >= 100, mantido
  });

  it("8. Exibe banner de aviso discreto quando há conflito de filter_type e renderiza outros filtros válidos", () => {
    const validTags: SectionAnalysisTag[] = [
      {
        id: 2,
        variable_type_id: 51,
        variable_type_code: "PRESSAO",
        variable_type_name: "Pressão Hidráulica",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 202,
        pi_tag_name: "FORNO.PRESS",
        section_tag_map: { 1: 202 },
        pi_tag_ids: [202],
      },
    ];

    const conflicts: ConflictedVariable[] = [
      {
        variableTypeId: 50,
        variableTypeCode: "VELOCIDADE",
        variableTypeName: "Velocidade de Linha",
        details: [
          { sectionId: 1, sectionName: "FORNO", filterType: "MIN_MAX" },
          { sectionId: 2, sectionName: "ACABAMENTO", filterType: "SELECTION" },
        ],
      },
    ];

    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={vi.fn()}
        analysisTags={validTags}
        conflictedVariables={conflicts}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    // Banner de conflito presente com data-testid específico
    const warning = screen.getByTestId("conflict-warning-50");
    expect(warning).toBeInTheDocument();
    expect(warning).toHaveTextContent("Velocidade de Linha");
    expect(warning).toHaveTextContent("possui configurações de filtro incompatíveis");

    // Outros filtros válidos são renderizados normalmente
    expect(screen.queryByTestId("dynamic-filter-min-51")).toBeInTheDocument();
    expect(screen.getAllByText(/Pressão Hidráulica/).length).toBeGreaterThan(0);
  });

  it("9. Emite sectionTagMap na DataFilterRule ao aplicar filtro em 'Todas as seções'", () => {
    const onChange = vi.fn();
    const tagsWithMap: SectionAnalysisTag[] = [
      {
        id: 1,
        variable_type_id: 50,
        variable_type_code: "VELOCIDADE",
        variable_type_name: "Velocidade de Linha",
        filter_data_type: "REAL",
        filter_type: "MIN_MAX",
        pi_tag_id: 201,
        pi_tag_name: "FORNO.VEL",
        section_tag_map: { 1: 201, 2: 301 },
        pi_tag_ids: [201, 301],
      },
    ];

    render(
      <AdvancedFiltersPanel
        configuration={mockConfig}
        enabled={true}
        tagOptions={[]}
        summary={null}
        ruleResults={[]}
        hasData={true}
        initialExpanded={true}
        onChange={onChange}
        analysisTags={tagsWithMap}
        dynamicFilters={{}}
        onDynamicFilterChange={vi.fn()}
      />,
    );

    const minInput = screen.getByTestId("dynamic-filter-min-50");
    fireEvent.change(minInput, { target: { value: "50" } });

    expect(onChange).toHaveBeenCalled();
    const lastConfig: DataFilterConfiguration = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    const generatedRule = lastConfig.rules.find((r) => r.id === "section-filter:50");
    expect(generatedRule).toBeDefined();
    expect(generatedRule).toMatchObject({
      kind: "numeric",
      operator: "greaterThanOrEqual",
      value: 50,
      sectionTagMap: { 1: 201, 2: 301 },
    });
  });

  it("10. isFixedAnalysisTag identifica os quatro campos fixos e mantém tipos extras dinâmicos", () => {
    const tagLargura: SectionAnalysisTag = {
      id: 1,
      variable_type_id: 13,
      variable_type_code: "LARGURA",
      variable_type_name: "Largura Nominal",
      filter_data_type: "REAL",
      filter_type: "MIN_MAX",
      pi_tag_id: 104,
      pi_tag_name: "SEC1.WIDTH",
    };
    const tagEspessura: SectionAnalysisTag = {
      id: 2,
      variable_type_id: 14,
      variable_type_code: "ESPESSURA",
      variable_type_name: "Espessura Nominal",
      filter_data_type: "REAL",
      filter_type: "MIN_MAX",
      pi_tag_id: 105,
      pi_tag_name: "SEC1.THICK",
    };
    const tagUm: SectionAnalysisTag = {
      id: 3,
      variable_type_id: 15,
      variable_type_code: "UM",
      variable_type_name: "Unidade Metalúrgica",
      filter_data_type: "STRING",
      filter_type: "TEXT",
      pi_tag_id: 106,
      pi_tag_name: "SEC1.UM",
    };
    const tagSteelType: SectionAnalysisTag = {
      id: 4,
      variable_type_id: 16,
      variable_type_code: "TIPO DE ACO",
      variable_type_name: "Tipo de Aço",
      filter_data_type: "STRING",
      filter_type: "TEXT",
      pi_tag_id: 107,
      pi_tag_name: "SEC1.STEEL_TYPE",
    };
    const tagVelocidade: SectionAnalysisTag = {
      id: 4,
      variable_type_id: 50,
      variable_type_code: "VELOCIDADE",
      variable_type_name: "Velocidade de Linha",
      filter_data_type: "REAL",
      filter_type: "MIN_MAX",
      pi_tag_id: 201,
      pi_tag_name: "SEC1.VEL",
    };

    expect(isFixedAnalysisTag(tagLargura)).toBe(true);
    expect(isFixedAnalysisTag(tagEspessura)).toBe(true);
    expect(isFixedAnalysisTag(tagUm)).toBe(true);
    expect(isFixedAnalysisTag(tagSteelType)).toBe(true);
    expect(isFixedAnalysisTag(tagVelocidade)).toBe(false);
  });
});

