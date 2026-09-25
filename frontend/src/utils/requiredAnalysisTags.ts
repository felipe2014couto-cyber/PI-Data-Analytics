import { DataFilterRule, DynamicAnalysisFilter, SectionAnalysisTag, SeriesAssignment } from "../types";

export interface ResolveRequiredAnalysisTagsOptions {
  analysisTagIds: {
    width: number | null;
    um?: number | null;
    thickness: number | null;
    steelType: number | null;
  };
  extraAnalysisTags?: SectionAnalysisTag[];
  filtersEnabled: boolean;
  filterRules?: DataFilterRule[];
  dynamicFilters?: Record<number, DynamicAnalysisFilter>;
  sectionId?: number | null;
  seriesAssignments?: SeriesAssignment[];
  analysisContextTagIds?: Set<number>;
}

export function resolveRequiredAnalysisTagIds(
  options: ResolveRequiredAnalysisTagsOptions,
): number[] {
  const {
    analysisTagIds,
    extraAnalysisTags = [],
    filtersEnabled,
    filterRules = [],
    dynamicFilters = {},
    sectionId = null,
    seriesAssignments = [],
    analysisContextTagIds,
  } = options;

  const required = new Set<number>();

  // 1. Scatter roles: if any auxiliary tag is assigned an active scatter role ("x" or "y")
  for (const assignment of seriesAssignments) {
    if (assignment.scatterRole && assignment.scatterRole !== "none") {
      required.add(assignment.tagId);
    }
  }

  // 2. If filters are not globally enabled, auxiliary tags for filtering are not required
  if (!filtersEnabled) {
    if (analysisContextTagIds) {
      return Array.from(required).filter((id) => analysisContextTagIds.has(id));
    }
    return Array.from(required);
  }

  // 3. Process explicit filter rules
  for (const rule of filterRules) {
    if (!rule.enabled) continue;

    let isActive = false;

    if (rule.kind === "numeric") {
      const hasValue = rule.value !== null && rule.value !== undefined && Number.isFinite(rule.value);
      const hasSecond = rule.secondValue !== null && rule.secondValue !== undefined && Number.isFinite(rule.secondValue);
      isActive = hasValue || hasSecond;
    } else if (rule.kind === "text") {
      if (typeof rule.value === "string") {
        const trimmed = rule.value.trim();
        const upper = trimmed.toUpperCase();
        isActive = trimmed.length > 0 && upper !== "ALL" && upper !== "TODOS";
      }
    } else if (rule.kind === "excludeValue") {
      isActive = rule.value !== null && rule.value !== undefined && String(rule.value).trim().length > 0;
    }

    if (!isActive) continue;

    // Rule is active and restricts data
    if ("tagId" in rule && typeof rule.tagId === "number") {
      required.add(rule.tagId);
    }

    if ("sectionTagMap" in rule && rule.sectionTagMap) {
      if (sectionId && rule.sectionTagMap[sectionId]) {
        required.add(rule.sectionTagMap[sectionId]);
      } else if (!sectionId) {
        for (const tagId of Object.values(rule.sectionTagMap)) {
          required.add(tagId);
        }
      }
    }

    if (typeof rule.id === "string") {
      if (rule.id === "named-filter:steelModel" && analysisTagIds.steelType !== null) {
        required.add(analysisTagIds.steelType);
      } else if ((rule.id === "named-filter:widthMin" || rule.id === "named-filter:widthMax") && analysisTagIds.width !== null) {
        required.add(analysisTagIds.width);
      } else if ((rule.id === "named-filter:thicknessMin" || rule.id === "named-filter:thicknessMax") && analysisTagIds.thickness !== null) {
        required.add(analysisTagIds.thickness);
      } else if (rule.id === "named-filter:umCode" && analysisTagIds.um !== null && analysisTagIds.um !== undefined) {
        required.add(analysisTagIds.um);
      }
    }
  }

  // 4. Process dynamic analysis filters
  for (const [varTypeIdStr, f] of Object.entries(dynamicFilters)) {
    const varTypeId = Number(varTypeIdStr) || f.variable_type_id;
    let isActive = false;

    if (f.min !== null && f.min !== undefined && Number.isFinite(f.min)) {
      isActive = true;
    } else if (f.max !== null && f.max !== undefined && Number.isFinite(f.max)) {
      isActive = true;
    } else if (f.expression && typeof f.expression === "string") {
      const expr = f.expression.trim().toUpperCase();
      if (expr.length > 0 && expr !== "ALL" && expr !== "TODOS") {
        isActive = true;
      }
    } else if (f.value !== undefined && f.value !== null) {
      const val = String(f.value).trim().toUpperCase();
      if (val.length > 0 && val !== "ALL" && val !== "TODOS") {
        isActive = true;
      }
    }

    if (!isActive) continue;

    const matchingTags = extraAnalysisTags.filter((t) => t.variable_type_id === varTypeId);
    for (const tag of matchingTags) {
      if (sectionId && tag.section_tag_map?.[sectionId]) {
        required.add(tag.section_tag_map[sectionId]);
      } else if (tag.pi_tag_ids && tag.pi_tag_ids.length > 0) {
        for (const id of tag.pi_tag_ids) {
          required.add(id);
        }
      } else if (tag.pi_tag_id) {
        required.add(tag.pi_tag_id);
      }
    }
  }

  if (analysisContextTagIds) {
    return Array.from(required).filter((id) => analysisContextTagIds.has(id));
  }
  return Array.from(required);
}
