import { Alert, Col, Form, Row } from "react-bootstrap";
import type { AnalysisMetric, MetricConfiguration, TimeSeriesSeries } from "../types";
import { ANALYSIS_METRICS, createMetricConfiguration, METRIC_BY_ID, validateMetricConfiguration } from "../utils/analysisMetrics";

interface Props {
  configuration: MetricConfiguration;
  series: readonly TimeSeriesSeries[];
  onChange: (configuration: MetricConfiguration) => void;
}

const numericInput = (value: number | null, onChange: (value: number | null) => void, testId: string, label: string) => (
  <Form.Group as={Col} xs={6} controlId={testId}>
    <Form.Label>{label}</Form.Label>
    <Form.Control type="number" step="any" value={value ?? ""} data-testid={testId}
      onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} />
  </Form.Group>
);

export function MetricConfigurationPanel({ configuration, series, onChange }: Props) {
  const metric = configuration.kind === "none" ? null : configuration.metric;
  const definition = metric ? METRIC_BY_ID.get(metric) : null;
  const errors = validateMetricConfiguration(configuration, series);
  const needsPair = "actualTagId" in configuration;
  const identity = (entry: TimeSeriesSeries) => entry.series_instance_id ?? `tag:${entry.tag_id}`;
  const selectSeries = (role: "actual" | "reference", selectedIdentity: string) => {
    if (!("actualTagId" in configuration)) return;
    const selected = series.find((entry) => identity(entry) === selectedIdentity);
    if (role === "actual") onChange({ ...configuration, actualTagId: selected?.tag_id ?? null, actualSeriesInstanceId: selected ? identity(selected) : null });
    else onChange({ ...configuration, referenceTagId: selected?.tag_id ?? null, referenceSeriesInstanceId: selected ? identity(selected) : null });
  };
  return (
    <section className="border rounded p-3" data-testid="metric-configuration">
      <Form.Group controlId="analysis-metric">
        <Form.Label>Métrica de análise</Form.Label>
        <Form.Select value={metric ?? ""} data-testid="analysis-metric"
          onChange={(event) => onChange(createMetricConfiguration((event.target.value || null) as AnalysisMetric | null))}>
          <option value="">Nenhuma métrica</option>
          {ANALYSIS_METRICS.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </Form.Select>
      </Form.Group>
      {definition ? <Form.Text className="d-block mt-1 text-muted" data-testid="metric-description">{definition.description} Requisito: {definition.requirements}.</Form.Text> : null}
      {needsPair ? (
        <Row className="g-2 mt-1">
          <Form.Group as={Col} xs={12} sm={6} controlId="metric-actual-series">
            <Form.Label>Série real</Form.Label>
            <Form.Select value={configuration.actualSeriesInstanceId ?? (configuration.actualTagId === null ? "" : `tag:${configuration.actualTagId}`)} data-testid="metric-actual-series" onChange={(event) => selectSeries("actual", event.target.value)}>
              <option value="">Selecione...</option>{series.map((entry) => <option key={identity(entry)} value={identity(entry)}>{entry.display_name} ({entry.tag_name})</option>)}
            </Form.Select>
          </Form.Group>
          <Form.Group as={Col} xs={12} sm={6} controlId="metric-reference-series">
            <Form.Label>Série de referência</Form.Label>
            <Form.Select value={configuration.referenceSeriesInstanceId ?? (configuration.referenceTagId === null ? "" : `tag:${configuration.referenceTagId}`)} data-testid="metric-reference-series" onChange={(event) => selectSeries("reference", event.target.value)}>
              <option value="">Selecione...</option>{series.map((entry) => <option key={identity(entry)} value={identity(entry)}>{entry.display_name} ({entry.tag_name})</option>)}
            </Form.Select>
          </Form.Group>
        </Row>
      ) : null}
      {configuration.kind === "specification" || configuration.kind === "errorCapability" ? (
        <Row className="g-2 mt-1">
          {numericInput(configuration.lowerSpecification, (value) => onChange({ ...configuration, lowerSpecification: value }), "metric-lie", "LIE")}
          {numericInput(configuration.upperSpecification, (value) => onChange({ ...configuration, upperSpecification: value }), "metric-lse", "LSE")}
        </Row>
      ) : null}
      {configuration.kind === "control" || configuration.kind === "oocError" ? (
        <Row className="g-2 mt-1">
          {numericInput(configuration.lowerControl, (value) => onChange({ ...configuration, lowerControl: value }), "metric-lic", "LIC")}
          {numericInput(configuration.upperControl, (value) => onChange({ ...configuration, upperControl: value }), "metric-lsc", "LSC")}
        </Row>
      ) : null}
      {errors.length ? <Alert variant="warning" className="mt-2 mb-0 py-2" role="alert" data-testid="metric-validation">{errors.join(" ")} A consulta ao PI continua disponível.</Alert> : null}
    </section>
  );
}
