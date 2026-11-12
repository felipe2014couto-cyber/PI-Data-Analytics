import { Alert, Badge, Button, Form, Modal } from "react-bootstrap";
import { AdvancedFiltersPanel } from "./AdvancedFiltersPanel";
import type {
  ConflictedVariable,
  DataFilterConfiguration,
  DynamicAnalysisFilter,
  FilterApplicationSummary,
  FilterRuleResult,
  SectionAnalysisTag,
} from "../types";

export interface CyclicLimitVariableOption {
  seriesInstanceId: string;
  tagId: number;
  displayName: string;
  unit?: string;
  axisIndex: number;
  axisText: string;
  lowerLimitTag: string | null;
  upperLimitTag: string | null;
  hasLimits: boolean;
}

export interface CyclicFiltersModalProps {
  show: boolean;
  onClose: () => void;
  // Filters section
  filterConfiguration: DataFilterConfiguration;
  onFilterConfigurationChange: (configuration: DataFilterConfiguration) => void;
  filterTagOptions: Array<{
    id: number;
    seriesInstanceId?: string;
    displayName: string;
    tagName: string;
    dataType: string;
    analysisRole?: "width" | "um" | "thickness" | "steelType";
  }>;
  filterSummary: FilterApplicationSummary | null;
  ruleResults: FilterRuleResult[];
  hasData: boolean;
  analysisTags?: SectionAnalysisTag[];
  conflictedVariables?: ConflictedVariable[];
  dynamicFilters?: Record<number, DynamicAnalysisFilter>;
  onDynamicFilterChange?: (filters: Record<number, DynamicAnalysisFilter>) => void;
  // Limits section
  limitsEnabled: boolean;
  onLimitsEnabledChange: (enabled: boolean) => void;
  selectedLimitSeriesIds: Set<string>;
  onToggleLimitSeries: (seriesInstanceId: string, enabled: boolean) => void;
  onSelectAllLimits?: () => void;
  onClearAllLimits?: () => void;
  limitVariables: CyclicLimitVariableOption[];
  // Query submission
  onSubmit?: () => void;
  queryLoading?: boolean;
}

export function CyclicFiltersModal({
  show,
  onClose,
  filterConfiguration,
  onFilterConfigurationChange,
  filterTagOptions,
  filterSummary,
  ruleResults,
  hasData,
  analysisTags = [],
  conflictedVariables = [],
  dynamicFilters = {},
  onDynamicFilterChange,
  limitsEnabled,
  onLimitsEnabledChange,
  selectedLimitSeriesIds,
  onToggleLimitSeries,
  onSelectAllLimits,
  onClearAllLimits,
  limitVariables,
  onSubmit,
  queryLoading = false,
}: CyclicFiltersModalProps) {
  if (!show) return null;

  return (
    <Modal
      show={show}
      onHide={onClose}
      size="lg"
      centered
      data-testid="cyclic-filters-modal"
      backdrop="static"
    >
      <Modal.Header closeButton>
        <Modal.Title className="h5 d-flex align-items-center gap-2">
          <span>Configurar Filtros e Limites — Base Cíclica</span>
        </Modal.Title>
      </Modal.Header>

      <Modal.Body style={{ maxHeight: "75vh", overflowY: "auto" }}>
        {/* Seção 1: Filtros de Consulta */}
        <section className="border rounded p-3 mb-3 bg-white" data-testid="cyclic-modal-filters-section">
          <h6 className="fw-bold mb-3 d-flex align-items-center gap-2">
            <i className="bi bi-funnel-fill text-primary" />
            <span>Filtros da Consulta</span>
          </h6>
          <AdvancedFiltersPanel
            hideToggle={true}
            initialExpanded={true}
            configuration={filterConfiguration}
            enabled={true}
            tagOptions={filterTagOptions}
            summary={filterSummary}
            ruleResults={ruleResults}
            hasData={hasData}
            onChange={onFilterConfigurationChange}
            analysisTags={analysisTags}
            conflictedVariables={conflictedVariables}
            dynamicFilters={dynamicFilters}
            onDynamicFilterChange={onDynamicFilterChange}
          />
        </section>

        {/* Seção 2: Limites Vinculados às Tags */}
        <section className="border rounded p-3 bg-white" data-testid="cyclic-modal-limits-section">
          <div className="d-flex align-items-center justify-content-between mb-2">
            <h6 className="fw-bold mb-0 d-flex align-items-center gap-2">
              <i className="bi bi-rulers text-primary" />
              <span>Limites Vinculados às Tags</span>
            </h6>
            <Form.Check id="cyclic-limits-switch">
              <Form.Check.Input
                type="checkbox"
                checked={limitsEnabled}
                onChange={(e) => onLimitsEnabledChange(e.target.checked)}
                data-testid="cyclic-limits-switch"
              />
              <Form.Check.Label className="fw-semibold">Exibir limites vinculados</Form.Check.Label>
            </Form.Check>
          </div>

          <div className="small text-muted mb-3">
            {limitsEnabled ? (
              <span data-testid="cyclic-limits-enabled-note">
                Selecione quais variáveis terão seus limites inferior e superior desenhados no gráfico no eixo correspondente:
              </span>
            ) : (
              <span>
                A exibição de limites está desativada. As seleções anteriores serão mantidas quando reativada.
              </span>
            )}
          </div>

          {limitsEnabled ? (
            <div>
              {limitVariables.length === 0 ? (
                <Alert variant="info" className="py-2 small mb-0" data-testid="cyclic-limits-empty-alert">
                  Nenhuma variável numérica disponível na seleção atual. Selecione ao menos uma tag para configurar limites.
                </Alert>
              ) : (
                <div className="d-flex flex-column gap-2" data-testid="cyclic-limits-variables-list">
                  <div className="d-flex justify-content-end gap-2 mb-1">
                    {onSelectAllLimits && (
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 text-decoration-none small"
                        onClick={onSelectAllLimits}
                        data-testid="cyclic-limits-select-all"
                      >
                        Selecionar todas com limite
                      </Button>
                    )}
                    {onSelectAllLimits && onClearAllLimits && <span className="text-muted">|</span>}
                    {onClearAllLimits && (
                      <Button
                        variant="link"
                        size="sm"
                        className="p-0 text-decoration-none text-secondary small"
                        onClick={onClearAllLimits}
                        data-testid="cyclic-limits-clear-all"
                      >
                        Desmarcar todas
                      </Button>
                    )}
                  </div>

                  {limitVariables.map((variable) => {
                    const isChecked = selectedLimitSeriesIds.has(variable.seriesInstanceId);
                    return (
                      <div
                        key={variable.seriesInstanceId}
                        className={`border rounded p-2 d-flex align-items-center justify-content-between ${
                          !variable.hasLimits ? "bg-light text-muted" : isChecked ? "bg-light-subtle border-primary" : ""
                        }`}
                        data-testid={`cyclic-limit-row-${variable.seriesInstanceId}`}
                      >
                        <div className="d-flex align-items-center gap-3">
                          <Form.Check id={`cyclic-limit-check-${variable.seriesInstanceId}`}>
                            <Form.Check.Input
                              type="checkbox"
                              checked={isChecked && variable.hasLimits}
                              disabled={!variable.hasLimits}
                              onChange={(e) => onToggleLimitSeries(variable.seriesInstanceId, e.target.checked)}
                              data-testid={`cyclic-limit-checkbox-${variable.seriesInstanceId}`}
                              aria-label={`Exibir limites de ${variable.displayName}`}
                            />
                          </Form.Check>
                          <div>
                            <div className="fw-semibold small d-flex align-items-center gap-2">
                              <span>{variable.displayName}</span>
                              <Badge bg="secondary" style={{ fontSize: "0.75rem" }} data-testid={`cyclic-limit-axis-${variable.seriesInstanceId}`}>
                                {variable.axisText}
                              </Badge>
                            </div>
                            <div className="small text-muted" style={{ fontSize: "0.8rem" }}>
                              {variable.hasLimits ? (
                                <>
                                  <span>Inf: <code>{variable.lowerLimitTag || "—"}</code></span>
                                  <span className="mx-2">•</span>
                                  <span>Sup: <code>{variable.upperLimitTag || "—"}</code></span>
                                </>
                              ) : (
                                <span className="text-warning fst-italic">Sem limites cadastrados</span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div>
                          {variable.hasLimits ? (
                            <Badge bg={isChecked ? "success" : "light"} text={isChecked ? undefined : "dark"} className={isChecked ? "" : "border"}>
                              {isChecked ? "Limites ativos" : "Oculto"}
                            </Badge>
                          ) : (
                            <Badge bg="light" text="muted" className="border">
                              Indisponível
                            </Badge>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : (
            <div className="p-2 border rounded bg-light text-muted small fst-italic" data-testid="cyclic-limits-disabled-note">
              Ative a opção acima para selecionar e desenhar os limites das variáveis no gráfico.
            </div>
          )}
        </section>
      </Modal.Body>

      <Modal.Footer className="d-flex justify-content-between">
        <div className="small text-muted">
          As alterações não são salvas automaticamente no perfil do usuário.
        </div>
        <div className="d-flex gap-2">
          <Button variant="secondary" onClick={onClose} data-testid="close-cyclic-filters-modal-btn">
            Fechar
          </Button>
          {onSubmit && (
            <Button
              variant="primary"
              onClick={() => {
                onClose();
                onSubmit();
              }}
              disabled={queryLoading}
              data-testid="cyclic-modal-submit-btn"
            >
              {queryLoading ? "Consultando..." : "Aplicar e Consultar"}
            </Button>
          )}
        </div>
      </Modal.Footer>
    </Modal>
  );
}
