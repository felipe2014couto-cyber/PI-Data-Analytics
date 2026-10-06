import type { ProductionUnitAnalysisResponse, ProductionUnitVariable } from "../../src/api";

export const UNIT_START = Date.parse("2026-10-02T10:00:00Z");
export const UNIT_DURATION = 5 * 60_000;

export function unitVariable(overrides: Partial<ProductionUnitVariable> = {}): ProductionUnitVariable {
  return {
    tag_id: 20, tag_name: "LFI_RB1_VEL_PROC_PV", display_name: "Velocidade", data_type: "NUMERIC", unit: "m/min",
    raw_sample_count: 2845, filtered_sample_count: 1329, sample_count: 1329, excluded_quality_count: 0,
    average: 28.4199002965, minimum: 25.003582, maximum: 31.1618557,
    first_timestamp: new Date(UNIT_START).toISOString(), last_timestamp: new Date(UNIT_START + UNIT_DURATION - 1).toISOString(),
    first_value: null, last_value: null, ...overrides,
  };
}

/** Synthetic segment times; statistics reproduce the values supplied by the user. */
export function unitResponse(variables = [unitVariable()]): ProductionUnitAnalysisResponse {
  return {
    section_id: 1, equipment_id: 1, um_tag_id: 29, um_tag_name: "LFI_RB1_CODIGO_UM_FORNO_ENT",
    start_time: new Date(UNIT_START).toISOString(), end_time: new Date(UNIT_START + 3 * UNIT_DURATION).toISOString(),
    segments: ["600304J2000B", "BOB L2 02/10/2026 06:14:26", "BOB L2 02/10/2026 06:26:20"].map((um, i) => ({
      segment_id: `unit-${i}`, um_value: um, status: "ASSIGNED",
      start_time: new Date(UNIT_START + i * UNIT_DURATION).toISOString(),
      end_time: new Date(UNIT_START + (i + 1) * UNIT_DURATION).toISOString(),
      duration_seconds: UNIT_DURATION / 1000, start_reason: "UM_TRANSITION", end_reason: i === 2 ? "QUERY_END" : "NEXT_UM",
      state_source_timestamp: new Date(UNIT_START + i * UNIT_DURATION).toISOString(),
      variables: variables.map((v) => ({
        ...v, ...(i === 1 ? { average: null, minimum: null, maximum: null, sample_count: 0, raw_sample_count: 1743, filtered_sample_count: 0 }
          : i === 2 ? { average: 31.0622640703 } : {}),
      })),
    })),
  };
}
