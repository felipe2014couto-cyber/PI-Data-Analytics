import { Card, Col, Row } from "react-bootstrap";
import type { ChartBuildResult } from "../utils/chartData";
import type { FilterApplicationSummary, QueryExecutionMetadata, TimeSeriesSeries } from "../types";

interface QuerySummaryProps {
  chart: ChartBuildResult | null;
  startLocal: string;
  endLocal: string;
  durationMs: number | null;
  seriesCount: number;
  partial: boolean;
  mode: "recorded" | "interpolated";
  filterSummary?: FilterApplicationSummary | null;
  queryExecution?: QueryExecutionMetadata | null;
  seriesMeta?: TimeSeriesSeries[];
}

function Metric({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <Card className="piad-card h-100" data-testid={testId}>
      <Card.Body>
        <div className="text-muted small">{label}</div>
        <div className="fs-5 fw-semibold">{value}</div>
      </Card.Body>
    </Card>
  );
}

export function QuerySummary({
  chart,
  startLocal,
  endLocal,
  durationMs,
  seriesCount,
  partial,
  mode,
  filterSummary,
  queryExecution,
  seriesMeta,
}: QuerySummaryProps) {
  const totalSeries = chart?.totalSeries ?? seriesCount;
  const totalPoints = filterSummary?.receivedPoints ?? chart?.totalPoints ?? 0;
  const numericPoints = chart?.totalNumericPoints ?? 0;
  const droppedPoints = (chart?.totalDroppedPoints ?? 0) + (filterSummary?.removedPoints ?? 0);
  const nonNumericPoints = chart?.totalNonNumericPoints ?? 0;
  const duration = durationMs === null ? "-" : durationMs + " ms";

  const anySampled = seriesMeta?.some((s) => s.sampled) ?? false;
  const anyTruncated = seriesMeta?.some((s) => s.truncated) ?? false;
  const effectiveInterval = queryExecution?.effective_interval;
  const chunkCount = queryExecution?.chunk_count;
  const piRequestCount = queryExecution?.pi_request_count;
  const visualTotal = queryExecution?.visual_total_points;

  const cacheHit = queryExecution?.cache_hit;
  const streamsetUsed = queryExecution?.streamset_used;
  const batchCount = queryExecution?.batch_count;
  const resolveMs = queryExecution?.resolve_ms;
  const fetchMs = queryExecution?.fetch_ms;
  const totalMs = queryExecution?.total_ms;
  const webidCacheHits = queryExecution?.webid_cache_hits;
  const webidCacheMisses = queryExecution?.webid_cache_misses;
  const individualFallback = queryExecution?.individual_fallback_requests;
  const strategy = queryExecution?.strategy;
  const subrequests = queryExecution?.batch_subrequest_count;
  const windowSplits = queryExecution?.window_split_count;
  const pointsReceived = queryExecution?.pi_points_received;
  const pointsReturned = queryExecution?.points_returned;
  const exactRecorded = mode === "recorded";
  const strategyLabel = strategy === "streamset-recorded-batch"
    ? "StreamSet Recorded + Batch"
    : strategy === "batch-recorded-fallback"
    ? "Batch Recorded (fallback)"
    : strategy ?? (streamsetUsed ? "StreamSet" : "Streams Recorded");

  const sourceLabel = cacheHit ? "Cache" : streamsetUsed ? "StreamSet" : "PI Web API";

  return (
    <div data-testid="query-summary">
      <Row className="g-2">
        <Col xs={6} md={4} lg={2}>
          <Metric label="Series" value={String(totalSeries)} testId="metric-series" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Pontos recebidos" value={String(totalPoints)} testId="metric-points" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Numericos" value={String(numericPoints)} testId="metric-numeric" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Descartados" value={String(droppedPoints)} testId="metric-dropped" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Nao numericos" value={String(nonNumericPoints)} testId="metric-nonnumeric" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Periodo" value={startLocal + " -> " + endLocal} testId="metric-period" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Duracao" value={duration} testId="metric-duration" />
        </Col>
        <Col xs={6} md={4} lg={2}>
          <Metric label="Modo" value={mode} testId="metric-mode" />
        </Col>
        {exactRecorded ? (
          <Col xs={12} md={8} lg={4}>
            <Metric label="Estratégia" value={strategyLabel} testId="metric-strategy" />
          </Col>
        ) : null}
        <Col xs={6} md={4} lg={2}>
          <Metric
            label="Status"
            value={partial ? "Parcial" : "Completo"}
            testId="metric-status"
          />
        </Col>
        {effectiveInterval ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Intervalo efetivo" value={effectiveInterval} testId="metric-effective-interval" />
          </Col>
        ) : null}
        {chunkCount != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Blocos" value={String(chunkCount)} testId="metric-chunks" />
          </Col>
        ) : null}
        {piRequestCount != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Req. PI" value={String(piRequestCount)} testId="metric-pi-requests" />
          </Col>
        ) : null}
        {visualTotal != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Pontos visuais" value={String(visualTotal)} testId="metric-visual-points" />
          </Col>
        ) : null}
        <Col xs={6} md={4} lg={2}>
          <Metric label="Fonte" value={sourceLabel} testId="metric-source" />
        </Col>
        {streamsetUsed ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="StreamSet" value={queryExecution?.streamset_mode ?? mode} testId="metric-streamset-mode" />
          </Col>
        ) : null}
        {batchCount != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Batches" value={String(batchCount)} testId="metric-batch-count" />
          </Col>
        ) : null}
        {subrequests != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Subconsultas" value={String(subrequests)} testId="metric-batch-subrequests" />
          </Col>
        ) : null}
        {windowSplits != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Janelas divididas" value={String(windowSplits)} testId="metric-window-splits" />
          </Col>
        ) : null}
        {pointsReceived != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Eventos recebidos" value={String(pointsReceived)} testId="metric-events-received" />
          </Col>
        ) : null}
        {pointsReturned != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Eventos retornados" value={String(pointsReturned)} testId="metric-events-returned" />
          </Col>
        ) : null}
        {webidCacheHits != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Cache WebId" value={String(webidCacheHits) + "H/" + String(webidCacheMisses ?? 0) + "M"} testId="metric-webid-cache" />
          </Col>
        ) : null}
        {individualFallback != null && individualFallback > 0 ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Fallback ind." value={String(individualFallback)} testId="metric-fallback" />
          </Col>
        ) : null}
        {resolveMs != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Resolucao" value={String(resolveMs) + "ms"} testId="metric-resolve-ms" />
          </Col>
        ) : null}
        {fetchMs != null ? (
          <Col xs={6} md={4} lg={2}>
            <Metric label="Busca PI" value={String(fetchMs) + "ms"} testId="metric-fetch-ms" />
          </Col>
        ) : null}
        {totalMs != null ? (
          <Col xs={6} md={3} lg={2}>
            <Metric label="Total" value={String(totalMs) + "ms"} testId="metric-total-ms" />
          </Col>
        ) : null}
      </Row>
      {exactRecorded ? (
        <div className="mt-2 p-2 border rounded bg-success bg-opacity-10 small" data-testid="recorded-exact-info">
          Valores registrados — exatos. Os eventos não foram interpolados nem reduzidos.
        </div>
      ) : anySampled ? (
        <div className="mt-2 p-2 border rounded bg-warning bg-opacity-10 small" data-testid="sampling-warning">
          Esta visualizacao utiliza uma amostra de {totalPoints} pontos dentre os pontos recuperados.
          Filtros e metricas exibidos na tela sao calculados sobre os pontos retornados
          para visualizacao.
        </div>
      ) : (
        <div className="mt-2 p-2 border rounded bg-success bg-opacity-10 small" data-testid="no-sampling-info">
          Todos os pontos recuperados foram utilizados.
        </div>
      )}
      {anyTruncated || queryExecution?.truncated ? (
        <div className="mt-1 p-2 border rounded bg-danger bg-opacity-10 small" data-testid="truncated-warning">
          A consulta atingiu o limite de segurança e pode não conter todos os eventos.
        </div>
      ) : null}
      {exactRecorded && ((pointsReceived ?? 0) >= 10000 || (windowSplits ?? 0) > 0) ? (
        <div className="mt-1 p-2 border rounded bg-warning bg-opacity-10 small" data-testid="recorded-volume-warning">
          A consulta contém muitos eventos registrados e pode demorar. Os valores não serão interpolados nem reduzidos.
        </div>
      ) : null}
    </div>
  );
}
