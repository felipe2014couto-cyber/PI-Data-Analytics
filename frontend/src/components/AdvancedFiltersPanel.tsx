import { useEffect, useState } from "react";
import { Button, Col, Form, OverlayTrigger, Popover, Row } from "react-bootstrap";
import { piTagsApi } from "../api";
import type {
  AnalysisFilterType,
  DataFilterConfiguration,
  DataFilterRule,
  DynamicAnalysisFilter,
  FilterApplicationSummary,
  FilterRuleResult,
  NumericFilterOperator,
  SectionAnalysisTag,
  ConflictedVariable,
} from "../types";
import { validateStringFilter } from "../utils/stringFilter";

interface AdvancedFiltersPanelProps {
  configuration: DataFilterConfiguration;
  enabled: boolean;
  tagOptions: Array<{
    id: number;
    seriesInstanceId?: string;
    displayName: string;
    tagName: string;
    dataType: string;
    analysisRole?: "width" | "um" | "thickness" | "steelType";
  }>;
  summary: FilterApplicationSummary | null;
  ruleResults: FilterRuleResult[];
  hasData: boolean;
  initialExpanded?: boolean;
  onChange: (configuration: DataFilterConfiguration) => void;
  analysisTags?: SectionAnalysisTag[];
  conflictedVariables?: ConflictedVariable[];
  dynamicFilters?: Record<number, DynamicAnalysisFilter>;
  onDynamicFilterChange?: (filters: Record<number, DynamicAnalysisFilter>) => void;
}

type FilterControl = "text" | "number" | "select";

interface FilterField {
  key: string;
  label: string;
  control: FilterControl;
  options?: string[];
}

interface FilterGroup {
  key: string;
  title: string;
  fields: FilterField[];
}

const FIELD_GROUPS: FilterGroup[] = [
  {
    key: "product",
    title: "Produto e identificação",
    fields: [
      { key: "steelModel", label: "Modelo do Aço", control: "text" },
      { key: "umCode", label: "Código UM", control: "text" },
      { key: "thicknessMin", label: "Espessura mínima", control: "number" },
      { key: "thicknessMax", label: "Espessura máxima", control: "number" },
      { key: "widthMin", label: "Largura mínima", control: "number" },
      { key: "widthMax", label: "Largura máxima", control: "number" },
      { key: "group", label: "Grupo", control: "select", options: ["Operacional", "Produto"] },
    ],
  },
  {
    key: "production",
    title: "Produção e operação",
    fields: [
      { key: "shift", label: "Turno", control: "select", options: ["1º turno", "2º turno", "3º turno"] },
    ],
  },
  {
    key: "length",
    title: "Comprimento",
    fields: [
      { key: "lengthPercentMin", label: "Comprimento mínimo %", control: "number" },
      { key: "lengthPercentMax", label: "Comprimento máximo %", control: "number" },
    ],
  },
];

const ALL_FIELDS = FIELD_GROUPS.flatMap((group) => group.fields);
const ANALYSIS_ROLE_BY_FIELD: Partial<Record<string, "width" | "um" | "thickness" | "steelType">> = {
  umCode: "um",
  steelModel: "steelType",
  thicknessMin: "thickness",
  thicknessMax: "thickness",
  widthMin: "width",
  widthMax: "width",
};
const FIELD_ALIASES: Record<string, string[]> = {
  steelModel: ["modelo aço", "modelo do aço", "steel"],
  umCode: ["codigo um", "código um"],
  thicknessMin: ["espessura mínima", "espessura min", "espessura"],
  thicknessMax: ["espessura máxima", "espessura max", "espessura"],
  widthMin: ["largura mínima", "largura min", "largura"],
  widthMax: ["largura máxima", "largura max", "largura"],
  group: ["grupo"],
  shift: ["turno"],
  lengthPercentMin: ["comprimento mínimo %", "comprimento minimo %"],
  lengthPercentMax: ["comprimento máximo %", "comprimento maximo %"],
};

const FIXED_VARIABLE_TYPE_CODES = new Set(["LARGURA", "ESPESSURA", "UM", "TIPO DE ACO", "TIPO ACO", "STEEL TYPE", "STEEL MODEL", "MODELO DO ACO"]);

export function isFixedAnalysisTag(tag: SectionAnalysisTag): boolean {
  const code = (tag.variable_type_code || "").toUpperCase().trim();
  const name = (tag.variable_type_name || "").toUpperCase().trim();
  if (FIXED_VARIABLE_TYPE_CODES.has(code) || FIXED_VARIABLE_TYPE_CODES.has(name)) {
    return true;
  }
  const normalized = normalize(code + " " + name);
  return (
    normalized.includes("largura") ||
    normalized.includes("espessura") ||
    normalized.includes("width") ||
    normalized.includes("thickness") ||
    normalized.includes("um") ||
    normalized.includes("unidade metalurgica") ||
    normalized.includes("tipo de aco") ||
    normalized.includes("tipo aco") ||
    normalized.includes("steel type") ||
    normalized.includes("steel model") ||
    normalized.includes("modelo do aco")
  );
}

export const RETIRED_NAMED_FILTER_FIELDS: readonly string[] = [
  "umSequenceCode",
  "genealogyCode",
  "reprocess",
  "furnace",
  "deviation",
  "lineStatus",
  "backwardMaterialRemoval",
  "coilMovement",
  "reheating",
  "defectMachine",
  "defectCode",
  "defectDescription",
  "defectCriticality",
  "eventType",
  "stopCode",
  "stopNatureCode",
  "responsibleTeamCode",
  "inputThicknessMin",
  "inputThicknessMax",
  "carbonMin",
  "carbonMax",
  "lengthAbsoluteMin",
  "lengthAbsoluteMax",
];

export function stripRetiredNamedFilterRules<T extends { id: string }>(rules: T[]): T[] {
  return rules.filter((rule) => {
    if (typeof rule.id !== "string") return true;
    if (!rule.id.startsWith("named-filter:")) return true;
    const fieldKey = rule.id.slice("named-filter:".length);
    return !RETIRED_NAMED_FILTER_FIELDS.includes(fieldKey);
  });
}

function normalize(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function findSourceTag(
  field: FilterField,
  tagOptions: AdvancedFiltersPanelProps["tagOptions"],
) {
  const analysisRole = ANALYSIS_ROLE_BY_FIELD[field.key];
  if (analysisRole) {
    return tagOptions.find((tag) => tag.analysisRole === analysisRole);
  }
  const aliases = (FIELD_ALIASES[field.key] ?? [field.label]).map(normalize);
  return tagOptions.find((tag) => {
    const searchable = normalize(`${tag.displayName} ${tag.tagName}`);
    return aliases.some((alias) => searchable.includes(alias));
  });
}

function ruleForField(
  field: FilterField,
  value: string,
  secondValue: string,
  tagOptions: AdvancedFiltersPanelProps["tagOptions"],
  operatorOverride?: NumericFilterOperator,
): DataFilterRule | null {
  const sourceTag = findSourceTag(field, tagOptions);
  if (!sourceTag || !value.trim()) return null;

  if (field.control === "number") {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue)) return null;
    const numericSecondValue = secondValue.trim() ? Number(secondValue) : null;
    if (secondValue.trim() && !Number.isFinite(numericSecondValue)) return null;
    const operator: NumericFilterOperator = operatorOverride ?? (numericSecondValue === null
      ? "equal"
      : "between");
    return {
      id: `named-filter:${field.key}`,
      kind: "numeric",
      enabled: true,
      tagId: sourceTag.id,
      seriesInstanceId: sourceTag.seriesInstanceId,
      operator,
      value: numericValue,
      secondValue: numericSecondValue,
    };
  }

  const textValue = field.key === "steelModel"
    ? value.split(";").map((part) => part.trim()).filter(Boolean).join(";")
    : value.trim();
  if (!textValue) return null;
  return {
    id: `named-filter:${field.key}`,
    kind: "text",
    enabled: true,
    tagId: sourceTag.id,
    seriesInstanceId: sourceTag.seriesInstanceId,
    operator: field.key === "steelModel"
      ? (textValue.includes("*") || textValue.includes(";") ? "wildcard" : "equal")
      : "contains",
    value: textValue,
    caseSensitive: false,
  };
}

function fieldTestId(key: string): string {
  return `named-filter-${key}`;
}

export function AdvancedFiltersPanel({
  configuration,
  enabled,
  tagOptions,
  summary,
  hasData,
  initialExpanded = true,
  onChange,
  analysisTags = [],
  conflictedVariables = [],
  dynamicFilters = {},
  onDynamicFilterChange,
}: AdvancedFiltersPanelProps) {
  const [expanded, setExpanded] = useState(initialExpanded);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState(false);
  const [unmappedFields, setUnmappedFields] = useState<string[]>([]);
  const [stringValidationErrors, setStringValidationErrors] = useState<Record<number, string | undefined>>({});
  const [distinctOptionsByTag, setDistinctOptionsByTag] = useState<Record<number, string[]>>({});

  const nonFixedAnalysisTags = analysisTags.filter((t) => !isFixedAnalysisTag(t));

  useEffect(() => {
    setDraft((prev) => {
      const hasSectionKeys = Object.keys(prev).some((k) => k.startsWith("sectionTag_"));
      if (!hasSectionKeys) return prev;
      const next: Record<string, string> = {};
      for (const [k, v] of Object.entries(prev)) {
        if (!k.startsWith("sectionTag_")) {
          next[k] = v;
        }
      }
      return next;
    });
  }, [analysisTags]);

  useEffect(() => {
    const selectionTags = nonFixedAnalysisTags.filter(
      (t) => (t.filter_type === "SELECTION" || (!t.filter_type && t.filter_data_type === "DIGITAL")),
    );
    for (const tag of selectionTags) {
      const tagIds = tag.pi_tag_ids && tag.pi_tag_ids.length > 0 ? tag.pi_tag_ids : (tag.pi_tag_id ? [tag.pi_tag_id] : []);
      for (const pid of tagIds) {
        if (!distinctOptionsByTag[pid]) {
          piTagsApi
            .getDistinctValues(pid)
            .then((values) => {
              setDistinctOptionsByTag((prev) => ({ ...prev, [pid]: values }));
            })
            .catch((err) => {
              console.error(`Erro ao buscar valores distintos para tag ${pid}:`, err);
              setDistinctOptionsByTag((prev) => ({ ...prev, [pid]: [] }));
            });
        }
      }
    }
  }, [nonFixedAnalysisTags]);

  const handleRealMinChange = (variableTypeId: number, rawVal: string) => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const min = rawVal.trim() !== "" ? parseFloat(rawVal) : null;
    const next: DynamicAnalysisFilter = { ...current, min: Number.isNaN(min) ? null : min };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
    setValue(`sectionTag_${variableTypeId}_min`, rawVal);
  };

  const handleRealMaxChange = (variableTypeId: number, rawVal: string) => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const max = rawVal.trim() !== "" ? parseFloat(rawVal) : null;
    const next: DynamicAnalysisFilter = { ...current, max: Number.isNaN(max) ? null : max };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
    setValue(`sectionTag_${variableTypeId}_max`, rawVal);
  };

  const handleDigitalChange = (variableTypeId: number, val: "ALL" | "ON" | "OFF" | string) => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const isAll = val === "ALL" || val === "";
    const next: DynamicAnalysisFilter = {
      ...current,
      value: isAll ? undefined : (val as any),
      expression: isAll ? undefined : val,
    };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
    setValue(`sectionTag_${variableTypeId}`, isAll ? "" : val);
  };

  const handleStringChange = (variableTypeId: number, rawVal: string) => {
    const validation = validateStringFilter(rawVal);
    setStringValidationErrors((prev) => ({
      ...prev,
      [variableTypeId]: validation.isValid ? undefined : validation.error,
    }));
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const next: DynamicAnalysisFilter = { ...current, expression: rawVal };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
    setValue(`sectionTag_${variableTypeId}`, rawVal);
  };

  const applyDraft = (values: Record<string, string>, markApplied: boolean) => {
    const rules: DataFilterRule[] = [];
    const notMapped: string[] = [];

    for (const field of ALL_FIELDS) {
      const value = values[field.key] ?? "";
      const secondKey = field.key.endsWith("Min") ? field.key.replace(/Min$/, "Max") : "";
      const secondValue = secondKey ? (values[secondKey] ?? "") : "";
      if (!value.trim()) continue;
      if (field.key.endsWith("Max")) {
        const minimumKey = field.key.replace(/Max$/, "Min");
        if ((values[minimumKey] ?? "").trim()) continue;
      }
      const sourceTag = findSourceTag(field, tagOptions);
      const minimumKey = field.key.endsWith("Max") ? field.key.replace(/Max$/, "Min") : "";
      const rule = ruleForField(
        field,
        value,
        secondValue,
        tagOptions,
        field.control === "number" && minimumKey && !(values[minimumKey] ?? "").trim()
          ? "lessThanOrEqual"
          : undefined,
      );
      if (rule) {
        rules.push(rule);
      } else if (!sourceTag) {
        notMapped.push(field.label);
      }
    }

    // Process additional section analysis tags into rules
    for (const tag of nonFixedAnalysisTags) {
      const resolvedFilterType: AnalysisFilterType = tag.filter_type ?? (
        tag.filter_data_type === "REAL"
          ? "MIN_MAX"
          : tag.filter_data_type === "DIGITAL"
          ? "SELECTION"
          : "TEXT"
      );

      switch (resolvedFilterType) {
        case "SELECTION": {
          const val = values[`sectionTag_${tag.variable_type_id}`] ?? "";
          if (val.trim()) {
            const isNumeric = tag.filter_data_type === "REAL";
            rules.push({
              id: `section-filter:${tag.variable_type_id}`,
              kind: isNumeric ? "numeric" : "text",
              enabled: true,
              tagId: tag.pi_tag_id,
              sectionTagMap: tag.section_tag_map,
              operator: "equal",
              value: isNumeric ? Number(val) : val.trim(),
              caseSensitive: false,
            } as DataFilterRule);
          }
          break;
        }

        case "MIN_MAX": {
          const minValStr = values[`sectionTag_${tag.variable_type_id}_min`] ?? "";
          const maxValStr = values[`sectionTag_${tag.variable_type_id}_max`] ?? "";
          const minVal = minValStr.trim() !== "" ? Number(minValStr) : null;
          const maxVal = maxValStr.trim() !== "" ? Number(maxValStr) : null;
          const hasMin = minVal !== null && Number.isFinite(minVal);
          const hasMax = maxVal !== null && Number.isFinite(maxVal);

          if (hasMin && hasMax) {
            rules.push({
              id: `section-filter:${tag.variable_type_id}`,
              kind: "numeric",
              enabled: true,
              tagId: tag.pi_tag_id,
              sectionTagMap: tag.section_tag_map,
              operator: "between",
              value: minVal,
              secondValue: maxVal,
            });
          } else if (hasMin) {
            rules.push({
              id: `section-filter:${tag.variable_type_id}`,
              kind: "numeric",
              enabled: true,
              tagId: tag.pi_tag_id,
              sectionTagMap: tag.section_tag_map,
              operator: "greaterThanOrEqual",
              value: minVal,
              secondValue: null,
            });
          } else if (hasMax) {
            rules.push({
              id: `section-filter:${tag.variable_type_id}`,
              kind: "numeric",
              enabled: true,
              tagId: tag.pi_tag_id,
              sectionTagMap: tag.section_tag_map,
              operator: "lessThanOrEqual",
              value: maxVal,
              secondValue: null,
            });
          }
          break;
        }

        case "TEXT": {
          const textVal = values[`sectionTag_${tag.variable_type_id}`] ?? "";
          if (textVal.trim()) {
            rules.push({
              id: `section-filter:${tag.variable_type_id}`,
              kind: "text",
              enabled: true,
              tagId: tag.pi_tag_id,
              sectionTagMap: tag.section_tag_map,
              operator: "equal",
              value: textVal.trim(),
              caseSensitive: false,
            });
          }
          break;
        }
      }
    }

    onChange({ ...configuration, rules });
    setUnmappedFields(notMapped);
    setApplied(markApplied || rules.length > 0);
  };

  const setValue = (key: string, value: string) => {
    const next = { ...draft, [key]: value };
    setDraft(next);
    // O valor digitado já passa a integrar a configuração ativa. Assim o
    // botão global "Consultar" nunca executa com um rascunho desatualizado.
    applyDraft(next, false);
  };

  const applyFilters = () => applyDraft(draft, true);

  const clearFilters = () => {
    setDraft({});
    setUnmappedFields([]);
    setApplied(false);
    setStringValidationErrors({});
    onChange({ ...configuration, rules: [] });
    onDynamicFilterChange?.({});
  };

  const activeDraftCount = Object.values(draft).filter((value) => value.trim()).length;
  const activeDynamicCount = Object.values(dynamicFilters).filter((f) => {
    if (f.min !== null && f.min !== undefined) return true;
    if (f.max !== null && f.max !== undefined) return true;
    if (f.expression && f.expression.trim()) return true;
    if (f.value === "ON" || f.value === "OFF") return true;
    return false;
  }).length;
  const totalActiveCount = activeDraftCount + activeDynamicCount;

  return (
    <div data-testid="advanced-filters-panel" className="named-filters-panel">
      <Button
        variant="outline-info"
        size="sm"
        className="w-100 mb-2"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
        aria-controls="named-filters-content"
        data-testid="advanced-filters-toggle"
      >
        {expanded ? "▲" : "▼"} Filtros
      </Button>

      {expanded ? (
        <div id="named-filters-content" className="border rounded p-3 mb-2" data-testid="advanced-filters-content">
          <div className="small text-muted mb-3">
            Use primeiro os parâmetros obrigatórios e depois os filtros opcionais necessários para reduzir o universo.
          </div>
          {!enabled ? (
            <div className="alert alert-secondary small py-2 mb-3">
              Filtros desativados. Os valores preenchidos serão preservados, mas não serão aplicados à consulta.
            </div>
          ) : null}

          {FIELD_GROUPS.map((group) => (
            <section key={group.key} className="named-filter-section" data-testid={`named-filter-group-${group.key}`}>
              <h6 className="named-filter-section-title">{group.title}</h6>
              <Row className="g-2">
                {group.fields.map((field) => {
                  const isSteelModel = field.key === "steelModel";
                  const fieldOptions = field.options ?? [];
                  return (
                    <Col key={field.key} xs={12} md={6}>
                      <Form.Group controlId={fieldTestId(field.key)}>
                        <Form.Label>{field.label}</Form.Label>
                        {field.control === "select" ? (
                          <Form.Select
                            size="sm"
                            disabled={!enabled}
                            value={draft[field.key] ?? ""}
                            onChange={(event) => setValue(field.key, event.target.value)}
                            data-testid={fieldTestId(field.key)}
                          >
                            <option value="">Todos</option>
                            {fieldOptions.map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </Form.Select>
                        ) : (
                          <Form.Control
                            size="sm"
                            disabled={!enabled}
                            type={field.control === "number" ? "number" : "text"}
                            step={field.control === "number" ? "any" : undefined}
                            value={draft[field.key] ?? ""}
                            onChange={(event) => setValue(field.key, event.target.value)}
                            placeholder={field.control === "number" ? "Valor" : isSteelModel ? "Digite o aço" : "Digite ou selecione"}
                            data-testid={fieldTestId(field.key)}
                          />
                        )}
                        {isSteelModel ? (
                          <Form.Text>Use ; para vários aços e * antes, no meio ou depois. Ex.: P304A;P49*.</Form.Text>
                        ) : null}
                      </Form.Group>
                    </Col>
                  );
                })}
              </Row>
            </section>
          ))}

          {(nonFixedAnalysisTags.length > 0 || conflictedVariables.length > 0) && (
            <section
              className="named-filter-section"
              data-testid="named-filter-group-extra-filters"
              data-section="extra-filters"
            >
              <h6 className="named-filter-section-title">Filtros extras</h6>
              {conflictedVariables.map((cv) => (
                <div
                  key={cv.variableTypeId}
                  className="alert alert-warning py-1 px-2 small mb-2 d-flex align-items-center gap-2"
                  data-testid={`conflict-warning-${cv.variableTypeId}`}
                >
                  <i className="bi bi-exclamation-triangle-fill text-warning flex-shrink-0" />
                  <span>
                    A variável <strong>{cv.variableTypeName}</strong> possui configurações de filtro incompatíveis entre seções e não pode ser filtrada em conjunto em &ldquo;Todas as seções&rdquo;.
                  </span>
                </div>
              ))}
              <Row className="g-2">
                {nonFixedAnalysisTags.map((tag) => {
                  const resolvedFilterType: AnalysisFilterType = tag.filter_type ?? (
                    tag.filter_data_type === "REAL"
                      ? "MIN_MAX"
                      : tag.filter_data_type === "DIGITAL"
                      ? "SELECTION"
                      : "TEXT"
                  );
                  const filterVal = dynamicFilters[tag.variable_type_id];

                  switch (resolvedFilterType) {
                    case "SELECTION": {
                      let distinctOptions: string[];
                      if (tag.filter_data_type === "DIGITAL") {
                        distinctOptions = ["ON", "OFF"];
                      } else {
                        const tagIds = tag.pi_tag_ids && tag.pi_tag_ids.length > 0 ? tag.pi_tag_ids : (tag.pi_tag_id ? [tag.pi_tag_id] : []);
                        const optionsSet = new Set<string>();
                        for (const pid of tagIds) {
                          for (const opt of distinctOptionsByTag[pid] ?? []) {
                            optionsSet.add(opt);
                          }
                        }
                        distinctOptions = Array.from(optionsSet);
                        if (tag.filter_data_type === "REAL") {
                          distinctOptions.sort((a, b) => Number(a) - Number(b));
                        } else {
                          distinctOptions.sort((a, b) => a.localeCompare(b));
                        }
                      }
                      const currentVal =
                        draft[`sectionTag_${tag.variable_type_id}`] ??
                        (filterVal?.value && filterVal.value !== "ALL" ? filterVal.value : filterVal?.expression ?? "");
                      const tagLabelSuffix = tag.pi_tag_ids && tag.pi_tag_ids.length > 1
                        ? `(${tag.pi_tag_ids.length} tags)`
                        : tag.pi_tag_name
                        ? `(${tag.pi_tag_name})`
                        : "";
                      return (
                        <Col key={tag.id} xs={12} md={6}>
                          <Form.Group controlId={`dynamic-filter-${tag.variable_type_id}`}>
                            <Form.Label className="mb-1 small fw-semibold">
                              {tag.variable_type_name}{" "}
                              {tagLabelSuffix && <span className="text-muted fw-normal">{tagLabelSuffix}</span>}
                            </Form.Label>
                            <Form.Select
                              size="sm"
                              disabled={!enabled}
                              value={currentVal}
                              onChange={(e) => handleDigitalChange(tag.variable_type_id, e.target.value)}
                              data-testid={tag.filter_data_type === "DIGITAL" ? `dynamic-filter-digital-${tag.variable_type_id}` : `dynamic-filter-select-${tag.variable_type_id}`}
                            >
                              <option value="">Todos</option>
                              {distinctOptions.map((opt) => (
                                <option key={opt} value={opt}>
                                  {opt === "ON" ? "Ligado (On)" : opt === "OFF" ? "Desligado (Off)" : opt}
                                </option>
                              ))}
                            </Form.Select>
                          </Form.Group>
                        </Col>
                      );
                    }

                    case "MIN_MAX": {
                      const currentMin = draft[`sectionTag_${tag.variable_type_id}_min`] ?? (filterVal?.min !== null && filterVal?.min !== undefined ? String(filterVal.min) : "");
                      const currentMax = draft[`sectionTag_${tag.variable_type_id}_max`] ?? (filterVal?.max !== null && filterVal?.max !== undefined ? String(filterVal.max) : "");
                      const tagLabelSuffix = tag.pi_tag_ids && tag.pi_tag_ids.length > 1
                        ? `(${tag.pi_tag_ids.length} tags)`
                        : tag.pi_tag_name
                        ? `(${tag.pi_tag_name})`
                        : "";
                      return (
                        <Col key={tag.id} xs={12} md={6}>
                          <Form.Group controlId={`dynamic-filter-${tag.variable_type_id}`}>
                            <div className="mb-1 small fw-semibold">
                              {tag.variable_type_name}{" "}
                              {tagLabelSuffix && <span className="text-muted fw-normal">{tagLabelSuffix}</span>}
                            </div>
                            <Row className="g-1">
                              <Col xs={6}>
                                <Form.Label className="small text-muted mb-0" htmlFor={`dynamic-filter-min-${tag.variable_type_id}`}>
                                  {tag.variable_type_name} mínima
                                </Form.Label>
                                <Form.Control
                                  id={`dynamic-filter-min-${tag.variable_type_id}`}
                                  size="sm"
                                  type="number"
                                  step="any"
                                  placeholder="Valor"
                                  disabled={!enabled}
                                  value={currentMin}
                                  onChange={(e) => handleRealMinChange(tag.variable_type_id, e.target.value)}
                                  data-testid={`dynamic-filter-min-${tag.variable_type_id}`}
                                />
                              </Col>
                              <Col xs={6}>
                                <Form.Label className="small text-muted mb-0" htmlFor={`dynamic-filter-max-${tag.variable_type_id}`}>
                                  {tag.variable_type_name} máxima
                                </Form.Label>
                                <Form.Control
                                  id={`dynamic-filter-max-${tag.variable_type_id}`}
                                  size="sm"
                                  type="number"
                                  step="any"
                                  placeholder="Valor"
                                  disabled={!enabled}
                                  value={currentMax}
                                  onChange={(e) => handleRealMaxChange(tag.variable_type_id, e.target.value)}
                                  data-testid={`dynamic-filter-max-${tag.variable_type_id}`}
                                />
                              </Col>
                            </Row>
                          </Form.Group>
                        </Col>
                      );
                    }

                    case "TEXT": {
                      const currentText = draft[`sectionTag_${tag.variable_type_id}`] ?? filterVal?.expression ?? "";
                      const tagLabelSuffix = tag.pi_tag_ids && tag.pi_tag_ids.length > 1
                        ? `(${tag.pi_tag_ids.length} tags)`
                        : tag.pi_tag_name
                        ? `(${tag.pi_tag_name})`
                        : "";
                      return (
                        <Col key={tag.id} xs={12} md={6}>
                          <Form.Group controlId={`dynamic-filter-${tag.variable_type_id}`}>
                            <div className="d-flex align-items-center justify-content-between mb-1">
                              <Form.Label className="mb-0 small fw-semibold">
                                {tag.variable_type_name}{" "}
                                {tagLabelSuffix && <span className="text-muted fw-normal">{tagLabelSuffix}</span>}
                              </Form.Label>
                              <OverlayTrigger
                                trigger={["hover", "focus"]}
                                placement="left"
                                overlay={
                                  <Popover id={`popover-info-${tag.variable_type_id}`}>
                                    <Popover.Header as="h3">Sintaxe de Filtro</Popover.Header>
                                    <Popover.Body className="small">
                                      <div><strong>Exato:</strong> <code>P99</code></div>
                                      <div><strong>Múltiplos:</strong> <code>P99; P100; P101</code></div>
                                      <div><strong>Curingas:</strong> <code>P*</code>, <code>*99</code>, <code>*99*</code></div>
                                      <div><strong>Intervalo:</strong> <code>P1:P100</code> ou <code>ABC001:ABC050</code></div>
                                    </Popover.Body>
                                  </Popover>
                                }
                              >
                                <span
                                  role="button"
                                  tabIndex={0}
                                  className="text-info cursor-pointer ms-1"
                                  style={{ fontSize: "0.85rem" }}
                                  title="Ajuda sobre expressões de texto"
                                  data-testid={`info-popover-${tag.variable_type_id}`}
                                >
                                  <i className="bi bi-info-circle" />
                                </span>
                              </OverlayTrigger>
                            </div>
                            <Form.Control
                              size="sm"
                              type="text"
                              placeholder="Digite ou selecione"
                              disabled={!enabled}
                              value={currentText}
                              onChange={(e) => handleStringChange(tag.variable_type_id, e.target.value)}
                              isInvalid={Boolean(stringValidationErrors[tag.variable_type_id])}
                              data-testid={`dynamic-filter-string-${tag.variable_type_id}`}
                            />
                            {stringValidationErrors[tag.variable_type_id] && (
                              <Form.Control.Feedback type="invalid">
                                {stringValidationErrors[tag.variable_type_id]}
                              </Form.Control.Feedback>
                            )}
                          </Form.Group>
                        </Col>
                      );
                    }

                    default:
                      return null;
                  }
                })}
              </Row>
            </section>
          )}

          {unmappedFields.length > 0 ? (
            <div className="alert alert-warning small py-2 mt-3 mb-0" data-testid="named-filters-unmapped">
              Os campos abaixo foram guardados, mas ainda não têm uma tag PI correspondente entre as séries selecionadas: {unmappedFields.join(", ")}.
            </div>
          ) : null}

          <div className="d-flex flex-wrap gap-2 align-items-center mt-3">
            <Button variant="primary" size="sm" onClick={applyFilters} disabled={!enabled} data-testid="named-filters-apply">
              Aplicar filtros
            </Button>
            <Button variant="outline-secondary" size="sm" onClick={clearFilters} disabled={!enabled} data-testid="filter-reset">
              Limpar filtros
            </Button>
            {totalActiveCount > 0 ? <span className="small text-muted">{totalActiveCount} parâmetro(s) preenchido(s)</span> : null}
            {applied ? <span className="small text-success">Filtros aplicados</span> : null}
          </div>

          {summary ? (
            <div className="small border-top mt-3 pt-2" data-testid="filter-summary">
              <div>Recebidos: {summary.receivedPoints}</div>
              <div>Restantes: {summary.remainingPoints}</div>
              <div>Descartados: {summary.removedPoints}</div>
            </div>
          ) : hasData ? (
            <div className="small text-muted border-top mt-3 pt-2" data-testid="filter-summary-empty">
              Nenhum filtro aplicado aos dados.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
