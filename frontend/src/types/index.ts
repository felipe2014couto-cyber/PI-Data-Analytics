export type PiTagDataType = "NUMERIC" | "NON_NUMERIC";

export type HistoricalReloadMode = "recorded" | "interpolated";

export interface HistoricalReloadRequest {
  start_time: string;
  end_time: string;
  mode: HistoricalReloadMode;
  interval?: string;
  tag_id?: number;
  variable_id?: number;
  equipment_id?: number;
  section_id?: number;
  all_active?: boolean;
}

export interface HistoricalReloadJob {
  id: number;
  tag_id: number;
  mode: HistoricalReloadMode;
  interval: string | null;
  target_start: string;
  target_end: string;
  next_start: string | null;
  status: string;
  stage: string;
  progress_percent: number;
  attempts: number;
  error_message: string | null;
  lease_owner: string | null;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  next_attempt_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface HistoricalReloadSummary {
  total_active_tags: number;
  tags_with_data: number;
  tags_without_data: number;
  partial_tags: number;
  modes: Array<Record<string, unknown>>;
}

export type PiTagValidationStatus = "PENDING" | "VALID" | "INVALID" | "ERROR";

export interface Equipment {
  id: number;
  code: string;
  name: string;
  description: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EquipmentCreate {
  code: string;
  name: string;
  description?: string | null;
  active?: boolean;
}

export interface EquipmentUpdate {
  code?: string;
  name?: string;
  description?: string | null;
  active?: boolean;
}

export type VariableFilterDataType = "REAL" | "STRING" | "DIGITAL";

export interface SectionAnalysisTag {
  id: number;
  variable_type_id: number;
  variable_type_code: string;
  variable_type_name: string;
  filter_data_type: VariableFilterDataType;
  pi_tag_id: number;
  pi_tag_name: string;
}

export interface SectionAnalysisTagInput {
  variable_type_id: number;
  pi_tag_id: number;
}

export interface Section {
  id: number;
  equipment_id: number;
  code: string;
  name: string;
  description: string | null;
  active: boolean;
  process_type: string | null;
  group_code: string | null;
  classification_tag_ids: number[];
  width_tag_id: number | null;
  um_tag_id: number | null;
  thickness_tag_id: number | null;
  analysis_tags?: SectionAnalysisTag[];
  created_at: string;
  updated_at: string;
}

export interface SectionCreate {
  equipment_id: number;
  code: string;
  name: string;
  description?: string | null;
  active?: boolean;
  process_type?: string | null;
  group_code?: string | null;
  classification_tag_ids?: number[];
  width_tag_id?: number | null;
  um_tag_id?: number | null;
  thickness_tag_id?: number | null;
  analysis_tags?: SectionAnalysisTagInput[] | null;
}

export interface SectionUpdate {
  equipment_id?: number;
  code?: string;
  name?: string;
  description?: string | null;
  active?: boolean;
  process_type?: string | null;
  group_code?: string | null;
  classification_tag_ids?: number[];
  width_tag_id?: number | null;
  um_tag_id?: number | null;
  thickness_tag_id?: number | null;
  analysis_tags?: SectionAnalysisTagInput[] | null;
}

export interface VariableType {
  id: number;
  code: string;
  name: string;
  description: string | null;
  default_unit: string | null;
  filter_data_type: VariableFilterDataType;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface VariableTypeCreate {
  code: string;
  name: string;
  description?: string | null;
  default_unit?: string | null;
  filter_data_type: VariableFilterDataType;
  active?: boolean;
}

export interface VariableTypeUpdate {
  code?: string;
  name?: string;
  description?: string | null;
  default_unit?: string | null;
  filter_data_type?: VariableFilterDataType;
  active?: boolean;
}

export interface DynamicAnalysisFilter {
  variable_type_id: number;
  min?: number | null;
  max?: number | null;
  expression?: string;
  value?: "ALL" | "ON" | "OFF";
}

export type PiTagLifecycleStatus = "ACTIVE" | "INACTIVE" | "DELETION_PENDING";
export type PiTagBackfillStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export interface PiTag {
  id: number;
  equipment_id: number;
  section_id: number | null;
  variable_type_id: number;
  pi_server: string;
  pi_tag_name: string;
  lower_limit_tag?: string | null;
  upper_limit_tag?: string | null;
  pi_web_id: string | null;
  display_name: string;
  description: string | null;
  engineering_unit: string | null;
  data_type: PiTagDataType;
  active: boolean;
  lifecycle_status?: PiTagLifecycleStatus;
  backfill_status?: PiTagBackfillStatus;
  validation_status: PiTagValidationStatus;
  validation_message: string | null;
  validated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PiTagCreate {
  equipment_id: number;
  section_id?: number | null;
  variable_type_id: number;
  pi_server: string;
  pi_tag_name: string;
  lower_limit_tag?: string | null;
  upper_limit_tag?: string | null;
  display_name: string;
  description?: string | null;
  engineering_unit?: string | null;
  data_type?: PiTagDataType;
  active?: boolean;
}

export interface PiTagUpdate {
  equipment_id?: number;
  section_id?: number | null;
  variable_type_id?: number;
  pi_server?: string;
  pi_tag_name?: string;
  lower_limit_tag?: string | null;
  upper_limit_tag?: string | null;
  display_name?: string;
  description?: string | null;
  engineering_unit?: string | null;
  data_type?: PiTagDataType;
  active?: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiError {
  error: ApiErrorBody;
}

export type UserRole = "admin" | "user";
export interface AuthUser { id: string; username: string; role: UserRole; is_active: boolean; must_change_password: boolean; created_at: string; updated_at: string; last_login_at: string | null; }
export interface AdminUserCreate { username: string; password: string; role: UserRole; is_active?: boolean; }
export interface AdminUserUpdate { username?: string; role?: UserRole; is_active?: boolean; }

export interface ListParams {
  page?: number;
  page_size?: number;
  search?: string;
  active?: boolean;
  equipment_id?: number;
  section_id?: number;
  variable_type_id?: number;
  validation_status?: PiTagValidationStatus;
  include_dependencies?: boolean;
  process_type?: string;
  group_code?: string;
  classification_tag_id?: number;
}

// PI Web API integration types (Phase 2)

export type PiConnectionStatus = "connected" | "unavailable" | "not_configured" | "verifying";

export interface ClassificationTag {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface ClassificationTag {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface PiHealth {
  status: PiConnectionStatus;
  base_url: string | null;
  data_server: string | null;
  response_time_ms: number | null;
  message: string | null;
  error_code: string | null;
}

export interface PiTagValidationResult {
  tag_id: number;
  status: PiTagValidationStatus;
  web_id: string | null;
  message: string | null;
  validated_at: string | null;
  error_code?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface PiTagValidationBatchResponse {
  total: number;
  valid: number;
  invalid: number;
  error: number;
  results: PiTagValidationResult[];
}

export type TimeSeriesMode = "recorded" | "interpolated";
export type TimeAnalysisRule = "DEFAULT" | "MEDIA" | "MAXIMO" | "MIN" | "OOC";
export type ComparisonType = "periods" | "equipments" | "categories";

export type TimezoneId = "America/Sao_Paulo";
export type TimePreset = "PT15M" | "PT1H" | "PT8H" | "P1D" | "P7D";
export type RelativeTimeUnit = "minute" | "hour" | "day" | "week";
export type RelativeTimeReference = "now" | "startOfDay" | "endOfDay";

export type TimePeriod =
  | { kind: "preset"; preset: TimePreset }
  | { kind: "absolute"; start: string; end: string; timezone: TimezoneId }
  | {
      kind: "relative";
      amount: number;
      unit: RelativeTimeUnit;
      reference: RelativeTimeReference;
      timezone: TimezoneId;
    };

export type VisualizationType =
  | "automatic"
  | "line"
  | "states"
  | "histogram"
  | "boxplot"
  | "scatter"
  | "bars"
  | "singleValue";

export type AnalysisModel = "unit" | "cyclic" | "oee" | "downtime" | "quality";
export type SeriesAxis = "primary" | "secondary";
export type ScatterRole = "none" | "x" | "y";

export interface SeriesAssignment {
  tagId: number;
  seriesInstanceId?: string;
  order: number;
  lineAxis: SeriesAxis;
  scatterRole: ScatterRole;
}

export type VisualLineStyle = "solid" | "dashed" | "dotted";

export interface VisualLimitLine {
  id: string;
  value: number;
  label: string;
  color: string;
  lineStyle: VisualLineStyle;
  width: number;
  visible: boolean;
}

export interface VisualNormLimitConfiguration {
  enabled: boolean;
  lowerColor: string;
  upperColor: string;
  lineStyle: VisualLineStyle;
  width: number;
}

export interface SeriesVisualConfiguration {
  seriesInstanceId: string;
  limits: VisualLimitLine[];
  normLimit: VisualNormLimitConfiguration | null;
}

export interface PiTagNormLimitPoint {
  timestamp: string;
  value: number | null;
}

export interface PiTagNormLimitSeries {
  tag_name: string | null;
  points: PiTagNormLimitPoint[];
}

export interface PiTagNormLimitsResponse {
  source_tag_id: number;
  start_time: string;
  end_time: string;
  mode: "recorded" | "interpolated";
  interval: string | null;
  lower: PiTagNormLimitSeries;
  upper: PiTagNormLimitSeries;
  errors: string[];
}

export interface VisualRulesState {
  enabled: boolean;
  selectedSeriesInstanceId: string | null;
  bySeries: Record<string, SeriesVisualConfiguration>;
  queryMode?: TimeSeriesMode;
}

export interface VisualConfigurationSidebarState {
  filters: {
    analysisModel: AnalysisModel;
    equipmentId: number | null;
    sectionId: number | null;
    variableTypeId: number | null;
    timePeriod: TimePeriod;
    timezone: TimezoneId;
    mode: TimeSeriesMode;
    interval: string;
    maxCount?: number;
    resolutionMode: string;
    targetPointsPerTag?: number;
    ignoreBadQuality: boolean;
    visualization: VisualizationType;
    timeAnalysisRule?: TimeAnalysisRule;
    filtersEnabled?: boolean;
    filterConfiguration: DataFilterConfiguration;
  };
  selectedTagIds: number[];
  seriesAssignments: SeriesAssignment[];
  metricConfiguration: MetricConfiguration;
  comparison: {
    type: ComparisonType | "disabled";
    contextBEquipmentId: number | null;
    contextBCategoryId: number | null;
    contextBTagIds: number[];
    contextBStart: string;
    contextBEnd: string;
  };
}
export interface VisualConfigurationDocument { schema_version: 1; visual_rules: VisualRulesState; sidebar_state?: VisualConfigurationSidebarState; }
export interface VisualConfiguration { id: string; name: string; description: string | null; current_version: number; created_at: string; updated_at: string; document: VisualConfigurationDocument | null; }
export interface VisualConfigurationVersion { id: string; version: number; document: VisualConfigurationDocument; operation: string; created_at: string; }

export type AnalysisMetric =
  | "cp"
  | "cpk"
  | "cpkError"
  | "count"
  | "standardDeviation"
  | "standardDeviationError"
  | "meanAbsoluteError"
  | "meanSquaredError"
  | "maximum"
  | "maximumError"
  | "mean"
  | "meanError"
  | "minimum"
  | "minimumError"
  | "ooc"
  | "oocMaeMaximum"
  | "oocMaeMean"
  | "pc"
  | "rootMeanSquaredError"
  | "total";

export type MetricConfiguration =
  | { kind: "none" }
  | { kind: "single"; metric: "count" | "standardDeviation" | "maximum" | "mean" | "minimum" | "total" }
  | { kind: "specification"; metric: "cp" | "cpk" | "pc"; lowerSpecification: number | null; upperSpecification: number | null }
  | { kind: "control"; metric: "ooc"; lowerControl: number | null; upperControl: number | null }
  | { kind: "error"; metric: "standardDeviationError" | "meanAbsoluteError" | "meanSquaredError" | "maximumError" | "meanError" | "minimumError" | "rootMeanSquaredError"; actualTagId: number | null; referenceTagId: number | null; actualSeriesInstanceId?: string | null; referenceSeriesInstanceId?: string | null }
  | { kind: "errorCapability"; metric: "cpkError"; actualTagId: number | null; referenceTagId: number | null; actualSeriesInstanceId?: string | null; referenceSeriesInstanceId?: string | null; lowerSpecification: number | null; upperSpecification: number | null }
  | { kind: "oocError"; metric: "oocMaeMaximum" | "oocMaeMean"; actualTagId: number | null; referenceTagId: number | null; actualSeriesInstanceId?: string | null; referenceSeriesInstanceId?: string | null; lowerControl: number | null; upperControl: number | null };

export type MetricResultStatus = "ok" | "insufficientData" | "invalidConfiguration" | "calculationError";

interface MetricResultBase {
  metric: AnalysisMetric;
  seriesTagId: number | null;
  referenceTagId: number | null;
  seriesInstanceId?: string | null;
  referenceSeriesInstanceId?: string | null;
  unit: string | null;
  sampleCount: number;
  excludedCount: number;
  oocCount?: number;
  message: string;
}

export type MetricResult = MetricResultBase & (
  | { status: "ok"; value: number }
  | { status: Exclude<MetricResultStatus, "ok">; value: null }
);

export interface TimeSeriesPoint {
  timestamp: string;
  value: number | string | boolean | null;
  plot_min?: number | null;
  plot_max?: number | null;
  plot_first?: number | null;
  plot_last?: number | null;
  plot_avg?: number | null;
  plot_min_ts?: string | null;
  plot_max_ts?: string | null;
  plot_first_ts?: string | null;
  plot_last_ts?: string | null;
  plot_sample_count?: number | null;
  is_gapfilled?: boolean;
  has_previous_value?: boolean | null;
  good: boolean;
  questionable: boolean;
  substituted: boolean;
  elapsed_ms?: number | null;
  filtered_out?: boolean;
}

export interface TimeSeriesSeries {
  tag_id: number;
  tag_name: string;
  display_name: string;
  equipment: string | null;
  section: string | null;
  variable_type: string | null;
  unit: string | null;
  points: TimeSeriesPoint[];
  source_point_count?: number | null;
  returned_point_count?: number | null;
  sampled?: boolean | null;
  truncated?: boolean | null;
  chunk_count?: number | null;
  context_id?: "A" | "B" | null;
  context_label?: string | null;
  comparison_type?: ComparisonType | null;
  series_instance_id?: string | null;
  category?: string | null;
  original_start_time?: string | null;
  original_end_time?: string | null;
  original_tag_id?: number | null;
}

export interface QueryExecutionMetadata {
  source?: "timescaledb" | "pi_web_api" | "hybrid" | null;
  effective_source_mode?: string | null;
  strategy?: string | null;
  resolution_mode: string;
  requested_target_points_per_tag?: number | null;
  effective_target_points_per_tag?: number | null;
  raw_point_count?: number | null;
  dynamic_bucket_seconds?: number | null;
  effective_interval?: string | null;
  plot_aggregate?: string | null;
  chunk_count?: number | null;
  subdivided_chunk_count?: number | null;
  pi_request_count?: number | null;
  visual_total_points?: number | null;
  sampled: boolean;
  partial: boolean;
  duration_ms?: number | null;
  cache_hit?: boolean | null;
  cache_age_ms?: number | null;
  webid_cache_hits?: number | null;
  webid_cache_misses?: number | null;
  streamset_used?: boolean | null;
  streamset_mode?: string | null;
  batch_count?: number | null;
  batch_size?: number | null;
  individual_fallback_requests?: number | null;
  retry_count?: number | null;
  batch_used?: boolean | null;
  streamset_group_count?: number | null;
  batch_subrequest_count?: number | null;
  initial_window_count?: number | null;
  window_split_count?: number | null;
  pi_http_requests?: number | null;
  pi_points_received?: number | null;
  points_returned?: number | null;
  rate_limit_count?: number | null;
  complete?: boolean | null;
  truncated?: boolean | null;
  queue_wait_ms?: number | null;
  resolve_ms?: number | null;
  fetch_ms?: number | null;
  processing_ms?: number | null;
  total_ms?: number | null;
  query_id?: string | null;
  requested_end?: string | null;
  effective_end?: string | null;
  data_available_until?: string | null;
  freshness_lag_seconds?: number | null;
  is_stale?: boolean | null;
}

export interface TimeSeriesError {
  tag_id: number;
  code: string;
  message: string;
}

export interface TimeSeries {
  start_time: string;
  end_time: string;
  mode: TimeSeriesMode;
  series: TimeSeriesSeries[];
  errors: TimeSeriesError[];
  query_execution?: QueryExecutionMetadata | null;
}

export interface ComparisonContextRequest {
  context_id: "A" | "B";
  context_label: string;
  tag_ids: number[];
  start_time: string;
  end_time: string;
}

export interface TimeSeriesComparisonRequest {
  comparison_type: ComparisonType;
  contexts: [ComparisonContextRequest, ComparisonContextRequest];
  mode: TimeSeriesMode;
  interval?: string;
  max_count?: number;
  resolution_mode: string;
  target_points_per_tag: number;
  query_id: string;
}

export interface ComparisonContextResult {
  context_id: "A" | "B";
  context_label: string;
  start_time: string;
  end_time: string;
  time_series: TimeSeries | null;
  error: { code: string; message: string } | null;
  complete: boolean;
}

export interface TimeSeriesComparison {
  comparison_enabled: boolean;
  comparison_type: ComparisonType;
  contexts: ComparisonContextResult[];
  metadata: {
    comparison_enabled: boolean;
    comparison_type: ComparisonType;
    context_count: number;
    series_instance_count: number;
    points_received_by_context: Record<string, number>;
    points_returned_by_context: Record<string, number>;
    duration_ms_by_context: Record<string, number>;
    strategy_by_context: Record<string, string | null>;
    cache_hit_by_context: Record<string, boolean | null>;
    pi_requests_by_context?: Record<string, number>;
    duration_ms: number;
    complete: boolean;
    partial: boolean;
    query_id: string | null;
  };
}

// Phase 5.4 – Advanced filter types

export type NumericFilterOperator =
  | "equal"
  | "notEqual"
  | "greaterThan"
  | "greaterThanOrEqual"
  | "lessThan"
  | "lessThanOrEqual"
  | "between"
  | "outside";

export type TextFilterOperator =
  | "equal"
  | "notEqual"
  | "contains"
  | "startsWith"
  | "endsWith";

export type Weekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

export interface QualityFilterConfiguration {
  excludeBad: boolean;
  excludeQuestionable: boolean;
  excludeSubstituted: boolean;
}

export type DataFilterRule =
  | {
      id: string;
      kind: "numeric";
      enabled: boolean;
      tagId: number;
      seriesInstanceId?: string;
      operator: NumericFilterOperator;
      value: number | null;
      secondValue: number | null;
    }
  | {
      id: string;
      kind: "text";
      enabled: boolean;
      tagId: number;
      seriesInstanceId?: string;
      operator: TextFilterOperator;
      value: string;
      caseSensitive: boolean;
    }
  | {
      id: string;
      kind: "weekday";
      enabled: boolean;
      days: Weekday[];
      timezone: "America/Sao_Paulo";
    }
  | {
      id: string;
      kind: "timeRange";
      enabled: boolean;
      startTime: string;
      endTime: string;
      timezone: "America/Sao_Paulo";
    }
  | {
      id: string;
      kind: "excludeValue";
      enabled: boolean;
      tagId: number;
      seriesInstanceId?: string;
      valueType: "number" | "string" | "boolean";
      value: number | string | boolean;
      caseSensitive: boolean;
    };

export interface DataFilterConfiguration {
  quality: QualityFilterConfiguration;
  rules: DataFilterRule[];
}

export interface FilterApplicationSummary {
  receivedPoints: number;
  remainingPoints: number;
  removedPoints: number;
  removedByQuality: number;
  removedByNumeric: number;
  removedByText: number;
  removedByDateTime: number;
  removedByExclusion: number;
}

export interface FilterRuleResult {
  ruleId: string;
  removedPoints: number;
}

export interface FilterRuleError {
  ruleId?: string;
  message: string;
}

export interface FilterApplicationResult {
  filteredTimeSeries: TimeSeries;
  summary: FilterApplicationSummary;
  ruleResults: FilterRuleResult[];
  errors: FilterRuleError[];
}

// ---------------------------------------------------------------------------
// CEP Analysis types
// ---------------------------------------------------------------------------

export type CepQueryStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type CepAnalysisStatus = "completed" | "partial" | "failed";
export type CepVariableStatus = "processed" | "no_data" | "error";

export interface CepAnalysisRequest {
  start_time: string;
  end_time: string;
  equipment_id?: number | null;
  section_id?: number | null;
  variable_ids?: number[] | null;
  include_recorded?: boolean;
  interpolated_interval?: "1m" | "2m" | "5m" | "10m" | "15m" | "30m" | "1h";
}

export interface CepAnalysisAccepted {
  query_id: string;
  query_status: "pending";
  message: string;
  progress_percent: number;
  completed_variables: number;
  total_variables: number;
}

export interface CepQueryPending {
  query_id: string;
  query_status: "pending";
  progress_percent: number;
  completed_variables: number;
  total_variables: number;
}

export interface CepQueryRunning {
  query_id: string;
  query_status: "running";
  started_at: string;
  progress_percent: number;
  completed_variables: number;
  total_variables: number;
}

export interface CepQueryCancelled {
  query_id: string;
  query_status: "cancelled";
  message: string;
  progress_percent: number;
  completed_variables: number;
  total_variables: number;
}

export interface CepAnalysisSummary {
  analysis_status: CepAnalysisStatus;
  overall_pct: number | null;
  total_variables: number;
  conformant_variables: number;
  non_conformant_variables: number;
  no_data_variables: number;
  failed_variables: number;
  period_start: string;
  period_end: string;
}

export interface CepVariableResult {
  variable_id: number;
  code: string;
  name: string;
  equipment_id: number;
  section_id: number;
  variable_type_id: number;
  conformity_pct: number | null;
  total_points: number;
  conformant: number;
  non_conformant: number;
  no_data: number;
  status: CepVariableStatus;
}

export interface CepDiagnostic {
  tag_id: number;
  tag_name: string;
  variable_ids: number[];
  error_code: string;
  message: string;
}

export interface CepRecordedPoint {
  timestamp: string;
  value: number | null;
  good: boolean;
  questionable: boolean;
  substituted: boolean;
}

export interface CepRecordedSeries {
  tag_id: number;
  tag_name: string;
  variable_ids: number[];
  points: CepRecordedPoint[];
  truncated: boolean;
  source_point_count: number | null;
}

export interface CepAnalysisMetadata {
  pi_request_count: number | null;
  pi_points_received: number | null;
  points_returned: number | null;
  webid_cache_hits: number | null;
  webid_cache_misses: number | null;
  duration_ms: number | null;
  tags_processed: number | null;
  tags_failed: number | null;
  webid_resolved: number | null;
  recorded_total_point_limit: number;
  recorded_returned_point_count: number;
  recorded_total_limit_reached: boolean;
  recorded_tags_not_acquired: string[];
}

export interface CepAnalysisResult {
  query_id: string;
  query_status: "completed" | "failed";
  summary: CepAnalysisSummary;
  variables: CepVariableResult[];
  diagnostics: CepDiagnostic[];
  recorded_series?: CepRecordedSeries[] | null;
  metadata: CepAnalysisMetadata;
  progress_percent: number;
  completed_variables: number;
  total_variables: number;
}

export interface CepVariableSeriesPoint {
  timestamp: string;
  value: number | null;
  lower_limit: number | null;
  upper_limit: number | null;
}

export interface CepNonConformingPoint {
  timestamp: string;
  value: number;
  lower_limit: number | null;
  upper_limit: number | null;
}

export interface CepVariableSeries {
  variable_id: number;
  variable_name: string;
  analysis_tag: string;
  lower_limit: number | null;
  upper_limit: number | null;
  points: CepVariableSeriesPoint[];
  non_conforming_points: CepNonConformingPoint[];
}

export type CepQueryResponse =
  | CepQueryPending
  | CepQueryRunning
  | CepQueryCancelled
  | CepAnalysisResult;

export type DatabaseHealthStatus = "healthy" | "warning" | "critical" | "unavailable";

export interface DatabaseConnectionInfo {
  reachable: boolean;
  latency_ms: number | null;
  name: string | null;
  postgresql_version: string | null;
  timescaledb_version: string | null;
  uptime_seconds: number | null;
  alembic_revision: string | null;
}

export interface StorageRelationInfo {
  schema_name: string;
  relation_name: string;
  relation_type: string;
  data_bytes: number;
  index_bytes: number;
  total_bytes: number;
  data_human: string;
  index_human: string;
  total_human: string;
}

export interface StorageInfo {
  database_bytes: number;
  database_human: string;
  tables_bytes: number;
  tables_human: string;
  indexes_bytes: number;
  indexes_human: string;
  toast_bytes: number;
  toast_human: string;
  pi_samples_bytes: number | null;
  pi_samples_human: string | null;
  pi_backfill_bytes: number | null;
  pi_backfill_human: string | null;
  pi_ingestion_bytes: number | null;
  pi_ingestion_human: string | null;
  filesystem_available: boolean;
  filesystem_reason: string | null;
  largest_relations: StorageRelationInfo[];
}

export interface ConnectionsInfo {
  current: number;
  maximum: number;
  usage_percent: number;
  active: number;
  idle: number;
  idle_in_transaction: number;
  waiting: number;
  worker_leader_connections: number;
  long_transactions_count: number;
  oldest_transaction_seconds: number | null;
  long_queries_count: number;
  oldest_query_seconds: number | null;
  commits: number | null;
  rollbacks: number | null;
  deadlocks: number | null;
  temp_files: number | null;
  temp_bytes: number | null;
  temp_human: string | null;
  stats_reset: string | null;
}

export interface LocksInfo {
  total: number;
  granted: number;
  waiting: number;
  advisory_locks: number;
  blocked_sessions: number;
  oldest_wait_seconds: number | null;
}

export interface TimescaleInfo {
  available: boolean;
  version: string | null;
  hypertables: number;
  chunks: number;
  continuous_aggregates: number;
  total_jobs: number;
  failed_jobs: number;
  last_run_status: string | null;
  last_successful_finish: string | null;
  compression_enabled: boolean | null;
  retention_configured: boolean | null;
}

export interface FreshnessInfo {
  latest_sample_at: string | null;
  latest_recorded_sample_at: string | null;
  lag_seconds: number | null;
  oldest_watermark: string | null;
  newest_watermark: string | null;
  ingestion_states: number;
  tags_in_backoff: number;
  tags_with_failures: number;
  backfill_jobs_by_status: Record<string, number>;
  expired_backfill_leases: number;
  consecutive_backfill_failures: number;
  last_success_at: string | null;
}

export interface HealthCheckItem {
  name: string;
  status: DatabaseHealthStatus;
  message: string;
}

export interface DatabaseHealthResponse {
  status: DatabaseHealthStatus;
  checked_at: string;
  duration_ms: number;
  cached: boolean;
  database: DatabaseConnectionInfo;
  storage: StorageInfo;
  connections: ConnectionsInfo;
  locks: LocksInfo;
  timescale: TimescaleInfo;
  freshness: FreshnessInfo;
  checks: HealthCheckItem[];
  unavailable_metrics: string[];
}

