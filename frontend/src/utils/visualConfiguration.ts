import type {
  MetricConfiguration,
  SeriesAssignment,
  TimezoneId,
  VisualConfigurationDocument,
  VisualConfigurationSidebarState,
  VisualRulesState,
} from "../types";

export interface PersistablePageState {
  filters: VisualConfigurationSidebarState["filters"];
  selectedTagIds: number[];
  seriesAssignments: SeriesAssignment[];
  metricConfiguration: MetricConfiguration;
  comparison: VisualConfigurationSidebarState["comparison"];
  visualRules: VisualRulesState;
}

const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function buildVisualConfigurationDocument(state: PersistablePageState): VisualConfigurationDocument {
  return copy({
    schema_version: 1,
    visual_rules: state.visualRules,
    sidebar_state: {
      filters: state.filters,
      selectedTagIds: state.selectedTagIds,
      seriesAssignments: state.seriesAssignments,
      metricConfiguration: state.metricConfiguration,
      comparison: state.comparison,
    },
  });
}

export function normalizeVisualConfigurationDocument(
  document: VisualConfigurationDocument,
  defaults: PersistablePageState,
  timezone: TimezoneId,
): PersistablePageState {
  const saved = document.sidebar_state;
  if (!saved) {
    return copy({
      ...defaults,
      filters: { ...defaults.filters, mode: document.visual_rules.queryMode ?? defaults.filters.mode },
      visualRules: document.visual_rules,
    });
  }
  return copy({
    filters: {
      ...defaults.filters,
      ...saved.filters,
      timezone,
      timePeriod: saved.filters.timePeriod ?? defaults.filters.timePeriod,
      filterConfiguration: saved.filters.filterConfiguration ?? defaults.filters.filterConfiguration,
    },
    selectedTagIds: saved.selectedTagIds ?? defaults.selectedTagIds,
    seriesAssignments: saved.seriesAssignments ?? defaults.seriesAssignments,
    metricConfiguration: saved.metricConfiguration ?? defaults.metricConfiguration,
    comparison: { ...defaults.comparison, ...saved.comparison },
    visualRules: document.visual_rules,
  });
}
