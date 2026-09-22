import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AdvancedFiltersPanel } from "../src/components/AdvancedFiltersPanel";
import type { DataFilterConfiguration, SectionAnalysisTag } from "../src/types";

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
    pi_tag_id: 101,
    pi_tag_name: "SEC1.CURRENT",
  },
  {
    id: 2,
    variable_type_id: 11,
    variable_type_code: "VALVULA_ON",
    variable_type_name: "Status Válvula",
    filter_data_type: "DIGITAL",
    pi_tag_id: 102,
    pi_tag_name: "SEC1.VALVE",
  },
  {
    id: 3,
    variable_type_id: 12,
    variable_type_code: "LOTE_PROD",
    variable_type_name: "Lote de Produção",
    filter_data_type: "STRING",
    pi_tag_id: 103,
    pi_tag_name: "SEC1.BATCH",
  },
  // Fixed variable types that must NOT be duplicated in dynamic section
  {
    id: 4,
    variable_type_id: 13,
    variable_type_code: "LARGURA",
    variable_type_name: "Largura Bobina",
    filter_data_type: "REAL",
    pi_tag_id: 104,
    pi_tag_name: "SEC1.WIDTH",
  },
  {
    id: 5,
    variable_type_id: 14,
    variable_type_code: "UM",
    variable_type_name: "Unidade Metalúrgica",
    filter_data_type: "STRING",
    pi_tag_id: 105,
    pi_tag_name: "SEC1.UM",
  },
  {
    id: 6,
    variable_type_id: 15,
    variable_type_code: "ESPESSURA",
    variable_type_name: "Espessura Nominal",
    filter_data_type: "REAL",
    pi_tag_id: 106,
    pi_tag_name: "SEC1.THICK",
  },
];

describe("AdvancedFiltersPanel Dynamic Filters", () => {
  it("renders dynamic section for non-fixed section analysis tags", () => {
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

    expect(screen.getByTestId("named-filter-group-section-variables")).toBeInTheDocument();
    expect(screen.getByText("Variáveis da Seção")).toBeInTheDocument();

    // Check that non-fixed tags are rendered
    expect(screen.getByText(/Corrente Elétrica/)).toBeInTheDocument();
    expect(screen.getByText(/Status Válvula/)).toBeInTheDocument();
    expect(screen.getByText(/Lote de Produção/)).toBeInTheDocument();

    // Check controls for REAL
    expect(screen.getByTestId("dynamic-filter-min-10")).toBeInTheDocument();
    expect(screen.getByTestId("dynamic-filter-max-10")).toBeInTheDocument();

    // Check control for DIGITAL
    expect(screen.getByTestId("dynamic-filter-digital-11")).toBeInTheDocument();

    // Check control for STRING
    expect(screen.getByTestId("dynamic-filter-string-12")).toBeInTheDocument();
    expect(screen.getByTestId("info-popover-12")).toBeInTheDocument();

    // Fixed tags must NOT be present in dynamic section
    expect(screen.queryByTestId("dynamic-filter-min-13")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-filter-string-14")).not.toBeInTheDocument();
    expect(screen.queryByTestId("dynamic-filter-min-15")).not.toBeInTheDocument();
  });

  it("triggers onDynamicFilterChange on REAL input", () => {
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
  });

  it("triggers onDynamicFilterChange on DIGITAL select", () => {
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
});
