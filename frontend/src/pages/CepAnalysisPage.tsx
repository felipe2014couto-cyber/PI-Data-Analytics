import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Modal, ProgressBar, Row, Table } from "react-bootstrap";
import type { EChartsOption } from "echarts";

import { cepApi, equipmentsApi, sectionsApi } from "../api";
import { ApiError } from "../api/http";
import { PageHeader } from "../components/PageHeader";
import type {
  CepAnalysisAccepted,
  CepAnalysisRequest,
  CepAnalysisResult,
  CepQueryCancelled,
  CepQueryRunning,
  CepRecordedSeries,
  Equipment,
  Section,
  CepVariableSeries,
  CepNonConformingPoint,
} from "../types";
import { EChartsWrapper } from "../components/EChartsWrapper";

const CEP_PROGRESS_POLL_INTERVAL_MS = 500;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function toIsoUtc(dateStr: string): string {
  if (!dateStr) return "";
  return new Date(dateStr).toISOString();
}

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(1) + "%";
}

function formatDatetime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "UTC" });
  } catch {
    return iso;
  }
}

function formatOccurrenceDatetime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pt-BR", {
      timeZone: "UTC",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function statusBadge(status: string) {
  const map: Record<string, { bg: string; label: string }> = {
    completed: { bg: "success", label: "Concluído" },
    partial: { bg: "warning", label: "Parcial" },
    failed: { bg: "danger", label: "Falha" },
    pending: { bg: "info", label: "Pendente" },
    running: { bg: "primary", label: "Executando" },
    cancelled: { bg: "secondary", label: "Cancelado" },
    processed: { bg: "success", label: "Processado" },
    no_data: { bg: "secondary", label: "Sem dados" },
    error: { bg: "danger", label: "Erro" },
  };
  const entry = map[status] ?? { bg: "secondary", label: status };
  return <Badge bg={entry.bg}>{entry.label}</Badge>;
}

export function buildCepSeriesChartOption(series: CepVariableSeries): EChartsOption {
  const points = (field: "value" | "lower_limit" | "upper_limit") =>
    series.points.map((point) => [
      point.timestamp,
      point[field] === -999 ? null : point[field],
    ] as [string, number | null]);
  return {
    tooltip: { trigger: "axis" },
    legend: { data: ["Tag de análise", "Limite inferior", "Limite superior"] },
    grid: { left: 60, right: 24, top: 48, bottom: 72 },
    xAxis: { type: "time" },
    yAxis: { type: "value" },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, bottom: 16, height: 24 },
    ],
    animation: false,
    series: [
      { name: "Tag de análise", type: "line", showSymbol: false, connectNulls: false, data: points("value"), lineStyle: { color: "#1976d2" }, itemStyle: { color: "#1976d2" } },
      { name: "Limite inferior", type: "line", showSymbol: false, connectNulls: false, data: points("lower_limit"), lineStyle: { color: "#dc3545" }, itemStyle: { color: "#dc3545" } },
      { name: "Limite superior", type: "line", showSymbol: false, connectNulls: false, data: points("upper_limit"), lineStyle: { color: "#dc3545" }, itemStyle: { color: "#dc3545" } },
    ],
  };
}

function CepVariableSeriesPanel({
  series,
  loading,
  error,
}: {
  series: CepVariableSeries | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <div className="text-muted py-3">Carregando série...</div>;
  if (error) return <Alert variant="danger" className="mb-0">{error}</Alert>;
  if (!series) return null;
  const lower = series.lower_limit !== null ? String(series.lower_limit) : "variável no tempo/ausente";
  const upper = series.upper_limit !== null ? String(series.upper_limit) : "variável no tempo/ausente";
  return (
    <div>
      <div className="small mb-2">
        <div><strong>Variável:</strong> {series.variable_name}</div>
        <div><strong>Tag utilizada:</strong> {series.analysis_tag || "—"}</div>
        <div><strong>Limite inferior:</strong> {lower} | <strong>Limite superior:</strong> {upper}</div>
      </div>
      {series.points.length === 0 ? (
        <Alert variant="secondary" className="mb-0">A tag não possui pontos Interpolated no período.</Alert>
      ) : (
        <EChartsWrapper option={buildCepSeriesChartOption(series)} height={360} />
      )}
    </div>
  );
}

function NonConformingTable({ points }: { points: CepNonConformingPoint[] }) {
  if (points.length === 0) {
    return <div className="text-muted small">Nenhuma ocorrência não conforme neste período.</div>;
  }
  return (
    <Table size="sm" striped hover className="mb-0">
      <thead>
        <tr>
          <th>Horário</th>
          <th>Valor</th>
          <th>Limite inferior</th>
          <th>Limite superior</th>
        </tr>
      </thead>
      <tbody>
        {points.map((point, index) => (
          <tr key={`${point.timestamp}-${index}`}>
            <td>{formatOccurrenceDatetime(point.timestamp)}</td>
            <td>{point.value}</td>
            <td>{point.lower_limit ?? "—"}</td>
            <td>{point.upper_limit ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

// ---------------------------------------------------------------------------
// Recorded pagination
// ---------------------------------------------------------------------------

const RECORDED_PAGE_SIZE = 100;

function RecordedSeriesPanel({ series }: { series: CepRecordedSeries }) {
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(series.points.length / RECORDED_PAGE_SIZE));
  const pagePoints = series.points.slice(page * RECORDED_PAGE_SIZE, (page + 1) * RECORDED_PAGE_SIZE);

  return (
    <Card className="mb-2">
      <Card.Header
        className="d-flex justify-content-between align-items-center"
        style={{ cursor: "pointer" }}
        onClick={() => setExpanded(!expanded)}
      >
        <span>
          <strong>{series.tag_name}</strong>
          {" — "}
          {series.points.length} pontos
          {series.truncated ? " (truncado)" : ""}
        </span>
        <span>{expanded ? "▲" : "▼"}</span>
      </Card.Header>
      {expanded && (
        <Card.Body>
          {series.truncated && (
            <Alert variant="warning" className="mb-2">
              Série truncada. {series.source_point_count === null
                ? "Total de pontos na fonte desconhecido."
                : `Total na fonte: ${series.source_point_count}`}
            </Alert>
          )}
          <div style={{ maxHeight: 300, overflow: "auto" }}>
            <Table size="sm" striped hover>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Valor</th>
                  <th>Good</th>
                  <th>Questionable</th>
                </tr>
              </thead>
              <tbody>
                {pagePoints.map((p, i) => (
                  <tr key={i}>
                    <td>{formatDatetime(p.timestamp)}</td>
                    <td>{p.value !== null && p.value !== undefined ? p.value : "—"}</td>
                    <td>{p.good ? "Sim" : "Não"}</td>
                    <td>{p.questionable ? "Sim" : "Não"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          {totalPages > 1 && (
            <div className="d-flex justify-content-between align-items-center mt-2">
              <Button size="sm" variant="outline-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Anterior
              </Button>
              <span>Página {page + 1} de {totalPages}</span>
              <Button size="sm" variant="outline-secondary" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
                Próxima
              </Button>
            </div>
          )}
        </Card.Body>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function CepAnalysisPage() {
  // Form state
  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [equipmentId, setEquipmentId] = useState<number | "">("");
  const [sectionId, setSectionId] = useState<number | "">("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [includeRecorded, setIncludeRecorded] = useState(false);
  const [periodMode, setPeriodMode] = useState<"relative" | "custom">("relative");
  const [relativePeriod, setRelativePeriod] = useState("24h");
  const [interpolatedInterval, setInterpolatedInterval] = useState<CepAnalysisRequest["interpolated_interval"]>("5m");

  // Operation state
  const [queryId, setQueryId] = useState<string | null>(null);
  const [queryStatus, setQueryStatus] = useState<string | null>(null);
  const [progressPercent, setProgressPercent] = useState(0);
  const [completedVariables, setCompletedVariables] = useState(0);
  const [totalVariables, setTotalVariables] = useState(0);
  const [result, setResult] = useState<CepAnalysisResult | null>(null);
  const [cancelledInfo, setCancelledInfo] = useState<CepQueryCancelled | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);

  // Refs
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  // Load equipments and sections
  useEffect(() => {
    mountedRef.current = true;
    equipmentsApi.list({ active: true, page_size: 200 }).then((r) => {
      if (mountedRef.current) setEquipments(r.items);
    }).catch(() => {});
    sectionsApi.list({ active: true, page_size: 200 }).then((r) => {
      if (mountedRef.current) setSections(r.items);
    }).catch(() => {});
    return () => { mountedRef.current = false; };
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollingRef.current) clearTimeout(pollingRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  // Polling logic
  const pollStatus = useCallback(async (qid: string) => {
    if (!mountedRef.current) return;
    try {
      const resp = await cepApi.getStatus(qid);
      if (!mountedRef.current) return;

      if (resp.query_status === "pending" || resp.query_status === "running") {
        setQueryStatus(resp.query_status);
        setProgressPercent(resp.progress_percent);
        setCompletedVariables(resp.completed_variables);
        setTotalVariables(resp.total_variables);
        if (resp.query_status === "running") {
          setStartedAt((resp as CepQueryRunning).started_at);
        }
        pollingRef.current = setTimeout(() => pollStatus(qid), CEP_PROGRESS_POLL_INTERVAL_MS);
      } else if (resp.query_status === "completed" || resp.query_status === "failed") {
        setQueryStatus(resp.query_status);
        setProgressPercent((resp as CepAnalysisResult).progress_percent);
        setCompletedVariables((resp as CepAnalysisResult).completed_variables);
        setTotalVariables((resp as CepAnalysisResult).total_variables);
        setResult(resp as CepAnalysisResult);
      } else if (resp.query_status === "cancelled") {
        setQueryStatus("cancelled");
        setProgressPercent(resp.progress_percent);
        setCompletedVariables(resp.completed_variables);
        setTotalVariables(resp.total_variables);
        setCancelledInfo(resp as CepQueryCancelled);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        setQueryStatus("expired");
        setError("Operação não encontrada ou expirada.");
      } else if (err instanceof ApiError && err.status === 401) {
        // Auth error - handled by interceptor
      } else {
        setError("Erro de conexão. Tente novamente.");
      }
    }
  }, []);

  // Submit analysis
  const handleSubmit = async () => {
    setError(null);
    setResult(null);
    setCancelledInfo(null);
    setQueryStatus(null);
    setProgressPercent(0);
    setCompletedVariables(0);
    setTotalVariables(0);
    setQueryId(null);
    setStartedAt(null);

    let startIso: string;
    let endIso: string;
    if (periodMode === "relative") {
      const end = new Date();
      const durationHours: Record<string, number> = { "1h": 1, "6h": 6, "12h": 12, "24h": 24, "7d": 24 * 7, "15d": 24 * 15, "30d": 24 * 30 };
      const hours = durationHours[relativePeriod];
      if (!hours) {
        setError("Período relativo inválido.");
        return;
      }
      endIso = end.toISOString();
      startIso = new Date(end.getTime() - hours * 60 * 60 * 1000).toISOString();
    } else {
      if (!startTime || !endTime) {
        setError("Período inicial e final são obrigatórios.");
        return;
      }
      startIso = toIsoUtc(startTime);
      endIso = toIsoUtc(endTime);
    }

    if (startIso >= endIso) {
      setError("A data inicial deve ser anterior à data final.");
      return;
    }

    const payload: CepAnalysisRequest = {
      start_time: startIso,
      end_time: endIso,
      include_recorded: includeRecorded,
      interpolated_interval: interpolatedInterval,
    };
    if (equipmentId !== "") payload.equipment_id = Number(equipmentId);
    if (sectionId !== "") payload.section_id = Number(sectionId);

    setSubmitting(true);
    try {
      const accepted: CepAnalysisAccepted = await cepApi.startAnalysis(payload);
      if (!mountedRef.current) return;
      setQueryId(accepted.query_id);
      setQueryStatus("pending");
      setProgressPercent(accepted.progress_percent);
      setCompletedVariables(accepted.completed_variables);
      setTotalVariables(accepted.total_variables);
      pollStatus(accepted.query_id);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Erro ao iniciar análise.");
      }
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  // Cancel analysis
  const handleCancel = async () => {
    setShowCancelModal(false);
    if (!queryId) return;
    try {
      const resp = await cepApi.cancelAnalysis(queryId);
      if (!mountedRef.current) return;
      setQueryStatus("cancelled");
      setProgressPercent(resp.progress_percent);
      setCompletedVariables(resp.completed_variables);
      setTotalVariables(resp.total_variables);
      setCancelledInfo(resp);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError("Operação já finalizada e não pode ser cancelada.");
        } else if (err.status === 404) {
          setError("Operação não encontrada ou expirada.");
        } else {
          setError(err.message);
        }
      }
    }
  };

  // Reset for new analysis
  const handleNew = () => {
    setQueryId(null);
    setQueryStatus(null);
    setProgressPercent(0);
    setCompletedVariables(0);
    setTotalVariables(0);
    setResult(null);
    setCancelledInfo(null);
    setStartedAt(null);
    setError(null);
  };

  const isTerminal = queryStatus === "completed" || queryStatus === "failed" ||
    queryStatus === "cancelled" || queryStatus === "expired";
  const canCancel = queryStatus === "pending" || queryStatus === "running";
  const availableSections = equipmentId === ""
    ? sections
    : sections.filter((section) => section.equipment_id === equipmentId);

  return (
    <div>
      <PageHeader title="Análise CEP" subtitle="Análise de conformidade de processo" />

      {/* Error alert */}
      {error && (
        <Alert variant="danger" dismissible onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Configuration form - shown when no active query */}
      {!queryId && (
        <Card className="mb-4">
          <Card.Header><strong>Configuração</strong></Card.Header>
          <Card.Body>
            <Row className="mb-3">
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Equipamento</Form.Label>
                  <Form.Select
                    value={equipmentId}
                    onChange={(e) => {
                      const nextEquipmentId = e.target.value === "" ? "" : Number(e.target.value);
                      setEquipmentId(nextEquipmentId);
                      if (sectionId !== "" && nextEquipmentId !== "" && !sections.some(
                        (section) => section.id === sectionId && section.equipment_id === nextEquipmentId,
                      )) setSectionId("");
                    }}
                  >
                    <option value="">Todos</option>
                    {equipments.map((eq) => (
                      <option key={eq.id} value={eq.id}>{eq.name}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Seção</Form.Label>
                  <Form.Select
                    value={sectionId}
                    onChange={(e) => setSectionId(e.target.value === "" ? "" : Number(e.target.value))}
                  >
                    <option value="">Todas</option>
                    {availableSections.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
            </Row>
            <Row className="mb-3">
              <Col md={4}>
                <Form.Group className="mb-3">
                  <Form.Label>Período</Form.Label>
                  <Form.Select value={periodMode} onChange={(e) => setPeriodMode(e.target.value as "relative" | "custom")}>
                    <option value="relative">Relativo</option>
                    <option value="custom">Personalizado</option>
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={4}>
                <Form.Group className="mb-3">
                  <Form.Label>Intervalo Interpolated</Form.Label>
                  <Form.Select value={interpolatedInterval} onChange={(e) => setInterpolatedInterval(e.target.value as CepAnalysisRequest["interpolated_interval"])}>
                    <option value="1m">1 minuto</option>
                    <option value="2m">2 minutos</option>
                    <option value="5m">5 minutos</option>
                    <option value="10m">10 minutos</option>
                    <option value="15m">15 minutos</option>
                    <option value="30m">30 minutos</option>
                    <option value="1h">1 hora</option>
                  </Form.Select>
                </Form.Group>
              </Col>
              {periodMode === "relative" && (
                <Col md={4}>
                  <Form.Group className="mb-3">
                    <Form.Label>Período relativo</Form.Label>
                    <Form.Select value={relativePeriod} onChange={(e) => setRelativePeriod(e.target.value)}>
                      <option value="1h">Última 1 hora</option>
                      <option value="6h">Últimas 6 horas</option>
                      <option value="12h">Últimas 12 horas</option>
                      <option value="24h">Últimas 24 horas</option>
                      <option value="7d">Últimos 7 dias</option>
                      <option value="15d">Últimos 15 dias</option>
                      <option value="30d">Últimos 30 dias</option>
                    </Form.Select>
                  </Form.Group>
                </Col>
              )}
            </Row>
            <Row className="mb-3">
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Data/hora inicial</Form.Label>
                  <Form.Control
                    type="datetime-local"
                    value={startTime}
                    disabled={periodMode === "relative"}
                    onChange={(e) => setStartTime(e.target.value)}
                  />
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group className="mb-3">
                  <Form.Label>Data/hora final</Form.Label>
                  <Form.Control
                    type="datetime-local"
                    value={endTime}
                    disabled={periodMode === "relative"}
                    onChange={(e) => setEndTime(e.target.value)}
                  />
                </Form.Group>
              </Col>
            </Row>
            <Row className="mb-3">
              <Col>
                <Form.Check
                  type="checkbox"
                  label="Incluir dados Recorded"
                  checked={includeRecorded}
                  onChange={(e) => setIncludeRecorded(e.target.checked)}
                />
              </Col>
            </Row>
            <div className="d-flex justify-content-end">
              <Button variant="primary" onClick={handleSubmit} disabled={submitting}>
                {submitting ? "Iniciando..." : "Iniciar Análise"}
              </Button>
            </div>
          </Card.Body>
        </Card>
      )}

      {/* Tracking - shown when query is active */}
      {queryId && !isTerminal && (
        <Card className="mb-4">
          <Card.Header><strong>Acompanhamento</strong></Card.Header>
          <Card.Body>
            <Row>
              <Col md={4}>
                <div className="mb-2"><strong>Estado:</strong> {statusBadge(queryStatus ?? "")}</div>
                <ProgressBar now={progressPercent} label={`${progressPercent}%`} className="mb-1" />
                <div className="small text-muted">{completedVariables} de {totalVariables} variáveis</div>
              </Col>
              <Col md={4}>
                <div className="mb-2"><strong>ID:</strong> <code>{queryId}</code></div>
              </Col>
              <Col md={4}>
                {startedAt && (
                  <div className="mb-2"><strong>Início:</strong> {formatDatetime(startedAt)}</div>
                )}
              </Col>
            </Row>
            {canCancel && (
              <div className="mt-3">
                <Button variant="outline-danger" size="sm" onClick={() => setShowCancelModal(true)}>
                  Cancelar Análise
                </Button>
              </div>
            )}
          </Card.Body>
        </Card>
      )}

      {/* Cancelled state */}
      {queryStatus === "cancelled" && cancelledInfo && (
        <Card className="mb-4">
          <Card.Header><strong>Operação Cancelada</strong></Card.Header>
          <Card.Body>
            <p>{cancelledInfo.message}</p>
            <ProgressBar now={progressPercent} label={`${progressPercent}%`} className="mb-1" />
            <div className="small text-muted mb-3">{completedVariables} de {totalVariables} variáveis</div>
            <p className="text-muted">ID: {cancelledInfo.query_id}</p>
            <Button variant="primary" onClick={handleNew}>Nova Análise</Button>
          </Card.Body>
        </Card>
      )}

      {/* Result */}
      {result && queryId && <ResultPanel result={result} queryId={queryId} onNew={handleNew} />}

      {/* Cancel confirmation modal */}
      <Modal show={showCancelModal} onHide={() => setShowCancelModal(false)}>
        <Modal.Header closeButton>
          <Modal.Title>Confirmar Cancelamento</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          Deseja realmente cancelar esta análise?
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setShowCancelModal(false)}>Não</Button>
          <Button variant="danger" onClick={handleCancel}>Sim, Cancelar</Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result panel
// ---------------------------------------------------------------------------

function ResultPanel({ result, queryId, onNew }: { result: CepAnalysisResult; queryId: string; onNew: () => void }) {
  const { summary, variables, diagnostics, recorded_series, metadata } = result;
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [expandedNonConformities, setExpandedNonConformities] = useState<Set<number>>(new Set());
  const [seriesCache, setSeriesCache] = useState<Record<number, CepVariableSeries>>({});
  const [seriesLoading, setSeriesLoading] = useState<Set<number>>(new Set());
  const [seriesErrors, setSeriesErrors] = useState<Record<number, string>>({});

  const toggleVariable = async (variableId: number) => {
    const nextExpanded = new Set(expanded);
    if (nextExpanded.has(variableId)) {
      nextExpanded.delete(variableId);
      setExpanded(nextExpanded);
      return;
    }
    nextExpanded.add(variableId);
    setExpanded(nextExpanded);
    if (seriesCache[variableId] || seriesLoading.has(variableId)) return;
    setSeriesLoading((current) => new Set(current).add(variableId));
    setSeriesErrors((current) => {
      const next = { ...current };
      delete next[variableId];
      return next;
    });
    try {
      const fetched = await cepApi.getVariableSeries(queryId, variableId);
      setSeriesCache((current) => ({ ...current, [variableId]: fetched }));
    } catch (err) {
      const message = err instanceof ApiError && err.status === 404
        ? "Série não encontrada, pois a operação expirou ou a variável não pertence a ela."
        : "Não foi possível carregar a série da variável.";
      setSeriesErrors((current) => ({ ...current, [variableId]: message }));
    } finally {
      setSeriesLoading((current) => {
        const next = new Set(current);
        next.delete(variableId);
        return next;
      });
    }
  };

  const toggleNonConformities = async (variableId: number) => {
    const next = new Set(expandedNonConformities);
    if (next.has(variableId)) {
      next.delete(variableId);
      setExpandedNonConformities(next);
      return;
    }
    next.add(variableId);
    setExpandedNonConformities(next);
    if (seriesCache[variableId] || seriesLoading.has(variableId)) return;
    setSeriesLoading((current) => new Set(current).add(variableId));
    setSeriesErrors((current) => {
      const updated = { ...current };
      delete updated[variableId];
      return updated;
    });
    try {
      const fetched = await cepApi.getVariableSeries(queryId, variableId);
      setSeriesCache((current) => ({ ...current, [variableId]: fetched }));
    } catch (err) {
      const message = err instanceof ApiError && err.status === 404
        ? "Detalhamento não encontrado, pois a operação expirou ou a variável não pertence a ela."
        : "Não foi possível carregar os detalhes não conformes.";
      setSeriesErrors((current) => ({ ...current, [variableId]: message }));
    } finally {
      setSeriesLoading((current) => {
        const updated = new Set(current);
        updated.delete(variableId);
        return updated;
      });
    }
  };

  return (
    <>
      {/* Summary */}
      <Card className="mb-4">
        <Card.Header><strong>Resumo Geral</strong></Card.Header>
        <Card.Body>
          <Row>
            <Col md={3}>
              <div className="mb-2"><strong>Status:</strong> {statusBadge(summary.analysis_status)}</div>
            </Col>
            <Col md={3}>
              <div className="mb-2"><strong>Conformidade:</strong> {formatPct(summary.overall_pct)}</div>
            </Col>
            <Col md={2}>
              <div className="mb-2"><strong>Conformes:</strong> {summary.conformant_variables}</div>
            </Col>
            <Col md={2}>
              <div className="mb-2"><strong>Não conformes:</strong> {summary.non_conformant_variables}</div>
            </Col>
            <Col md={2}>
              <div className="mb-2"><strong>Sem dados:</strong> {summary.no_data_variables}</div>
            </Col>
          </Row>
          <Row>
            <Col md={6}>
              <div className="mb-2"><strong>Progresso:</strong> {result.progress_percent}%</div>
              <ProgressBar now={result.progress_percent} label={`${result.progress_percent}%`} />
            </Col>
            <Col md={6}>
              <div className="mb-2"><strong>Variáveis processadas:</strong> {result.completed_variables} de {result.total_variables}</div>
            </Col>
          </Row>
          <Row>
            <Col md={3}>
              <div className="mb-2"><strong>Erros:</strong> {summary.failed_variables}</div>
            </Col>
            <Col md={3}>
              <div className="mb-2"><strong>Total:</strong> {summary.total_variables}</div>
            </Col>
            <Col md={3}>
              <div className="mb-2"><strong>Período:</strong> {formatDatetime(summary.period_start)}</div>
            </Col>
            <Col md={3}>
              <div className="mb-2"><strong>Até:</strong> {formatDatetime(summary.period_end)}</div>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {/* Variables table */}
      <Card className="mb-4">
        <Card.Header><strong>Resultados por Variável</strong></Card.Header>
        <Card.Body>
          <div style={{ overflowX: "auto" }}>
            <Table striped hover size="sm">
              <thead>
                <tr>
                  <th>Variável</th>
                  <th>Código</th>
                  <th>Status</th>
                  <th>Conformidade</th>
                  <th>Total</th>
                  <th>Conformes</th>
                  <th>Não conformes</th>
                  <th>Sem dados</th>
                </tr>
              </thead>
              <tbody>
                {variables.map((v) => (
                  <Fragment key={v.variable_id}>
                    <tr>
                      <td>
                        <Button
                          variant="link"
                          size="sm"
                          className="p-0 me-2 text-decoration-none"
                          aria-label={`${expanded.has(v.variable_id) ? "Recolher" : "Expandir"} ${v.name}`}
                          onClick={() => { void toggleVariable(v.variable_id); }}
                        >
                          {expanded.has(v.variable_id) ? "▾" : "▸"}
                        </Button>
                        {v.name}
                      </td>
                      <td><code>{v.code}</code></td>
                      <td>{statusBadge(v.status)}</td>
                      <td>{formatPct(v.conformity_pct)}</td>
                      <td>{v.total_points}</td>
                      <td>{v.conformant}</td>
                      <td>
                        {v.non_conformant > 0 ? (
                          <Button
                            variant="link"
                            size="sm"
                            className="p-0 text-decoration-none"
                            aria-label={`${expandedNonConformities.has(v.variable_id) ? "Recolher" : "Expandir"} não conformes de ${v.name}`}
                            onClick={() => { void toggleNonConformities(v.variable_id); }}
                          >
                            {v.non_conformant} {expandedNonConformities.has(v.variable_id) ? "▾" : "▸"}
                          </Button>
                        ) : v.non_conformant}
                      </td>
                      <td>{v.no_data}</td>
                    </tr>
                    {(expanded.has(v.variable_id) || expandedNonConformities.has(v.variable_id)) && (
                      <tr>
                        <td colSpan={8} className="bg-light">
                          {expanded.has(v.variable_id) && (
                            <CepVariableSeriesPanel
                              series={seriesCache[v.variable_id] ?? null}
                              loading={seriesLoading.has(v.variable_id)}
                              error={seriesErrors[v.variable_id] ?? null}
                            />
                          )}
                          {expandedNonConformities.has(v.variable_id) && (
                            <div className={expanded.has(v.variable_id) ? "mt-3" : ""}>
                              <div className="fw-semibold mb-2">Detalhes não conformes</div>
                              {seriesLoading.has(v.variable_id) && !seriesCache[v.variable_id] ? (
                                <div className="text-muted">Carregando ocorrências...</div>
                              ) : seriesErrors[v.variable_id] && !seriesCache[v.variable_id] ? (
                                <Alert variant="danger" className="mb-0">{seriesErrors[v.variable_id]}</Alert>
                              ) : seriesCache[v.variable_id] ? (
                                <NonConformingTable points={seriesCache[v.variable_id].non_conforming_points} />
                              ) : null}
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </Table>
          </div>
        </Card.Body>
      </Card>

      {/* Diagnostics */}
      {diagnostics.length > 0 && (
        <Card className="mb-4">
          <Card.Header><strong>Diagnósticos</strong></Card.Header>
          <Card.Body>
            {diagnostics.map((d, i) => (
              <Alert key={i} variant="warning" className="mb-2">
                <strong>{d.error_code}</strong>
                {d.tag_name ? ` — ${d.tag_name}` : ""}
                {d.variable_ids.length > 0 ? ` (variáveis: ${d.variable_ids.join(", ")})` : ""}
                <div>{d.message}</div>
              </Alert>
            ))}
          </Card.Body>
        </Card>
      )}

      {/* Recorded metadata */}
      {metadata.recorded_total_limit_reached && (
        <Alert variant="warning" className="mb-4">
          <strong>Limite agregado de Recorded atingido.</strong>
          {metadata.recorded_tags_not_acquired.length > 0 && (
            <div>Tags não adquiridas: {metadata.recorded_tags_not_acquired.join(", ")}</div>
          )}
        </Alert>
      )}

      {/* Recorded series */}
      {recorded_series && recorded_series.length > 0 && (
        <Card className="mb-4">
          <Card.Header><strong>Dados Recorded</strong></Card.Header>
          <Card.Body>
            <div className="mb-2 text-muted">
              Limite: {metadata.recorded_total_point_limit} pontos |
              Retornados: {metadata.recorded_returned_point_count} pontos
            </div>
            {recorded_series.map((s) => (
              <RecordedSeriesPanel key={s.tag_id} series={s} />
            ))}
          </Card.Body>
        </Card>
      )}

      {/* Metadata */}
      <Card className="mb-4">
        <Card.Header><strong>Metadados</strong></Card.Header>
        <Card.Body>
          <Row>
            <Col md={4}>
              <div className="mb-2"><strong>Duração:</strong> {metadata.duration_ms !== null ? `${metadata.duration_ms} ms` : "—"}</div>
            </Col>
            <Col md={4}>
              <div className="mb-2"><strong>Requests PI:</strong> {metadata.pi_request_count ?? "—"}</div>
            </Col>
            <Col md={4}>
              <div className="mb-2"><strong>Pontos recebidos:</strong> {metadata.pi_points_received ?? "—"}</div>
            </Col>
          </Row>
          <Row>
            <Col md={4}>
              <div className="mb-2"><strong>Tags processadas:</strong> {metadata.tags_processed ?? "—"}</div>
            </Col>
            <Col md={4}>
              <div className="mb-2"><strong>Tags com falha:</strong> {metadata.tags_failed ?? "—"}</div>
            </Col>
            <Col md={4}>
              <div className="mb-2"><strong>WebIds resolvidos:</strong> {metadata.webid_resolved ?? "—"}</div>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <div className="d-flex justify-content-end">
        <Button variant="primary" onClick={onNew}>Nova Análise</Button>
      </div>
    </>
  );
}
