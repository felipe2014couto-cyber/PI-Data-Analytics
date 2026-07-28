import { Button, Form } from "react-bootstrap";

import type { SeriesAssignment, SeriesAxis } from "../types";
import { assignmentIdentity } from "../utils/seriesAssignments";

export interface SeriesConfigurationTag {
  tagId: number;
  seriesInstanceId?: string;
  displayName: string;
  tagName: string;
  unit: string | null;
  numeric: boolean;
}

interface SeriesAssignmentsPanelProps {
  assignments: SeriesAssignment[];
  tags: SeriesConfigurationTag[];
  showScatter: boolean;
  errors: string[];
  onMove: (seriesId: string | number, direction: "up" | "down") => void;
  onLineAxisChange: (seriesId: string | number, axis: SeriesAxis) => void;
  onScatterAxisChange: (role: "x" | "y", seriesId: string | number | null) => void;
}

export function SeriesAssignmentsPanel({
  assignments,
  tags,
  showScatter,
  errors,
  onMove,
  onLineAxisChange,
  onScatterAxisChange,
}: SeriesAssignmentsPanelProps) {
  const tagById = new Map(tags.map((tag) => [assignmentIdentity(tag), tag]));
  const ordered = [...assignments].sort((left, right) => left.order - right.order);
  const numericTags = ordered
    .map((assignment) => tagById.get(assignmentIdentity(assignment)))
    .filter((tag): tag is SeriesConfigurationTag => Boolean(tag?.numeric));
  const xSeriesId = assignments.find((assignment) => assignment.scatterRole === "x");
  const ySeriesId = assignments.find((assignment) => assignment.scatterRole === "y");

  return (
    <section aria-labelledby="series-configuration-title" data-testid="series-configuration">
      <h6 id="series-configuration-title" className="mb-2">Configuração das séries e eixos</h6>
      {ordered.length === 0 ? (
        <div className="text-muted small">Selecione tags para configurar ordem e eixos.</div>
      ) : (
        <div className="d-flex flex-column gap-2">
          {ordered.map((assignment, index) => {
            const seriesId = assignmentIdentity(assignment);
            const controlId = assignment.seriesInstanceId ?? assignment.tagId;
            const tag = tagById.get(seriesId);
            if (!tag) return null;
            return (
              <div key={seriesId} className="border rounded p-2" data-testid={`series-assignment-${tag.seriesInstanceId ?? tag.tagId}`}>
                <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
                  <div className="small text-break">
                    <strong>{tag.displayName}</strong><br />
                    <span className="text-muted">{tag.tagName}{tag.unit?.trim() ? ` | ${tag.unit.trim()}` : " | Sem unidade"}</span>
                  </div>
                  <div className="btn-group btn-group-sm" role="group" aria-label={`Ordenar ${tag.displayName}`}>
                    <Button variant="outline-secondary" size="sm" disabled={index === 0}
                      aria-label={`Mover ${tag.displayName} para cima`} data-testid={`move-up-${assignment.tagId}`}
                      onClick={() => onMove(controlId, "up")}><i className="bi bi-arrow-up" /></Button>
                    <Button variant="outline-secondary" size="sm" disabled={index === ordered.length - 1}
                      aria-label={`Mover ${tag.displayName} para baixo`} data-testid={`move-down-${assignment.tagId}`}
                      onClick={() => onMove(controlId, "down")}><i className="bi bi-arrow-down" /></Button>
                  </div>
                </div>
                {tag.numeric ? (
                  <Form.Group controlId={`line-axis-${assignment.tagId}`}>
                    <Form.Label className="small mb-1">Eixo da linha</Form.Label>
                    <Form.Select size="sm" value={assignment.lineAxis}
                      data-testid={`line-axis-${assignment.tagId}`}
                    onChange={(event) => onLineAxisChange(controlId, event.target.value as SeriesAxis)}>
                      <option value="primary">Eixo Y principal (esquerda)</option>
                      <option value="secondary">Eixo Y secundário (direita)</option>
                    </Form.Select>
                  </Form.Group>
                ) : <div className="small text-muted">Série não numérica: sem eixo Y numérico.</div>}
              </div>
            );
          })}
        </div>
      )}

      {showScatter ? (
        <div className="border rounded p-2 mt-3" data-testid="scatter-axis-configuration">
          <Form.Group controlId="scatter-x" className="mb-2">
            <Form.Label>Eixo X</Form.Label>
            <Form.Select value={xSeriesId ? (xSeriesId.seriesInstanceId ?? xSeriesId.tagId) : ""} data-testid="scatter-x"
              onChange={(event) => { const tag = numericTags.find((item) => String(item.seriesInstanceId ?? item.tagId) === event.target.value); onScatterAxisChange("x", tag ? (tag.seriesInstanceId ?? tag.tagId) : null); }}>
              <option value="">Selecione uma tag numérica</option>
              {numericTags.map((tag) => { const id = assignmentIdentity(tag); const value = tag.seriesInstanceId ?? tag.tagId; return <option key={id} value={value} disabled={id === (ySeriesId ? assignmentIdentity(ySeriesId) : null)}>{tag.displayName} — {tag.tagName}</option>; })}
            </Form.Select>
          </Form.Group>
          <Form.Group controlId="scatter-y">
            <Form.Label>Eixo Y</Form.Label>
            <Form.Select value={ySeriesId ? (ySeriesId.seriesInstanceId ?? ySeriesId.tagId) : ""} data-testid="scatter-y"
              onChange={(event) => { const tag = numericTags.find((item) => String(item.seriesInstanceId ?? item.tagId) === event.target.value); onScatterAxisChange("y", tag ? (tag.seriesInstanceId ?? tag.tagId) : null); }}>
              <option value="">Selecione uma tag numérica</option>
              {numericTags.map((tag) => { const id = assignmentIdentity(tag); const value = tag.seriesInstanceId ?? tag.tagId; return <option key={id} value={value} disabled={id === (xSeriesId ? assignmentIdentity(xSeriesId) : null)}>{tag.displayName} — {tag.tagName}</option>; })}
            </Form.Select>
          </Form.Group>
        </div>
      ) : null}

      {errors.length > 0 ? (
        <div className="text-danger small mt-2" role="alert" data-testid="series-assignment-errors">
          {errors.map((error) => <div key={error}>{error}</div>)}
        </div>
      ) : null}
    </section>
  );
}
