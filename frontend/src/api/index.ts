import { httpClient } from "./http";
import type {
  Equipment,
  EquipmentCreate,
  EquipmentUpdate,
  ListParams,
  PaginatedResponse,
  PiHealth,
  PiTag,
  PiTagCreate,
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
  VariableType,
  VariableTypeCreate,
  VariableTypeUpdate,
  AuthUser,
  AdminUserCreate,
  AdminUserUpdate,
  VisualConfiguration,
  VisualConfigurationDocument,
  VisualConfigurationVersion,
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
};

export const piApi = {
  health() {
    return httpClient.get<PiHealth>("/pi/health");
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
      query_id?: string;
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
      query_id: params.query_id,
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
