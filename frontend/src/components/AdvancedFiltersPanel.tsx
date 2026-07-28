import { useState } from "react";
import { Button, Col, Form, Row } from "react-bootstrap";
import type {
  DataFilterConfiguration,
  DataFilterRule,
  FilterApplicationSummary,
  FilterRuleResult,
  NumericFilterOperator,
  QualityFilterConfiguration,
  TextFilterOperator,
  Weekday,
} from "../types";
import { APPLICATION_TIMEZONE } from "../utils/timePeriod";

interface AdvancedFiltersPanelProps {
  configuration: DataFilterConfiguration;
  tagOptions: Array<{ id: number; seriesInstanceId?: string; displayName: string; tagName: string; dataType: string }>;
  summary: FilterApplicationSummary | null;
  ruleResults: FilterRuleResult[];
  hasData: boolean;
  onChange: (configuration: DataFilterConfiguration) => void;
}

const WEEKDAY_LABELS: Record<Weekday, string> = {
  monday: "Segunda",
  tuesday: "Terça",
  wednesday: "Quarta",
  thursday: "Quinta",
  friday: "Sexta",
  saturday: "Sábado",
  sunday: "Domingo",
};

const WEEKDAY_ORDER: Weekday[] = [
  "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
];

const NUMERIC_OPERATORS: Array<{ value: NumericFilterOperator; label: string }> = [
  { value: "equal", label: "Igual" },
  { value: "notEqual", label: "Diferente" },
  { value: "greaterThan", label: "Maior que" },
  { value: "greaterThanOrEqual", label: "Maior ou igual" },
  { value: "lessThan", label: "Menor que" },
  { value: "lessThanOrEqual", label: "Menor ou igual" },
  { value: "between", label: "Entre" },
  { value: "outside", label: "Fora do intervalo" },
];

const TEXT_OPERATORS: Array<{ value: TextFilterOperator; label: string }> = [
  { value: "equal", label: "Igual" },
  { value: "notEqual", label: "Diferente" },
  { value: "contains", label: "Contém" },
  { value: "startsWith", label: "Começa com" },
  { value: "endsWith", label: "Termina com" },
];

let nextRuleId = 1;
function generateRuleId(): string {
  return `rule_${nextRuleId++}_${Date.now()}`;
}

function formatRuleDescription(rule: DataFilterRule, tagLabel: string): string {
  switch (rule.kind) {
    case "numeric": {
      const opLabels: Record<string, string> = {
        equal: "=", notEqual: "≠", greaterThan: ">", greaterThanOrEqual: "≥",
        lessThan: "<", lessThanOrEqual: "≤", between: "entre", outside: "fora",
      };
      const op = opLabels[rule.operator] ?? rule.operator;
      if (rule.operator === "between" || rule.operator === "outside") {
        return `${tagLabel}: ${op} ${rule.value} e ${rule.secondValue}`;
      }
      return `${tagLabel}: ${op} ${rule.value}`;
    }
    case "text": {
      const opLabels: Record<string, string> = {
        equal: "=", notEqual: "≠", contains: "contém", startsWith: "começa com", endsWith: "termina com",
      };
      const cs = rule.caseSensitive ? " (dif. maiúsc.)" : "";
      return `${tagLabel}: ${opLabels[rule.operator] ?? rule.operator} "${rule.value}"${cs}`;
    }
    case "weekday":
      return `Dias: ${rule.days.map((d) => WEEKDAY_LABELS[d]).join(", ")}`;
    case "timeRange":
      return `Horário: ${rule.startTime} até ${rule.endTime} (${APPLICATION_TIMEZONE})`;
    case "excludeValue": {
      const cs = rule.valueType === "string" && rule.caseSensitive ? " (dif. maiúsc.)" : "";
      return `Excluir ${tagLabel} = ${String(rule.value)}${cs}`;
    }
  }
}

export function AdvancedFiltersPanel({
  configuration,
  tagOptions,
  summary,
  ruleResults,
  hasData,
  onChange,
}: AdvancedFiltersPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const quality = configuration.quality;
  const rules = configuration.rules;

  const setQuality = (update: Partial<QualityFilterConfiguration>) => {
    onChange({ ...configuration, quality: { ...quality, ...update } });
  };

  const addRule = (rule: DataFilterRule) => {
    onChange({ ...configuration, rules: [...rules, rule] });
  };

  const updateRule = (ruleId: string, update: Partial<DataFilterRule>) => {
    onChange({
      ...configuration,
      rules: rules.map((r) => (r.id === ruleId ? ({ ...r, ...update } as DataFilterRule) : r)),
    });
  };

  const removeRule = (ruleId: string) => {
    onChange({ ...configuration, rules: rules.filter((r) => r.id !== ruleId) });
  };

  const resetFilters = () => {
    onChange({
      quality: { excludeBad: true, excludeQuestionable: false, excludeSubstituted: false },
      rules: [],
    });
  };

  const numericTagOptions = tagOptions.filter((t) => t.dataType === "NUMERIC");
  const textTagOptions = tagOptions.filter((t) => t.dataType === "NON_NUMERIC");
  const allTagOptions = tagOptions;

  const optionIdentity = (tag: { id: number; seriesInstanceId?: string }) => tag.seriesInstanceId ?? `tag:${tag.id}`;
  const tagLabel = (tagId: number, seriesInstanceId?: string): string => {
    const tag = tagOptions.find((t) => seriesInstanceId ? t.seriesInstanceId === seriesInstanceId : t.id === tagId);
    return tag ? `${tag.displayName} (${tag.tagName})` : `Tag #${tagId}`;
  };

  const ruleResultMap = new Map(ruleResults.map((r) => [r.ruleId, r.removedPoints]));

  const [newNumericSeriesId, setNewNumericSeriesId] = useState<string>(numericTagOptions[0] ? optionIdentity(numericTagOptions[0]) : "");
  const [newNumericOperator, setNewNumericOperator] = useState<NumericFilterOperator>("equal");
  const [newNumericValue, setNewNumericValue] = useState<string>("");
  const [newNumericSecondValue, setNewNumericSecondValue] = useState<string>("");

  const [newTextSeriesId, setNewTextSeriesId] = useState<string>(textTagOptions[0] ? optionIdentity(textTagOptions[0]) : "");
  const [newTextOperator, setNewTextOperator] = useState<TextFilterOperator>("equal");
  const [newTextValue, setNewTextValue] = useState<string>("");
  const [newTextCaseSensitive, setNewTextCaseSensitive] = useState(false);

  const [newExcludeSeriesId, setNewExcludeSeriesId] = useState<string>(allTagOptions[0] ? optionIdentity(allTagOptions[0]) : "");
  const [newExcludeValueType, setNewExcludeValueType] = useState<"number" | "string" | "boolean">("number");
  const [newExcludeValue, setNewExcludeValue] = useState<string>("");
  const [newExcludeCaseSensitive, setNewExcludeCaseSensitive] = useState(false);

  const [selectedWeekdays, setSelectedWeekdays] = useState<Weekday[]>([]);
  const [timeRangeStart, setTimeRangeStart] = useState("");
  const [timeRangeEnd, setTimeRangeEnd] = useState("");

  const needsSecondValue = newNumericOperator === "between" || newNumericOperator === "outside";

  const handleAddNumeric = () => {
    const selectedTag = numericTagOptions.find((tag) => optionIdentity(tag) === newNumericSeriesId);
    if (!selectedTag) return;
    const value = Number(newNumericValue);
    if (!Number.isFinite(value)) return;
    let secondValue: number | null = null;
    if (needsSecondValue) {
      secondValue = Number(newNumericSecondValue);
      if (!Number.isFinite(secondValue)) return;
    }
    addRule({
      id: generateRuleId(),
      kind: "numeric",
      enabled: true,
      tagId: selectedTag.id,
      seriesInstanceId: selectedTag.seriesInstanceId,
      operator: newNumericOperator,
      value,
      secondValue,
    });
    setNewNumericValue("");
    setNewNumericSecondValue("");
  };

  const handleAddText = () => {
    const selectedTag = textTagOptions.find((tag) => optionIdentity(tag) === newTextSeriesId);
    if (!selectedTag) return;
    if (!newTextValue.trim()) return;
    addRule({
      id: generateRuleId(),
      kind: "text",
      enabled: true,
      tagId: selectedTag.id,
      seriesInstanceId: selectedTag.seriesInstanceId,
      operator: newTextOperator,
      value: newTextValue,
      caseSensitive: newTextCaseSensitive,
    });
    setNewTextValue("");
  };

  const handleAddWeekday = () => {
    if (selectedWeekdays.length === 0) return;
    const existing = rules.find((r) => r.kind === "weekday");
    if (existing) {
      updateRule(existing.id, { days: selectedWeekdays } as Partial<DataFilterRule>);
    } else {
      addRule({
        id: generateRuleId(),
        kind: "weekday",
        enabled: true,
        days: selectedWeekdays,
        timezone: "America/Sao_Paulo",
      });
    }
  };

  const handleAddTimeRange = () => {
    if (!/^\d{1,2}:\d{2}$/.test(timeRangeStart) || !/^\d{1,2}:\d{2}$/.test(timeRangeEnd)) return;
    const existing = rules.find((r) => r.kind === "timeRange");
    if (existing) {
      updateRule(existing.id, { startTime: timeRangeStart, endTime: timeRangeEnd } as Partial<DataFilterRule>);
    } else {
      addRule({
        id: generateRuleId(),
        kind: "timeRange",
        enabled: true,
        startTime: timeRangeStart,
        endTime: timeRangeEnd,
        timezone: "America/Sao_Paulo",
      });
    }
  };

  const handleAddExclude = () => {
    const selectedTag = allTagOptions.find((tag) => optionIdentity(tag) === newExcludeSeriesId);
    if (!selectedTag) return;
    if (newExcludeValueType === "number") {
      const num = Number(newExcludeValue);
      if (!Number.isFinite(num)) return;
      addRule({
        id: generateRuleId(),
        kind: "excludeValue",
        enabled: true,
        tagId: selectedTag.id,
        seriesInstanceId: selectedTag.seriesInstanceId,
        valueType: "number",
        value: num,
        caseSensitive: false,
      });
    } else if (newExcludeValueType === "string") {
      if (!newExcludeValue.trim()) return;
      addRule({
        id: generateRuleId(),
        kind: "excludeValue",
        enabled: true,
        tagId: selectedTag.id,
        seriesInstanceId: selectedTag.seriesInstanceId,
        valueType: "string",
        value: newExcludeValue,
        caseSensitive: newExcludeCaseSensitive,
      });
    } else {
      if (newExcludeValue !== "true" && newExcludeValue !== "false") return;
      addRule({
        id: generateRuleId(),
        kind: "excludeValue",
        enabled: true,
        tagId: selectedTag.id,
        seriesInstanceId: selectedTag.seriesInstanceId,
        valueType: "boolean",
        value: newExcludeValue === "true",
        caseSensitive: false,
      });
    }
    setNewExcludeValue("");
  };

  return (
    <div data-testid="advanced-filters-panel">
      <Button
        variant="outline-info"
        size="sm"
        className="w-100 mb-2"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        data-testid="advanced-filters-toggle"
      >
        {expanded ? "▲" : "▼"} Filtros
      </Button>
      {expanded && (
        <div className="border rounded p-3 mb-2" data-testid="advanced-filters-content">
          <Row className="g-3">
            <Col xs={12}><h6 className="mb-1">Qualidade</h6></Col>
            <Col xs={4}>
              <Form.Check
                type="switch"
                id="filter-exclude-bad"
                label="Excluir qualidade ruim"
                checked={quality.excludeBad}
                onChange={(e) => setQuality({ excludeBad: e.target.checked })}
                data-testid="filter-exclude-bad"
              />
            </Col>
            <Col xs={4}>
              <Form.Check
                type="switch"
                id="filter-exclude-questionable"
                label="Excluir questionáveis"
                checked={quality.excludeQuestionable}
                onChange={(e) => setQuality({ excludeQuestionable: e.target.checked })}
                data-testid="filter-exclude-questionable"
              />
            </Col>
            <Col xs={4}>
              <Form.Check
                type="switch"
                id="filter-exclude-substituted"
                label="Excluir substituídos"
                checked={quality.excludeSubstituted}
                onChange={(e) => setQuality({ excludeSubstituted: e.target.checked })}
                data-testid="filter-exclude-substituted"
              />
            </Col>
          </Row>

          <hr className="my-2" />

          <h6 className="mb-2">Filtros do eixo Y</h6>
          <Row className="g-2 mb-2">
            <Col xs={12} sm={6} md={3}>
              <Form.Group controlId="numeric-tag">
                <Form.Label>Tag</Form.Label>
                <Form.Select
                  size="sm"
                  value={newNumericSeriesId}
                  onChange={(e) => setNewNumericSeriesId(e.target.value)}
                  data-testid="filter-numeric-tag"
                >
                  {numericTagOptions.map((tag) => (
                    <option key={optionIdentity(tag)} value={optionIdentity(tag)}>{tag.displayName}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="numeric-operator">
                <Form.Label>Tipo</Form.Label>
                <Form.Select
                  size="sm"
                  value={newNumericOperator}
                  onChange={(e) => setNewNumericOperator(e.target.value as NumericFilterOperator)}
                  data-testid="filter-numeric-operator"
                >
                  <option value="numeric">Numérico</option>
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="numeric-operator-select">
                <Form.Label>Operador</Form.Label>
                <Form.Select
                  size="sm"
                  value={newNumericOperator}
                  onChange={(e) => setNewNumericOperator(e.target.value as NumericFilterOperator)}
                  data-testid="filter-numeric-operator-select"
                >
                  {NUMERIC_OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="numeric-value">
                <Form.Label>Valor</Form.Label>
                <Form.Control
                  size="sm"
                  type="number"
                  step="any"
                  value={newNumericValue}
                  onChange={(e) => setNewNumericValue(e.target.value)}
                  data-testid="filter-numeric-value"
                />
              </Form.Group>
            </Col>
            {needsSecondValue && (
              <Col xs={6} sm={3} md={2}>
                <Form.Group controlId="numeric-second-value">
                  <Form.Label> até </Form.Label>
                  <Form.Control
                    size="sm"
                    type="number"
                    step="any"
                    value={newNumericSecondValue}
                    onChange={(e) => setNewNumericSecondValue(e.target.value)}
                    data-testid="filter-numeric-second-value"
                  />
                </Form.Group>
              </Col>
            )}
            <Col xs={12} sm={3} md={1} className="d-flex align-items-end">
              <Button size="sm" variant="outline-primary" onClick={handleAddNumeric} data-testid="filter-add-numeric">
                Adicionar
              </Button>
            </Col>
          </Row>

          <Row className="g-2 mb-2">
            <Col xs={12} sm={6} md={3}>
              <Form.Group controlId="text-tag">
                <Form.Label>Tag</Form.Label>
                <Form.Select
                  size="sm"
                  value={newTextSeriesId}
                  onChange={(e) => setNewTextSeriesId(e.target.value)}
                  data-testid="filter-text-tag"
                >
                  {textTagOptions.map((tag) => (
                    <option key={optionIdentity(tag)} value={optionIdentity(tag)}>{tag.displayName}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="text-type">
                <Form.Label>Tipo</Form.Label>
                <Form.Select size="sm" disabled data-testid="filter-text-type">
                  <option value="text">Texto</option>
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="text-operator">
                <Form.Label>Operador</Form.Label>
                <Form.Select
                  size="sm"
                  value={newTextOperator}
                  onChange={(e) => setNewTextOperator(e.target.value as TextFilterOperator)}
                  data-testid="filter-text-operator"
                >
                  {TEXT_OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2}>
              <Form.Group controlId="text-value">
                <Form.Label>Valor</Form.Label>
                <Form.Control
                  size="sm"
                  type="text"
                  value={newTextValue}
                  onChange={(e) => setNewTextValue(e.target.value)}
                  data-testid="filter-text-value"
                />
              </Form.Group>
            </Col>
            <Col xs={6} sm={3} md={2} className="d-flex align-items-end">
              <Form.Check
                type="switch"
                id="filter-text-case"
                label="Dif. maiúsc."
                checked={newTextCaseSensitive}
                onChange={(e) => setNewTextCaseSensitive(e.target.checked)}
                data-testid="filter-text-case"
              />
            </Col>
            <Col xs={12} sm={3} md={1} className="d-flex align-items-end">
              <Button size="sm" variant="outline-primary" onClick={handleAddText} data-testid="filter-add-text">
                Adicionar
              </Button>
            </Col>
          </Row>

          <hr className="my-2" />

          <h6 className="mb-2">Filtros opcionais</h6>
          <Row className="g-2 mb-2">
            <Col xs={12}>
              <Form.Label>Dias da semana</Form.Label>
              <div className="d-flex flex-wrap gap-2">
                {WEEKDAY_ORDER.map((day) => (
                  <Form.Check
                    key={day}
                    type="switch"
                    id={`weekday-${day}`}
                    label={WEEKDAY_LABELS[day]}
                    checked={selectedWeekdays.includes(day)}
                    onChange={(e) => {
                      setSelectedWeekdays(
                        e.target.checked
                          ? [...selectedWeekdays, day]
                          : selectedWeekdays.filter((d) => d !== day),
                      );
                    }}
                    data-testid={`weekday-${day}`}
                  />
                ))}
              </div>
            </Col>
            <Col xs={12} sm={4}>
              <Button size="sm" variant="outline-info" onClick={handleAddWeekday} data-testid="filter-add-weekday">
                Aplicar dias
              </Button>
            </Col>
          </Row>

          <Row className="g-2 mb-2">
            <Col xs={6} sm={3}>
              <Form.Group controlId="timerange-start">
                <Form.Label>Hora inicial</Form.Label>
                <Form.Control
                  size="sm"
                  type="time"
                  value={timeRangeStart}
                  onChange={(e) => setTimeRangeStart(e.target.value)}
                  data-testid="filter-timerange-start"
                />
              </Form.Group>
            </Col>
            <Col xs={6} sm={3}>
              <Form.Group controlId="timerange-end">
                <Form.Label>Hora final</Form.Label>
                <Form.Control
                  size="sm"
                  type="time"
                  value={timeRangeEnd}
                  onChange={(e) => setTimeRangeEnd(e.target.value)}
                  data-testid="filter-timerange-end"
                />
              </Form.Group>
            </Col>
            <Col xs={12} sm={3} className="d-flex align-items-end">
              <Button size="sm" variant="outline-info" onClick={handleAddTimeRange} data-testid="filter-add-timerange">
                Aplicar horário
              </Button>
            </Col>
          </Row>

          <hr className="my-2" />

          <h6 className="mb-2">Filtros - Excluir</h6>
          <Row className="g-2 mb-2">
            <Col xs={12} sm={4}>
              <Form.Group controlId="exclude-tag">
                <Form.Label>Tag</Form.Label>
                <Form.Select
                  size="sm"
                  value={newExcludeSeriesId}
                  onChange={(e) => setNewExcludeSeriesId(e.target.value)}
                  data-testid="filter-exclude-tag"
                >
                  {allTagOptions.map((tag) => (
                    <option key={optionIdentity(tag)} value={optionIdentity(tag)}>{tag.displayName}</option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={2}>
              <Form.Group controlId="exclude-type">
                <Form.Label>Tipo</Form.Label>
                <Form.Select
                  size="sm"
                  value={newExcludeValueType}
                  onChange={(e) => setNewExcludeValueType(e.target.value as "number" | "string" | "boolean")}
                  data-testid="filter-exclude-type"
                >
                  <option value="number">Número</option>
                  <option value="string">Texto</option>
                  <option value="boolean">Booleano</option>
                </Form.Select>
              </Form.Group>
            </Col>
            <Col xs={6} sm={2}>
              <Form.Group controlId="exclude-value">
                <Form.Label>Valor</Form.Label>
                <Form.Control
                  size="sm"
                  type={newExcludeValueType === "number" ? "number" : "text"}
                  value={newExcludeValue}
                  onChange={(e) => setNewExcludeValue(e.target.value)}
                  data-testid="filter-exclude-value"
                />
              </Form.Group>
            </Col>
            {newExcludeValueType === "string" && (
              <Col xs={6} sm={2} className="d-flex align-items-end">
                <Form.Check
                  type="switch"
                  id="exclude-case"
                  label="Dif. maiúsc."
                  checked={newExcludeCaseSensitive}
                  onChange={(e) => setNewExcludeCaseSensitive(e.target.checked)}
                  data-testid="filter-exclude-case"
                />
              </Col>
            )}
            <Col xs={12} sm={2} className="d-flex align-items-end">
              <Button size="sm" variant="outline-danger" onClick={handleAddExclude} data-testid="filter-add-exclude">
                Excluir valor
              </Button>
            </Col>
          </Row>

          {rules.length > 0 && (
            <>
              <hr className="my-2" />
              <h6 className="mb-2">Regras ativas</h6>
              <div className="d-flex flex-column gap-1" data-testid="filter-rules-list">
                {rules.map((rule) => (
                  <div
                    key={rule.id}
                    className={`border rounded p-2 small ${rule.enabled ? "" : "opacity-50"}`}
                    data-testid={`filter-rule-${rule.id}`}
                  >
                    <div className="d-flex justify-content-between align-items-start">
                      <div>
                        <span className="fw-semibold">
                          {rule.kind === "numeric" || rule.kind === "text" || rule.kind === "excludeValue"
                            ? formatRuleDescription(rule, tagLabel(rule.tagId, rule.seriesInstanceId))
                            : formatRuleDescription(rule, "")}
                        </span>
                        <span className="text-muted ms-2">
                          ({rule.enabled ? "ativo" : "inativo"} · removidos: {ruleResultMap.get(rule.id) ?? 0})
                        </span>
                      </div>
                      <div className="d-flex gap-1">
                        <Button
                          size="sm"
                          variant={rule.enabled ? "outline-warning" : "outline-success"}
                          onClick={() => updateRule(rule.id, { enabled: !rule.enabled })}
                          aria-label={rule.enabled ? "Desativar regra" : "Ativar regra"}
                          data-testid={`rule-toggle-${rule.id}`}
                        >
                          {rule.enabled ? "Desativar" : "Ativar"}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline-danger"
                          onClick={() => removeRule(rule.id)}
                          aria-label="Remover regra"
                          data-testid={`rule-remove-${rule.id}`}
                        >
                          Remover
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <hr className="my-2" />

          <h6 className="mb-2">Resumo</h6>
          {summary ? (
            <div className="small" data-testid="filter-summary">
              <div>Recebidos: {summary.receivedPoints}</div>
              <div>Restantes: {summary.remainingPoints}</div>
              <div>Descartados: {summary.removedPoints}</div>
              {summary.removedByQuality > 0 && <div className="text-muted ms-2">Qualidade: {summary.removedByQuality}</div>}
              {summary.removedByNumeric > 0 && <div className="text-muted ms-2">Numérico: {summary.removedByNumeric}</div>}
              {summary.removedByText > 0 && <div className="text-muted ms-2">Texto: {summary.removedByText}</div>}
              {summary.removedByDateTime > 0 && <div className="text-muted ms-2">Data/horário: {summary.removedByDateTime}</div>}
              {summary.removedByExclusion > 0 && <div className="text-muted ms-2">Exclusões: {summary.removedByExclusion}</div>}
            </div>
          ) : hasData ? (
            <div className="small text-muted" data-testid="filter-summary-empty">Nenhum filtro ativo.</div>
          ) : null}

          {rules.length > 0 && (
            <div className="mt-2">
              <Button size="sm" variant="outline-danger" onClick={resetFilters} data-testid="filter-reset">
                Limpar filtros
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
