import { Alert, Card, Col, Row } from "react-bootstrap";
import type { MetricResult, TimeSeriesSeries } from "../types";
import { METRIC_BY_ID } from "../utils/analysisMetrics";
import { formatNumericValue } from "../utils/values";

interface Props { results: readonly MetricResult[]; series: readonly TimeSeriesSeries[]; }

export function MetricResults({ results, series }: Props) {
  if (!results.length) return null;
  const byInstance = new Map(series.map((entry) => [entry.series_instance_id ?? `tag:${entry.tag_id}`, entry]));
  const byId = new Map(series.map((entry) => [entry.tag_id, entry]));
  return (
    <Card className="piad-card mb-3" data-testid="metric-results">
      <Card.Header>Resultados da métrica</Card.Header>
      <Card.Body>
        <Row className="g-3">
          {results.map((item, index) => {
            const source = item.seriesInstanceId ? byInstance.get(item.seriesInstanceId) : item.seriesTagId === null ? null : byId.get(item.seriesTagId);
            const reference = item.referenceSeriesInstanceId ? byInstance.get(item.referenceSeriesInstanceId) : item.referenceTagId === null ? null : byId.get(item.referenceTagId);
            return <Col xs={12} md={6} xl={4} key={`${item.metric}-${item.seriesInstanceId ?? item.seriesTagId ?? "validation"}-${index}`}>
              <Card className="h-100" data-testid="metric-result-card">
                <Card.Body>
                  <div className="small text-muted">{METRIC_BY_ID.get(item.metric)?.name ?? item.metric}</div>
                  {source ? <div className="fw-semibold">{source.display_name} <span className="small text-muted">({source.tag_name})</span></div> : null}
                  {reference ? <div className="small">Referência: {reference.display_name} ({reference.tag_name})</div> : null}
                  {item.status === "ok" && item.value !== null ? <div className="display-6 my-2" data-testid="metric-value">{formatNumericValue(item.value)}{item.unit ? <span className="fs-6 ms-1">{item.unit}</span> : null}</div> : <Alert variant={item.status === "invalidConfiguration" ? "warning" : "secondary"} className="my-2 py-2">{item.message}</Alert>}
                  <div className="small text-muted">Amostras/pares: {item.sampleCount} · Ignorados: {item.excludedCount}{item.oocCount === undefined ? "" : ` · Fora de controle: ${item.oocCount}`}</div>
                </Card.Body>
              </Card>
            </Col>;
          })}
        </Row>
      </Card.Body>
    </Card>
  );
}
