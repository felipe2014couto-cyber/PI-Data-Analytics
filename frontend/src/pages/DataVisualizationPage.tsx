import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Col, Form, Row } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

import { equipmentsApi, piApi, piTagsApi, sectionsApi, sipApi, timeSeriesApi, variableTypesApi } from "../api";
import { ApiError } from "../api/http";
import type {
  DataFilterConfiguration,
  Equipment,
  AnalysisModel,
  TimeAnalysisRule,
  PiHealth,
  PiTag,
  Section,
  SectionAnalysisTag,
  ConflictedVariable,
  TimePeriod,
  TimeSeries,
  TimeSeriesMode,
  ComparisonType,
  SeriesAssignment,
  SeriesAxis,
  MetricConfiguration,
  DynamicAnalysisFilter,
  VariableType,
  VisualizationType,
  VisualRulesState,
  VisualConfigurationDocument,
  PiTagNormLimitsResponse,
} from "../types";
import { DataFiltersPanel } from "../components/DataFiltersPanel";
import { SeriesAssignmentsPanel, type SeriesConfigurationTag } from "../components/SeriesAssignmentsPanel";
import { QuerySummary } from "../components/QuerySummary";
import { ComparisonPanel } from "../components/ComparisonPanel";
import { TimeSeriesChart, type ZoomQueryOutcome } from "../components/TimeSeriesChart";
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
import { AdvancedFiltersPanel, isFixedAnalysisTag, stripRetiredNamedFilterRules } from "../components/AdvancedFiltersPanel";
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
import { applyTimeAnalysisRule } from "../utils/timeAnalysisRule";
import { buildNormLimitSeries, type NormLimitSeries } from "../utils/normLimitSeries";
import { buildUmChartSeries, type UmChartSeries } from "../utils/umChartSeries";
import { EMPTY_VISUAL_CONFIGURATION, defaultNormLimitConfig } from "../utils/visualRules";
import type { ChartSeries } from "../utils/chartData";

const TIME_CHART_SYNC_GROUP = "piad-data-visualization-time";

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

const NORM_LIMIT_CACHE_LIMIT = 50;

interface FiltersState {
  analysisModel: AnalysisModel;
  equipmentId: number | null;
  sectionId: number | null;
  variableTypeId: number | null;
  timePeriod: TimePeriod;
  timezone: "America/Sao_Paulo";
  mode: TimeSeriesMode;
  interval: string;
  resolutionMode: string;
  ignoreBadQuality: boolean;
  visualization: VisualizationType;
  timeAnalysisRule: TimeAnalysisRule;
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
  mode: "recorded",
  interval: "10s",
  resolutionMode: "automatic",
  ignoreBadQuality: true,
  visualization: "automatic",
  timeAnalysisRule: "MEDIA",
  filtersEnabled: true,
  filterConfiguration: INITIAL_FILTER_CONFIG,
};

function intervalToSeconds(value: string): number {
  const match = /^(\d+)([smhd])$/.exec(value);
  if (!match) return Number.POSITIVE_INFINITY;
  const amount = Number(match[1]);
  return amount * ({ s: 1, m: 60, h: 3600, d: 86400 } as const)[match[2] as "s" | "m" | "h" | "d"];
}

interface QueryState {
  timeSeries: TimeSeries | null;
  loading: boolean;
  errorMessage: string | null;
  partial: boolean;
  errorPerSeries: Array<{ tag_id: number; code: string; message: string }>;
  startedAt: number | null;
  finishedAt: number | null;
  resolvedPeriod: ResolvedTimePeriod | null;
  errorDetails: HistoricalErrorDetails | null;
}

interface HistoricalErrorDetails {
  affected_tags?: Array<{ tag_id: number; intervals?: Array<{ start: string; end: string }> }>;
  mode?: string;
  resolution?: string;
  requested_period?: { start: string; end: string };
  data_available_until?: string;
  requested_end?: string;
  effective_end?: string;
  freshness_lag_seconds?: number;
  reload_available?: boolean;
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
  errorDetails: null,
};

interface ZoomQueryState {
  loading: boolean;
  errorMessage: string | null;
  errorDetails: HistoricalErrorDetails | null;
}

const INITIAL_ZOOM_QUERY: ZoomQueryState = {
  loading: false,
  errorMessage: null,
  errorDetails: null,
};

function zoomCacheKey(start: Date, end: Date): string {
  return `${start.getTime()}:${end.getTime()}`;
}

function hasSufficientZoomDetail(
  result: TimeSeries,
  visibleStart: Date,
  visibleEnd: Date,
  targetPointsPerTag: number,
): boolean {
  const loadedStart = Date.parse(result.start_time);
  const loadedEnd = Date.parse(result.end_time);
  if (
    !Number.isFinite(loadedStart) || !Number.isFinite(loadedEnd) ||
    visibleStart.getTime() < loadedStart || visibleEnd.getTime() > loadedEnd
  ) {
    return false;
  }
  const effectiveInterval = result.query_execution?.effective_interval?.toLowerCase();
  if (effectiveInterval === "recorded") return true;
  const currentBucketSeconds = effectiveInterval ? intervalToSeconds(effectiveInterval) : Number.POSITIVE_INFINITY;
  const visibleSeconds = Math.max(1, (visibleEnd.getTime() - visibleStart.getTime()) / 1000);
  const idealBucketSeconds = Math.max(1, Math.ceil(visibleSeconds / Math.max(1, targetPointsPerTag)));
  return currentBucketSeconds <= idealBucketSeconds;
}



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
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [chartWidth, setChartWidth] = useState<number>(1500);

  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;
    const updateWidth = () => {
      const width = el.getBoundingClientRect().width;
      if (width > 0) setChartWidth(Math.round(width));
    };
    updateWidth();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          if (entry.contentRect.width > 0) {
            setChartWidth(Math.round(entry.contentRect.width));
          }
        }
      });
      observer.observe(el);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  const dynamicPointsPerTag = useMemo(() => {
    // 1 ponto por pixel da largura do componente de gráfico (limitado tecnicamente entre 500 e 2500)
    return Math.max(500, Math.min(2500, chartWidth || 1500));
  }, [chartWidth]);

  const navigate = useNavigate();
  const { user } = useAuth();
  const [filters, setFilters] = useState<FiltersState>(INITIAL_FILTERS);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [seriesAssignments, setSeriesAssignments] = useState<SeriesAssignment[]>([]);
  const [metricConfiguration, setMetricConfiguration] = useState<MetricConfiguration>({ kind: "none" });
  const [query, setQuery] = useState<QueryState>(INITIAL_QUERY);
  const [zoomQuery, setZoomQuery] = useState<ZoomQueryState>(INITIAL_ZOOM_QUERY);
  const [zoomedRange, setZoomedRange] = useState<{ start: Date; end: Date } | null>(null);
  const [dynamicFilters, setDynamicFilters] = useState<Record<number, DynamicAnalysisFilter>>({});
  const [filterValidationError, setFilterValidationError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ComparisonState>(INITIAL_COMPARISON);
  const [visualRules, setVisualRules] = useState<VisualRulesState>(INITIAL_VISUAL_RULES);
  const [resolvedLimitSeries, setResolvedLimitSeries] = useState<ChartSeries[]>([]);
  const limitAbortRef = useRef<AbortController | null>(null);
  const [rawNormResponses, setRawNormResponses] = useState<
    Record<string, { tag: PiTag; response: PiTagNormLimitsResponse }>
  >({});
  const [normLimitErrors, setNormLimitErrors] = useState<Record<string, string>>({});
  const [normLimitLoading, setNormLimitLoading] = useState<Record<string, boolean>>({});
  const normLimitAbortRef = useRef<AbortController | null>(null);
  const normLimitCacheRef = useRef<Map<string, PiTagNormLimitsResponse>>(new Map());
  const normLimitInFlightRef = useRef<Map<string, Promise<PiTagNormLimitsResponse>>>(new Map());
  const activeNormContextKeyRef = useRef<string>("");

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
  const zoomAbortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);
  const zoomRequestSeqRef = useRef(0);
  const initialQueryRef = useRef<QueryState | null>(null);
  const activeQueryRef = useRef<QueryState>(INITIAL_QUERY);
  const zoomCacheRef = useRef<Map<string, QueryState>>(new Map());
  const zoomRejectedRef = useRef<Set<string>>(new Set());
  const zoomInFlightRef = useRef<{ key: string; promise: Promise<ZoomQueryOutcome> } | null>(null);
  const queryIdRef = useRef<string | null>(null);
  const cancelledQueryIdsRef = useRef<Set<string>>(new Set());
  const scatterInitializedRef = useRef(false);
  activeQueryRef.current = query;

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
      const sipSources = await sipApi.list();
      if (signal?.aborted) return;
      const sipTags: PiTag[] = sipSources.filter((source) => source.active).map((source) => ({
        id: -source.id,
        equipment_id: source.equipment_id,
        section_id: source.section_id,
        variable_type_id: source.variable_type_id,
        pi_server: "SIP",
        pi_tag_name: `SIP SQL: ${source.name}`,
        pi_web_id: null,
        display_name: source.name,
        description: "Consulta Oracle SIP somente leitura",
        engineering_unit: vt.items.find((item) => item.id === source.variable_type_id)?.default_unit ?? null,
        data_type: vt.items.find((item) => item.id === source.variable_type_id)?.filter_data_type === "REAL" ? "NUMERIC" : "NON_NUMERIC",
        active: source.active,
        validation_status: "VALID",
        validation_message: null,
        validated_at: null,
        created_at: source.created_at,
        updated_at: source.updated_at,
      }));
      setTags([...tagList.filter((tag) => tag.active), ...sipTags]);
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
        message: err instanceof Error ? err.message : "Falha ao consultar o estado da ingestão",
        error_code: "INGESTION_HEALTH_FAILED",
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
  // consulta para que os filtros de largura e espessura possam mascarar
  // as demais séries. A UM é exibida no gráfico (não é ocultada).
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
      steelType: resolveUniqueTagId(candidateSections.map((section) => section.steel_type_tag_id ?? null)),
    };
  }, [filters.equipmentId, filters.sectionId, sections, tags]);

  const piTagById = useMemo(() => new Map(tags.map((tag) => [tag.id, tag])), [tags]);

  const { extraAnalysisTags, conflictedVariables } = useMemo(() => {
    // Helper to exclude fixed tags by code, name, or if matching section's fixed tag IDs
    const isExtra = (t: SectionAnalysisTag, sec?: Section): boolean => {
      if (isFixedAnalysisTag(t)) return false;
      if (sec) {
        if (
          t.pi_tag_id &&
          (t.pi_tag_id === sec.width_tag_id ||
            t.pi_tag_id === sec.um_tag_id ||
            t.pi_tag_id === sec.thickness_tag_id ||
            t.pi_tag_id === sec.steel_type_tag_id)
        ) {
          return false;
        }
      }
      return true;
    };

    // 1. Specific section selected:
    if (filters.sectionId) {
      const section = sectionMap.get(filters.sectionId);
      if (!section) return { extraAnalysisTags: [], conflictedVariables: [] };
      const rawTags = section.analysis_tags ?? [];
      const extraTags: SectionAnalysisTag[] = rawTags
        .filter((t) => isExtra(t, section))
        .map((t) => ({
          ...t,
          section_tag_map: t.pi_tag_id ? { [filters.sectionId!]: t.pi_tag_id } : {},
          pi_tag_ids: t.pi_tag_id ? [t.pi_tag_id] : [],
        }));
      return { extraAnalysisTags: extraTags, conflictedVariables: [] };
    }

    // 2. "Todas as seções" with equipment selected:
    if (filters.equipmentId) {
      const equipSections = sections.filter((s) => s.equipment_id === filters.equipmentId);
      interface TagEntry {
        tag: SectionAnalysisTag;
        sectionId: number;
        sectionName: string;
      }
      const byVar = new Map<number, TagEntry[]>();

      for (const sec of equipSections) {
        for (const t of sec.analysis_tags ?? []) {
          if (!isExtra(t, sec)) continue;
          const varId = t.variable_type_id;
          if (!byVar.has(varId)) {
            byVar.set(varId, []);
          }
          byVar.get(varId)!.push({ tag: t, sectionId: sec.id, sectionName: sec.name });
        }
      }

      const consolidated: SectionAnalysisTag[] = [];
      const conflicts: ConflictedVariable[] = [];

      for (const [varId, entries] of byVar.entries()) {
        const types = new Set(entries.map((e) => e.tag.filter_type).filter(Boolean));
        if (types.size > 1) {
          // Filter type conflict across sections
          const first = entries[0].tag;
          conflicts.push({
            variableTypeId: varId,
            variableTypeCode: first.variable_type_code,
            variableTypeName: first.variable_type_name || `Variável #${varId}`,
            details: entries.map((e) => ({
              sectionId: e.sectionId,
              sectionName: e.sectionName,
              filterType: e.tag.filter_type,
            })),
          });
          continue;
        }

        const first = entries[0].tag;
        const section_tag_map: Record<number, number> = {};
        const piTagIdsSet = new Set<number>();

        for (const e of entries) {
          if (e.sectionId && e.tag.pi_tag_id) {
            section_tag_map[e.sectionId] = e.tag.pi_tag_id;
            piTagIdsSet.add(e.tag.pi_tag_id);
          }
        }

        consolidated.push({
          ...first,
          section_tag_map,
          pi_tag_ids: Array.from(piTagIdsSet),
        });
      }

      return { extraAnalysisTags: consolidated, conflictedVariables: conflicts };
    }

    // 3. No equipment selected
    return { extraAnalysisTags: [], conflictedVariables: [] };
  }, [filters.equipmentId, filters.sectionId, sectionMap, sections]);

  // IDs das tags internas que devem permanecer ocultas no gráfico
  // (largura, espessura, tipo de aço e tags dinâmicas). A UM é exibida em eixo próprio.
  const analysisContextTagIds = useMemo(
    () => {
      const ids = new Set<number>();
      if (analysisTagIds.width !== null) ids.add(analysisTagIds.width);
      if (analysisTagIds.thickness !== null) ids.add(analysisTagIds.thickness);
      if (analysisTagIds.steelType !== null) ids.add(analysisTagIds.steelType);
      for (const t of extraAnalysisTags) {
        if (t.pi_tag_ids && t.pi_tag_ids.length > 0) {
          for (const id of t.pi_tag_ids) {
            ids.add(id);
          }
        } else if (t.pi_tag_id) {
          ids.add(t.pi_tag_id);
        }
      }
      return ids;
    },
    [analysisTagIds, extraAnalysisTags],
  );
  const analysisHiddenTagIds = useMemo(
    () => new Set(
      Array.from(analysisContextTagIds).filter((tagId) => !selectedTagIds.includes(tagId)),
    ),
    [analysisContextTagIds, selectedTagIds],
  );
  const queryTagIds = useMemo(
    () => {
      // Tags selecionadas pelo usuário + tags fixas auxiliares e tags de análise da seção
      // A UM NÃO entra automaticamente: só entra se o usuário selecioná-la explicitamente em selectedTagIds.
      const set = new Set<number>([...selectedTagIds, ...analysisContextTagIds]);
      return Array.from(set);
    },
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

  // Reset dynamic filters and clean section-filter rules when equipment or section changes
  useEffect(() => {
    setDynamicFilters({});
    setFilters((prev) => {
      const hasSectionRules = prev.filterConfiguration.rules.some((r) => r.id.startsWith("section-filter:"));
      if (!hasSectionRules) return prev;
      return {
        ...prev,
        filterConfiguration: {
          ...prev.filterConfiguration,
          rules: prev.filterConfiguration.rules.filter((r) => !r.id.startsWith("section-filter:")),
        },
      };
    });
  }, [filters.equipmentId, filters.sectionId]);

  const activeDynamicFilters = useMemo<DynamicAnalysisFilter[]>(() => {
    if (!filters.filtersEnabled || !filters.sectionId) return [];
    return Object.values(dynamicFilters).filter((f) => {
      if (f.min !== null && f.min !== undefined) return true;
      if (f.max !== null && f.max !== undefined) return true;
      if (f.expression && f.expression.trim() && f.expression.trim() !== "ALL") return true;
      if (f.value && f.value !== "ALL" && f.value !== "") return true;
      return false;
    });
  }, [filters.filtersEnabled, filters.sectionId, dynamicFilters]);

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
    const seriesSectionMap = new Map<string, number>();
    for (const s of orderedTimeSeries.series) {
      const piTag = piTagById.get(s.tag_id);
      if (piTag?.section_id !== null && piTag?.section_id !== undefined) {
        const key = s.series_instance_id ?? `tag:${s.tag_id}`;
        seriesSectionMap.set(key, piTag.section_id);
      }
    }
    return applyDataFilters(orderedTimeSeries, filters.filterConfiguration, {
      summarySeriesKeys: visibleSeriesKeys,
      crossSeriesRuleIds,
      seriesSectionMap,
    });
  }, [analysisContextTagIds, analysisHiddenTagIds, filters.filtersEnabled, orderedTimeSeries, query.timeSeries, filters.filterConfiguration, piTagById]);

  const filteredTimeSeries: TimeSeries | null = useMemo(() => {
    const source = filterResult?.filteredTimeSeries ?? orderedTimeSeries;
    if (!source) return null;
    return {
      ...source,
      series: source.series.filter((series) => !analysisHiddenTagIds.has(series.tag_id)),
    };
  }, [analysisHiddenTagIds, filterResult, orderedTimeSeries]);

  const chartTimeSeries: TimeSeries | null = useMemo(() => {
    let baseSeries: TimeSeries | null;
    if (!filteredTimeSeries || !filterResult || filterResult.summary.removedPoints === 0) {
      baseSeries = filteredTimeSeries;
    } else {
      const filteredBySeries = new Map(
        filteredTimeSeries.series.map((series) => [
          series.series_instance_id ?? `tag:${series.tag_id}`,
          new Map(series.points.map((point) => [point.timestamp, point])),
        ]),
      );
      baseSeries = {
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
    }
    if (!baseSeries) return null;
    if (filters.analysisModel === "cyclic") {
      return baseSeries;
    }
    return applyTimeAnalysisRule(baseSeries, filters.timeAnalysisRule);
  }, [filterResult, filteredTimeSeries, orderedTimeSeries, filters.timeAnalysisRule, filters.analysisModel]);

  // Extrai a série da UM antes do agrupamento para que ela não seja classificada
  // como textual e renderizada em gráfico de estados separado. A UM é
  // renderizada separadamente com eixo próprio dentro do mesmo TimeSeriesChart.
  const chartTimeSeriesWithoutUm: TimeSeries | null = useMemo(() => {
    if (!chartTimeSeries || analysisTagIds.um === null) return chartTimeSeries;
    return {
      ...chartTimeSeries,
      series: chartTimeSeries.series.filter((series) => series.tag_id !== analysisTagIds.um),
    };
  }, [chartTimeSeries, analysisTagIds.um]);

  const chartGroups = useMemo(() => {
    if (!chartTimeSeriesWithoutUm) return null;
    return buildChartDataGroups(chartTimeSeriesWithoutUm, {
      ignoreBadQuality: false,
    });
  }, [chartTimeSeriesWithoutUm]);
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

  const seriesToPiTag = useMemo(() => {
    const map = new Map<string, PiTag>();
    if (query.timeSeries) {
      for (const s of query.timeSeries.series) {
        if (analysisHiddenTagIds.has(s.tag_id)) continue;
        const piTag = piTagById.get(s.tag_id);
        const instanceId = s.series_instance_id ?? `tag:${s.tag_id}`;
        if (piTag) map.set(instanceId, piTag);
      }
    } else {
      const selected = new Set(selectedTagIds);
      for (const tag of tags) {
        if (!selected.has(tag.id)) continue;
        map.set(`tag:${tag.id}`, tag);
      }
    }
    return map;
  }, [analysisHiddenTagIds, piTagById, query.timeSeries, selectedTagIds, tags]);

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
    const linkedOptions = (Object.entries(analysisTagIds) as Array<["width" | "um" | "thickness" | "steelType", number | null]>)
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
    const tagsById = new Map(tags.map((tag) => [tag.id, tag]));
    const tagsByName = new Map(tags.map((tag) => [tag.pi_tag_name, tag]));
    const expanded = new Set(ids);
    for (const id of ids) {
      const tag = tagsById.get(id);
      if (!tag) continue;
      const lowerName = tag.lower_limit_tag?.trim();
      if (lowerName) {
        const lowerTag = tagsByName.get(lowerName);
        if (lowerTag) expanded.add(lowerTag.id);
      }
      const upperName = tag.upper_limit_tag?.trim();
      if (upperName) {
        const upperTag = tagsByName.get(upperName);
        if (upperTag) expanded.add(upperTag.id);
      }
    }
    const merged = Array.from(expanded);
    if (merged.length === ids.length && merged.every((id, index) => id === ids[index])) {
      setSelectedTagIds(ids);
    } else {
      setSelectedTagIds(merged);
    }
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
    void Promise.resolve(timeSeriesApi.cancelQuery(qid)).catch(() => {});
  };

  const handleAnalysisModelChange = (analysisModel: AnalysisModel) => {
    if (analysisModel === filters.analysisModel) return;

    if (abortRef.current) {
      abortRef.current.abort();
    }
    if (queryIdRef.current) {
      const qid = queryIdRef.current;
      if (!cancelledQueryIdsRef.current.has(qid)) {
        cancelledQueryIdsRef.current.add(qid);
        void Promise.resolve(timeSeriesApi.cancelQuery(qid)).catch(() => {});
      }
      queryIdRef.current = null;
    }
    requestSeqRef.current += 1;
    setCancelling(false);

    setFilters((prev) => ({
      ...prev,
      analysisModel,
      timeAnalysisRule:
        analysisModel === "cyclic"
          ? "DEFAULT"
          : prev.timeAnalysisRule === "DEFAULT"
          ? "MEDIA"
          : prev.timeAnalysisRule,
    }));
  };

  const handleClear = () => {
    abortRef.current?.abort();
    zoomAbortRef.current?.abort();
    zoomRequestSeqRef.current += 1;
    zoomInFlightRef.current = null;
    zoomCacheRef.current.clear();
    zoomRejectedRef.current.clear();
    initialQueryRef.current = null;
    queryIdRef.current = null;
    setFilters(INITIAL_FILTERS);
    setSelectedTagIds([]);
    setSeriesAssignments([]);
    setMetricConfiguration({ kind: "none" });
    setComparison(INITIAL_COMPARISON);
    setVisualRules(INITIAL_VISUAL_RULES);
    scatterInitializedRef.current = false;
    setQuery(INITIAL_QUERY);
    setZoomQuery(INITIAL_ZOOM_QUERY);
    setFilterValidationError(null);
  };

  const openHistoricalReload = (overrideDetails?: HistoricalErrorDetails | null) => {
    const details = overrideDetails ?? query.errorDetails;
    if (user?.role !== "admin" || !details?.reload_available) return;
    const tagIds = (details.affected_tags ?? []).map((entry) => entry.tag_id);
    const period = details.requested_period ?? (query.resolvedPeriod ? {
      start: query.resolvedPeriod.startTime,
      end: query.resolvedPeriod.endTime,
    } : null);
    if (!tagIds.length || !period) return;
    const params = new URLSearchParams({
      tag_ids: tagIds.join(","),
      start_time: period.start,
      end_time: period.end,
      mode: "recorded",
      interval: details.resolution ?? (details.mode === "recorded" ? "10s" : "300s"),
    });
    navigate(`/admin/recargas-historicas?${params.toString()}`);
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
    const baseFilterConfiguration = restored.filters.filterConfiguration ?? { quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false }, rules: [] };
    const cleanedFilterConfiguration = {
      ...baseFilterConfiguration,
      rules: stripRetiredNamedFilterRules(baseFilterConfiguration.rules),
    };
    setFilters({
      ...INITIAL_FILTERS,
      ...restored.filters,
      timeAnalysisRule: restored.filters.timeAnalysisRule ?? "DEFAULT",
      filtersEnabled: restored.filters.filtersEnabled ?? true,
      filterConfiguration: cleanedFilterConfiguration,
    });
    setSelectedTagIds(restored.selectedTagIds);
    setSeriesAssignments(restored.seriesAssignments);
    setMetricConfiguration(restored.metricConfiguration);
    setComparison(restored.comparison);
    setVisualRules(restored.visualRules);
    scatterInitializedRef.current = restored.seriesAssignments.some((item) => item.scatterRole !== "none");
    setQuery(INITIAL_QUERY);
  };

  const computeValidationError = (): string | null => {
    if (filters.analysisModel !== "unit" && filters.analysisModel !== "cyclic") return "O modelo selecionado ainda não está disponível.";
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
    if (selectedTagIds.some((id) => id < 0) && filters.mode !== "recorded") {
      return "Consultas SIP aceitam somente o modo Recorded.";
    }
    if (filters.mode === "interpolated" && !filters.interval) {
      return "Selecione um intervalo para valores interpolados.";
    }
    if (filters.mode === "interpolated" && intervalToSeconds(filters.interval) < 10) {
      return "O intervalo mínimo para valores interpolados é de 10 segundos.";
    }
    if ((filters.visualization === "automatic" || filters.visualization === "line") && !assignmentValidation.validAxes) {
      return assignmentValidation.axisErrors[0];
    }
    return null;
  };

  const fetchTimeSeriesPeriod = useCallback(async (
    period: ResolvedTimePeriod,
    qid: string,
    signal: AbortSignal,
    zoomBasePeriod?: ResolvedTimePeriod,
  ): Promise<TimeSeries> => {
    if (comparison.type === "disabled") {
      return timeSeriesApi.query(
        {
          tag_ids: queryTagIds,
          start_time: period.startTime,
          end_time: period.endTime,
          mode: filters.mode,
          interval: filters.mode === "interpolated" ? filters.interval : undefined,
          resolution_mode: filters.resolutionMode,
          target_points_per_tag: dynamicPointsPerTag,
          relative_period: zoomBasePeriod ? false : filters.timePeriod.kind !== "absolute",
          query_id: qid,
          section_id: filters.sectionId ?? undefined,
          analysis_filters: filters.sectionId && activeDynamicFilters.length > 0 ? activeDynamicFilters : undefined,
        },
        signal,
      );
    }

    let contextBStart = comparison.type === "periods"
      ? new Date(comparison.contextBStart)
      : new Date(period.startTime);
    let contextBEnd = comparison.type === "periods"
      ? new Date(comparison.contextBEnd)
      : new Date(period.endTime);
    if (comparison.type === "periods" && zoomBasePeriod) {
      const baseAStart = Date.parse(zoomBasePeriod.startTime);
      const baseBStart = Date.parse(comparison.contextBStart);
      contextBStart = new Date(baseBStart + Date.parse(period.startTime) - baseAStart);
      contextBEnd = new Date(baseBStart + Date.parse(period.endTime) - baseAStart);
    }

    const comparisonResult = await timeSeriesApi.compare({
      comparison_type: comparison.type,
      contexts: [
        {
          context_id: "A",
          context_label: "Contexto A — Referência",
          tag_ids: queryTagIds,
          start_time: period.startTime,
          end_time: period.endTime,
        },
        {
          context_id: "B",
          context_label: "Contexto B — Comparação",
          tag_ids: comparison.type === "periods" ? queryTagIds : comparison.contextBTagIds,
          start_time: contextBStart.toISOString(),
          end_time: contextBEnd.toISOString(),
        },
      ],
      mode: filters.mode,
      interval: filters.mode === "interpolated" ? filters.interval : undefined,
      resolution_mode: filters.resolutionMode,
      target_points_per_tag: dynamicPointsPerTag,
      query_id: qid,
    }, signal);
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
  }, [comparison, filters.interval, filters.mode, filters.resolutionMode, dynamicPointsPerTag, filters.timePeriod.kind, queryTagIds]);

  const runQuery = async () => {
    const error = computeValidationError();
    if (error) {
      setFilterValidationError(error);
      return;
    }
    setFilterValidationError(null);
    const capturedNow = new Date();
    let resolvedPeriod: ResolvedTimePeriod;
    try {
      resolvedPeriod = resolveTimePeriod(filters.timePeriod, capturedNow);
    } catch (periodError) {
      setQuery((prev) => ({
        ...prev,
        errorMessage: periodError instanceof Error ? periodError.message : "Período inválido.",
        errorDetails: null,
      }));
      return;
    }
    if (queryTagIds.some((id) => id > 0) && piHealth && piHealth.status !== "connected" && piHealth.status !== "unavailable") {
      setQuery((prev) => ({
        ...prev,
        errorMessage: "PI Web API nao esta disponivel. Verifique a conexao.",
        errorDetails: null,
      }));
      return;
    }
    setCancelling(false);
    abortRef.current?.abort();
    zoomAbortRef.current?.abort();
    zoomRequestSeqRef.current += 1;
    zoomInFlightRef.current = null;
    zoomCacheRef.current.clear();
    zoomRejectedRef.current.clear();
    initialQueryRef.current = null;
    setZoomQuery(INITIAL_ZOOM_QUERY);
    setZoomedRange(null);
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
      errorDetails: null,
    });

    try {
      const result = await fetchTimeSeriesPeriod(resolvedPeriod, qid, controller.signal);
      if (mySeq !== requestSeqRef.current) return;
      queryIdRef.current = null;
      const finishedAt = Date.now();
      const initialQueryState: QueryState = {
        timeSeries: result,
        loading: false,
        errorMessage: null,
        errorDetails: null,
        partial: result.errors.length > 0 || result.query_execution?.partial === true || result.query_execution?.complete === false,
        errorPerSeries: result.errors,
        startedAt,
        finishedAt,
        resolvedPeriod,
      };
      initialQueryRef.current = initialQueryState;
      zoomCacheRef.current.set(
        zoomCacheKey(new Date(resolvedPeriod.startTime), new Date(resolvedPeriod.endTime)),
        initialQueryState,
      );
      setQuery(initialQueryState);
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
          errorDetails: null,
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
        errorDetails: err instanceof ApiError && err.details && typeof err.details === "object" ? err.details as HistoricalErrorDetails : null,
        partial: false,
        errorPerSeries: [],
        startedAt,
        finishedAt: Date.now(),
        resolvedPeriod,
      });
    }
  };

  const handleVisibleWindowChange = useCallback((
    visibleStart: Date,
    visibleEnd: Date,
  ): Promise<ZoomQueryOutcome> => {
    const initial = initialQueryRef.current;
    if (!initial?.timeSeries || !initial.resolvedPeriod) {
      return Promise.resolve("superseded");
    }

    const effectiveStart = visibleStart;
    const effectiveEnd = visibleEnd;
    const key = zoomCacheKey(effectiveStart, effectiveEnd);
    const activeResult = activeQueryRef.current.timeSeries;

    if (zoomRejectedRef.current.has(key)) {
      return Promise.resolve("rejected");
    }

    // Refuse sub-second zoom without sufficient points in the active series
    const rawWindowMs = visibleEnd.getTime() - visibleStart.getTime();
    if (rawWindowMs < 1000 && activeResult) {
      const sMs = visibleStart.getTime();
      const eMs = visibleEnd.getTime();
      const pointsInWindow = activeResult.series.reduce((sum, s) => {
        return (
          sum +
          (s.points?.filter((p) => {
            const t = Date.parse(p.timestamp);
            return t >= sMs && t <= eMs;
          }).length ?? 0)
        );
      }, 0);
      if (pointsInWindow < 2) {
        zoomRejectedRef.current.add(key);
        return Promise.resolve("rejected");
      }
    }

    // Cache hit: restore stored query state immediately
    const cached = zoomCacheRef.current.get(key);
    if (cached) {
      zoomAbortRef.current?.abort();
      zoomRequestSeqRef.current += 1;
      zoomInFlightRef.current = null;
      setZoomQuery(INITIAL_ZOOM_QUERY);
      setZoomedRange({ start: effectiveStart, end: effectiveEnd });
      setQuery(cached);
      return Promise.resolve("applied");
    }

    // Current resolution already covers this window with sufficient detail:
    // no re-fetch needed, just update the visible range.
    if (activeResult && hasSufficientZoomDetail(activeResult, effectiveStart, effectiveEnd, dynamicPointsPerTag)) {
      zoomAbortRef.current?.abort();
      zoomRequestSeqRef.current += 1;
      zoomInFlightRef.current = null;
      setZoomQuery(INITIAL_ZOOM_QUERY);
      setZoomedRange({ start: effectiveStart, end: effectiveEnd });
      return Promise.resolve("applied");
    }

    // Terminal recorded resolution with no points in the requested sub-window:
    // cannot fetch finer recorded data, reject without firing redundant query.
    const isTerminalResolution =
      activeResult?.query_execution?.effective_interval?.toLowerCase() === "recorded" &&
      !activeResult?.query_execution?.sampled;
    if (isTerminalResolution && activeResult) {
      const startMs = visibleStart.getTime();
      const endMs = visibleEnd.getTime();
      const pointsInWindow = activeResult.series.reduce((sum, s) => {
        return (
          sum +
          (s.points?.filter((p) => {
            const t = Date.parse(p.timestamp);
            return t >= startMs && t <= endMs;
          }).length ?? 0)
        );
      }, 0);
      if (pointsInWindow === 0) {
        zoomRejectedRef.current.add(key);
        return Promise.resolve("rejected");
      }
    }

    // In-flight request for the exact same window: reuse the promise
    if (zoomInFlightRef.current?.key === key) {
      return zoomInFlightRef.current.promise;
    }

    // Fire a new zoom query
    zoomAbortRef.current?.abort();
    const controller = new AbortController();
    zoomAbortRef.current = controller;
    const mySeq = ++zoomRequestSeqRef.current;
    const qid = _generateQueryId();
    const startedAt = Date.now();
    setZoomQuery({ loading: true, errorMessage: null, errorDetails: null });
    const visiblePeriod: ResolvedTimePeriod = {
      startTime: effectiveStart.toISOString(),
      endTime: effectiveEnd.toISOString(),
      timezone: initial.resolvedPeriod.timezone,
      referenceTime: initial.resolvedPeriod.referenceTime,
    };

    const promise = (async (): Promise<ZoomQueryOutcome> => {
      try {
        const result = await fetchTimeSeriesPeriod(
          visiblePeriod,
          qid,
          controller.signal,
          initial.resolvedPeriod ?? undefined,
        );
        if (mySeq !== zoomRequestSeqRef.current) return "superseded";
        const totalPoints = result.series.reduce((sum, s) => sum + (s.points?.length ?? 0), 0);
        if (totalPoints === 0 || (result.query_execution?.points_returned ?? 0) === 0) {
          zoomRejectedRef.current.add(key);
          setZoomQuery(INITIAL_ZOOM_QUERY);
          return "rejected";
        }
        const next: QueryState = {
          ...initial,
          timeSeries: result,
          loading: false,
          errorMessage: null,
          errorDetails: null,
          partial: result.errors.length > 0 || result.query_execution?.partial === true,
          errorPerSeries: result.errors,
          startedAt,
          finishedAt: Date.now(),
        };
        zoomCacheRef.current.set(key, next);
        setZoomedRange({ start: effectiveStart, end: effectiveEnd });
        setQuery(next);
        setZoomQuery(INITIAL_ZOOM_QUERY);
        return "applied";
      } catch (error) {
        if (mySeq !== zoomRequestSeqRef.current || controller.signal.aborted) {
          return "superseded";
        }
        const details = error instanceof ApiError && error.details && typeof error.details === "object"
          ? error.details as HistoricalErrorDetails
          : null;
        const coverageMissing = error instanceof ApiError && error.status === 409;
        setZoomQuery({
          loading: false,
          errorMessage: coverageMissing
            ? "Não há cobertura RECORDED completa na resolução necessária para este zoom. O detalhe agregado não será exibido como dado de segundos."
            : error instanceof Error ? error.message : "Falha ao carregar o detalhe do zoom.",
          errorDetails: details,
        });
        return "rejected";
      } finally {
        if (zoomInFlightRef.current?.key === key) zoomInFlightRef.current = null;
      }
    })();
    zoomInFlightRef.current = { key, promise };
    return promise;
  }, [fetchTimeSeriesPeriod, dynamicPointsPerTag]);

  const handleRestoreInitialZoom = useCallback(() => {
    zoomAbortRef.current?.abort();
    zoomRequestSeqRef.current += 1;
    zoomInFlightRef.current = null;
    setZoomQuery(INITIAL_ZOOM_QUERY);
    setZoomedRange(null);
    if (initialQueryRef.current) setQuery(initialQueryRef.current);
  }, []);

  useEffect(() => () => {
    zoomAbortRef.current?.abort();
    zoomRequestSeqRef.current += 1;
  }, []);

  const handleSubmit = () => void runQuery();

  const selectedEquipment = filters.equipmentId
    ? equipmentMap.get(filters.equipmentId) ?? null
    : null;

  const piConfigured = (selectedTagIds.length > 0 && queryTagIds.every((id) => id < 0)) || piHealth?.status !== "not_configured";

  const durationMs =
    query.finishedAt && query.startedAt ? query.finishedAt - query.startedAt : null;

  const resolvedForResult = query.resolvedPeriod;
  const resolvedLabels = resolvedForResult
    ? formatResolvedTimePeriod(resolvedForResult).split(" até ")
    : ["—", "—"];
  const baseStart = resolvedForResult ? new Date(resolvedForResult.startTime) : new Date(0);
  const baseEnd = resolvedForResult ? new Date(resolvedForResult.endTime) : new Date(0);
  const chartStart = zoomedRange ? zoomedRange.start : baseStart;
  const chartEnd = zoomedRange ? zoomedRange.end : baseEnd;
  const zoomedLabels = zoomedRange
    ? [
        zoomedRange.start.toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE }),
        zoomedRange.end.toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE }),
      ]
    : null;

  const selectedSeriesInstanceId = visualRules.selectedSeriesInstanceId;
  const selectedPiTagForNorm = selectedSeriesInstanceId ? seriesToPiTag.get(selectedSeriesInstanceId) ?? null : null;

  const normEnabledSeriesKey = useMemo(() => {
    if (!visualRules.enabled) return "";
    const list: string[] = [];
    for (const [instanceId, cfg] of Object.entries(visualRules.bySeries)) {
      if (cfg.normLimit?.enabled) list.push(instanceId);
    }
    return list.sort().join(",");
  }, [visualRules.enabled, visualRules.bySeries]);

  // Conjunto final de séries com limites de norma ativos. Reflete estritamente
  // o que o usuário habilitou manualmente no painel visual (inclusive no modo OOC).
  const effectiveNormEnabledKey = normEnabledSeriesKey;

  const effectiveNormEnabledSeries = useMemo(() => {
    if (!effectiveNormEnabledKey) return new Set<string>();
    return new Set<string>(effectiveNormEnabledKey.split(","));
  }, [effectiveNormEnabledKey]);

  // Constrói a série da UM a partir do chartTimeSeries original somente quando
  // a tag da UM estiver explicitamente marcada/selecionada pelo usuário em selectedTagIds.
  const isUmSelected = useMemo(() => {
    if (analysisTagIds.um === null) return false;
    return selectedTagIds.includes(analysisTagIds.um);
  }, [analysisTagIds.um, selectedTagIds]);

  const umChartSeries: UmChartSeries | null = useMemo(() => {
    if (!isUmSelected || !chartTimeSeries || analysisTagIds.um === null) return null;
    const umTimeSeries = chartTimeSeries.series.find((series) => series.tag_id === analysisTagIds.um);
    if (!umTimeSeries) return null;
    const color = "#0288d1";
    const endIso = new Date(chartEnd.getTime() + 1).toISOString();
    return buildUmChartSeries({
      seriesInstanceId: umTimeSeries.series_instance_id ?? `tag:${umTimeSeries.tag_id}`,
      tagId: umTimeSeries.tag_id,
      tagName: umTimeSeries.tag_name,
      displayName: `UM (${umTimeSeries.tag_name})`,
      unit: umTimeSeries.unit,
      color,
      points: umTimeSeries.points.map((point) => ({
        timestamp: point.timestamp,
        value: point.value,
        good: point.good,
        questionable: point.questionable,
        substituted: point.substituted,
      })),
      endTimeIso: endIso,
    });
  }, [isUmSelected, chartTimeSeries, analysisTagIds.um, chartEnd]);

  const handleAddNormLimit = useCallback((seriesInstanceId: string) => {
    setVisualRules((current) => {
      const cfg = current.bySeries[seriesInstanceId] ?? EMPTY_VISUAL_CONFIGURATION(seriesInstanceId);
      if (cfg.normLimit?.enabled) return current;
      return {
        ...current,
        bySeries: {
          ...current.bySeries,
          [seriesInstanceId]: { ...cfg, normLimit: defaultNormLimitConfig() },
        },
      };
    });
  }, []);

  const handleRemoveNormLimit = useCallback((seriesInstanceId: string) => {
    setVisualRules((current) => {
      const cfg = current.bySeries[seriesInstanceId];
      if (!cfg) return current;
      const nextCfg: typeof cfg = { ...cfg, normLimit: null };
      return {
        ...current,
        bySeries: { ...current.bySeries, [seriesInstanceId]: nextCfg },
      };
    });
    setRawNormResponses((current) => {
      if (!(seriesInstanceId in current)) return current;
      const { [seriesInstanceId]: _drop, ...rest } = current;
      return rest;
    });
    setNormLimitErrors((current) => {
      const { [seriesInstanceId]: _drop, ...rest } = current;
      return rest;
    });
  }, []);

  const effectiveNormQuery = useMemo(() => {
    if (!resolvedForResult || !effectiveNormEnabledKey) {
      return {
        key: "",
        startTimeIso: "",
        endTimeIso: "",
        mode: filters.mode,
        interval: filters.mode === "interpolated" ? filters.interval : undefined,
        items: [] as Array<{
          instanceId: string;
          tagId: number;
          displayName: string;
          cacheKey: string;
        }>,
      };
    }

    const startTimeIso = chartStart.toISOString();
    const endTimeIso = chartEnd.toISOString();
    const interval = filters.mode === "interpolated" ? filters.interval : undefined;
    const sortedIds = effectiveNormEnabledKey.split(",").filter(Boolean);

    const items = sortedIds
      .map((instanceId) => {
        const piTag = seriesToPiTag.get(instanceId);
        const tagId = piTag?.id ?? 0;
        const lowerRef = piTag?.lower_limit_tag ?? "";
        const upperRef = piTag?.upper_limit_tag ?? "";
        const cacheKey = `${filters.analysisModel}|${tagId}|${lowerRef}|${upperRef}|${startTimeIso}|${endTimeIso}|${filters.mode}|${interval ?? ""}`;
        return {
          instanceId,
          tagId,
          displayName: piTag?.display_name ?? instanceId,
          cacheKey,
        };
      })
      .filter((item) => item.tagId > 0);

    const key =
      `${filters.mode}|${interval ?? ""}|${startTimeIso}|${endTimeIso}|` +
      items.map((it) => `${it.instanceId}:${it.cacheKey}`).join(";");

    return {
      key,
      startTimeIso,
      endTimeIso,
      mode: filters.mode,
      interval,
      items,
    };
  }, [
    resolvedForResult,
    effectiveNormEnabledKey,
    seriesToPiTag,
    chartStart,
    chartEnd,
    filters.analysisModel,
    filters.mode,
    filters.interval,
  ]);

  useEffect(() => {
    normLimitAbortRef.current?.abort();
    if (!effectiveNormQuery.key || effectiveNormQuery.items.length === 0) {
      setRawNormResponses((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      setNormLimitErrors((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      setNormLimitLoading((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      return;
    }

    const currentKey = effectiveNormQuery.key;
    activeNormContextKeyRef.current = currentKey;

    const controller = new AbortController();
    normLimitAbortRef.current = controller;

    const loadingMap: Record<string, boolean> = {};
    for (const item of effectiveNormQuery.items) {
      if (!normLimitCacheRef.current.has(item.cacheKey)) {
        loadingMap[item.instanceId] = true;
      }
    }
    setNormLimitLoading(loadingMap);

    void (async () => {
      try {
        const nextData: Record<string, { tag: PiTag; response: PiTagNormLimitsResponse }> = {};
        const nextErrors: Record<string, string> = {};

        await Promise.all(
          effectiveNormQuery.items.map(async (item) => {
            if (controller.signal.aborted || activeNormContextKeyRef.current !== currentKey) {
              return;
            }
            try {
              let response: PiTagNormLimitsResponse | undefined = normLimitCacheRef.current.get(item.cacheKey);
              if (!response) {
                let inFlight = normLimitInFlightRef.current.get(item.cacheKey);
                if (!inFlight) {
                  inFlight = piTagsApi
                    .getNormLimits(
                      item.tagId,
                      {
                        start_time: effectiveNormQuery.startTimeIso,
                        end_time: effectiveNormQuery.endTimeIso,
                        mode: effectiveNormQuery.mode,
                        interval: effectiveNormQuery.interval,
                      },
                      controller.signal,
                    )
                    .then((res) => {
                      const cache = normLimitCacheRef.current;
                      if (cache.has(item.cacheKey)) {
                        cache.delete(item.cacheKey);
                      } else if (cache.size >= NORM_LIMIT_CACHE_LIMIT) {
                        const oldestKey = cache.keys().next().value;
                        if (oldestKey !== undefined) cache.delete(oldestKey);
                      }
                      cache.set(item.cacheKey, res);
                      return res;
                    })
                    .finally(() => {
                      normLimitInFlightRef.current.delete(item.cacheKey);
                    });
                  normLimitInFlightRef.current.set(item.cacheKey, inFlight);
                }
                response = await inFlight;
              }

              if (controller.signal.aborted || activeNormContextKeyRef.current !== currentKey) {
                return;
              }

              const tag = seriesToPiTag.get(item.instanceId);
              if (tag) {
                nextData[item.instanceId] = { tag, response };
              }
              if (response.errors?.length) {
                nextErrors[item.instanceId] = `${item.displayName}: ${response.errors.join(" ")}`;
              }
            } catch (err) {
              if (controller.signal.aborted || activeNormContextKeyRef.current !== currentKey) {
                return;
              }
              nextErrors[item.instanceId] = `${item.displayName}: ${
                err instanceof ApiError ? err.message : "Não foi possível consultar os limites de norma."
              }`;
            }
          }),
        );

        if (controller.signal.aborted || activeNormContextKeyRef.current !== currentKey) {
          return;
        }

        setRawNormResponses(nextData);
        setNormLimitErrors(nextErrors);
        setNormLimitLoading({});
      } catch {
        // already handled per-entry
      }
    })();

    return () => {
      controller.abort();
    };
  }, [effectiveNormQuery, seriesToPiTag]);

  const normLimitSeries = useMemo<NormLimitSeries[]>(() => {
    if (effectiveNormEnabledSeries.size === 0) return [];
    const out: NormLimitSeries[] = [];
    for (const instanceId of effectiveNormEnabledSeries) {
      const entry = rawNormResponses[instanceId];
      if (!entry) continue;
      const { tag, response } = entry;
      const cfg = visualRules.bySeries[instanceId];
      const configNorm = cfg?.normLimit ?? defaultNormLimitConfig();
      const targetSeries = numericChart?.series.find(
        (s) => (s.seriesInstanceId ?? `tag:${s.tagId}`) === instanceId,
      );
      const yAxisIndex = targetSeries?.yAxisIndex ?? 0;
      out.push(
        buildNormLimitSeries({
          seriesInstanceId: instanceId,
          tagName: tag.pi_tag_name,
          mainDisplayName: tag.display_name,
          lowerTagName: response.lower.tag_name ?? tag.lower_limit_tag ?? null,
          upperTagName: response.upper.tag_name ?? tag.upper_limit_tag ?? null,
          yAxisIndex,
          lineStyle: configNorm.lineStyle,
          width: configNorm.width,
          lowerColor: configNorm.lowerColor,
          upperColor: configNorm.upperColor,
          lowerPoints: response.lower.points,
          upperPoints: response.upper.points,
          startTimeIso: chartStart.toISOString(),
          endTimeIso: chartEnd.toISOString(),
        }),
      );
    }
    return out;
  }, [
    effectiveNormEnabledSeries,
    rawNormResponses,
    visualRules.bySeries,
    numericChart,
    chartStart,
    chartEnd,
  ]);

  const normLimitRuntime = useMemo(() => {
    const map: Record<
      string,
      {
        status: "idle" | "loading" | "ready" | "error";
        error: string | null;
        lowerTagName: string | null;
        upperTagName: string | null;
      }
    > = {};
    for (const s of normLimitSeries) {
      map[s.seriesInstanceId] = { status: "ready", error: null, lowerTagName: s.tagName, upperTagName: s.tagName };
    }
    for (const [instanceId, message] of Object.entries(normLimitErrors)) {
      const existing = map[instanceId] ?? {
        status: "error" as const,
        error: null,
        lowerTagName: null,
        upperTagName: null,
      };
      map[instanceId] = { ...existing, status: "error", error: message };
    }
    for (const [instanceId, loading] of Object.entries(normLimitLoading)) {
      if (loading && !map[instanceId]) {
        map[instanceId] = { status: "loading", error: null, lowerTagName: null, upperTagName: null };
      }
    }
    return map;
  }, [normLimitSeries, normLimitErrors, normLimitLoading]);

  const displayedNormLimitSeries = normLimitSeries;

  const allPimsTagLimits = useMemo(() => {
    return [];
  }, [visualRules]);

  useEffect(() => {
    // Pims-tag legacy limits were replaced by norm limits; nothing to resolve here.
    if (allPimsTagLimits.length === 0) {
      limitAbortRef.current?.abort();
      setResolvedLimitSeries([]);
    }
  }, [allPimsTagLimits]);

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
        subtitle="Gráfico de linha com dados históricos do TimescaleDB"
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
                Ingestão: {piHealth.status}
              </span>
            ) : (
              <span className="badge bg-info" data-testid="pi-connection-loading">
                Verificando ingestão...
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
              <i className="bi bi-arrow-repeat me-1" /> Verificar ingestão
            </Button>
            <Button
              variant="primary"
              size="sm"
              className="btn-piad-primary"
              onClick={handleSubmit}
              disabled={query.loading || Boolean(periodPreview.error) || (filters.analysisModel !== "unit" && filters.analysisModel !== "cyclic")}
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
                onAnalysisModelChange={handleAnalysisModelChange}
                timeAnalysisRule={filters.timeAnalysisRule}
                onTimeAnalysisRuleChange={(timeAnalysisRule) => setFilters((prev) => ({ ...prev, timeAnalysisRule }))}
                mode={filters.mode}
                onModeChange={(mode) => setFilters((prev) => ({ ...prev, mode }))}
                interval={filters.interval}
                onIntervalChange={(value) => setFilters((prev) => ({ ...prev, interval: value }))}
                resolutionMode={filters.resolutionMode}
                onResolutionModeChange={(value) => setFilters((prev) => ({ ...prev, resolutionMode: value }))}
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
                visualConfiguration={
                  <VisualRulesPanel
                    state={visualRules}
                    series={visualSeriesOptions}
                    onChange={setVisualRules}
                    onAddNormLimit={handleAddNormLimit}
                    onRemoveNormLimit={handleRemoveNormLimit}
                    normLimits={normLimitRuntime}
                    selectedPiTag={
                      selectedPiTagForNorm
                        ? {
                            id: selectedPiTagForNorm.id,
                            lowerLimitTag: selectedPiTagForNorm.lower_limit_tag ?? null,
                            upperLimitTag: selectedPiTagForNorm.upper_limit_tag ?? null,
                          }
                        : null
                    }
                  />
                }
                metricConfiguration={
                  <MetricConfigurationPanel
                    configuration={metricConfiguration}
                    series={metricSeriesOptions}
                    onChange={setMetricConfiguration}
                  />
                }
                advancedFilters={
                  <AdvancedFiltersPanel
                    initialExpanded={false}
                    configuration={filters.filterConfiguration}
                    enabled={filters.filtersEnabled}
                    tagOptions={advancedFilterTagOptions}
                    summary={filterResult?.summary ?? null}
                    ruleResults={filterResult?.ruleResults ?? []}
                    hasData={query.timeSeries !== null}
                    onChange={handleFilterConfigurationChange}
                    analysisTags={extraAnalysisTags}
                    conflictedVariables={conflictedVariables}
                    dynamicFilters={dynamicFilters}
                    onDynamicFilterChange={setDynamicFilters}
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
                errorMessage={filterValidationError}
              />
            </Card.Body>
          </Card>
        </Col>
        <Col xs={12} lg={8} xl={9}>
          <Card className="piad-card mb-3">
            <Card.Body ref={chartContainerRef}>
              {query.timeSeries?.query_execution?.data_available_until && query.timeSeries.query_execution.effective_end &&
              query.timeSeries.query_execution.requested_end !== query.timeSeries.query_execution.effective_end ? (
                <Alert variant="info" data-testid="data-available-until">
                  Dados disponíveis até: {new Date(query.timeSeries.query_execution.data_available_until).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })}
                </Alert>
              ) : null}
              {zoomQuery.errorMessage && query.timeSeries ? (
                <Alert variant="warning" data-testid="zoom-coverage-error">
                  <div className="fw-semibold mb-1">Detalhamento do zoom indisponível</div>
                  <div>{zoomQuery.errorMessage}</div>
                  {zoomQuery.errorDetails?.requested_period ? (
                    <div className="small mt-1">
                      Janela solicitada: {new Date(zoomQuery.errorDetails.requested_period.start).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })} até {new Date(zoomQuery.errorDetails.requested_period.end).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })}
                    </div>
                  ) : null}
                  {zoomQuery.errorDetails?.reload_available && user?.role === "admin" ? (
                    <Button
                      variant="warning"
                      size="sm"
                      className="mt-2"
                      onClick={() => openHistoricalReload(zoomQuery.errorDetails)}
                      data-testid="zoom-historical-reload-button"
                    >
                      Recarregar período
                    </Button>
                  ) : zoomQuery.errorDetails?.reload_available ? (
                    <div className="small mt-2">A cobertura precisa ser carregada por um administrador.</div>
                  ) : null}
                </Alert>
              ) : null}
              {query.loading ? (
                <div className="piad-loading" data-testid="chart-loading">
                  <span className="spinner-border spinner-border-sm me-2" /> Carregando serie temporal...
                </div>
              ) : query.errorMessage ? (
                <Alert variant="danger" className="mb-0" data-testid="chart-error">
                  <div className="fw-semibold mb-1">Falha na consulta</div>
                  <div>{query.errorMessage}</div>
                  {query.errorDetails?.mode || query.errorDetails?.resolution ? (
                    <div className="small mt-2">
                      Modo: {query.errorDetails.mode ?? filters.mode} · Resolução: {query.errorDetails.resolution ?? "automática"}
                    </div>
                  ) : null}
                  {query.errorDetails?.requested_period ? (
                    <div className="small">
                      Período: {new Date(query.errorDetails.requested_period.start).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })} até {new Date(query.errorDetails.requested_period.end).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })}
                    </div>
                  ) : null}
                  {query.errorDetails?.data_available_until ? (
                    <div className="small">Dados disponíveis até: {new Date(query.errorDetails.data_available_until).toLocaleString("pt-BR", { timeZone: APPLICATION_TIMEZONE })}</div>
                  ) : null}
                  {query.errorDetails?.reload_available && user?.role === "admin" ? (
                    <Button variant="warning" size="sm" className="mt-2 me-2" onClick={() => openHistoricalReload()} data-testid="historical-reload-button">
                      Recarregar período
                    </Button>
                  ) : query.errorDetails?.reload_available ? (
                    <div className="small mt-2">A cobertura precisa ser carregada por um administrador.</div>
                  ) : null}
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
                <div data-testid="chart-groups" className="position-relative">
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
                      {Object.keys(normLimitErrors).length > 0 ? (
                        <Alert variant="warning" className="py-2 mb-2" data-testid="limit-errors">
                          <div className="fw-semibold mb-1">Limites com problema</div>
                          <ul className="mb-0 ps-3">
                            {Object.entries(normLimitErrors).map(([limitId, message]) => (
                              <li key={limitId}>{message}</li>
                            ))}
                          </ul>
                        </Alert>
                      ) : null}
                      <TimeSeriesChart
                        chart={numericChart}
                        equipment={equipmentTitle}
                        start={chartStart}
                        end={chartEnd}
                        baseStart={baseStart}
                        baseEnd={baseEnd}
                        isZoomed={Boolean(zoomedRange)}
                        mode={filters.mode}
                        titleLabel={
                          filters.visualization === "line" ? "Linha temporal" : undefined
                        }
                        visualRules={visualRules}
                        limitSeries={resolvedLimitSeries}
                        normLimitSeries={displayedNormLimitSeries}
                        umSeries={umChartSeries}
                        syncGroup={TIME_CHART_SYNC_GROUP}
                        enableZoomKeyboardUndo
                        onVisibleWindowChange={handleVisibleWindowChange}
                        onRestoreInitialZoom={handleRestoreInitialZoom}
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
                        baseStart={baseStart}
                        baseEnd={baseEnd}
                        isZoomed={Boolean(zoomedRange)}
                        mode={filters.mode}
                        visualRules={visualRules}
                        syncGroup={TIME_CHART_SYNC_GROUP}
                        enableZoomKeyboardUndo={!numericChart || filters.visualization === "states"}
                        onVisibleWindowChange={handleVisibleWindowChange}
                        onRestoreInitialZoom={handleRestoreInitialZoom}
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
                zoomedStartLocal={zoomedLabels ? zoomedLabels[0] : undefined}
                zoomedEndLocal={zoomedLabels ? zoomedLabels[1] : undefined}
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
