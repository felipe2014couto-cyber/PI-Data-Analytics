import { vi } from "vitest";
import type {
  Equipment,
  PaginatedResponse,
  PiHealth,
  PiTag,
  PiTagValidationBatchResponse,
  PiTagValidationResult,
  Section,
  VariableType,
} from "../../src/types";

export const equipmentFixture: Equipment = {
  id: 1,
  code: "RB3",
  name: "Equipamento RB3",
  description: "Descricao",
  active: true,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

export const sectionFixture: Section = {
  id: 1,
  equipment_id: 1,
  code: "FORNO",
  name: "Forno",
  description: null,
  active: true,
  width_tag_id: null,
  um_tag_id: null,
  thickness_tag_id: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

export const variableTypeFixture: VariableType = {
  id: 1,
  code: "TEMPERATURE",
  name: "Temperatura",
  description: null,
  default_unit: "C",
  active: true,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

export const piTagFixture: PiTag = {
  id: 1,
  equipment_id: 1,
  section_id: 1,
  variable_type_id: 1,
  pi_server: "PIMS",
  pi_tag_name: "RB3.FURNO.TEMP",
  pi_web_id: null,
  display_name: "Temperatura do forno",
  description: null,
  engineering_unit: "C",
  data_type: "NUMERIC",
  active: true,
  validation_status: "PENDING",
  validation_message: null,
  validated_at: null,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

export const connectedHealthFixture: PiHealth = {
  status: "connected",
  base_url: "https://pi.local/piwebapi",
  data_server: "PI_DATA",
  response_time_ms: 42,
  message: null,
  error_code: null,
};

export const notConfiguredHealthFixture: PiHealth = {
  status: "not_configured",
  base_url: null,
  data_server: null,
  response_time_ms: null,
  message: "PI Web API nao configurado.",
  error_code: null,
};

export function paginated<T>(items: T[], page = 1, pageSize = 10, total?: number): PaginatedResponse<T> {
  const t = total ?? items.length;
  return {
    items,
    page,
    page_size: pageSize,
    total: t,
    pages: Math.max(1, Math.ceil(t / pageSize)),
  };
}

export const apiMock = {
  authMe: vi.fn().mockResolvedValue({ id: "test-admin", username: "test-admin", role: "admin", is_active: true, must_change_password: false, created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00", last_login_at: null }),
  authLogin: vi.fn(),
  authLogout: vi.fn(),
  authChangePassword: vi.fn(),
  adminListUsers: vi.fn().mockResolvedValue([]),
  adminCreateUser: vi.fn(),
  adminUpdateUser: vi.fn(),
  adminActivateUser: vi.fn(),
  adminDeactivateUser: vi.fn(),
  adminResetPassword: vi.fn(),
  visualConfigList: vi.fn().mockResolvedValue([]),
  visualConfigGet: vi.fn(),
  visualConfigCreate: vi.fn(),
  visualConfigUpdate: vi.fn(),
  visualConfigRename: vi.fn(),
  visualConfigHistory: vi.fn(),
  visualConfigGetVersion: vi.fn(),
  visualConfigRestore: vi.fn(),
  visualConfigRemove: vi.fn(),
  healthCheck: vi.fn(),
  piHealth: vi.fn(),
  listEquipments: vi.fn(),
  createEquipment: vi.fn(),
  listSections: vi.fn(),
  createSection: vi.fn(),
  listVariableTypes: vi.fn(),
  createVariableType: vi.fn(),
  listPiTags: vi.fn(),
  createPiTag: vi.fn(),
  updatePiTag: vi.fn(),
  validatePiTag: vi.fn(),
  validateBatchPiTags: vi.fn(),
  timeSeriesQuery: vi.fn(),
  timeSeriesCompare: vi.fn(),
  cancelQuery: vi.fn(),
};

export function mockApiModule() {
  return {
    authApi: { me: apiMock.authMe, login: apiMock.authLogin, logout: apiMock.authLogout, changePassword: apiMock.authChangePassword },
    adminUsersApi: { list: apiMock.adminListUsers, create: apiMock.adminCreateUser, update: apiMock.adminUpdateUser, activate: apiMock.adminActivateUser, deactivate: apiMock.adminDeactivateUser, resetPassword: apiMock.adminResetPassword },
    visualConfigurationsApi: { list: apiMock.visualConfigList, get: apiMock.visualConfigGet, create: apiMock.visualConfigCreate, update: apiMock.visualConfigUpdate, rename: apiMock.visualConfigRename, history: apiMock.visualConfigHistory, getVersion: apiMock.visualConfigGetVersion, restore: apiMock.visualConfigRestore, remove: apiMock.visualConfigRemove },
    healthApi: {
      check: apiMock.healthCheck,
    },
    piApi: {
      health: apiMock.piHealth,
    },
    equipmentsApi: {
      list: apiMock.listEquipments,
      get: vi.fn(),
      create: apiMock.createEquipment,
      update: vi.fn(),
      remove: vi.fn(),
    },
    sectionsApi: {
      list: apiMock.listSections,
      get: vi.fn(),
      create: apiMock.createSection,
      update: vi.fn(),
      remove: vi.fn(),
    },
    variableTypesApi: {
      list: apiMock.listVariableTypes,
      get: vi.fn(),
      create: apiMock.createVariableType,
      update: vi.fn(),
      remove: vi.fn(),
    },
    piTagsApi: {
      list: apiMock.listPiTags,
      get: vi.fn(),
      create: apiMock.createPiTag,
      update: apiMock.updatePiTag,
      remove: vi.fn(),
      validate: apiMock.validatePiTag,
      validateBatch: apiMock.validateBatchPiTags,
    },
    timeSeriesApi: {
      query: apiMock.timeSeriesQuery,
      compare: apiMock.timeSeriesCompare,
      cancelQuery: apiMock.cancelQuery,
    },
  };
}

export function makeValidationResult(
  tagId: number,
  status: PiTagValidationResult["status"],
  overrides: Partial<PiTagValidationResult> = {},
): PiTagValidationResult {
  return {
    tag_id: tagId,
    status,
    web_id: status === "VALID" ? `W-${tagId}` : null,
    message: status === "VALID" ? "Tag localizada no PI Web API." : null,
    validated_at: "2026-07-15T12:00:00",
    error_code: null,
    metadata: null,
    ...overrides,
  };
}

export function makeBatchResult(
  items: Array<{ tagId: number; status: PiTagValidationResult["status"] }>,
): PiTagValidationBatchResponse {
  const results = items.map((item) => makeValidationResult(item.tagId, item.status));
  return {
    total: results.length,
    valid: results.filter((r) => r.status === "VALID").length,
    invalid: results.filter((r) => r.status === "INVALID").length,
    error: results.filter((r) => r.status === "ERROR").length,
    results,
  };
}
