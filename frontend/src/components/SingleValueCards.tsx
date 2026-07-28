import { Card, Col, Row } from "react-bootstrap";

import type { TimeSeriesSeries } from "../types";
import { buildSingleValueEntries, type DisplayableValue } from "../utils/singleValue";
import { formatNumericValue } from "../utils/values";

interface SingleValueCardsProps {
  series: readonly TimeSeriesSeries[];
  ignoreBadQuality: boolean;
}

function formatValue(value: DisplayableValue): string {
  return typeof value === "number" ? formatNumericValue(value) : String(value);
}

function flag(value: boolean): string {
  return value ? "true" : "false";
}

export function SingleValueCards({ series, ignoreBadQuality }: SingleValueCardsProps) {
  const entries = buildSingleValueEntries(series, ignoreBadQuality);
  return (
    <Row className="g-3" data-testid="single-value-cards">
      {entries.map(({ series: entry, observation, quality }) => (
        <Col key={entry.tag_id} xs={12} sm={6} xl={4} data-testid="single-value-card-column">
          <Card
            className={`h-100 border-${quality.variant}`}
            data-testid={`single-value-card-${entry.tag_id}`}
            data-quality-status={quality.status}
          >
            <Card.Header className={`text-bg-${quality.variant} d-flex justify-content-between gap-2`}>
              <span className="fw-semibold">{entry.display_name}</span>
              <span>{quality.status}</span>
            </Card.Header>
            <Card.Body>
              <div className="text-muted small mb-2">{entry.tag_name}</div>
              {observation ? (
                <>
                  <div className="display-6 text-break" data-testid={`single-value-${entry.tag_id}`}>
                    {formatValue(observation.value)}
                    {entry.unit?.trim() ? (
                      <span className="fs-6 ms-2">{entry.unit.trim()}</span>
                    ) : null}
                  </div>
                  <div className="small mt-3">
                    {new Date(observation.timestamp).toLocaleString("pt-BR")}
                  </div>
                  <div className="small mt-2" data-testid={`single-value-flags-${entry.tag_id}`}>
                    Good: {flag(observation.good)} | Questionable: {flag(observation.questionable)} | Substituted: {flag(observation.substituted)}
                  </div>
                </>
              ) : (
                <div className="py-3" data-testid={`single-value-empty-${entry.tag_id}`}>
                  <div className="h5 mb-1">Sem valor disponível</div>
                  <div className="text-muted">Sem dados</div>
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      ))}
    </Row>
  );
}
