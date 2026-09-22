import { httpClient } from "./http";
import type {
  ClassificationTag,
  Equipment,
  EquipmentCreate,
  EquipmentUpdate,
  ListParams,
  PaginatedResponse,
  PiHealth,
  PiTag,
  PiTagCreate,
  PiTagNormLimitsResponse,
  PiTagUpdate,
  PiTagValidationBatchResponse,
  PiTagValidationResult,
  Section,
  SectionCreate,
  SectionUpdate,
  TimeSeries,
  TimeSeriesComparison,
  TimeSeriesComparisonRequest,
  TimeSeriesMode,
  DynamicAnalysisFilter,
  VariableType,
  VariableTypeCreate,
  VariableTypeUpdate,
  AuthUser,
  AdminUserCreate,
  AdminUserUpdate,
  VisualConfiguration,
  VisualConfigurationDocument,
  VisualConfigurationVersion,
  CepAnalysisRequest,
  CepAnalysisAccepted,
  CepQueryResponse,
  CepQueryCancelled,
  CepVariableSeries,
  HistoricalReloadJob,
  HistoricalReloadRequest,
  HistoricalReloadSummary,
} from "../types";

export const authApi = {
  login(username: string, password: string) { return httpClient.post<AuthUser>("/auth/login", { username, password }); },
  logout() { return httpClient.post<void>("/auth/logout"); },
  me() { return httpClient.get<AuthUser>("/auth/me"); },
  changePassword(currentPassword: string, newPassword: string) { return httpClient.put<AuthUser>("/auth/change-password", { current_password: currentPassword, new_password: newPassword }); },
};

export const adminUsersApi = {
  list() { return httpClient.get<AuthUser[]>("/admin/users"); },
  create(payload: AdminUserCreate) { return httpClient.post<AuthUser>("/admin/users", payload); },
  update(id: string, payload: AdminUserUpdate) { return httpClient.put<AuthUser>(`/admin/users/${id}`, payload); },
  activate(id: string) { return httpClient.post<AuthUser>(`/admin/users/${id}/activate`); },
  deactivate(id: string) { return httpClient.post<AuthUser>(`/admin/users/${id}/deactivate`); },
  resetPassword(id: string, newPassword: string) { return httpClient.post<AuthUser>(`/admin/users/${id}/reset-password`, { new_password: newPassword }); },
};

export const historicalReloadApi = {
  create(payload: HistoricalReloadRequest) { return httpClient.post<HistoricalReloadJob[]>("/admin/historical-reloads", payload); },
  list() { return httpClient.get<HistoricalReloadJob[]>("/admin/historical-reloads", { limit: 500 }); },
  summary() { return httpClient.get<HistoricalReloadSummary>("/admin/historical-reloads/summary"); },
  cancel(id: number) { return httpClient.post<HistoricalReloadJob>(`/admin/historical-reloads/${id}/cancel`); },
  cancelBatch(jobIds: number[]) {
    return httpClient.post<HistoricalReloadJob[]>("/admin/historical-reloads/cancel-batch", { job_ids: jobIds });
  },
  clearTerminal() { return httpClient.delete<{ deleted: number }>("/admin/historical-reloads/terminal"); },
};

export const visualConfigurationsApi = {
  list() { return httpClient.get<VisualConfiguration[]>("/visual-configurations"); },
  get(id: string) { return httpClient.get<VisualConfiguration>(`/visual-configurations/${id}`); },
  create(name: string, document: VisualConfigurationDocument) { return httpClient.post<VisualConfiguration>("/visual-configurations", { name, document }); },
  update(id: string, expectedVersion: number, document: VisualConfigurationDocument) { return httpClient.put<VisualConfiguration>(`/visual-configurations/${id}`, { expected_version: expectedVersion, document }); },
  rename(id: string, expectedVersion: number, name: string) { return httpClient.post<VisualConfiguration>(`/visual-configurations/${id}/rename`, { expected_version: expectedVersion, name }); },
  history(id: string) { return httpClient.get<VisualConfigurationVersion[]>(`/visual-configurations/${id}/history`); },
  getVersion(id: string, version: number) { return httpClient.get<VisualConfigurationVersion>(`/visual-configurations/${id}/history/${version}`); },
  restore(id: string, expectedVersion: number, version: number) { return httpClient.post<VisualConfiguration>(`/visual-configurations/${id}/restore`, { expected_version: expectedVersion, version }); },
  remove(id: string) { return httpClient.delete<void>(`/visual-configurations/${id}`); },
};

function buildListQuery(params?: ListParams): Record<string, unknown> {
  if (!params) {
    return {};
  }
  return {
    page: params.page,
    page_size: params.page_size,
    search: params.search,
    active: params.active,
    equipment_id: params.equipment_id,
    section_id: params.section_id,
    variable_type_id: params.variable_type_id,
    validation_status: params.validation_status,
    include_dependencies: params.include_dependencies,
    process_type: params.process_type,
    group_code: params.group_code,
    classification_tag_id: params.classification_tag_id,
  };
}

export const equipmentsApi = {
  list(params?: ListParams) {
    return httpClient.get<PaginatedResponse<Equipment>>("/equipments", buildListQuery(params));
  },
  get(id: number) {
    return httpClient.get<Equipment>(`/equipments/${id}`);
  },
  create(payload: EquipmentCreate) {
    return httpClient.post<Equipment>("/equipments", payload);
  },
  update(id: number, payload: EquipmentUpdate) {
    return httpClient.put<Equipment>(`/equipments/${id}`, payload);
  },
  remove(id: number) {
    return httpClient.delete<void>(`/equipments/${id}`);
  },
};

export const sectionsApi = {
  list(params?: ListParams) {
    return httpClient.get<PaginatedResponse<Section>>("/sections", buildListQuery(params));
  },
  get(id: number) {
    return httpClient.get<Section>(`/sections/${id}`);
  },
  create(payload: SectionCreate) {
    return httpClient.post<Section>("/sections", payload);
  },
  update(id: number, payload: SectionUpdate) {
    return httpClient.put<Section>(`/sections/${id}`, payload);
  },
  remove(id: number) {
    return httpClient.delete<void>(`/sections/${id}`);
  },
};

export const variableTypesApi = {
  list(params?: ListParams) {
    return httpClient.get<PaginatedResponse<VariableType>>("/variable-types", buildListQuery(params));
  },
  get(id: number) {
    return httpClient.get<VariableType>(`/variable-types/${id}`);
  },
  create(payload: VariableTypeCreate) {
    return httpClient.post<VariableType>("/variable-types", payload);
  },
  update(id: number, payload: VariableTypeUpdate) {
    return httpClient.put<VariableType>(`/variable-types/${id}`, payload);
  },
  remove(id: number) {
    return httpClient.delete<void>(`/variable-types/${id}`);
  },
};

export const classificationTagsApi = {
  list(params?: { search?: string }) {
    const query = params?.search ? `?search=${encodeURIComponent(params.search)}` : "";
    return httpClient.get<ClassificationTag[]>(`/classification-tags${query}`);
  },
  get(id: number) {
    return httpClient.get<ClassificationTag>(`/classification-tags/${id}`);
  },
  create(payload: { name: string }) {
    return httpClient.post<ClassificationTag>("/classification-tags", payload);
  },
  remove(id: number) {
    return httpClient.delete<void>(`/classification-tags/${id}`);
  },
};

export const piTagsApi = {
  list(params?: ListParams) {
    return httpClient.get<PaginatedResponse<PiTag>>("/pi-tags", buildListQuery(params));
  },
  get(id: number) {
    return httpClient.get<PiTag>(`/pi-tags/${id}`);
  },
  create(payload: PiTagCreate) {
    return httpClient.post<PiTag>("/pi-tags", payload);
  },
  update(id: number, payload: PiTagUpdate) {
    return httpClient.put<PiTag>(`/pi-tags/${id}`, payload);
  },
  remove(id: number) {
    return httpClient.delete<void>(`/pi-tags/${id}`);
  },
  validate(id: number) {
    return httpClient.post<PiTagValidationResult>(`/pi-tags/${id}/validate`);
  },
  validateBatch(tagIds?: number[]) {
    return httpClient.post<PiTagValidationBatchResponse>("/pi-tags/validate", { tag_ids: tagIds ?? null });
  },
  getNormLimits(
    id: number,
    params: {
      start_time: string;
      end_time: string;
      mode: TimeSeriesMode;
      interval?: string;
      max_count?: number;
    },
    signal?: AbortSignal,
  ) {
    const query: Record<string, unknown> = {
      start_time: params.start_time,
      end_time: params.end_time,
      mode: params.mode,
    };
    if (params.interval) query.interval = params.interval;
    if (params.max_count !== undefined) query.max_count = params.max_count;
    return httpClient.get<PiTagNormLimitsResponse>(`/pi-tags/${id}/norm-limits`, query, signal);
  },
};

export const piApi = {
  health() {
    // The visualization reads the persisted worker state. It never pings PI.
    return httpClient.get<PiHealth>("/ingestion/health");
  },
};

export const timeSeriesApi = {
  compare(params: TimeSeriesComparisonRequest, signal?: AbortSignal) {
    return httpClient.post<TimeSeriesComparison>("/time-series/comparison", params, signal);
  },
  query(
    params: {
      tag_ids: number[];
      start_time: string;
      end_time: string;
      mode?: TimeSeriesMode;
      interval?: string;
      max_count?: number;
      resolution_mode?: string;
      target_points_per_tag?: number;
      relative_period?: boolean;
      query_id?: string;
      section_id?: number;
      analysis_filters?: DynamicAnalysisFilter[];
    },
    signal?: AbortSignal,
  ) {
    const query: Record<string, unknown> = {
      tag_ids: params.tag_ids,
      start_time: params.start_time,
      end_time: params.end_time,
      mode: params.mode,
      interval: params.interval,
      max_count: params.max_count,
      resolution_mode: params.resolution_mode,
      target_points_per_tag: params.target_points_per_tag,
      relative_period: params.relative_period,
      query_id: params.query_id,
      section_id: params.section_id,
      analysis_filters:
        params.analysis_filters && params.analysis_filters.length > 0
          ? JSON.stringify(params.analysis_filters)
          : undefined,
    };
    return httpClient.get<TimeSeries>("/time-series", query, signal);
  },
  cancelQuery(queryId: string) {
    return httpClient.post<{ query_id: string; cancelled: boolean }>(`/time-series/${queryId}/cancel`);
  },
  exportCsv(
    params: {
      tag_ids: number[];
      start_time: string;
      end_time: string;
      mode?: TimeSeriesMode;
      interval?: string;
    },
    signal?: AbortSignal,
  ) {
    const query: Record<string, unknown> = {
      tag_ids: params.tag_ids,
      start_time: params.start_time,
      end_time: params.end_time,
      mode: params.mode,
      interval: params.interval,
    };
    const url = httpClient.buildUrl("/time-series/export", query);
    const csrf = document.cookie.split("; ").find((entry) => entry.startsWith("pads_csrf="))?.split("=").slice(1).join("=");
    return fetch(url, { method: "POST", signal, credentials: "include", headers: csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : undefined });
  },
};

export const healthApi = {
  check() {
    return httpClient.get<{ status: string; application: string }>("/health");
  },
};

export const cepApi = {
  startAnalysis(payload: CepAnalysisRequest) {
    return httpClient.post<CepAnalysisAccepted>("/cep/analyze", payload);
  },
  getStatus(queryId: string) {
    return httpClient.get<CepQueryResponse>(`/cep/analyze/${queryId}`);
  },
  cancelAnalysis(queryId: string) {
    return httpClient.post<CepQueryCancelled>(`/cep/analyze/${queryId}/cancel`);
  },
  getVariableSeries(queryId: string, variableId: number) {
    return httpClient.get<CepVariableSeries>(`/cep/analyze/${queryId}/variables/${variableId}/series`);
  },
};
