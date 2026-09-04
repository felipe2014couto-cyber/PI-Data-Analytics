import { useState } from "react";
import { Button, Col, Form, Row } from "react-bootstrap";
import type {
  DataFilterConfiguration,
  DataFilterRule,
  FilterApplicationSummary,
  FilterRuleResult,
  NumericFilterOperator,
} from "../types";
import { STEEL_MODELS } from "../constants/steelModels";

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
  onChange: (configuration: DataFilterConfiguration) => void;
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
      { key: "umSequenceCode", label: "Código UM-SEQ", control: "text" },
      { key: "genealogyCode", label: "Código UM Genealogia", control: "text" },
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
      { key: "reprocess", label: "Reprocesso", control: "select", options: ["Sim", "Não"] },
      { key: "furnace", label: "Forno", control: "text" },
      { key: "deviation", label: "Desvio", control: "select", options: ["Sim", "Não"] },
      { key: "lineStatus", label: "Status Linha", control: "select", options: ["Operando", "Parada", "Indisponível"] },
      { key: "backwardMaterialRemoval", label: "Retirada Matéria Trás", control: "select", options: ["Sim", "Não"] },
      { key: "coilMovement", label: "Movimentação Bobinas", control: "select", options: ["Sim", "Não"] },
      { key: "reheating", label: "Relaminação", control: "select", options: ["Sim", "Não"] },
    ],
  },
  {
    key: "quality",
    title: "Defeitos e qualidade",
    fields: [
      { key: "defectMachine", label: "Máquina Defeito", control: "text" },
      { key: "defectCode", label: "Código Defeito", control: "text" },
      { key: "defectDescription", label: "Descrição Defeito", control: "text" },
      { key: "defectCriticality", label: "Criticidade Defeito", control: "select", options: ["Baixa", "Média", "Alta", "Crítica"] },
    ],
  },
  {
    key: "events",
    title: "Paradas e eventos",
    fields: [
      { key: "eventType", label: "Tipo de Evento", control: "select", options: ["Operacional", "Qualidade", "Manutenção", "Processo"] },
      { key: "stopCode", label: "Código de Parada", control: "text" },
      { key: "stopNatureCode", label: "Código Natureza Parada", control: "text" },
      { key: "responsibleTeamCode", label: "Código Equipe Responsável", control: "text" },
    ],
  },
  {
    key: "input",
    title: "Características de entrada e composição",
    fields: [
      { key: "inputThicknessMin", label: "Espessura mínima entrada", control: "number" },
      { key: "inputThicknessMax", label: "Espessura máxima entrada", control: "number" },
      { key: "carbonMin", label: "Teor de carbono mínimo", control: "number" },
      { key: "carbonMax", label: "Teor de carbono máximo", control: "number" },
    ],
  },
  {
    key: "length",
    title: "Comprimento",
    fields: [
      { key: "lengthPercentMin", label: "Comprimento mínimo %", control: "number" },
      { key: "lengthPercentMax", label: "Comprimento máximo %", control: "number" },
      { key: "lengthAbsoluteMin", label: "Comprimento mínimo absoluto", control: "number" },
      { key: "lengthAbsoluteMax", label: "Comprimento máximo absoluto", control: "number" },
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
  umSequenceCode: ["um-seq", "um seq"],
  genealogyCode: ["genealogia", "um genealogia"],
  thicknessMin: ["espessura mínima", "espessura min", "espessura"],
  thicknessMax: ["espessura máxima", "espessura max", "espessura"],
  widthMin: ["largura mínima", "largura min", "largura"],
  widthMax: ["largura máxima", "largura max", "largura"],
  group: ["grupo"],
  shift: ["turno"],
  reprocess: ["reprocesso"],
  furnace: ["forno"],
  deviation: ["desvio"],
  lineStatus: ["status linha", "status da linha"],
  backwardMaterialRemoval: ["retirada matéria trás", "retirada materia tras"],
  coilMovement: ["movimentação bobinas", "movimentacao bobinas"],
  reheating: ["relaminação", "relaminacao"],
  defectMachine: ["máquina defeito", "maquina defeito"],
  defectCode: ["código defeito", "codigo defeito"],
  defectDescription: ["descrição defeito", "descricao defeito"],
  defectCriticality: ["criticidade defeito"],
  eventType: ["tipo de evento"],
  stopCode: ["código de parada", "codigo de parada"],
  stopNatureCode: ["natureza parada", "natureza da parada"],
  responsibleTeamCode: ["equipe responsável", "equipe responsavel"],
  inputThicknessMin: ["espessura mínima entrada", "espessura minima entrada"],
  inputThicknessMax: ["espessura máxima entrada", "espessura maxima entrada"],
  carbonMin: ["carbono mínimo", "carbono minimo"],
  carbonMax: ["carbono máximo", "carbono maximo"],
  lengthPercentMin: ["comprimento mínimo %", "comprimento minimo %"],
  lengthPercentMax: ["comprimento máximo %", "comprimento maximo %"],
  lengthAbsoluteMin: ["comprimento mínimo absoluto", "comprimento minimo absoluto"],
  lengthAbsoluteMax: ["comprimento máximo absoluto", "comprimento maximo absoluto"],
};

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
  onChange,
}: AdvancedFiltersPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState(false);
  const [unmappedFields, setUnmappedFields] = useState<string[]>([]);

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
    onChange({ ...configuration, rules: [] });
  };

  const activeDraftCount = Object.values(draft).filter((value) => value.trim()).length;

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
            {activeDraftCount > 0 ? <span className="small text-muted">{activeDraftCount} parâmetro(s) preenchido(s)</span> : null}
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
