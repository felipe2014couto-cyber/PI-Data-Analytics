import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";

import { equipmentsApi, piApi, sectionsApi, timeSeriesApi, variableTypesApi } from "../api";
import { ApiError } from "../api/http";
import type {
  DataFilterConfiguration,
  Equipment,
  AnalysisModel,
  PiHealth,
  PiTag,
  Section,
  TimePeriod,
  TimeSeries,
  TimeSeriesMode,
  ComparisonType,
  SeriesAssignment,
  SeriesAxis,
  MetricConfiguration,
  VariableType,
  VisualizationType,
  VisualRulesState,
  VisualConfigurationDocument,
} from "../types";
import { DataFiltersPanel } from "../components/DataFiltersPanel";
import { SeriesAssignmentsPanel, type SeriesConfigurationTag } from "../components/SeriesAssignmentsPanel";
import { QuerySummary } from "../components/QuerySummary";
import { ComparisonPanel } from "../components/ComparisonPanel";
import { TimeSeriesChart } from "../components/TimeSeriesChart";
import { HistogramChart } from "../components/HistogramChart";
import { BoxPlotChart } from "../components/BoxPlotChart";
import { ScatterPlotChart } from "../components/ScatterPlotChart";
import { LatestValuesBarChart } from "../components/LatestValuesBarChart";
import { SingleValueCards } from "../components/SingleValueCards";
import { MetricConfigurationPanel } from "../components/MetricConfigurationPanel";
import { MetricResults } from "../components/MetricResults";
import { VisualRulesPanel, type VisualSeriesOption } from "../components/VisualRulesPanel";
import { VisualConfigurationsPanel } from "../components/VisualConfigurationsPanel";
import { PageHeader } from "../components/PageHeader";
import { AdvancedFiltersPanel } from "../components/AdvancedFiltersPanel";
import { applyLineAssignments, buildChartDataGroups, resolveVisualization } from "../utils/chartData";
import { downloadTimeSeriesCsv, buildCsvFilename, buildTimeSeriesCsv, downloadBlob } from "../utils/csv";
import { applyDataFilters } from "../utils/dataFilters";
import { groupSeriesByUnit } from "../utils/statistics";
import { alignSeriesByTimestamp, groupLatestValuesByUnit } from "../utils/comparison";
import { assignmentIdentity } from "../utils/seriesAssignments";
import { buildTagOption, type TagOption } from "../components/TagMultiSelect";
import {
  APPLICATION_TIMEZONE,
  formatResolvedTimePeriod,
  resolveTimePeriod,
  type ResolvedTimePeriod,
} from "../utils/timePeriod";
import {
  initializeScatterAssignments,
  moveAssignment,
  reconcileAssignments,
  resolveSeriesOrder,
  setLineAxis,
  setScatterAxis,
  validateAssignments,
  type AssignmentTag,
} from "../utils/seriesAssignments";
import { calculateMetricResults } from "../utils/analysisMetrics";
import { buildVisualConfigurationDocument, normalizeVisualConfigurationDocument, type PersistablePageState } from "../utils/visualConfiguration";

const DEFAULT_MAX_COUNT = 2000;

function _generateQueryId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    // crypto.randomUUID may throw in non-secure contexts (HTTP)
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

interface FiltersState {
  analysisModel: AnalysisModel;
  equipmentId: number | null;
  sectionId: number | null;
  variableTypeId: number | null;
  timePeriod: TimePeriod;
  timezone: "America/Sao_Paulo";
  mode: TimeSeriesMode;
  interval: string;
  maxCount: number;
  resolutionMode: string;
  targetPointsPerTag: number;
  ignoreBadQuality: boolean;
  visualization: VisualizationType;
  filtersEnabled: boolean;
  filterConfiguration: DataFilterConfiguration;
}

const INITIAL_FILTER_CONFIG: DataFilterConfiguration = {
  quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

const INITIAL_FILTERS: FiltersState = {
  analysisModel: "unit",
  equipmentId: null,
  sectionId: null,
  variableTypeId: null,
  timePeriod: { kind: "preset", preset: "PT1H" },
  timezone: APPLICATION_TIMEZONE,
  mode: "interpolated",
  interval: "1m",
  maxCount: DEFAULT_MAX_COUNT,
  resolutionMode: "automatic",
  targetPointsPerTag: 10000,
  ignoreBadQuality: true,
  visualization: "automatic",
  filtersEnabled: true,
  filterConfiguration: INITIAL_FILTER_CONFIG,
};

interface QueryState {
  timeSeries: TimeSeries | null;
  loading: boolean;
  errorMessage: string | null;
  partial: boolean;
  errorPerSeries: Array<{ tag_id: number; code: string; message: string }>;
  startedAt: number | null;
  finishedAt: number | null;
  resolvedPeriod: ResolvedTimePeriod | null;
}

const INITIAL_QUERY: QueryState = {
  timeSeries: null,
  loading: false,
  errorMessage: null,
  partial: false,
  errorPerSeries: [],
  startedAt: null,
  finishedAt: null,
  resolvedPeriod: null,
};

interface ComparisonState {
  type: ComparisonType | "disabled";
  contextBEquipmentId: number | null;
  contextBCategoryId: number | null;
  contextBTagIds: number[];
  contextBStart: string;
  contextBEnd: string;
}

const INITIAL_COMPARISON: ComparisonState = {
  type: "disabled",
  contextBEquipmentId: null,
  contextBCategoryId: null,
  contextBTagIds: [],
  contextBStart: "",
  contextBEnd: "",
};

const INITIAL_VISUAL_RULES: VisualRulesState = { enabled: false, selectedSeriesInstanceId: null, bySeries: {} };

function syncQualityConfig(
  prev: FiltersState,
  ignoreBadQuality: boolean,
): FiltersState {
  return {
    ...prev,
    ignoreBadQuality,
    filterConfiguration: {
      ...prev.filterConfiguration,
      quality: {
        ...prev.filterConfiguration.quality,
        excludeBad: ignoreBadQuality,
      },
    },
  };
}

export function DataVisualizationPage() {
  const [filters, setFilters] = useState<FiltersState>(INITIAL_FILTERS);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [seriesAssignments, setSeriesAssignments] = useState<SeriesAssignment[]>([]);
  const [metricConfiguration, setMetricConfiguration] = useState<MetricConfiguration>({ kind: "none" });
  const [query, setQuery] = useState<QueryState>(INITIAL_QUERY);
  const [comparison, setComparison] = useState<ComparisonState>(INITIAL_COMPARISON);
  const [visualRules, setVisualRules] = useState<VisualRulesState>(INITIAL_VISUAL_RULES);

  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [variableTypes, setVariableTypes] = useState<VariableType[]>([]);
  const [tags, setTags] = useState<PiTag[]>([]);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupsLoaded, setLookupsLoaded] = useState(false);

  const [piHealth, setPiHealth] = useState<PiHealth | null>(null);
  const [piChecking, setPiChecking] = useState(false);
  const [csvCompleteLoading, setCsvCompleteLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);
  const queryIdRef = useRef<string | null>(null);
  const cancelledQueryIdsRef = useRef<Set<string>>(new Set());
  const scatterInitializedRef = useRef(false);

  const loadLookups = useCallback(async (signal?: AbortSignal) => {
    try {
      const [eq, sec, vt] = await Promise.all([
        equipmentsApi.list({ page: 1, page_size: 200 }),
        sectionsApi.list({ page: 1, page_size: 200 }),
        variableTypesApi.list({ page: 1, page_size: 200 }),
      ]);
      if (signal?.aborted) return;
      setEquipments(eq.items ?? []);
      setSections(sec.items ?? []);
      setVariableTypes(vt.items ?? []);
      // Buscar tags via endpoint dedicado com paginacao ate o limite da POC
      const tagList: PiTag[] = [];
      let page = 1;
      while (true) {
        const resp = await (
          await import("../api")
        ).piTagsApi.list({ page, page_size: 200 });
        if (signal?.aborted) return;
        tagList.push(...(resp.items ?? []));
        if ((resp.items ?? []).length === 0 || page >= (resp.pages ?? 0)) break;
        page += 1;
      }
      setTags(tagList.filter((tag) => tag.active));
      setLookupsLoaded(true);
    } catch (err) {
      if (!signal?.aborted) {
        setLookupError(err instanceof Error ? err.message : "Falha ao carregar catalogos.");
      }
    }
  }, []);

  const loadPiHealth = useCallback(async () => {
    setPiChecking(true);
    try {
      const data = await piApi.health();
      setPiHealth(data);
    } catch (err) {
      setPiHealth({
        status: "unavailable",
        base_url: null,
        data_server: null,
        response_time_ms: null,
        message: err instanceof Error ? err.message : "Falha ao consultar /api/pi/health",
        error_code: "PI_HEALTH_FAILED",
      });
    } finally {
      setPiChecking(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadLookups(controller.signal);
    void loadPiHealth();
    return () => controller.abort();
  }, [loadLookups, loadPiHealth]);

  const equipmentMap = useMemo(() => new Map(equipments.map((e) => [e.id, e])), [equipments]);
  const sectionMap = useMemo(() => new Map(sections.map((s) => [s.id, s])), [sections]);
  const variableTypeMap = useMemo(() => new Map(variableTypes.map((v) => [v.id, v])), [variableTypes]);

  // As tags vinculadas à seção/equipamento são séries auxiliares: entram na
  // consulta para que os filtros de largura, UM e espessura possam mascarar
  // as demais séries, mas não aparecem como curvas adicionais no gráfico.
  const analysisTagIds = useMemo(() => {
    const candidateSections = sections.filter((section) => {
      if (filters.sectionId) return section.id === filters.sectionId;
      return filters.equipmentId !== null && section.equipment_id === filters.equipmentId;
    });
    const resolveUniqueTagId = (tagIds: Array<number | null>) => {
      const uniqueTagIds = Array.from(new Set(
        tagIds.filter((tagId): tagId is number => tagId !== null && tags.some((tag) => tag.id === tagId)),
      ));
      return uniqueTagIds.length === 1 ? uniqueTagIds[0] : null;
    };

    return {
      width: resolveUniqueTagId(candidateSections.map((section) => section.width_tag_id)),
      um: resolveUniqueTagId(candidateSections.map((section) => section.um_tag_id)),
      thickness: resolveUniqueTagId(candidateSections.map((section) => section.thickness_tag_id)),
    };
  }, [filters.equipmentId, filters.sectionId, sections, tags]);

  const analysisContextTagIds = useMemo(
    () => new Set(Object.values(analysisTagIds).filter((tagId): tagId is number => tagId !== null)),
    [analysisTagIds],
  );
  const analysisHiddenTagIds = useMemo(
    () => new Set(
      Array.from(analysisContextTagIds).filter((tagId) => !selectedTagIds.includes(tagId)),
    ),
    [analysisContextTagIds, selectedTagIds],
  );
  const queryTagIds = useMemo(
    () => Array.from(new Set([...selectedTagIds, ...analysisContextTagIds])),
    [analysisContextTagIds, selectedTagIds],
  );

  const tagOptions: TagOption[] = useMemo(() => {
    return tags
      .filter((tag) => tag.active)
      .map((tag) => buildTagOption(
        tag,
        equipmentMap.get(tag.equipment_id),
        tag.section_id === null ? undefined : sectionMap.get(tag.section_id),
        variableTypeMap.get(tag.variable_type_id),
      ));
  }, [tags, equipmentMap, sectionMap, variableTypeMap]);

  const filteredTagOptions = useMemo(() => {
    return tagOptions.filter((option) => {
      if (filters.equipmentId) {
        const equipment = equipmentMap.get(filters.equipmentId);
        if (!equipment || option.equipmentCode !== equipment.code) return false;
      }
      if (filters.sectionId) {
        const section = sectionMap.get(filters.sectionId);
        if (!section || (option.sectionId !== null && option.sectionId !== filters.sectionId)) return false;
      }
      if (filters.variableTypeId) {
        const variableType = variableTypeMap.get(filters.variableTypeId);
        if (!variableType || option.variableTypeCode !== variableType.code) return false;
      }
      return true;
    });
  }, [tagOptions, filters, equipmentMap, sectionMap, variableTypeMap]);

  // Whenever equipment or section changes, prune selectedTagIds that no longer match.
  useEffect(() => {
    if (!lookupsLoaded) return;
    const allowed = new Set(filteredTagOptions.map((o) => o.id));
    setSelectedTagIds((prev) => {
      const next = prev.filter((id) => allowed.has(id));
      return next.length === prev.length ? prev : next;
    });
  }, [filteredTagOptions, lookupsLoaded]);

  const equipmentOptions = useMemo(
    () => equipments.map((eq) => ({ id: eq.id, code: eq.code, name: eq.name })),
    [equipments],
  );
  const sectionOptions = useMemo(
    () => sections.map((s) => ({ id: s.id, code: s.code, name: s.name, equipmentId: s.equipment_id })),
    [sections],
  );
  const variableTypeOptions = useMemo(
    () => variableTypes.map((v) => ({ id: v.id, code: v.code, name: v.name })),
    [variableTypes],
  );

  const periodPreview = useMemo(() => {
    const now = new Date();
    try {
      const resolved = resolveTimePeriod(filters.timePeriod, now);
      return { resolved, error: null };
    } catch (error) {
      return {
        resolved: null,
        error: error instanceof Error ? error.message : "Período inválido.",
      };
    }
  }, [filters.timePeriod]);

  const selectedAssignmentTags = useMemo<AssignmentTag[]>(() => {
    const visibleSeries = query.timeSeries?.series.filter((series) => !analysisHiddenTagIds.has(series.tag_id));
    if (visibleSeries?.some((series) => series.series_instance_id)) {
      return visibleSeries.map((series) => ({
        tagId: series.tag_id,
        seriesInstanceId: series.series_instance_id ?? undefined,
        unit: series.unit,
        numeric: series.points.some((point) => typeof point.value === "number" && Number.isFinite(point.value)),
      }));
    }
    const tagsById = new Map(tags.map((tag) => [tag.id, tag]));
    return selectedTagIds.flatMap((tagId) => {
      const tag = tagsById.get(tagId);
      return tag ? [{ tagId, unit: tag.engineering_unit, numeric: tag.data_type === "NUMERIC" }] : [];
    });
  }, [analysisHiddenTagIds, selectedTagIds, tags, query.timeSeries]);

  useEffect(() => {
    if (!lookupsLoaded) return;
    setSeriesAssignments((current) => reconcileAssignments(current, selectedAssignmentTags));
  }, [selectedAssignmentTags, lookupsLoaded]);

  const orderedTimeSeries = useMemo(() => {
    if (!query.timeSeries) return null;
    return {
      ...query.timeSeries,
      series: resolveSeriesOrder(query.timeSeries.series, seriesAssignments, (series) => series.tag_id, (series) => series.series_instance_id ?? undefined),
    };
  }, [query.timeSeries, seriesAssignments]);

  const filterResult = useMemo(() => {
    if (!filters.filtersEnabled || !orderedTimeSeries || !query.timeSeries) return null;
    const visibleSeriesKeys = new Set(
      orderedTimeSeries.series
        .filter((series) => !analysisHiddenTagIds.has(series.tag_id))
        .map((series) => series.series_instance_id ?? `tag:${series.tag_id}`),
    );
    const crossSeriesRuleIds = new Set(
      filters.filterConfiguration.rules
        .filter((rule) => rule.enabled && "tagId" in rule && analysisContextTagIds.has(rule.tagId))
        .map((rule) => rule.id),
    );
    return applyDataFilters(orderedTimeSeries, filters.filterConfiguration, {
      summarySeriesKeys: visibleSeriesKeys,
      crossSeriesRuleIds,
    });
  }, [analysisContextTagIds, analysisHiddenTagIds, filters.filtersEnabled, orderedTimeSeries, query.timeSeries, filters.filterConfiguration]);

  const filteredTimeSeries: TimeSeries | null = useMemo(() => {
    const source = filterResult?.filteredTimeSeries ?? orderedTimeSeries;
    if (!source) return null;
    return {
      ...source,
      series: source.series.filter((series) => !analysisHiddenTagIds.has(series.tag_id)),
    };
  }, [analysisHiddenTagIds, filterResult, orderedTimeSeries]);

  const chartTimeSeries: TimeSeries | null = useMemo(() => {
    if (!filteredTimeSeries || !filterResult || filterResult.summary.removedPoints === 0) {
      return filteredTimeSeries;
    }
    const filteredBySeries = new Map(
      filteredTimeSeries.series.map((series) => [
        series.series_instance_id ?? `tag:${series.tag_id}`,
        new Map(series.points.map((point) => [point.timestamp, point])),
      ]),
    );
    return {
      ...filteredTimeSeries,
      series: filteredTimeSeries.series.map((series) => {
        const seriesKey = series.series_instance_id ?? `tag:${series.tag_id}`;
        const keptPoints = filteredBySeries.get(seriesKey);
        const originalSeries = orderedTimeSeries?.series.find(
          (candidate) => (candidate.series_instance_id ?? `tag:${candidate.tag_id}`) === seriesKey,
        );
        if (!keptPoints || !originalSeries) return series;
        return {
          ...series,
          points: originalSeries.points.map((point) =>
            keptPoints.has(point.timestamp)
              ? keptPoints.get(point.timestamp)!
              : { ...point, value: null, filtered_out: true },
          ),
        };
      }),
    };
  }, [filterResult, filteredTimeSeries, orderedTimeSeries]);

  const chartGroups = useMemo(() => {
    if (!chartTimeSeries) return null;
    return buildChartDataGroups(chartTimeSeries, {
      ignoreBadQuality: false,
    });
  }, [chartTimeSeries]);
  const chart = chartGroups?.summary ?? null;
  const visualizationPlan = useMemo(
    () => (chartGroups ? resolveVisualization(chartGroups, filters.visualization) : null),
    [chartGroups, filters.visualization],
  );
  const numericChartRaw = visualizationPlan?.numeric ?? null;
  const numericChart = useMemo(
    () => applyLineAssignments(numericChartRaw, seriesAssignments),
    [numericChartRaw, seriesAssignments],
  );
  const textualChart = visualizationPlan?.textual ?? null;
  const incompatibleSeries = visualizationPlan?.incompatibleSeries ?? [];
  const excessTextualSeries = visualizationPlan?.excessTextualSeries ?? [];
  const mixedSeries = chartGroups?.mixedSeries ?? [];

  const actualNumericIds = useMemo(
    () => new Set(chartGroups?.numeric?.series.map((series) => series.seriesInstanceId ?? `tag:${series.tagId}`) ?? []),
    [chartGroups],
  );
  const effectiveAssignmentTags = useMemo<AssignmentTag[]>(
    () => selectedAssignmentTags.map((tag) => ({
      ...tag,
      numeric: chartGroups ? actualNumericIds.has(assignmentIdentity(tag)) : tag.numeric,
    })),
    [selectedAssignmentTags, chartGroups, actualNumericIds],
  );
  const assignmentValidation = useMemo(
    () => validateAssignments(seriesAssignments, effectiveAssignmentTags, filters.visualization === "scatter"),
    [seriesAssignments, effectiveAssignmentTags, filters.visualization],
  );

  useEffect(() => {
    if (scatterInitializedRef.current || actualNumericIds.size < 2) return;
    scatterInitializedRef.current = true;
    setSeriesAssignments((current) => initializeScatterAssignments(current, current.filter((item) => actualNumericIds.has(assignmentIdentity(item))).map((item) => item.tagId)));
  }, [actualNumericIds]);
  const showBothCharts = numericChart !== null && textualChart !== null;
  const boxPlotGroups = useMemo(
    () => groupSeriesByUnit(numericChart?.series ?? []),
    [numericChart],
  );
  const originalNumericSeries = useMemo(() => {
    if (!filteredTimeSeries) return [];
    return filteredTimeSeries.series.filter((series) => actualNumericIds.has(series.series_instance_id ?? `tag:${series.tag_id}`));
  }, [filteredTimeSeries, actualNumericIds]);

  const metricNumericSeries = useMemo(
    () => filteredTimeSeries?.series.filter((entry) =>
      entry.points.some((point) =>
        typeof point.value === "number" && Number.isFinite(point.value),
      ),
    ) ?? [],
    [filteredTimeSeries],
  );

  const metricSeriesOptions = useMemo(() => {
    if (filteredTimeSeries) return metricNumericSeries;
    const selected = new Set(selectedTagIds);
    return tags.filter((tag) => selected.has(tag.id) && tag.data_type === "NUMERIC").map((tag) => ({
      tag_id: tag.id, tag_name: tag.pi_tag_name, display_name: tag.display_name,
      equipment: null, section: null, variable_type: null, unit: tag.engineering_unit, points: [],
    }));
  }, [filteredTimeSeries, metricNumericSeries, selectedTagIds, tags]);
  const metricResults = useMemo(
    () => calculateMetricResults(metricNumericSeries, metricConfiguration, false),
    [metricNumericSeries, metricConfiguration],
  );

  const scatterXSeries = useMemo(() => {
    const assignment = seriesAssignments.find((item) => item.scatterRole === "x");
    return assignment ? originalNumericSeries.find((series) => (series.series_instance_id ?? `tag:${series.tag_id}`) === assignmentIdentity(assignment)) ?? null : null;
  }, [seriesAssignments, originalNumericSeries]);
  const scatterYSeries = useMemo(() => {
    const assignment = seriesAssignments.find((item) => item.scatterRole === "y");
    return assignment ? originalNumericSeries.find((series) => (series.series_instance_id ?? `tag:${series.tag_id}`) === assignmentIdentity(assignment)) ?? null : null;
  }, [seriesAssignments, originalNumericSeries]);
  const latestValueGroups = useMemo(
    () => groupLatestValuesByUnit(originalNumericSeries, false),
    [originalNumericSeries],
  );
  const scatterPairs = useMemo(
    () =>
      scatterXSeries && scatterYSeries
        ? alignSeriesByTimestamp(
            scatterXSeries,
            scatterYSeries,
            false,
          )
        : [],
    [scatterXSeries, scatterYSeries],
  );

  const seriesConfigurationTags = useMemo<SeriesConfigurationTag[]>(() => {
    const visibleSeries = query.timeSeries?.series.filter((series) => !analysisHiddenTagIds.has(series.tag_id));
    if (visibleSeries?.some((series) => series.series_instance_id)) {
      return visibleSeries.map((series) => ({
        tagId: series.tag_id,
        seriesInstanceId: series.series_instance_id ?? undefined,
        displayName: series.display_name,
        tagName: series.tag_name,
        unit: series.unit,
        numeric: series.points.some((point) => typeof point.value === "number" && Number.isFinite(point.value)),
      }));
    }
    const optionsById = new Map(tagOptions.map((option) => [option.id, option]));
    return effectiveAssignmentTags.flatMap((tag) => {
      const option = optionsById.get(tag.tagId);
      return option ? [{ tagId: tag.tagId, displayName: option.displayName, tagName: option.tagName, unit: tag.unit, numeric: tag.numeric }] : [];
    });
  }, [analysisHiddenTagIds, tagOptions, effectiveAssignmentTags, query.timeSeries]);

  const visualSeriesOptions = useMemo<VisualSeriesOption[]>(() => {
    if (query.timeSeries) return query.timeSeries.series
      .filter((series) => !analysisHiddenTagIds.has(series.tag_id))
      .map((series) => ({
      seriesInstanceId: series.series_instance_id ?? `tag:${series.tag_id}`,
      label: `${series.display_name} (${series.tag_name})`,
      numeric: series.points.some((point) => typeof point.value === "number" && Number.isFinite(point.value)),
    }));
    const selected = new Set(selectedTagIds);
    return tags.filter((tag) => selected.has(tag.id)).map((tag) => ({
      seriesInstanceId: `tag:${tag.id}`,
      label: `${tag.display_name} (${tag.pi_tag_name})`,
      numeric: tag.data_type === "NUMERIC",
    }));
  }, [analysisHiddenTagIds, query.timeSeries, selectedTagIds, tags]);

  const advancedFilterTagOptions = useMemo(() => {
    const visibleOptions = selectedAssignmentTags.map((tag) => {
      const piTag = tags.find((item) => item.id === tag.tagId);
      const resultSeries = query.timeSeries?.series.find((series) =>
        (series.series_instance_id ?? `tag:${series.tag_id}`) === assignmentIdentity(tag),
      );
      return {
        id: tag.tagId,
        seriesInstanceId: tag.seriesInstanceId,
        displayName: resultSeries?.display_name ?? piTag?.display_name ?? `Tag ${tag.tagId}`,
        tagName: resultSeries?.tag_name ?? piTag?.pi_tag_name ?? "",
        dataType: piTag?.data_type ?? "NUMERIC",
      };
    });
    const linkedOptions = (Object.entries(analysisTagIds) as Array<["width" | "um" | "thickness", number | null]>)
      .filter((entry): entry is ["width" | "um" | "thickness", number] => entry[1] !== null)
      .map(([analysisRole, tagId]) => {
        const piTag = tags.find((tag) => tag.id === tagId);
        const resultSeries = query.timeSeries?.series.find((series) => series.tag_id === tagId);
        if (!piTag && !resultSeries) return null;
        return {
          id: tagId,
          analysisRole,
          seriesInstanceId: resultSeries?.series_instance_id ?? undefined,
          displayName: resultSeries?.display_name ?? piTag?.display_name ?? `Tag ${tagId}`,
          tagName: resultSeries?.tag_name ?? piTag?.pi_tag_name ?? "",
          dataType: piTag?.data_type ?? "NUMERIC",
        };
      })
      .filter((option): option is NonNullable<typeof option> => option !== null);
    if (linkedOptions.length === 0) return visibleOptions;
    const linkedIds = new Set(linkedOptions.map((option) => option.id));
    return [
      ...linkedOptions,
      ...visibleOptions.filter((option) => !linkedIds.has(option.id)),
    ];
  }, [analysisTagIds, query.timeSeries, selectedAssignmentTags, tags]);

  const handleEquipmentChange = (id: number | null) => {
    setFilters((prev) => ({ ...prev, equipmentId: id, sectionId: null }));
  };

  const handleSectionChange = (id: number | null) => {
    setFilters((prev) => ({ ...prev, sectionId: id }));
  };

  const handleVariableTypeChange = (id: number | null) => {
    setFilters((prev) => ({ ...prev, variableTypeId: id }));
  };

  const handleTagsChange = (ids: number[]) => {
    setSelectedTagIds(ids);
  };

  const handleFilterConfigurationChange = (filterConfiguration: DataFilterConfiguration) => {
    setFilters((prev) => ({
      ...prev,
      filterConfiguration,
      ignoreBadQuality: filterConfiguration.quality.excludeBad,
    }));
  };

  const handleCancel = () => {
    const qid = queryIdRef.current;
    if (!qid) return;
    if (cancelledQueryIdsRef.current.has(qid)) return;
    cancelledQueryIdsRef.current.add(qid);
    setCancelling(true);
    abortRef.current?.abort();
    timeSeriesApi.cancelQuery(qid).catch(() => {});
  };

  const handleClear = () => {
    abortRef.current?.abort();
    queryIdRef.current = null;
    setFilters(INITIAL_FILTERS);
    setSelectedTagIds([]);
    setSeriesAssignments([]);
    setMetricConfiguration({ kind: "none" });
    setComparison(INITIAL_COMPARISON);
    setVisualRules(INITIAL_VISUAL_RULES);
    scatterInitializedRef.current = false;
    setQuery(INITIAL_QUERY);
  };

  const visualConfigurationDocument = buildVisualConfigurationDocument({
    filters,
    selectedTagIds,
    seriesAssignments,
    metricConfiguration,
    comparison,
    visualRules,
  });

  const openVisualConfiguration = (document: VisualConfigurationDocument) => {
    const defaults: PersistablePageState = {
      filters: INITIAL_FILTERS,
      selectedTagIds: [],
      seriesAssignments: [],
      metricConfiguration: { kind: "none" },
      comparison: INITIAL_COMPARISON,
      visualRules: INITIAL_VISUAL_RULES,
    };
    const restored = normalizeVisualConfigurationDocument(document, defaults, APPLICATION_TIMEZONE);
    setFilters({ ...restored.filters, filtersEnabled: restored.filters.filtersEnabled ?? true });
    setSelectedTagIds(restored.selectedTagIds);
    setSeriesAssignments(restored.seriesAssignments);
    setMetricConfiguration(restored.metricConfiguration);
    setComparison(restored.comparison);
    setVisualRules(restored.visualRules);
    scatterInitializedRef.current = restored.seriesAssignments.some((item) => item.scatterRole !== "none");
    setQuery(INITIAL_QUERY);
  };

  const computeValidationError = (): string | null => {
    if (filters.analysisModel !== "unit") return "O modelo selecionado ainda não está disponível.";
    if (!filters.equipmentId) return "Selecione uma máquina.";
    if (!selectedTagIds.length) return "Selecione ao menos uma tag.";
    if (comparison.type === "periods") {
      if (!comparison.contextBStart || !comparison.contextBEnd) return "Informe as datas inicial e final do Contexto B.";
      if (new Date(comparison.contextBStart).getTime() >= new Date(comparison.contextBEnd).getTime()) return "O período do Contexto B é inválido.";
    }
    if (comparison.type === "equipments" && !comparison.contextBEquipmentId) return "Selecione o equipamento do Contexto B.";
    if (comparison.type === "categories" && !comparison.contextBCategoryId) return "Selecione a categoria do Contexto B.";
    if ((comparison.type === "equipments" || comparison.type === "categories") && !comparison.contextBTagIds.length) {
      return "Selecione ao menos uma tag no Contexto B.";
    }
    if (filters.mode === "interpolated" && !filters.interval) {
      return "Selecione um intervalo para valores interpolados.";
    }
    if (filters.maxCount < 1) return "Maximo de pontos por tag deve ser >= 1.";
    if ((filters.visualization === "automatic" || filters.visualization === "line") && !assignmentValidation.validAxes) {
      return assignmentValidation.axisErrors[0];
    }
    return null;
  };

  const runQuery = async () => {
    const error = computeValidationError();
    if (error) {
      setQuery((prev) => ({ ...prev, errorMessage: error }));
      return;
    }
    const capturedNow = new Date();
    let resolvedPeriod: ResolvedTimePeriod;
    try {
      resolvedPeriod = resolveTimePeriod(filters.timePeriod, capturedNow);
    } catch (periodError) {
      setQuery((prev) => ({
        ...prev,
        errorMessage: periodError instanceof Error ? periodError.message : "Período inválido.",
      }));
      return;
    }
    if (piHealth && piHealth.status !== "connected" && piHealth.status !== "unavailable") {
      setQuery((prev) => ({
        ...prev,
        errorMessage: "PI Web API nao esta disponivel. Verifique a conexao.",
      }));
      return;
    }
    setCancelling(false);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const mySeq = ++requestSeqRef.current;
    const qid = _generateQueryId();
    cancelledQueryIdsRef.current.clear();
    queryIdRef.current = qid;
    const startedAt = Date.now();
    setQuery({
      timeSeries: null,
      loading: true,
      errorMessage: null,
      partial: false,
      errorPerSeries: [],
      startedAt,
      finishedAt: null,
      resolvedPeriod,
    });

    try {
      const result = comparison.type === "disabled" ? await timeSeriesApi.query(
        {
          tag_ids: queryTagIds,
          start_time: resolvedPeriod.startTime,
          end_time: resolvedPeriod.endTime,
          mode: filters.mode,
          interval: filters.mode === "interpolated" ? filters.interval : undefined,
          max_count: filters.mode === "recorded" && filters.resolutionMode === "manual" ? filters.maxCount : undefined,
          resolution_mode: filters.resolutionMode,
          target_points_per_tag: filters.targetPointsPerTag,
          query_id: qid,
        },
        controller.signal,
      ) : await timeSeriesApi.compare({
        comparison_type: comparison.type,
        contexts: [
          {
            context_id: "A",
            context_label: "Contexto A — Referência",
            tag_ids: queryTagIds,
            start_time: resolvedPeriod.startTime,
            end_time: resolvedPeriod.endTime,
          },
          {
            context_id: "B",
            context_label: "Contexto B — Comparação",
            tag_ids: comparison.type === "periods" ? queryTagIds : comparison.contextBTagIds,
            start_time: comparison.type === "periods" ? new Date(comparison.contextBStart).toISOString() : resolvedPeriod.startTime,
            end_time: comparison.type === "periods" ? new Date(comparison.contextBEnd).toISOString() : resolvedPeriod.endTime,
          },
        ],
        mode: filters.mode,
        interval: filters.mode === "interpolated" ? filters.interval : undefined,
        max_count: filters.mode === "recorded" && filters.resolutionMode === "manual" ? filters.maxCount : undefined,
        resolution_mode: filters.resolutionMode,
        target_points_per_tag: filters.targetPointsPerTag,
        query_id: qid,
      }, controller.signal).then((comparisonResult): TimeSeries => {
        const series = comparisonResult.contexts.flatMap((context) =>
          (context.time_series?.series ?? []).map((entry) => ({
            ...entry,
            original_tag_id: entry.tag_id,
            display_name: `${entry.display_name} — ${context.context_label}`,
          })),
        );
        const errors = comparisonResult.contexts.flatMap((context) =>
          context.time_series?.errors ?? (context.error ? [{ tag_id: 0, ...context.error }] : []),
        );
        return {
          start_time: comparisonResult.contexts[0].start_time,
          end_time: comparisonResult.contexts[0].end_time,
          mode: filters.mode,
          series,
          errors,
          query_execution: {
            resolution_mode: filters.resolutionMode,
            sampled: false,
            partial: comparisonResult.metadata.partial,
            duration_ms: comparisonResult.metadata.duration_ms,
            complete: comparisonResult.metadata.complete,
            points_returned: Object.values(comparisonResult.metadata.points_returned_by_context).reduce((sum, count) => sum + count, 0),
            query_id: comparisonResult.metadata.query_id,
          },
        };
      });
      if (mySeq !== requestSeqRef.current) return;
      queryIdRef.current = null;
      const finishedAt = Date.now();
      setQuery({
        timeSeries: result,
        loading: false,
        errorMessage: null,
        partial: result.errors.length > 0 || result.query_execution?.partial === true,
        errorPerSeries: result.errors,
        startedAt,
        finishedAt,
        resolvedPeriod,
      });
    } catch (err) {
      if (mySeq !== requestSeqRef.current) return;
      if (err instanceof DOMException && err.name === "AbortError") {
        setQuery({
          timeSeries: null,
          loading: false,
          errorMessage: "Consulta cancelada.",
          partial: false,
          errorPerSeries: [],
          startedAt,
          finishedAt: Date.now(),
          resolvedPeriod,
        });
        return;
      }
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : "Falha na consulta.";
      setQuery({
        timeSeries: null,
        loading: false,
        errorMessage: message,
        partial: false,
        errorPerSeries: [],
        startedAt,
        finishedAt: Date.now(),
        resolvedPeriod,
      });
    }
  };

  const handleSubmit = () => void runQuery();

  const selectedEquipment = filters.equipmentId
    ? equipmentMap.get(filters.equipmentId) ?? null
    : null;

  const piConfigured = piHealth?.status !== "not_configured";

  const durationMs =
    query.finishedAt && query.startedAt ? query.finishedAt - query.startedAt : null;

  const resolvedForResult = query.resolvedPeriod;
  const resolvedLabels = resolvedForResult
    ? formatResolvedTimePeriod(resolvedForResult).split(" até ")
    : ["—", "—"];
  const chartStart = resolvedForResult ? new Date(resolvedForResult.startTime) : new Date(0);
  const chartEnd = resolvedForResult ? new Date(resolvedForResult.endTime) : new Date(0);

  const equipmentTitle = selectedEquipment?.code ?? "Máquina";

  const handleCsvComplete = useCallback(async () => {
    if (!query.resolvedPeriod || selectedTagIds.length === 0) return;
    setCsvCompleteLoading(true);
    try {
      const controller = new AbortController();
      const response = await timeSeriesApi.exportCsv(
        {
          tag_ids: selectedTagIds,
          start_time: query.resolvedPeriod.startTime,
          end_time: query.resolvedPeriod.endTime,
          mode: filters.mode,
          interval: filters.mode === "interpolated" ? filters.interval : undefined,
        },
        controller.signal,
      );
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "exportacao_completa_pi.csv";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      // Ignore cancellation errors
    } finally {
      setCsvCompleteLoading(false);
    }
  }, [query.resolvedPeriod, selectedTagIds, filters.mode, filters.interval]);

  const estimatedVisualPoints = useMemo(() => {
    if (!query.resolvedPeriod) return null;
    const tagCount = selectedTagIds.length;
    const target = filters.targetPointsPerTag || 10000;
    const total = tagCount * target;
    return total > 0 ? Math.min(total, 200000) : null;
  }, [query.resolvedPeriod, selectedTagIds.length, filters.targetPointsPerTag]);

  const errorByTagId = useMemo(() => {
    const map = new Map<number, { code: string; message: string }>();
    for (const entry of query.errorPerSeries) {
      map.set(entry.tag_id, { code: entry.code, message: entry.message });
    }
    return map;
  }, [query.errorPerSeries]);

  return (
    <div data-testid="data-visualization-page">
      <PageHeader
        title="Visualizacao de Dados"
        subtitle="Grafico de linha com consulta direta ao PI Web API"
        center={
          <VisualConfigurationsPanel
            document={visualConfigurationDocument}
            onOpen={openVisualConfiguration}
          />
        }
        actions={
          <div className="d-flex flex-wrap gap-2 align-items-center">
            {piHealth ? (
              <span
                className={`badge ${
                  piHealth.status === "connected"
                    ? "bg-success"
                    : piHealth.status === "unavailable"
                    ? "bg-danger"
                    : "bg-secondary"
                }`}
                data-testid="pi-connection-status"
                data-status={piHealth.status}
              >
                PI: {piHealth.status}
              </span>
            ) : (
              <span className="badge bg-info" data-testid="pi-connection-loading">
                Verificando PI...
              </span>
            )}
            <Form.Check
              type="switch"
              id="filters-enabled-switch"
              label="Filtros"
              checked={filters.filtersEnabled}
              onChange={(event) => setFilters((prev) => ({ ...prev, filtersEnabled: event.target.checked }))}
              className="small mb-0"
              data-testid="filters-enabled-switch"
            />
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={() => void loadPiHealth()}
              disabled={piChecking}
            >
              <i className="bi bi-arrow-repeat me-1" /> Verificar PI
            </Button>
            <Button
              variant="primary"
              size="sm"
              className="btn-piad-primary"
              onClick={handleSubmit}
              disabled={query.loading || Boolean(periodPreview.error) || filters.analysisModel !== "unit"}
              data-testid="filters-submit-top"
            >
              <i className="bi bi-search me-1" /> {query.loading ? "Consultando..." : "Consultar"}
            </Button>
            <Button
              variant="outline-primary"
              size="sm"
              onClick={() => query.timeSeries && downloadTimeSeriesCsv(query.timeSeries)}
              disabled={!query.timeSeries || query.timeSeries.series.length === 0}
              data-testid="download-csv"
            >
              <i className="bi bi-filetype-csv me-1" /> Baixar CSV original
            </Button>
            <Button
              variant="outline-success"
              size="sm"
              onClick={() => {
                if (filteredTimeSeries) {
                  const csv = buildTimeSeriesCsv(filteredTimeSeries);
                  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
                  downloadBlob(blob, buildCsvFilename(filteredTimeSeries, "filtrado").replace("pi-analytics-data", "dados_pi_filtrados"));
                }
              }}
              disabled={!filteredTimeSeries || filteredTimeSeries.series.length === 0}
              data-testid="download-csv-filtered"
            >
              <i className="bi bi-filetype-csv me-1" /> Baixar CSV filtrado
            </Button>
          </div>
        }
      />

      {lookupError ? (
        <Alert variant="warning" className="mb-3">
          Falha ao carregar catalogos: {lookupError}
        </Alert>
      ) : null}

      <Row className="g-3">
        <Col xs={12} lg={4} xl={3}>
          <Card className="piad-card">
            <Card.Body>
              <DataFiltersPanel
                equipmentOptions={equipmentOptions}
                sectionOptions={sectionOptions}
                variableTypeOptions={variableTypeOptions}
                tagOptions={filteredTagOptions}
                selectedEquipmentId={filters.equipmentId}
                onEquipmentChange={handleEquipmentChange}
                selectedSectionId={filters.sectionId}
                onSectionChange={handleSectionChange}
                selectedVariableTypeId={filters.variableTypeId}
                onVariableTypeChange={handleVariableTypeChange}
                selectedTagIds={selectedTagIds}
                onTagsChange={handleTagsChange}
                timePeriod={filters.timePeriod}
                onTimePeriodChange={(timePeriod) => setFilters((prev) => ({ ...prev, timePeriod }))}
                timePeriodError={periodPreview.error}
                timePeriodSummary={periodPreview.resolved ? formatResolvedTimePeriod(periodPreview.resolved) : null}
                analysisModel={filters.analysisModel}
                onAnalysisModelChange={(analysisModel) => setFilters((prev) => ({ ...prev, analysisModel }))}
                mode={filters.mode}
                onModeChange={(mode) => setFilters((prev) => ({ ...prev, mode }))}
                interval={filters.interval}
                onIntervalChange={(value) => setFilters((prev) => ({ ...prev, interval: value }))}
                resolutionMode={filters.resolutionMode}
                onResolutionModeChange={(value) => setFilters((prev) => ({ ...prev, resolutionMode: value }))}
                targetPointsPerTag={filters.targetPointsPerTag}
                onTargetPointsPerTagChange={(value) => setFilters((prev) => ({ ...prev, targetPointsPerTag: value }))}
                targetPointsPerTagLimit={50000}
                estimatedVisualPoints={estimatedVisualPoints}
                ignoreBadQuality={filters.ignoreBadQuality}
                onCancel={handleCancel}
                csvCompleteLoading={csvCompleteLoading}
                onCsvComplete={() => void handleCsvComplete()}
                onIgnoreBadQualityChange={(value) =>
                  setFilters((prev) => syncQualityConfig(prev, value))
                }
                visualization={filters.visualization}
                onVisualizationChange={(visualization) =>
                  setFilters((prev) => ({ ...prev, visualization }))
                }
                seriesConfiguration={
                  <SeriesAssignmentsPanel
                    assignments={seriesAssignments}
                    tags={seriesConfigurationTags}
                    showScatter={filters.visualization === "scatter"}
                    errors={[
                      ...(filters.visualization === "automatic" || filters.visualization === "line"
                        ? assignmentValidation.axisErrors : []),
                      ...(filters.visualization === "scatter" ? assignmentValidation.scatterErrors : []),
                    ]}
                    onMove={(tagId, direction) =>
                      setSeriesAssignments((current) => moveAssignment(current, tagId, direction))
                    }
                    onLineAxisChange={(tagId, axis: SeriesAxis) =>
                      setSeriesAssignments((current) => setLineAxis(current, tagId, axis))
                    }
                    onScatterAxisChange={(role, tagId) => {
                      scatterInitializedRef.current = true;
                      setSeriesAssignments((current) => setScatterAxis(current, role, tagId));
                    }}
                  />
                }
                visualConfiguration={<VisualRulesPanel state={visualRules} series={visualSeriesOptions} onChange={setVisualRules} />}
                metricConfiguration={
                  <MetricConfigurationPanel
                    configuration={metricConfiguration}
                    series={metricSeriesOptions}
                    onChange={setMetricConfiguration}
                  />
                }
                advancedFilters={
                  <AdvancedFiltersPanel
                    configuration={filters.filterConfiguration}
                    enabled={filters.filtersEnabled}
                    tagOptions={advancedFilterTagOptions}
                    summary={filterResult?.summary ?? null}
                    ruleResults={filterResult?.ruleResults ?? []}
                    hasData={query.timeSeries !== null}
                    onChange={handleFilterConfigurationChange}
                  />
                }
                comparisonConfiguration={
                  <ComparisonPanel
                    type={comparison.type}
                    onTypeChange={(type) => setComparison((current) => ({ ...current, type, contextBTagIds: [] }))}
                    contextBEquipmentId={comparison.contextBEquipmentId}
                    onContextBEquipmentChange={(contextBEquipmentId) => setComparison((current) => ({ ...current, contextBEquipmentId, contextBTagIds: [] }))}
                    contextBCategoryId={comparison.contextBCategoryId}
                    onContextBCategoryChange={(contextBCategoryId) => setComparison((current) => ({ ...current, contextBCategoryId, contextBTagIds: [] }))}
                    contextBTagIds={comparison.contextBTagIds}
                    onContextBTagsChange={(contextBTagIds) => setComparison((current) => ({ ...current, contextBTagIds }))}
                    contextBStart={comparison.contextBStart}
                    contextBEnd={comparison.contextBEnd}
                    onContextBStartChange={(contextBStart) => setComparison((current) => ({ ...current, contextBStart }))}
                    onContextBEndChange={(contextBEnd) => setComparison((current) => ({ ...current, contextBEnd }))}
                    equipmentOptions={equipmentOptions}
                    categoryOptions={variableTypeOptions}
                    tagOptions={tagOptions}
                  />
                }
                piConfigured={piConfigured}
                onClear={handleClear}
                onSubmit={handleSubmit}
                submitting={query.loading}
                cancelling={cancelling}
                errorMessage={query.errorMessage}
              />
            </Card.Body>
          </Card>
        </Col>
        <Col xs={12} lg={8} xl={9}>
          <Card className="piad-card mb-3">
            <Card.Body>
              {query.loading ? (
                <div className="piad-loading" data-testid="chart-loading">
                  <span className="spinner-border spinner-border-sm me-2" /> Carregando serie temporal...
                </div>
              ) : query.errorMessage ? (
                <Alert variant="danger" className="mb-0" data-testid="chart-error">
                  <div className="fw-semibold mb-1">Falha na consulta</div>
                  <div>{query.errorMessage}</div>
                  <Button
                    variant="outline-danger"
                    size="sm"
                    className="mt-2"
                    onClick={() => void runQuery()}
                  >
                    Tentar novamente
                  </Button>
                </Alert>
              ) : !query.timeSeries ? (
                <div className="piad-empty" data-testid="chart-empty">
                  <i className="bi bi-graph-up" aria-hidden="true" />
                  <h5 className="mt-3">Selecione os filtros e clique em Consultar</h5>
                  <p className="mb-0">
                    O grafico sera gerado a partir dos valores retornados pelo PI Web API.
                    Os horários são configurados em America/Sao_Paulo e enviados ao
                    backend como instantes UTC.
                  </p>
                </div>
              ) : chartGroups ? (
                <div data-testid="chart-groups">
                  {numericChart &&
                  filters.visualization !== "histogram" &&
                  filters.visualization !== "boxplot" &&
                  filters.visualization !== "scatter" &&
                  filters.visualization !== "bars" &&
                  filters.visualization !== "singleValue" ? (
                    <div
                      className={showBothCharts ? "mb-4" : undefined}
                      data-testid="numeric-chart"
                    >
                      {showBothCharts ? (
                        <h5 className="mb-2">Séries numéricas</h5>
                      ) : null}
                      <TimeSeriesChart
                        chart={numericChart}
                        equipment={equipmentTitle}
                        start={chartStart}
                        end={chartEnd}
                        mode={filters.mode}
                        loading={query.loading}
                        titleLabel={
                          filters.visualization === "line" ? "Linha temporal" : undefined
                        }
                        visualRules={visualRules}
                      />
                    </div>
                  ) : null}
                  {numericChart && filters.visualization === "histogram" ? (
                    <div data-testid="histogram-charts" className="d-flex flex-column gap-4">
                      {numericChart.series.map((series) => (
                        <div key={series.tagId} data-testid="histogram-chart">
                          <HistogramChart series={series} />
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {numericChart && filters.visualization === "boxplot" ? (
                    <div data-testid="boxplot-charts" className="d-flex flex-column gap-4">
                      {boxPlotGroups.map((group) => (
                        <div key={group.unit.toLocaleLowerCase("pt-BR")} data-testid="boxplot-chart">
                          <BoxPlotChart group={group} />
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {filters.visualization === "scatter" &&
                  scatterXSeries && scatterYSeries &&
                  scatterPairs.length >= 2 ? (
                    <div data-testid="scatter-chart">
                      <ScatterPlotChart
                        xSeries={scatterXSeries}
                        ySeries={scatterYSeries}
                        ignoreBadQuality={filters.ignoreBadQuality}
                      />
                    </div>
                  ) : null}
                  {filters.visualization === "scatter" &&
                  (!scatterXSeries || !scatterYSeries) ? (
                    <Alert variant="info" className="mb-0" data-testid="scatter-series-guidance">
                      {originalNumericSeries.length === 0
                        ? "A dispersão exige duas séries numéricas; selecione explicitamente os eixos X e Y."
                        : originalNumericSeries.length === 1
                        ? "Selecione mais uma tag numérica e atribua explicitamente os eixos X e Y."
                        : `Foram encontradas ${originalNumericSeries.length} séries numéricas; selecione explicitamente tags diferentes para os eixos X e Y.`}
                    </Alert>
                  ) : null}
                  {filters.visualization === "scatter" &&
                  scatterXSeries && scatterYSeries &&
                  scatterPairs.length < 2 ? (
                    <Alert variant="info" className="mb-0" data-testid="scatter-pairs-guidance">
                      Não há pontos temporais coincidentes suficientes para a dispersão. Use
                      “Valores interpolados” para alinhar as tags.
                    </Alert>
                  ) : null}
                  {filters.visualization === "bars" && latestValueGroups.length > 0 ? (
                    <div data-testid="latest-bars-charts" className="d-flex flex-column gap-4">
                      {latestValueGroups.map((group) => (
                        <div key={group.unit.toLocaleLowerCase("pt-BR")} data-testid="latest-bars-chart">
                          <LatestValuesBarChart group={group} />
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {filters.visualization === "singleValue" ? (
                    <SingleValueCards
                      series={filteredTimeSeries?.series ?? []}
                      ignoreBadQuality={false}
                    />
                  ) : null}
                  {textualChart ? (
                    <div data-testid="textual-chart">
                      {showBothCharts ? (
                        <h5 className="mb-2">Estados</h5>
                      ) : null}
                      <TimeSeriesChart
                        chart={textualChart}
                        equipment={equipmentTitle}
                        start={chartStart}
                        end={chartEnd}
                        mode={filters.mode}
                        loading={query.loading}
                        visualRules={visualRules}
                      />
                    </div>
                  ) : null}
                  {excessTextualSeries.length > 0 ? (
                    <Alert
                      variant="warning"
                      className={numericChart ? "mt-3 mb-0" : "mb-0"}
                      data-testid="chart-multiple-textual"
                    >
                      O gráfico de estados aceita uma tag textual. Selecione somente uma tag textual;
                      não exibida{excessTextualSeries.length > 1 ? "s" : ""}: {" "}
                      <strong>
                        {excessTextualSeries.map((series) => series.displayName).join(", ")}
                      </strong>.
                    </Alert>
                  ) : null}
                  {incompatibleSeries.length > 0 ? (
                    <Alert
                      variant="info"
                      className={numericChart || textualChart ? "mt-3 mb-0" : "mb-0"}
                      data-testid="chart-incompatible-visualization"
                    >
                      {filters.visualization === "states" ? (
                        <>
                          Séries numéricas não são compatíveis com “Estados”: {" "}
                          <strong>
                            {incompatibleSeries.map((series) => series.displayName).join(", ")}
                          </strong>. Escolha “Linha temporal” ou “Automática” para visualizá-las.
                        </>
                      ) : (
                        <>
                          Séries textuais não são compatíveis com “
                          {filters.visualization === "histogram"
                            ? "Histograma"
                            : filters.visualization === "boxplot"
                            ? "Boxplot"
                            : filters.visualization === "scatter"
                            ? "Dispersão"
                            : filters.visualization === "bars"
                            ? "Barras — último valor"
                            : "Linha temporal"}
                          ”: {" "}
                          <strong>
                            {incompatibleSeries.map((series) => series.displayName).join(", ")}
                          </strong>. Escolha “Estados” ou “Automática” para visualizá-las.
                        </>
                      )}
                    </Alert>
                  ) : null}
                  {mixedSeries.length > 0 && filters.visualization !== "singleValue" ? (
                    <Alert
                      variant="warning"
                      className={numericChart || textualChart ? "mt-3 mb-0" : "mb-0"}
                      data-testid="chart-mixed-series"
                    >
                      {mixedSeries.length === 1 ? "A tag" : "As tags"}{" "}
                      <strong>{mixedSeries.map((series) => series.displayName).join(", ")}</strong>{" "}
                      {mixedSeries.length === 1 ? "possui" : "possuem"} valores numericos e
                      textuais na mesma serie e nao foi exibida.
                    </Alert>
                  ) : null}
                  {filters.visualization !== "singleValue" &&
                  !numericChart && !textualChart && mixedSeries.length === 0 &&
                  incompatibleSeries.length === 0 && excessTextualSeries.length === 0 ? (
                    <div className="piad-empty" data-testid="chart-no-data">
                      <i className="bi bi-emoji-neutral" aria-hidden="true" />
                      <h5 className="mt-3">Nenhum valor encontrado</h5>
                      <p className="mb-0">
                        O PI Web API nao retornou valores validos para o periodo selecionado.
                        Ajuste o intervalo ou desmarque a opcao
                        &quot;Ignorar qualidade ruim&quot;.
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </Card.Body>
          </Card>
          {query.timeSeries ? <MetricResults results={metricResults} series={metricNumericSeries} /> : null}
          {query.timeSeries ? (
            <div className="mb-3">
              <QuerySummary
                chart={chart}
                startLocal={resolvedLabels[0]}
                endLocal={resolvedLabels[1]}
                durationMs={durationMs}
                seriesCount={filteredTimeSeries?.series.length ?? query.timeSeries.series.length}
                partial={query.partial}
                mode={filters.mode}
                filterSummary={filterResult?.summary ?? null}
                queryExecution={query.timeSeries?.query_execution ?? null}
                seriesMeta={filteredTimeSeries?.series ?? []}
              />
            </div>
          ) : null}
          {query.partial && query.errorPerSeries.length > 0 ? (
            <Card className="piad-card mb-3" data-testid="partial-results">
              <Card.Header>Resultado parcial</Card.Header>
              <Card.Body>
                <p className="mb-2">
                  Algumas series nao puderam ser carregadas. O grafico apresenta apenas
                  as series obtidas com sucesso.
                </p>
                <ul className="mb-0">
                  {query.errorPerSeries.map((entry) => (
                    <li key={entry.tag_id}>
                      <strong>Tag {entry.tag_id}</strong>: {errorByTagId.get(entry.tag_id)?.message ?? entry.message}{" "}
                      <code className="ms-2">({entry.code})</code>
                    </li>
                  ))}
                </ul>
              </Card.Body>
            </Card>
          ) : null}
        </Col>
      </Row>
    </div>
  );
}
