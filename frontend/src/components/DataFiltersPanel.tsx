import { Accordion, Form, Row, Col, Button, Alert, Collapse } from "react-bootstrap";
import { useState, type ReactNode } from "react";

import { TagMultiSelect, type TagOption } from "./TagMultiSelect";
import { APPLICATION_TIMEZONE, TIME_PRESET_OPTIONS } from "../utils/timePeriod";
import type { AnalysisModel, TimePeriod, TimePreset, TimeSeriesMode, VisualizationType } from "../types";

export type { TagOption };

export const INTERVAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "1s", label: "1 segundo" },
  { value: "5s", label: "5 segundos" },
  { value: "10s", label: "10 segundos" },
  { value: "30s", label: "30 segundos" },
  { value: "1m", label: "1 minuto" },
  { value: "5m", label: "5 minutos" },
  { value: "10m", label: "10 minutos" },
  { value: "15m", label: "15 minutos" },
  { value: "30m", label: "30 minutos" },
  { value: "1h", label: "1 hora" },
  { value: "2h", label: "2 horas" },
  { value: "4h", label: "4 horas" },
  { value: "8h", label: "8 horas" },
  { value: "12h", label: "12 horas" },
  { value: "1d", label: "1 dia" },
];

interface DataFiltersPanelProps {
  equipmentOptions: Array<{ id: number; code: string; name: string }>;
  sectionOptions: Array<{ id: number; code: string; name: string; equipmentId: number }>;
  variableTypeOptions: Array<{ id: number; code: string; name: string }>;
  tagOptions: TagOption[];

  selectedEquipmentId: number | null;
  onEquipmentChange: (id: number | null) => void;

  selectedSectionId: number | null;
  onSectionChange: (id: number | null) => void;

  selectedVariableTypeId: number | null;
  onVariableTypeChange: (id: number | null) => void;

  selectedTagIds: number[];
  onTagsChange: (ids: number[]) => void;

  timePeriod: TimePeriod;
  onTimePeriodChange: (period: TimePeriod) => void;
  timePeriodError: string | null;
  timePeriodSummary: string | null;

  analysisModel: AnalysisModel;
  onAnalysisModelChange: (model: AnalysisModel) => void;

  mode: TimeSeriesMode;
  onModeChange: (mode: TimeSeriesMode) => void;
  interval: string;
  onIntervalChange: (value: string) => void;

  resolutionMode: string;
  onResolutionModeChange: (value: string) => void;
  targetPointsPerTag: number;
  onTargetPointsPerTagChange: (value: number) => void;
  targetPointsPerTagLimit: number;
  estimatedVisualPoints: number | null;

  onCancel: () => void;

  csvCompleteLoading: boolean;
  onCsvComplete: () => void;

  ignoreBadQuality: boolean;
  onIgnoreBadQualityChange: (value: boolean) => void;

  visualization: VisualizationType;
  onVisualizationChange: (value: VisualizationType) => void;
  seriesConfiguration: ReactNode;
  metricConfiguration: ReactNode;
  advancedFilters: ReactNode;
  comparisonConfiguration: ReactNode;
  visualConfiguration: ReactNode;

  piConfigured: boolean;

  onClear: () => void;
  onSubmit: () => void;
  submitting: boolean;
  cancelling?: boolean;
  errorMessage: string | null;
}

export function DataFiltersPanel(props: DataFiltersPanelProps) {
  const [graphConfigurationExpanded, setGraphConfigurationExpanded] = useState(false);
  const {
    equipmentOptions,
    sectionOptions,
    variableTypeOptions,
    tagOptions,
    selectedEquipmentId,
    onEquipmentChange,
    selectedSectionId,
    onSectionChange,
    selectedVariableTypeId,
    onVariableTypeChange,
    selectedTagIds,
    onTagsChange,
    timePeriod,
    onTimePeriodChange,
    timePeriodError,
    timePeriodSummary,
    analysisModel,
    onAnalysisModelChange,
    mode,
    onModeChange,
    interval,
    onIntervalChange,
    resolutionMode,
    onResolutionModeChange,
    targetPointsPerTag,
    onTargetPointsPerTagChange,
    targetPointsPerTagLimit,
    estimatedVisualPoints,
    ignoreBadQuality,
    onIgnoreBadQualityChange,
    visualization,
    onVisualizationChange,
    seriesConfiguration,
    metricConfiguration,
    advancedFilters,
    comparisonConfiguration,
    visualConfiguration,
    piConfigured,
    onClear,
    onSubmit,
    submitting,
    cancelling,
    errorMessage,
    onCancel,
    csvCompleteLoading,
    onCsvComplete,
  } = props;

  const sectionsForEquipment = selectedEquipmentId
    ? sectionOptions.filter((section) => section.equipmentId === selectedEquipmentId)
    : [];

  return (
    <div data-testid="data-filters-panel" className="d-flex flex-column gap-3">
      {!piConfigured ? (
        <Alert variant="warning" className="mb-0" data-testid="pi-not-configured-warning">
          PI Web API nao configurado no backend. Configure as variaveis
          <code> PI_WEB_API_* </code> e <code> PI_DATA_SERVER_NAME </code>
          no servidor para habilitar a consulta.
        </Alert>
      ) : null}
      {errorMessage ? (
        <Alert variant="danger" className="mb-0" data-testid="filters-error">
          {errorMessage}
        </Alert>
      ) : null}

      <Accordion defaultActiveKey={["period", "context"]} alwaysOpen className="filter-accordion">
        <Accordion.Item eventKey="period">
          <Accordion.Header>Período</Accordion.Header>
          <Accordion.Body className="d-flex flex-column gap-3" data-testid="period-filters">
      <Form.Group controlId="period-kind">
        <Form.Label>Tipo de período</Form.Label>
        <Form.Select
          value={timePeriod.kind}
          onChange={(event) => {
            const kind = event.target.value;
            if (kind === "preset") onTimePeriodChange({ kind, preset: "PT1H" });
            if (kind === "absolute") onTimePeriodChange({ kind, start: "", end: "", timezone: APPLICATION_TIMEZONE });
            if (kind === "relative") onTimePeriodChange({ kind, amount: 1, unit: "hour", reference: "now", timezone: APPLICATION_TIMEZONE });
          }}
          data-testid="period-kind"
        >
          <option value="preset">Predefinido</option>
          <option value="absolute">Absoluto</option>
          <option value="relative">Relativo</option>
        </Form.Select>
      </Form.Group>

      {timePeriod.kind === "preset" ? (
        <Form.Group controlId="period-preset">
          <Form.Label>Período predefinido</Form.Label>
          <Form.Select
            value={timePeriod.preset}
            onChange={(event) => onTimePeriodChange({ kind: "preset", preset: event.target.value as TimePreset })}
            data-testid="period-preset"
          >
            {TIME_PRESET_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </Form.Select>
        </Form.Group>
      ) : null}

      {timePeriod.kind === "absolute" ? (
        <Row className="g-2">
          <Col xs={6}>
            <Form.Group controlId="absolute-start">
              <Form.Label>Data e hora inicial</Form.Label>
              <Form.Control
                type="datetime-local"
                value={timePeriod.start}
                onChange={(event) => onTimePeriodChange({ ...timePeriod, start: event.target.value })}
                data-testid="absolute-start"
                aria-describedby="time-period-help time-period-error"
                aria-invalid={Boolean(timePeriodError)}
              />
            </Form.Group>
          </Col>
          <Col xs={6}>
            <Form.Group controlId="absolute-end">
              <Form.Label>Data e hora final</Form.Label>
              <Form.Control
                type="datetime-local"
                value={timePeriod.end}
                onChange={(event) => onTimePeriodChange({ ...timePeriod, end: event.target.value })}
                data-testid="absolute-end"
                aria-describedby="time-period-help time-period-error"
                aria-invalid={Boolean(timePeriodError)}
              />
            </Form.Group>
          </Col>
        </Row>
      ) : null}

      {timePeriod.kind === "relative" ? (
        <Row className="g-2">
          <Col xs={12} sm={4}>
            <Form.Group controlId="relative-amount">
              <Form.Label>Quantidade</Form.Label>
              <Form.Control type="number" min={1} step={1} value={timePeriod.amount}
                onChange={(event) => onTimePeriodChange({ ...timePeriod, amount: Number(event.target.value) })}
                data-testid="relative-amount" aria-describedby="time-period-help time-period-error"
                aria-invalid={Boolean(timePeriodError)} />
            </Form.Group>
          </Col>
          <Col xs={12} sm={4}>
            <Form.Group controlId="relative-unit">
              <Form.Label>Unidade</Form.Label>
              <Form.Select value={timePeriod.unit} data-testid="relative-unit"
                onChange={(event) => onTimePeriodChange({ ...timePeriod, unit: event.target.value as "minute" | "hour" | "day" | "week" })}>
                <option value="minute">Minutos</option><option value="hour">Horas</option>
                <option value="day">Dias</option><option value="week">Semanas</option>
              </Form.Select>
            </Form.Group>
          </Col>
          <Col xs={12} sm={4}>
            <Form.Group controlId="relative-reference">
              <Form.Label>Referência</Form.Label>
              <Form.Select value={timePeriod.reference} data-testid="relative-reference"
                onChange={(event) => onTimePeriodChange({ ...timePeriod, reference: event.target.value as "now" | "startOfDay" | "endOfDay" })}>
                <option value="now">Agora</option><option value="startOfDay">Início do dia</option>
                <option value="endOfDay">Fim do dia</option>
              </Form.Select>
            </Form.Group>
          </Col>
        </Row>
      ) : null}

      <Form.Text id="time-period-help" className="text-muted" data-testid="time-period-timezone">
        Fuso: {APPLICATION_TIMEZONE}
      </Form.Text>
      {timePeriodError ? <div id="time-period-error" className="text-danger small" role="alert" data-testid="time-period-error">{timePeriodError}</div> : null}
      {timePeriodSummary ? <div className="small border rounded p-2" data-testid="time-period-summary">{timePeriodSummary}<br />Fuso: {APPLICATION_TIMEZONE}</div> : null}

          </Accordion.Body>
        </Accordion.Item>

        <Accordion.Item eventKey="context">
          <Accordion.Header>Contexto</Accordion.Header>
          <Accordion.Body className="d-flex flex-column gap-3" data-testid="context-filters">
      <Form.Group controlId="analysis-model">
        <Form.Label>Modelo</Form.Label>
        <Form.Select value={analysisModel}
          onChange={(event) => onAnalysisModelChange(event.target.value as AnalysisModel)}
          data-testid="analysis-model">
          <option value="unit">Base Unidade</option>
          <option value="cyclic" disabled>Base Cíclica — Disponível em uma fase futura.</option>
          <option value="oee" disabled>Base OEE — Disponível em uma fase futura.</option>
          <option value="downtime" disabled>Base Paradas — Disponível em uma fase futura.</option>
          <option value="quality" disabled>Base Qualidade — Disponível em uma fase futura.</option>
        </Form.Select>
        <Form.Text className="text-muted">Somente Base Unidade está disponível nesta etapa.</Form.Text>
      </Form.Group>

      <Form.Group controlId="equipment-select">
        <Form.Label>Máquina</Form.Label>
        <Form.Select
          value={selectedEquipmentId === null ? "" : String(selectedEquipmentId)}
          onChange={(event) => onEquipmentChange(event.target.value ? Number(event.target.value) : null)}
          data-testid="equipment-select"
        >
          <option value="">Selecione...</option>
          {equipmentOptions.map((equipment) => (
            <option key={equipment.id} value={equipment.id}>
              {equipment.code} - {equipment.name}
            </option>
          ))}
        </Form.Select>
      </Form.Group>

      <Form.Group controlId="section-select">
        <Form.Label>Secao</Form.Label>
        <Form.Select
          value={selectedSectionId === null ? "" : String(selectedSectionId)}
          onChange={(event) => onSectionChange(event.target.value ? Number(event.target.value) : null)}
          disabled={!selectedEquipmentId}
          data-testid="section-select"
        >
          <option value="">Todas</option>
          {sectionsForEquipment.map((section) => (
            <option key={section.id} value={section.id}>
              {section.code} - {section.name}
            </option>
          ))}
        </Form.Select>
      </Form.Group>
          </Accordion.Body>
        </Accordion.Item>
      </Accordion>

      <Form.Group controlId="variable-type-select">
        <Form.Label>Tipo de variavel</Form.Label>
        <Form.Select
          value={selectedVariableTypeId === null ? "" : String(selectedVariableTypeId)}
          onChange={(event) =>
            onVariableTypeChange(event.target.value ? Number(event.target.value) : null)
          }
          data-testid="variable-type-select"
        >
          <option value="">Todos</option>
          {variableTypeOptions.map((vt) => (
            <option key={vt.id} value={vt.id}>
              {vt.code} - {vt.name}
            </option>
          ))}
        </Form.Select>
      </Form.Group>

      <div>
        <Form.Label>Tags</Form.Label>
        <TagMultiSelect
          options={tagOptions}
          selectedIds={selectedTagIds}
          onChange={onTagsChange}
          testId="tag-multi-select"
        />
        <Form.Text className="text-muted">
          Apenas tags ativas com validacao <strong>VALID</strong> ou <strong>PENDING</strong> podem ser
          selecionadas.
        </Form.Text>
      </div>

      <hr className="my-2" />

      <div>
        <Button
          variant="outline-info"
          size="sm"
          className="w-100 mb-2"
          onClick={() => setGraphConfigurationExpanded((expanded) => !expanded)}
          aria-expanded={graphConfigurationExpanded}
          aria-controls="graph-configuration-content"
          data-testid="graph-configuration-toggle"
        >
          {graphConfigurationExpanded ? "▲" : "▼"} Configurações do gráfico
        </Button>
        <Collapse in={graphConfigurationExpanded}>
          <div id="graph-configuration-content" data-testid="graph-configuration-content">
            <div className="border rounded p-3 mb-2 d-flex flex-column gap-3">
              <Form.Group controlId="visualization-select">
                <Form.Label>Visualização</Form.Label>
                <Form.Select
                  value={visualization}
                  onChange={(event) =>
                    onVisualizationChange(event.target.value as VisualizationType)
                  }
                  data-testid="visualization-select"
                >
                  <option value="automatic">Automática</option>
                  <option value="line">Linha temporal</option>
                  <option value="states">Estados</option>
                  <option value="histogram">Histograma</option>
                  <option value="boxplot">Boxplot</option>
                  <option value="scatter">Dispersão</option>
                  <option value="bars">Barras — último valor</option>
                  <option value="singleValue">Valor único</option>
                </Form.Select>
              </Form.Group>

              {comparisonConfiguration}

              {seriesConfiguration}

              {visualConfiguration}

              {metricConfiguration}
            </div>
          </div>
        </Collapse>
      </div>

      {advancedFilters}

      <Form.Group>
        <Form.Label className="d-block">Modo de consulta</Form.Label>
        <div className="d-flex gap-3">
          <Form.Check
            type="radio"
            id="mode-recorded"
            name="mode"
            label="Valores registrados — exatos"
            checked={mode === "recorded"}
            onChange={() => onModeChange("recorded")}
            data-testid="mode-recorded"
          />
          <Form.Check
            type="radio"
            id="mode-interpolated"
            name="mode"
            label="Valores interpolados"
            checked={mode === "interpolated"}
            onChange={() => onModeChange("interpolated")}
            data-testid="mode-interpolated"
          />
        </div>
      </Form.Group>

      <Form.Group>
        <Form.Label className="d-block">Resolucao</Form.Label>
        <div className="d-flex gap-3">
          <Form.Check
            type="radio"
            id="resolution-auto"
            name="resolutionMode"
            label="Automatica"
            checked={resolutionMode === "automatic"}
            onChange={() => onResolutionModeChange("automatic")}
            data-testid="resolution-auto"
          />
          <Form.Check
            type="radio"
            id="resolution-manual"
            name="resolutionMode"
            label="Manual"
            checked={resolutionMode === "manual"}
            onChange={() => onResolutionModeChange("manual")}
            data-testid="resolution-manual"
          />
        </div>
      </Form.Group>

      {resolutionMode === "manual" && mode === "interpolated" ? (
        <Form.Group controlId="interval-select">
          <Form.Label>Intervalo</Form.Label>
          <Form.Select
            value={interval}
            onChange={(event) => onIntervalChange(event.target.value)}
            data-testid="interval-select"
          >
            {INTERVAL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Form.Select>
        </Form.Group>
      ) : null}

      <Row className="g-2">
        <Col xs={6}>
          <Form.Group controlId="max-count">
            <Form.Label>Max. pontos exibidos por tag</Form.Label>
            <Form.Control
              type="number"
              min={1000}
              max={targetPointsPerTagLimit}
              value={targetPointsPerTag}
              onChange={(event) => onTargetPointsPerTagChange(Number(event.target.value))}
              data-testid="max-count"
            />
            <Form.Text className="text-muted">Max: {targetPointsPerTagLimit}</Form.Text>
          </Form.Group>
        </Col>
        <Col xs={6} className="d-flex align-items-end">
          <Form.Check
            type="switch"
            id="ignore-bad-quality"
            label="Ignorar qualidade ruim"
            checked={ignoreBadQuality}
            onChange={(event) => onIgnoreBadQualityChange(event.target.checked)}
            data-testid="ignore-bad-quality"
          />
        </Col>
      </Row>

      {estimatedVisualPoints !== null ? (
        <div className="small text-muted" data-testid="estimated-points">
          Estimativa: ~{estimatedVisualPoints.toLocaleString("pt-BR")} pontos visuais
        </div>
      ) : null}

      {estimatedVisualPoints !== null && estimatedVisualPoints > 200000 ? (
        <div className="small text-danger" data-testid="visual-budget-warning">
          A estimativa ultrapassa o limite global de 200.000 pontos. Utilize resolucao automatica ou exportacao completa.
        </div>
      ) : null}

      <div className="d-flex gap-2">
        <Button
          variant="outline-secondary"
          onClick={onClear}
          type="button"
          data-testid="filters-clear"
        >
          Limpar
        </Button>
        {submitting ? (
          <Button
            variant="danger"
            onClick={onCancel}
            type="button"
            disabled={cancelling}
            data-testid="filters-cancel"
          >
            {cancelling ? "Cancelando..." : "Cancelar"}
          </Button>
        ) : (
          <Button
            variant="primary"
            className="btn-piad-primary"
            onClick={onSubmit}
            disabled={submitting || Boolean(timePeriodError) || analysisModel !== "unit"}
            type="button"
            data-testid="filters-submit"
          >
            Consultar
          </Button>
        )}
        <Button
          variant="outline-info"
          size="sm"
          onClick={onCsvComplete}
          disabled={csvCompleteLoading}
          data-testid="csv-complete"
        >
          {csvCompleteLoading ? "Exportando..." : "CSV completo - sem filtros locais"}
        </Button>
      </div>
    </div>
  );
}
