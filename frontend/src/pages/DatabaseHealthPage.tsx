import { useCallback, useEffect, useId, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Nav,
  OverlayTrigger,
  Row,
  Spinner,
  Tab,
  Table,
  Tooltip,
} from "react-bootstrap";

import { databaseHealthApi } from "../api";
import type {
  DatabaseHealthResponse,
  DatabaseHealthStatus,
  HealthCheckItem,
  StorageRelationInfo,
} from "../types";

function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "-";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "N/A";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  }
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let val = bytes;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx++;
  }
  return `${val.toFixed(2)} ${units[idx]}`;
}

function getStatusBadgeVariant(status: DatabaseHealthStatus): string {
  switch (status) {
    case "healthy":
      return "success";
    case "warning":
      return "warning";
    case "critical":
      return "danger";
    case "unavailable":
    default:
      return "secondary";
  }
}

function getStatusLabel(status: DatabaseHealthStatus): string {
  switch (status) {
    case "healthy":
      return "Saudável";
    case "warning":
      return "Alerta";
    case "critical":
      return "Crítico";
    case "unavailable":
    default:
      return "Indisponível";
  }
}

export function DatabaseHealthPage() {
  const autoRefreshSelectId = useId();
  const [data, setData] = useState<DatabaseHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [intervalSeconds, setIntervalSeconds] = useState<number>(30);
  const [activeTab, setActiveTab] = useState<string>("storage");

  const fetchHealth = useCallback(async (bypassCache: boolean = false) => {
    if (bypassCache) {
      setIsRefreshing(true);
    }
    try {
      const response = await databaseHealthApi.getHealth(bypassCache);
      setData(response);
      setError(null);
      setRefreshError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro ao consultar saúde do banco de dados";
      setData((prev) => {
        if (!prev) {
          setError(msg);
        } else {
          setRefreshError("Falha na atualização dos dados. Exibindo última leitura com sucesso.");
        }
        return prev;
      });
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    void fetchHealth(false);
  }, [fetchHealth]);

  // Controlled auto-refresh with cleanup
  useEffect(() => {
    if (intervalSeconds <= 0) return;
    const timer = setInterval(() => {
      void fetchHealth(false);
    }, intervalSeconds * 1000);
    return () => clearInterval(timer);
  }, [intervalSeconds, fetchHealth]);

  const storageTooltip = (
    <Tooltip id="storage-tooltip">
      O tamanho exibido representa o volume lógico ocupado pela base de dados no PostgreSQL/TimescaleDB.
      O espaço livre total em disco no sistema operacional não está disponível nesta camada por restrições
      de permissão e segurança.
    </Tooltip>
  );

  return (
    <div className="database-health-page">
      {/* Header */}
      <div className="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-3">
        <div>
          <div className="d-flex align-items-center gap-2">
            <h1 className="h4 mb-0 fw-bold text-navy">
              <i className="bi bi-database-fill-gear me-2 text-primary" />
              Saúde do Banco
            </h1>
            {data && (
              <Badge
                bg={getStatusBadgeVariant(data.status)}
                className="px-2 py-1 fs-6"
                data-testid="consolidated-status-badge"
              >
                {getStatusLabel(data.status)}
              </Badge>
            )}
          </div>
          <div className="text-muted small mt-1">
            Monitoramento operacional e diagnóstico do PostgreSQL / TimescaleDB
          </div>
        </div>

        <div className="d-flex flex-wrap align-items-center gap-2">
          {data && (
            <div className="d-flex align-items-center gap-2 me-2 small text-muted">
              <span>
                Última checagem: <strong>{formatDate(data.checked_at)}</strong>
              </span>
              <Badge bg="light" text="dark" className="border">
                {data.duration_ms} ms
              </Badge>
              {data.cached ? (
                <Badge bg="info" className="text-white" title="Resposta recuperada do cache em memória">
                  Cache
                </Badge>
              ) : (
                <Badge bg="secondary" title="Resposta consultada em tempo real no banco">
                  Direto
                </Badge>
              )}
            </div>
          )}

          <div className="d-flex align-items-center gap-1">
            <Form.Label htmlFor={autoRefreshSelectId} className="visually-hidden">
              Atualização automática
            </Form.Label>
            <Form.Select
              id={autoRefreshSelectId}
              size="sm"
              value={intervalSeconds}
              onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              style={{ width: "160px" }}
              title="Intervalo de atualização automática"
              aria-label="Atualização automática"
            >
              <option value={0}>Auto-refresh: Desativado</option>
              <option value={30}>Auto-refresh: 30s</option>
              <option value={60}>Auto-refresh: 1 min</option>
              <option value={300}>Auto-refresh: 5 min</option>
            </Form.Select>

            <Button
              size="sm"
              variant="outline-primary"
              disabled={isRefreshing || loading}
              onClick={() => void fetchHealth(true)}
              className="d-flex align-items-center gap-1"
            >
              {isRefreshing ? (
                <>
                  <Spinner size="sm" animation="border" />
                  <span>Atualizando...</span>
                </>
              ) : (
                <>
                  <i className="bi bi-arrow-clockwise" />
                  <span>Atualizar agora</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Dismissible warning when background refresh failed but we still have data */}
      {refreshError && (
        <Alert
          variant="warning"
          dismissible
          onClose={() => setRefreshError(null)}
          className="d-flex align-items-center gap-2"
        >
          <i className="bi bi-exclamation-triangle-fill flex-shrink-0" />
          <div>{refreshError}</div>
        </Alert>
      )}

      {/* Initial loading state */}
      {loading && !data && (
        <div className="text-center py-5">
          <Spinner animation="border" variant="primary" className="mb-3" />
          <div className="text-muted">Carregando métricas de saúde do banco de dados...</div>
        </div>
      )}

      {/* Initial error state without prior data */}
      {error && !data && (
        <Alert variant="danger">
          <Alert.Heading>Erro ao consultar o banco de dados</Alert.Heading>
          <p>{error}</p>
          <hr />
          <div className="d-flex justify-content-end">
            <Button variant="outline-danger" onClick={() => void fetchHealth(true)}>
              Tentar novamente
            </Button>
          </div>
        </Alert>
      )}

      {/* Content when data is present */}
      {data && (
        <>
          {/* 8 Key Cards */}
          <Row className="g-3 mb-4">
            {/* Card 1: Estado do Banco */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Estado do Banco</span>
                    <i className="bi bi-hdd-network text-primary fs-5" />
                  </div>
                  <div className="d-flex align-items-center gap-2 mb-2">
                    <Badge bg={getStatusBadgeVariant(data.status)} className="fs-6 px-2 py-1">
                      {getStatusLabel(data.status)}
                    </Badge>
                  </div>
                  <div className="small text-muted text-truncate" title={data.database.postgresql_version ?? ""}>
                    {data.database.postgresql_version?.split(" ")[0] ?? "PostgreSQL"}
                  </div>
                  <div className="small text-secondary text-truncate" title={`${data.database.name ?? "-"} | Alembic: ${data.database.alembic_revision ?? "-"}`}>
                    {data.database.name ?? "db"} (Rev: {data.database.alembic_revision?.slice(0, 8) ?? "-"})
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 2: Latência */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Latência</span>
                    <i className="bi bi-speedometer2 text-info fs-5" />
                  </div>
                  <div className="h4 mb-1 fw-bold">
                    {data.database.latency_ms !== null ? data.database.latency_ms.toFixed(2) : "-"}{" "}
                    <span className="fs-6 fw-normal text-muted">ms</span>
                  </div>
                  <div className="small text-muted">
                    Ping de consulta SELECT 1
                  </div>
                  <div className="small text-success">
                    Uptime: {data.database.uptime_seconds ? formatDuration(data.database.uptime_seconds) : "-"}
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 3: Espaço Ocupado */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold d-flex align-items-center gap-1">
                      Espaço Ocupado
                      <OverlayTrigger placement="top" overlay={storageTooltip}>
                        <i className="bi bi-info-circle text-muted" style={{ cursor: "pointer" }} />
                      </OverlayTrigger>
                    </span>
                    <i className="bi bi-pie-chart text-warning fs-5" />
                  </div>
                  <div className="h4 mb-1 fw-bold text-dark">
                    {data.storage.database_human}
                  </div>
                  <div className="small text-muted">
                    Tabelas: {data.storage.tables_human} | Índices: {data.storage.indexes_human}
                  </div>
                  <div className="small text-secondary text-truncate" title="Espaço de SO livre indisponível">
                    {data.storage.filesystem_available === false ? "Disco SO: Indisponível" : "Disco SO: OK"}
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 4: Conexões */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Conexões</span>
                    <i className="bi bi-people-fill text-success fs-5" />
                  </div>
                  <div className="h4 mb-1 fw-bold">
                    {data.connections.current}{" "}
                    <span className="fs-6 fw-normal text-muted">
                      / {data.connections.maximum > 0 ? data.connections.maximum : "∞"}
                    </span>
                  </div>
                  <div className="small text-muted">
                    {data.connections.usage_percent !== null
                      ? `${data.connections.usage_percent.toFixed(1)}% utilizado`
                      : "Sem limite definido"}
                  </div>
                  <div className="small text-secondary">
                    {data.connections.active} ativas, {data.connections.idle} ociosas
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 5: Último Dado Recebido */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Último Dado</span>
                    <i className="bi bi-clock-history text-primary fs-5" />
                  </div>
                  <div className="fw-bold text-dark text-truncate mb-1" title={data.freshness.latest_sample_at ?? ""}>
                    {data.freshness.latest_sample_at ? formatDate(data.freshness.latest_sample_at) : "Sem dados"}
                  </div>
                  <div className="small text-muted text-truncate" title={`Recorded: ${formatDate(data.freshness.latest_recorded_sample_at)}`}>
                    Recorded: {formatDate(data.freshness.latest_recorded_sample_at)}
                  </div>
                  <div className="small text-secondary">
                    Watermark: {data.freshness.newest_watermark ? formatDate(data.freshness.newest_watermark) : "-"}
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 6: Atraso da Ingestão */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Atraso Ingestão</span>
                    <i className="bi bi-hourglass-split text-info fs-5" />
                  </div>
                  <div className="h4 mb-1 fw-bold">
                    {data.freshness.lag_seconds !== null ? formatDuration(data.freshness.lag_seconds) : "N/A"}
                  </div>
                  <div className="small text-muted">
                    {data.freshness.tags_in_backoff} tags em backoff
                  </div>
                  <div className="small text-secondary">
                    {data.freshness.tags_with_failures} tags com falhas
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 7: Recargas Históricas */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Recargas</span>
                    <i className="bi bi-cloud-arrow-down text-purple fs-5" />
                  </div>
                  <div className="h5 mb-1 fw-bold">
                    {data.freshness.backfill_jobs_by_status.RUNNING ?? 0} executando
                  </div>
                  <div className="small text-muted">
                    {data.freshness.backfill_jobs_by_status.PENDING ?? 0} pendentes
                  </div>
                  <div className="small text-secondary">
                    {data.freshness.consecutive_backfill_failures} falhas consecutivas
                  </div>
                </Card.Body>
              </Card>
            </Col>

            {/* Card 8: Locks Aguardando */}
            <Col xs={12} sm={6} lg={3}>
              <Card className="piad-card h-100 shadow-sm border-0">
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-start mb-2">
                    <span className="text-muted small text-uppercase fw-semibold">Locks Aguardando</span>
                    <i className="bi bi-lock-fill text-danger fs-5" />
                  </div>
                  <div className={`h4 mb-1 fw-bold ${data.locks.waiting > 0 ? "text-danger" : "text-success"}`}>
                    {data.locks.waiting}
                  </div>
                  <div className="small text-muted">
                    {data.locks.blocked_sessions} sessões bloqueadas
                  </div>
                  <div className="small text-secondary">
                    {data.locks.advisory_locks} advisory locks ativos
                  </div>
                </Card.Body>
              </Card>
            </Col>
          </Row>

          {/* Detailed Tabbed Sections */}
          <Tab.Container activeKey={activeTab} onSelect={(k) => setActiveTab(k || "storage")}>
            <Card className="piad-card shadow-sm border-0 mb-4">
              <Card.Header className="bg-white border-bottom pt-3 pb-0">
                <Nav variant="tabs">
                  <Nav.Item>
                    <Nav.Link eventKey="storage" className="d-flex align-items-center gap-1">
                      <i className="bi bi-hdd-stack" />
                      <span>Armazenamento & Tabelas</span>
                    </Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="connections" className="d-flex align-items-center gap-1">
                      <i className="bi bi-activity" />
                      <span>Conexões & Atividade</span>
                    </Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="locks" className="d-flex align-items-center gap-1">
                      <i className="bi bi-shield-lock" />
                      <span>Locks & Concorrência</span>
                    </Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="timescale" className="d-flex align-items-center gap-1">
                      <i className="bi bi-layers-half" />
                      <span>TimescaleDB</span>
                    </Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="freshness" className="d-flex align-items-center gap-1">
                      <i className="bi bi-arrow-repeat" />
                      <span>Frescor dos Dados</span>
                    </Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="checks" className="d-flex align-items-center gap-1">
                      <i className="bi bi-check2-circle" />
                      <span>Diagnósticos ({data.checks.length})</span>
                    </Nav.Link>
                  </Nav.Item>
                </Nav>
              </Card.Header>

              <Card.Body className="p-4">
                <Tab.Content>
                  {/* Tab 1: Storage */}
                  <Tab.Pane eventKey="storage">
                    <div className="mb-4">
                      {/* Top Storage Cards */}
                      <Row className="g-3 mb-3">
                        <Col sm={3}>
                          <div className="p-3 bg-light rounded h-100">
                            <div className="d-flex align-items-center justify-content-between mb-1">
                              <span className="text-muted small">Tamanho do Banco</span>
                              <OverlayTrigger
                                placement="top"
                                overlay={<Tooltip id="tooltip-db-size">Tamanho do banco: Espaço atualmente alocado pelas relações deste banco.</Tooltip>}
                              >
                                <i className="bi bi-info-circle text-secondary" style={{ cursor: "pointer" }} />
                              </OverlayTrigger>
                            </div>
                            <div className="h5 fw-bold mb-0 text-primary">{data.storage.database_human}</div>
                          </div>
                        </Col>
                        <Col sm={3}>
                          <div className="p-3 bg-light rounded h-100">
                            <div className="text-muted small mb-1">Tabelas (Heap Puro)</div>
                            <div className="h5 fw-bold mb-0">{data.storage.tables_heap_human ?? data.storage.tables_human}</div>
                            <div className="small text-muted" style={{ fontSize: "0.75rem" }}>Sem sobreposição com TOAST</div>
                          </div>
                        </Col>
                        <Col sm={3}>
                          <div className="p-3 bg-light rounded h-100">
                            <div className="text-muted small mb-1">TOAST (Armazenamento Estendido)</div>
                            <div className="h5 fw-bold mb-0">{data.storage.toast_human}</div>
                            <div className="small text-muted" style={{ fontSize: "0.75rem" }}>Inclui blocos comprimidos columnstore</div>
                          </div>
                        </Col>
                        <Col sm={3}>
                          <div className="p-3 bg-light rounded h-100">
                            <div className="text-muted small mb-1">Índices Totais</div>
                            <div className="h5 fw-bold mb-0">{data.storage.indexes_human}</div>
                            <div className="small text-muted" style={{ fontSize: "0.75rem" }}>B-Tree do banco</div>
                          </div>
                        </Col>
                      </Row>

                      {/* Decomposição da Hypertable pi_samples_timescale */}
                      <Card className="border mb-3">
                        <Card.Header className="bg-light d-flex justify-content-between align-items-center py-2">
                          <span className="fw-bold small">Decomposição Física da Hypertable (pi_samples_timescale)</span>
                          {data.storage.pi_samples_human && (
                            <Badge bg="primary" className="px-2 py-1">
                              Total: {data.storage.pi_samples_human}
                            </Badge>
                          )}
                        </Card.Header>
                        <Card.Body className="p-3">
                          <Row className="g-3">
                            <Col sm={6} lg={3}>
                              <div className="p-2 border rounded">
                                <div className="text-muted small">Chunks Recentes (Rowstore)</div>
                                <div className="h6 fw-bold mb-0">{data.storage.recent_rowstore_human ?? "-"}</div>
                                <div className="text-secondary" style={{ fontSize: "0.75rem" }}>Últimos 7 dias (ingestão ativa)</div>
                              </div>
                            </Col>
                            <Col sm={6} lg={3}>
                              <div className="p-2 border rounded">
                                <div className="d-flex align-items-center justify-content-between">
                                  <span className="text-muted small">Delta Rowstore Histórico</span>
                                  <OverlayTrigger
                                    placement="top"
                                    overlay={<Tooltip id="tooltip-delta">Delta rowstore histórico: Dados inseridos por backfill em chunks que já estavam no columnstore e ainda aguardam reconversão.</Tooltip>}
                                  >
                                    <i className="bi bi-info-circle text-secondary" style={{ cursor: "pointer" }} />
                                  </OverlayTrigger>
                                </div>
                                <div className="h6 fw-bold mb-0 text-warning">{data.storage.historical_delta_rowstore_human ?? "-"}</div>
                                <div className="text-secondary" style={{ fontSize: "0.75rem" }}>Backfills em chunks históricos</div>
                              </div>
                            </Col>
                            <Col sm={6} lg={3}>
                              <div className="p-2 border rounded">
                                <div className="d-flex align-items-center justify-content-between">
                                  <span className="text-muted small">Columnstore Atual</span>
                                  <OverlayTrigger
                                    placement="top"
                                    overlay={<Tooltip id="tooltip-col">Columnstore atual: Espaço físico atual das estruturas colunares comprimidas.</Tooltip>}
                                  >
                                    <i className="bi bi-info-circle text-secondary" style={{ cursor: "pointer" }} />
                                  </OverlayTrigger>
                                </div>
                                <div className="h6 fw-bold mb-0 text-success">{data.storage.columnstore_human ?? "-"}</div>
                                <div className="text-secondary" style={{ fontSize: "0.75rem" }}>Estruturas colunares compactadas</div>
                              </div>
                            </Col>
                            <Col sm={6} lg={3}>
                              <div className="p-2 border rounded">
                                <div className="text-muted small">Índices Rowstore da Hypertable</div>
                                <div className="h6 fw-bold mb-0">{data.storage.rowstore_indexes_human ?? "-"}</div>
                                <div className="text-secondary" style={{ fontSize: "0.75rem" }}>Árvores B-Tree nos chunks</div>
                              </div>
                            </Col>
                          </Row>

                          {data.storage.continuous_aggregates_human && (
                            <div className="mt-3 pt-2 border-top d-flex justify-content-between align-items-center small text-muted">
                              <span>Continuous Aggregates (Gráficos e Agregações Contínuas):</span>
                              <strong className="text-dark">{data.storage.continuous_aggregates_human}</strong>
                            </div>
                          )}
                        </Card.Body>
                      </Card>

                      {/* Conversão Inicial Snapshot */}
                      {data.storage.compression_before_human && (
                        <Card className="border mb-3 bg-light">
                          <Card.Body className="py-2 px-3">
                            <div className="d-flex flex-wrap align-items-center justify-content-between gap-2">
                              <div className="d-flex align-items-center gap-2">
                                <i className="bi bi-clock-history text-secondary" />
                                <span className="small fw-semibold">Conversão Inicial (Snapshot Histórico):</span>
                                <OverlayTrigger
                                  placement="top"
                                  overlay={<Tooltip id="tooltip-comp-stats">Antes/depois da conversão: Estatística histórica registrada no momento em que os chunks foram convertidos. Não representa o tamanho total atual da hypertable.</Tooltip>}
                                >
                                  <i className="bi bi-info-circle text-secondary" style={{ cursor: "pointer" }} />
                                </OverlayTrigger>
                              </div>
                              <div className="small">
                                <span>Antes: <strong>{data.storage.compression_before_human}</strong></span>
                                <span className="mx-2 text-muted">➔</span>
                                <span>Depois: <strong className="text-success">{data.storage.compression_after_human}</strong></span>
                                {data.storage.compression_ratio_pct !== null && data.storage.compression_ratio_pct !== undefined && (
                                  <Badge bg="success" className="ms-2">
                                    -{data.storage.compression_ratio_pct}%
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </Card.Body>
                        </Card>
                      )}

                      {/* App Tables Breakdown */}
                      <Row className="g-3 mb-3">
                        {data.storage.pi_samples_human && (
                          <Col sm={4}>
                            <div className="p-3 border rounded">
                              <div className="text-muted small">Amostras (pi_samples_timescale)</div>
                              <div className="h6 fw-bold mb-0">{data.storage.pi_samples_human}</div>
                            </div>
                          </Col>
                        )}
                        {data.storage.pi_backfill_human && (
                          <Col sm={4}>
                            <div className="p-3 border rounded">
                              <div className="text-muted small">Recargas (pi_backfill_jobs)</div>
                              <div className="h6 fw-bold mb-0">{data.storage.pi_backfill_human}</div>
                            </div>
                          </Col>
                        )}
                        {data.storage.pi_ingestion_human && (
                          <Col sm={4}>
                            <div className="p-3 border rounded">
                              <div className="text-muted small">Ingestão (pi_ingestion_state)</div>
                              <div className="h6 fw-bold mb-0">{data.storage.pi_ingestion_human}</div>
                            </div>
                          </Col>
                        )}
                      </Row>

                      {data.storage.filesystem_available === false && (
                        <Alert variant="secondary" className="small d-flex align-items-center gap-2 mb-4">
                          <i className="bi bi-info-circle-fill text-primary fs-5 flex-shrink-0" />
                          <div>
                            <strong>Observação sobre Espaço Livre em Disco:</strong>{" "}
                            {data.storage.filesystem_reason ??
                              "Métrica do sistema operacional não disponível para o usuário da aplicação. A aplicação monitora o espaço lógico ocupado no catálogo do PostgreSQL."}
                          </div>
                        </Alert>
                      )}

                      <h6 className="fw-bold mb-3">Top Maiores Relações</h6>
                      {data.storage.largest_relations.length > 0 ? (
                        <Table responsive hover className="align-middle mb-0 border">
                          <thead className="table-light">
                            <tr>
                              <th>#</th>
                              <th>Relação</th>
                              <th>Tipo</th>
                              <th>Tamanho Total</th>
                              <th>Dados</th>
                              <th>Índices</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.storage.largest_relations.map((rel: StorageRelationInfo, idx: number) => (
                              <tr key={`${rel.schema_name}.${rel.relation_name}`}>
                                <td className="text-muted small">{idx + 1}</td>
                                <td>
                                  <code>{rel.schema_name !== "public" ? `${rel.schema_name}.` : ""}{rel.relation_name}</code>
                                </td>
                                <td>
                                  <Badge bg={rel.relation_type === "table" ? "primary" : rel.relation_type === "index" ? "secondary" : "info"}>
                                    {rel.relation_type}
                                  </Badge>
                                </td>
                                <td className="fw-semibold">{rel.total_human}</td>
                                <td className="text-muted small">{rel.data_human}</td>
                                <td className="text-muted small">{rel.index_human}</td>
                              </tr>
                            ))}
                          </tbody>
                        </Table>
                      ) : (
                        <div className="text-muted small">Nenhuma relação detalhada disponível.</div>
                      )}
                    </div>
                  </Tab.Pane>

                  {/* Tab 2: Connections & Activity */}
                  <Tab.Pane eventKey="connections">
                    <Row className="g-3 mb-4">
                      <Col sm={6} md={3}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Ativas (Executando)</div>
                          <div className="h4 fw-bold text-success mb-0">{data.connections.active}</div>
                        </div>
                      </Col>
                      <Col sm={6} md={3}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Ociosas (Idle)</div>
                          <div className="h4 fw-bold text-secondary mb-0">{data.connections.idle}</div>
                        </div>
                      </Col>
                      <Col sm={6} md={3}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Em Transação (Idle in tx)</div>
                          <div className={`h4 fw-bold mb-0 ${data.connections.idle_in_transaction > 0 ? "text-warning" : "text-dark"}`}>
                            {data.connections.idle_in_transaction}
                          </div>
                        </div>
                      </Col>
                      <Col sm={6} md={3}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Aguardando Lock</div>
                          <div className={`h4 fw-bold mb-0 ${data.connections.waiting > 0 ? "text-danger" : "text-dark"}`}>
                            {data.connections.waiting}
                          </div>
                        </div>
                      </Col>
                    </Row>

                    <Row className="g-4">
                      <Col md={6}>
                        <Card className="border">
                          <Card.Header className="bg-light fw-bold small">Detalhes de Conexão</Card.Header>
                          <Table size="sm" className="mb-0">
                            <tbody>
                              <tr>
                                <td className="text-muted">Total de Conexões Atuais</td>
                                <td className="fw-semibold text-end">{data.connections.current}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Limite Máximo Permitido (max_connections)</td>
                                <td className="fw-semibold text-end">{data.connections.maximum > 0 ? data.connections.maximum : "Ilimitado"}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Percentual de Utilização</td>
                                <td className="fw-semibold text-end">
                                  {data.connections.usage_percent !== null
                                    ? `${data.connections.usage_percent.toFixed(1)}%`
                                    : "N/A"}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Conexões de Workers com Leader Lock</td>
                                <td className="fw-semibold text-end">{data.connections.worker_leader_connections}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Transações Longas Ativas</td>
                                <td className="fw-semibold text-end">{data.connections.long_transactions_count}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Duração da Transação Mais Antiga</td>
                                <td className="fw-semibold text-end">
                                  {data.connections.oldest_transaction_seconds !== null
                                    ? formatDuration(data.connections.oldest_transaction_seconds)
                                    : "Nenhuma"}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Queries Longas Ativas</td>
                                <td className="fw-semibold text-end">{data.connections.long_queries_count}</td>
                              </tr>
                            </tbody>
                          </Table>
                        </Card>
                      </Col>

                      <Col md={6}>
                        <Card className="border">
                          <Card.Header className="bg-light fw-bold small">Atividade de Banco (pg_stat_database)</Card.Header>
                          <Table size="sm" className="mb-0">
                            <tbody>
                              <tr>
                                <td className="text-muted">Commits Acumulados</td>
                                <td className="fw-semibold text-end">{data.connections.commits?.toLocaleString() ?? "N/A"}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Rollbacks Acumulados</td>
                                <td className="fw-semibold text-end">{data.connections.rollbacks?.toLocaleString() ?? "N/A"}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Deadlocks Detectados</td>
                                <td className={`fw-semibold text-end ${(data.connections.deadlocks ?? 0) > 0 ? "text-danger" : ""}`}>
                                  {data.connections.deadlocks?.toLocaleString() ?? "N/A"}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Arquivos Temporários Criados</td>
                                <td className="fw-semibold text-end">
                                  {data.connections.temp_files?.toLocaleString() ?? "0"}
                                  {data.connections.temp_human ? ` (${data.connections.temp_human})` : ""}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Último Reset das Estatísticas</td>
                                <td className="fw-semibold text-end">{formatDate(data.connections.stats_reset)}</td>
                              </tr>
                            </tbody>
                          </Table>
                        </Card>
                      </Col>
                    </Row>
                  </Tab.Pane>

                  {/* Tab 3: Locks */}
                  <Tab.Pane eventKey="locks">
                    <Row className="g-3 mb-4">
                      <Col sm={4}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Total de Locks</div>
                          <div className="h4 fw-bold text-dark mb-0">{data.locks.total}</div>
                        </div>
                      </Col>
                      <Col sm={4}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Locks Concedidos</div>
                          <div className="h4 fw-bold text-success mb-0">{data.locks.granted}</div>
                        </div>
                      </Col>
                      <Col sm={4}>
                        <div className="p-3 bg-light rounded text-center">
                          <div className="text-muted small">Locks Aguardando</div>
                          <div className={`h4 fw-bold mb-0 ${data.locks.waiting > 0 ? "text-danger" : "text-success"}`}>
                            {data.locks.waiting}
                          </div>
                        </div>
                      </Col>
                    </Row>

                    <Card className="border mb-3">
                      <Card.Header className="bg-light fw-bold small">Concorrência e Bloqueios</Card.Header>
                      <Table size="sm" className="mb-0">
                        <tbody>
                          <tr>
                            <td className="text-muted">Sessões Bloqueadas (blocked_sessions)</td>
                            <td className={`fw-semibold text-end ${data.locks.blocked_sessions > 0 ? "text-danger" : ""}`}>
                              {data.locks.blocked_sessions}
                            </td>
                          </tr>
                          <tr>
                            <td className="text-muted">Locks Consultivos de Sessão (Advisory Locks)</td>
                            <td className="fw-semibold text-end">{data.locks.advisory_locks}</td>
                          </tr>
                          <tr>
                            <td className="text-muted">Tempo da Espera Mais Antiga</td>
                            <td className="fw-semibold text-end">
                              {data.locks.oldest_wait_seconds !== null
                                ? formatDuration(data.locks.oldest_wait_seconds)
                                : "Nenhum lock aguardando"}
                            </td>
                          </tr>
                        </tbody>
                      </Table>
                    </Card>

                    <Alert variant="info" className="small mb-0">
                      <i className="bi bi-shield-check me-2" />
                      <strong>Nota sobre Locks Consultivos:</strong> Os workers em segundo plano (Ingestão Online e
                      Recarga Histórica) utilizam locks consultivos de sessão (<code>pg_try_advisory_lock</code>) para
                      eleição de líder. Esses locks são esperados, não bloqueiam leitura/escrita de tabelas e não
                      são tratados como falso positivo.
                    </Alert>
                  </Tab.Pane>

                  {/* Tab 4: TimescaleDB */}
                  <Tab.Pane eventKey="timescale">
                    {data.timescale.available ? (
                      <div>
                        <div className="d-flex align-items-center gap-2 mb-3">
                          <Badge bg="success" className="px-2 py-1">Ativo</Badge>
                          <span className="fw-bold">TimescaleDB {data.timescale.version ?? ""}</span>
                        </div>

                        <Row className="g-3 mb-4">
                          <Col sm={6} md={3}>
                            <div className="p-3 bg-light rounded text-center">
                              <div className="text-muted small">Hypertables</div>
                              <div className="h4 fw-bold text-primary mb-0">{data.timescale.hypertables}</div>
                            </div>
                          </Col>
                          <Col sm={6} md={3}>
                            <div className="p-3 bg-light rounded text-center">
                              <div className="text-muted small">Chunks Criados</div>
                              <div className="h4 fw-bold text-info mb-0">{data.timescale.chunks}</div>
                            </div>
                          </Col>
                          <Col sm={6} md={3}>
                            <div className="p-3 bg-light rounded text-center">
                              <div className="text-muted small">Continuous Aggregates</div>
                              <div className="h4 fw-bold text-success mb-0">{data.timescale.continuous_aggregates}</div>
                            </div>
                          </Col>
                          <Col sm={6} md={3}>
                            <div className="p-3 bg-light rounded text-center">
                              <div className="text-muted small">Jobs Agendados</div>
                              <div className="h4 fw-bold text-dark mb-0">
                                {data.timescale.total_jobs}{" "}
                                {data.timescale.operational_failed_jobs && data.timescale.operational_failed_jobs > 0 ? (
                                  <span className="fs-6 text-danger">({data.timescale.operational_failed_jobs} falhas)</span>
                                ) : data.timescale.telemetry_failed ? (
                                  <span className="fs-6 text-info">(telemetria externa offline)</span>
                                ) : null}
                              </div>
                            </div>
                          </Col>
                        </Row>

                        {data.timescale.telemetry_failed && (
                          <Alert variant="info" className="small d-flex align-items-center gap-2 mb-3">
                            <i className="bi bi-info-circle-fill flex-shrink-0 fs-5" />
                            <div>
                              <strong>Informativo: telemetria externa indisponível.</strong> O job interno nativo do TimescaleDB que reporta métricas anônimas para servidores externos não possui rota de internet no ambiente. Isso não afeta nenhuma operação de banco, integridade de dados ou jobs de ingestão/compressão.
                            </div>
                          </Alert>
                        )}

                        {/* Columnstore Maintenance Status Card */}
                        {data.timescale.columnstore_maintenance && (
                          <Card className="border mb-3">
                            <Card.Header className="bg-light fw-bold small d-flex justify-content-between align-items-center py-2">
                              <span>Manutenção de Columnstore (Recompressão de Deltas)</span>
                              <Badge bg={data.timescale.columnstore_maintenance.enabled ? "success" : "secondary"}>
                                {data.timescale.columnstore_maintenance.enabled ? "Habilitada" : "Aguardando / Desativada"}
                              </Badge>
                            </Card.Header>
                            <Card.Body className="p-3">
                              <Row className="g-3 mb-2">
                                <Col sm={4}>
                                  <div className="small text-muted">Candidatos com Delta</div>
                                  <div className="fw-bold">{data.timescale.columnstore_maintenance.candidate_chunks_count ?? 0} chunks</div>
                                </Col>
                                <Col sm={4}>
                                  <div className="small text-muted">Chunks Processados</div>
                                  <div className="fw-bold">{data.timescale.columnstore_maintenance.chunks_processed_total ?? 0}</div>
                                </Col>
                                <Col sm={4}>
                                  <div className="small text-muted">Espaço Recuperado</div>
                                  <div className="fw-bold text-success">
                                    {formatBytes(data.timescale.columnstore_maintenance.bytes_recovered_total ?? 0)}
                                  </div>
                                </Col>
                              </Row>
                              <div className="small text-muted mt-2 pt-2 border-top">
                                <strong>Status:</strong> {data.timescale.columnstore_maintenance.waiting_reason ?? "Ocioso"}
                                {data.timescale.columnstore_maintenance.current_chunk && (
                                  <span className="ms-2 badge bg-primary">
                                    Processando: {data.timescale.columnstore_maintenance.current_chunk}
                                  </span>
                                )}
                              </div>
                            </Card.Body>
                          </Card>
                        )}

                        <Card className="border">
                          <Card.Header className="bg-light fw-bold small">Políticas e Background Jobs</Card.Header>
                          <Table size="sm" className="mb-0">
                            <tbody>
                              <tr>
                                <td className="text-muted">Status do Último Job</td>
                                <td className="fw-semibold text-end">
                                  {data.timescale.last_run_status ? (
                                    <Badge bg={data.timescale.last_run_status === "Success" ? "success" : "warning"}>
                                      {data.timescale.last_run_status}
                                    </Badge>
                                  ) : (
                                    "-"
                                  )}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Último Término com Sucesso</td>
                                <td className="fw-semibold text-end">{formatDate(data.timescale.last_successful_finish)}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Compressão Nativa</td>
                                <td className="fw-semibold text-end">
                                  {data.timescale.compression_enabled ? (
                                    <Badge bg="success">Habilitada</Badge>
                                  ) : (
                                    <Badge bg="secondary">Não configurada</Badge>
                                  )}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Política de Retenção Automática</td>
                                <td className="fw-semibold text-end">
                                  {data.timescale.retention_configured ? (
                                    <Badge bg="info">Configurada</Badge>
                                  ) : (
                                    <span className="text-muted">Padrão</span>
                                  )}
                                </td>
                              </tr>
                            </tbody>
                          </Table>
                        </Card>
                      </div>
                    ) : (
                      <Alert variant="warning">
                        <Alert.Heading>TimescaleDB não detectado</Alert.Heading>
                        <p className="mb-0">
                          A extensão TimescaleDB não está ativa ou instalada nesta base de dados. O sistema está
                          operando em modo PostgreSQL padrão ou SQLite.
                        </p>
                      </Alert>
                    )}
                  </Tab.Pane>

                  {/* Tab 5: Freshness & Workers */}
                  <Tab.Pane eventKey="freshness">
                    <Row className="g-4 mb-4">
                      <Col md={6}>
                        <Card className="border h-100">
                          <Card.Header className="bg-light fw-bold small">Ingestão Contínua</Card.Header>
                          <Table size="sm" className="mb-0">
                            <tbody>
                              <tr>
                                <td className="text-muted">Última Amostra Inserida</td>
                                <td className="fw-semibold text-end">{formatDate(data.freshness.latest_sample_at)}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Última Amostra Gravada no PI</td>
                                <td className="fw-semibold text-end">{formatDate(data.freshness.latest_recorded_sample_at)}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Atraso Estimado (Lag)</td>
                                <td className="fw-semibold text-end">
                                  {data.freshness.lag_seconds !== null
                                    ? formatDuration(data.freshness.lag_seconds)
                                    : "N/A"}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Menor Watermark Registrado</td>
                                <td className="fw-semibold text-end">{formatDate(data.freshness.oldest_watermark)}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Maior Watermark Registrado</td>
                                <td className="fw-semibold text-end">{formatDate(data.freshness.newest_watermark)}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Estados de Ingestão Monitorados</td>
                                <td className="fw-semibold text-end">{data.freshness.ingestion_states}</td>
                              </tr>
                              <tr>
                                <td className="text-muted">Tags em Modo Backoff</td>
                                <td className={`fw-semibold text-end ${data.freshness.tags_in_backoff > 0 ? "text-warning" : ""}`}>
                                  {data.freshness.tags_in_backoff}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Tags com Falhas Consecutivas</td>
                                <td className={`fw-semibold text-end ${data.freshness.tags_with_failures > 0 ? "text-danger" : ""}`}>
                                  {data.freshness.tags_with_failures}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Último Sucesso Geral de Ingestão</td>
                                <td className="fw-semibold text-end">{formatDate(data.freshness.last_success_at)}</td>
                              </tr>
                            </tbody>
                          </Table>
                        </Card>
                      </Col>

                      <Col md={6}>
                        <Card className="border h-100">
                          <Card.Header className="bg-light fw-bold small">Recargas Históricas (Backfill)</Card.Header>
                          <Table size="sm" className="mb-0">
                            <tbody>
                              <tr>
                                <td className="text-muted">Jobs em Execução (RUNNING)</td>
                                <td className="fw-semibold text-end text-primary">
                                  {data.freshness.backfill_jobs_by_status.RUNNING ?? 0}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Jobs Pendentes (PENDING)</td>
                                <td className="fw-semibold text-end">
                                  {data.freshness.backfill_jobs_by_status.PENDING ?? 0}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Jobs Concluídos (COMPLETED)</td>
                                <td className="fw-semibold text-end text-success">
                                  {data.freshness.backfill_jobs_by_status.COMPLETED ?? 0}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Jobs com Falha (FAILED)</td>
                                <td className={`fw-semibold text-end ${(data.freshness.backfill_jobs_by_status.FAILED ?? 0) > 0 ? "text-danger" : ""}`}>
                                  {data.freshness.backfill_jobs_by_status.FAILED ?? 0}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Jobs Cancelados (CANCELLED)</td>
                                <td className="fw-semibold text-end text-secondary">
                                  {data.freshness.backfill_jobs_by_status.CANCELLED ?? 0}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Leases Expirados</td>
                                <td className={`fw-semibold text-end ${data.freshness.expired_backfill_leases > 0 ? "text-warning" : ""}`}>
                                  {data.freshness.expired_backfill_leases}
                                </td>
                              </tr>
                              <tr>
                                <td className="text-muted">Falhas Consecutivas</td>
                                <td className={`fw-semibold text-end ${data.freshness.consecutive_backfill_failures > 0 ? "text-danger" : ""}`}>
                                  {data.freshness.consecutive_backfill_failures}
                                </td>
                              </tr>
                            </tbody>
                          </Table>
                        </Card>
                      </Col>
                    </Row>
                  </Tab.Pane>

                  {/* Tab 6: Diagnósticos (Checks) */}
                  <Tab.Pane eventKey="checks">
                    <Table responsive hover className="align-middle border mb-4">
                      <thead className="table-light">
                        <tr>
                          <th style={{ width: "220px" }}>Verificação</th>
                          <th style={{ width: "130px" }}>Status</th>
                          <th>Diagnóstico / Mensagem</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.checks.map((check: HealthCheckItem) => (
                          <tr key={check.name}>
                            <td className="fw-semibold">{check.name}</td>
                            <td>
                              <Badge bg={getStatusBadgeVariant(check.status)}>
                                {getStatusLabel(check.status)}
                              </Badge>
                            </td>
                            <td className="small text-muted">{check.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>

                    {data.unavailable_metrics.length > 0 && (
                      <Alert variant="warning" className="small">
                        <div className="fw-bold mb-1">Métricas Indisponíveis nesta Execução:</div>
                        <ul className="mb-0 ps-3">
                          {data.unavailable_metrics.map((item: string) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </Alert>
                    )}
                  </Tab.Pane>
                </Tab.Content>
              </Card.Body>
            </Card>
          </Tab.Container>
        </>
      )}
    </div>
  );
}
