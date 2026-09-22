import { useState } from "react";
import { Button, Col, Form, OverlayTrigger, Popover, Row } from "react-bootstrap";
import type {
  DataFilterConfiguration,
  DataFilterRule,
  DynamicAnalysisFilter,
  FilterApplicationSummary,
  FilterRuleResult,
  NumericFilterOperator,
  SectionAnalysisTag,
} from "../types";
import { STEEL_MODELS } from "../constants/steelModels";
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
    analysisRole?: "width" | "um" | "thickness";
  }>;
  summary: FilterApplicationSummary | null;
  ruleResults: FilterRuleResult[];
  hasData: boolean;
  initialExpanded?: boolean;
  onChange: (configuration: DataFilterConfiguration) => void;
  analysisTags?: SectionAnalysisTag[];
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
      { key: "steelModel", label: "Modelo do Aço", control: "select", options: STEEL_MODELS },
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
const ANALYSIS_ROLE_BY_FIELD: Partial<Record<string, "width" | "um" | "thickness">> = {
  umCode: "um",
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

const FIXED_VARIABLE_TYPE_CODES = new Set(["LARGURA", "ESPESSURA", "UM"]);

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

  return {
    id: `named-filter:${field.key}`,
    kind: "text",
    enabled: true,
    tagId: sourceTag.id,
    seriesInstanceId: sourceTag.seriesInstanceId,
    operator: "contains",
    value: value.trim(),
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
  dynamicFilters = {},
  onDynamicFilterChange,
}: AdvancedFiltersPanelProps) {
  const [expanded, setExpanded] = useState(initialExpanded);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState(false);
  const [unmappedFields, setUnmappedFields] = useState<string[]>([]);
  const [stringValidationErrors, setStringValidationErrors] = useState<Record<number, string | undefined>>({});

  const nonFixedAnalysisTags = analysisTags.filter(
    (t) => !FIXED_VARIABLE_TYPE_CODES.has((t.variable_type_code || "").toUpperCase()),
  );

  const handleRealMinChange = (variableTypeId: number, rawVal: string) => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const min = rawVal.trim() !== "" ? parseFloat(rawVal) : null;
    const next: DynamicAnalysisFilter = { ...current, min: Number.isNaN(min) ? null : min };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
  };

  const handleRealMaxChange = (variableTypeId: number, rawVal: string) => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const max = rawVal.trim() !== "" ? parseFloat(rawVal) : null;
    const next: DynamicAnalysisFilter = { ...current, max: Number.isNaN(max) ? null : max };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
  };

  const handleDigitalChange = (variableTypeId: number, val: "ALL" | "ON" | "OFF") => {
    const current = dynamicFilters[variableTypeId] ?? { variable_type_id: variableTypeId };
    const next: DynamicAnalysisFilter = { ...current, value: val };
    onDynamicFilterChange?.({ ...dynamicFilters, [variableTypeId]: next });
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
                            {(field.options ?? []).map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </Form.Select>
                        ) : (
                          <Form.Control
                            size="sm"
                            disabled={!enabled}
                            type={field.control === "number" ? "number" : "text"}
                            step={field.control === "number" ? "any" : undefined}
                            list={isSteelModel ? "steel-model-options" : undefined}
                            value={draft[field.key] ?? ""}
                            onChange={(event) => setValue(field.key, event.target.value)}
                            placeholder={field.control === "number" ? "Valor" : "Digite ou selecione"}
                            data-testid={fieldTestId(field.key)}
                          />
                        )}
                        {isSteelModel ? (
                          <datalist id="steel-model-options">
                            {STEEL_MODELS.map((model) => <option key={model} value={model} />)}
                          </datalist>
                        ) : null}
                      </Form.Group>
                    </Col>
                  );
                })}
              </Row>
            </section>
          ))}

          {nonFixedAnalysisTags.length > 0 && (
            <section className="named-filter-section" data-testid="named-filter-group-section-variables">
              <h6 className="named-filter-section-title">Variáveis da Seção</h6>
              <Row className="g-2">
                {nonFixedAnalysisTags.map((tag) => {
                  const filterVal = dynamicFilters[tag.variable_type_id];
                  return (
                    <Col key={tag.id} xs={12} md={6}>
                      <Form.Group controlId={`dynamic-filter-${tag.variable_type_id}`}>
                        <div className="d-flex align-items-center justify-content-between mb-1">
                          <Form.Label className="mb-0 small fw-semibold">
                            {tag.variable_type_name}{" "}
                            <span className="text-muted fw-normal">({tag.pi_tag_name})</span>
                          </Form.Label>
                          {tag.filter_data_type === "STRING" && (
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
                          )}
                        </div>

                        {tag.filter_data_type === "REAL" && (
                          <Row className="g-1">
                            <Col xs={6}>
                              <Form.Control
                                size="sm"
                                type="number"
                                step="any"
                                placeholder="Mínimo"
                                disabled={!enabled}
                                value={filterVal?.min ?? ""}
                                onChange={(e) => handleRealMinChange(tag.variable_type_id, e.target.value)}
                                data-testid={`dynamic-filter-min-${tag.variable_type_id}`}
                              />
                            </Col>
                            <Col xs={6}>
                              <Form.Control
                                size="sm"
                                type="number"
                                step="any"
                                placeholder="Máximo"
                                disabled={!enabled}
                                value={filterVal?.max ?? ""}
                                onChange={(e) => handleRealMaxChange(tag.variable_type_id, e.target.value)}
                                data-testid={`dynamic-filter-max-${tag.variable_type_id}`}
                              />
                            </Col>
                          </Row>
                        )}

                        {tag.filter_data_type === "DIGITAL" && (
                          <Form.Select
                            size="sm"
                            disabled={!enabled}
                            value={filterVal?.value ?? "ALL"}
                            onChange={(e) =>
                              handleDigitalChange(
                                tag.variable_type_id,
                                e.target.value as "ALL" | "ON" | "OFF",
                              )
                            }
                            data-testid={`dynamic-filter-digital-${tag.variable_type_id}`}
                          >
                            <option value="ALL">Todos</option>
                            <option value="ON">Ligado (On)</option>
                            <option value="OFF">Desligado (Off)</option>
                          </Form.Select>
                        )}

                        {tag.filter_data_type === "STRING" && (
                          <>
                            <Form.Control
                              size="sm"
                              type="text"
                              placeholder="Digite valor ou expressão..."
                              disabled={!enabled}
                              value={filterVal?.expression ?? ""}
                              onChange={(e) => handleStringChange(tag.variable_type_id, e.target.value)}
                              isInvalid={Boolean(stringValidationErrors[tag.variable_type_id])}
                              data-testid={`dynamic-filter-string-${tag.variable_type_id}`}
                            />
                            {stringValidationErrors[tag.variable_type_id] && (
                              <Form.Control.Feedback type="invalid">
                                {stringValidationErrors[tag.variable_type_id]}
                              </Form.Control.Feedback>
                            )}
                          </>
                        )}
                      </Form.Group>
                    </Col>
                  );
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
