import { describe, expect, it } from "vitest";
import { resolveRequiredAnalysisTagIds } from "../src/utils/requiredAnalysisTags";
import { DataFilterRule, DynamicAnalysisFilter, SectionAnalysisTag, SeriesAssignment } from "../src/types";

describe("resolveRequiredAnalysisTagIds & queryTagIds composition", () => {
  const analysisTagIds = {
    width: 30,
    um: 29,
    thickness: 31,
    steelType: 80,
  };

  const dynamicTagString: SectionAnalysisTag = {
    variable_type_id: 101,
    variable_type_code: "STR_VAR",
    variable_type_name: "String Variable",
    filter_data_type: "STRING",
    pi_tag_id: 90,
  };

  const dynamicTagReal: SectionAnalysisTag = {
    variable_type_id: 102,
    variable_type_code: "REAL_VAR",
    variable_type_name: "Real Variable",
    filter_data_type: "REAL",
    pi_tag_id: 91,
  };

  const extraAnalysisTags: SectionAnalysisTag[] = [dynamicTagString, dynamicTagReal];

  const analysisContextTagIds = new Set<number>([30, 31, 80, 90, 91]);

  function buildQueryTagIds(selectedTagIds: number[], requiredTagIds: number[]): number[] {
    const set = new Set<number>(selectedTagIds);
    for (const id of requiredTagIds) {
      set.add(id);
    }
    return Array.from(set);
  }

  // 1. selected=[20,23], nenhum filtro -> [20,23]
  it("1. preserves selectedTagIds [20,23] and excludes auxiliary tags when no filter is active", () => {
    const selectedTagIds = [20, 23];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: false,
      filterRules: [],
      analysisContextTagIds,
    });
    expect(required).toEqual([]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23]);
  });

  // 2. selected=[20,23], steel configured but Modelo do Aço=Todos -> [20,23]
  it("2. does not include steelType tag when Modelo do Aço is 'Todos' or 'ALL'", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:steelModel",
        kind: "text",
        enabled: true,
        tagId: 80,
        operator: "equal",
        value: "Todos",
        caseSensitive: false,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toEqual([]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23]);
  });

  // 3. selected=[20,23], Modelo do Aço ativo -> [20,23,80]
  it("3. includes steelType tag (80) when Modelo do Aço has an active grade filter", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:steelModel",
        kind: "text",
        enabled: true,
        tagId: 80,
        operator: "equal",
        value: "SAE 1020",
        caseSensitive: false,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toContain(80);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 80]);
  });

  // 4. selected=[20,23], Espessura min ativa -> [20,23,31]
  it("4. includes thickness tag (31) when thickness minimum is active", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:thicknessMin",
        kind: "numeric",
        enabled: true,
        tagId: 31,
        operator: "greaterThanOrEqual",
        value: 2.5,
        secondValue: null,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toEqual([31]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 31]);
  });

  // 5. selected=[20,23], Largura ativa -> [20,23,30]
  it("5. includes width tag (30) when width filter is active", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:widthMin",
        kind: "numeric",
        enabled: true,
        tagId: 30,
        operator: "greaterThanOrEqual",
        value: 1200,
        secondValue: null,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toEqual([30]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 30]);
  });

  // 6. selected=[20,23], Espessura + Aço -> [20,23,31,80]
  it("6. includes both thickness and steel tags when both filters are active", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:thicknessMin",
        kind: "numeric",
        enabled: true,
        tagId: 31,
        operator: "greaterThanOrEqual",
        value: 2.5,
        secondValue: null,
      },
      {
        id: "named-filter:steelModel",
        kind: "text",
        enabled: true,
        tagId: 80,
        operator: "equal",
        value: "HC340",
        caseSensitive: false,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toContain(31);
    expect(required).toContain(80);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 31, 80]);
  });

  // 7. selected=[20,23,80], nenhum filtro -> [20,23,80]
  it("7. includes tag 80 when explicitly selected by the user, even with no filters active", () => {
    const selectedTagIds = [20, 23, 80];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: false,
      filterRules: [],
      analysisContextTagIds,
    });
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 80]);
  });

  // 8. tag dinâmica STRING configurada mas ALL -> não incluir
  it("8. does not include dynamic STRING tag when value/expression is ALL", () => {
    const selectedTagIds = [20, 23];
    const dynamicFilters: Record<number, DynamicAnalysisFilter> = {
      101: {
        variable_type_id: 101,
        expression: "ALL",
      },
    };
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules: [],
      dynamicFilters,
      analysisContextTagIds,
    });
    expect(required).toEqual([]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23]);
  });

  // 9. tag dinâmica STRING com expressão -> incluir
  it("9. includes dynamic STRING tag when expression is non-empty and not ALL", () => {
    const selectedTagIds = [20, 23];
    const dynamicFilters: Record<number, DynamicAnalysisFilter> = {
      101: {
        variable_type_id: 101,
        expression: "GRADE_A",
      },
    };
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules: [],
      dynamicFilters,
      analysisContextTagIds,
    });
    expect(required).toContain(90);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 90]);
  });

  // 10. tag dinâmica REAL sem limites -> não incluir
  it("10. does not include dynamic REAL tag when min and max are null", () => {
    const selectedTagIds = [20, 23];
    const dynamicFilters: Record<number, DynamicAnalysisFilter> = {
      102: {
        variable_type_id: 102,
        min: null,
        max: null,
      },
    };
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules: [],
      dynamicFilters,
      analysisContextTagIds,
    });
    expect(required).toEqual([]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23]);
  });

  // 11. tag dinâmica REAL com min/max -> incluir
  it("11. includes dynamic REAL tag when min or max has a numeric value", () => {
    const selectedTagIds = [20, 23];
    const dynamicFilters: Record<number, DynamicAnalysisFilter> = {
      102: {
        variable_type_id: 102,
        min: 15.5,
        max: null,
      },
    };
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: true,
      filterRules: [],
      dynamicFilters,
      analysisContextTagIds,
    });
    expect(required).toContain(91);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 91]);
  });

  // 12. scatter role utilizando auxiliar -> incluir
  it("12. includes auxiliary tag when assigned a scatter role (x or y)", () => {
    const selectedTagIds = [20, 23];
    const seriesAssignments: SeriesAssignment[] = [
      {
        tagId: 30,
        order: 1,
        lineAxis: "primary",
        scatterRole: "x",
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: false,
      filterRules: [],
      seriesAssignments,
      analysisContextTagIds,
    });
    expect(required).toContain(30);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23, 30]);
  });

  it("does not include any auxiliary tags if global filters toggle is false, even if rules are present", () => {
    const selectedTagIds = [20, 23];
    const filterRules: DataFilterRule[] = [
      {
        id: "named-filter:steelModel",
        kind: "text",
        enabled: true,
        tagId: 80,
        operator: "equal",
        value: "SAE 1020",
        caseSensitive: false,
      },
    ];
    const required = resolveRequiredAnalysisTagIds({
      analysisTagIds,
      extraAnalysisTags,
      filtersEnabled: false, // toggle OFF
      filterRules,
      analysisContextTagIds,
    });
    expect(required).toEqual([]);
    expect(buildQueryTagIds(selectedTagIds, required)).toEqual([20, 23]);
  });
});
