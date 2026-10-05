import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const analyze = vi.hoisted(() => vi.fn());
vi.mock("../src/api", () => ({ productionUnitsApi: { analyze } }));

import { ProductionUnitAnalysisPanel } from "../src/components/ProductionUnitAnalysisPanel";

const props = {
  sectionId: 5,
  tagIds: [20],
  startTime: "2026-10-02T09:11:57Z",
  endTime: "2026-10-02T09:59:21Z",
  filtersEnabled: false,
  filterConfiguration: { quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false }, rules: [] },
  analysisFilters: [],
  filtersActive: false,
};

describe("ProductionUnitAnalysisPanel", () => {
  beforeEach(() => analyze.mockReset());

  it("requests selected recorded tags and renders per-UM statistics", async () => {
    analyze.mockResolvedValueOnce({
      section_id: 5, equipment_id: 1, um_tag_id: 29, um_tag_name: "LFI_RB1_CODIGO_UM_FORNO_ENT",
      start_time: props.startTime, end_time: props.endTime,
      segments: [{
        segment_id: "29:2026-10-02T09:11:57Z", um_value: "UM_A", status: "ASSIGNED",
        start_time: props.startTime, end_time: "2026-10-02T09:36:07Z", duration_seconds: 1450,
        start_reason: "UM_TRANSITION", end_reason: "NEXT_UM", state_source_timestamp: props.startTime,
          variables: [{ tag_id: 20, tag_name: "LFI_RB1_VEL_PROC_PV", display_name: "Velocidade", data_type: "NUMERIC", unit: "m/min", sample_count: 2845, raw_sample_count: 2845, filtered_sample_count: 2845, excluded_quality_count: 0, average: 26.996152, minimum: 20.0436363, maximum: 36.0862732, first_timestamp: props.startTime, last_timestamp: props.endTime, first_value: null, last_value: null }],
      }],
    });
    render(<ProductionUnitAnalysisPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Calcular por UM" }));

    await waitFor(() => expect(analyze).toHaveBeenCalledWith({ section_id: 5, equipment_id: undefined, tag_ids: [20], start_time: props.startTime, end_time: props.endTime, filter_configuration: { filtersEnabled: false, quality: props.filterConfiguration.quality, rules: [] }, analysis_filters: [] }));
    expect(await screen.findByText(/UM_A/)).toBeInTheDocument();
    expect(screen.getByText(/2\.845 válidas/)).toBeInTheDocument();
    expect(screen.getByText("26,996152 m/min")).toBeInTheDocument();
  });

  it("sends current generic and dynamic filters instead of blocking the calculation", async () => {
    const numericRule = { id: "width", kind: "numeric" as const, enabled: true, tagId: 15, operator: "between" as const, value: 1200, secondValue: 1250 };
    const dynamicFilter = { variable_type_id: 7, min: 1.1, max: 1.3 };
    analyze.mockResolvedValueOnce({ section_id: 5, equipment_id: 1, um_tag_id: 29, um_tag_name: "UM", start_time: props.startTime, end_time: props.endTime, segments: [] });
    render(<ProductionUnitAnalysisPanel {...props} filtersEnabled filtersActive filterConfiguration={{ ...props.filterConfiguration, rules: [numericRule] }} analysisFilters={[dynamicFilter]} />);
    expect(screen.getByRole("button", { name: "Calcular por UM" })).toBeEnabled();
    expect(screen.getByText(/calculadas com os filtros enviados na consulta/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Calcular por UM" }));
    await waitFor(() => expect(analyze).toHaveBeenCalledWith(expect.objectContaining({
      filter_configuration: expect.objectContaining({ filtersEnabled: true, rules: [numericRule] }),
      analysis_filters: [dynamicFilter],
    })));
  });
});
