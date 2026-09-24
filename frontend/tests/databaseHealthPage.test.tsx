import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { apiMock, mockApiModule } from "./mocks/api";

vi.mock("../src/api", () => mockApiModule());
import { DatabaseHealthPage } from "../src/pages/DatabaseHealthPage";
import type { DatabaseHealthResponse } from "../src/types";

const mockHealthResponse: DatabaseHealthResponse = {
  status: "healthy",
  checked_at: "2026-09-22T12:00:00Z",
  duration_ms: 12.5,
  cached: false,
  database: {
    reachable: true,
    latency_ms: 2.1,
    name: "pi_analytics",
    postgresql_version: "PostgreSQL 18.4",
    timescaledb_version: "2.27.1",
    uptime_seconds: 3600,
    alembic_revision: "rev12345678",
  },
  storage: {
    database_bytes: 7276951231,
    database_human: "6.94 GB",
    tables_bytes: 2826403840,
    tables_human: "2.63 GB",
    tables_heap_bytes: 2431098880,
    tables_heap_human: "2.26 GB",
    indexes_bytes: 4405395456,
    indexes_human: "4.10 GB",
    toast_bytes: 395304960,
    toast_human: "377.00 MB",
    pi_samples_bytes: 6816948224,
    pi_samples_human: "6.35 GB",
    recent_rowstore_bytes: 944472064,
    recent_rowstore_human: "900.70 MB",
    historical_delta_rowstore_bytes: 5197357056,
    historical_delta_rowstore_human: "4.84 GB",
    columnstore_bytes: 482426880,
    columnstore_human: "460.08 MB",
    rowstore_indexes_bytes: 4259110912,
    rowstore_indexes_human: "3.97 GB",
    continuous_aggregates_bytes: 379338752,
    continuous_aggregates_human: "361.77 MB",
    compression_before_bytes: 5616123904,
    compression_before_human: "5.23 GB",
    compression_after_bytes: 355131392,
    compression_after_human: "338.68 MB",
    compression_ratio_pct: 93.68,
    pi_backfill_bytes: 524288,
    pi_backfill_human: "512.00 KB",
    pi_ingestion_bytes: 65536,
    pi_ingestion_human: "64.00 KB",
    filesystem_available: false,
    filesystem_reason: "Métrica do sistema operacional não disponível para o usuário da aplicação",
    largest_relations: [
      {
        schema_name: "_timescaledb_internal",
        relation_name: "_hyper_1_339_chunk",
        relation_type: "table",
        data_bytes: 48800000,
        index_bytes: 90500000,
        total_bytes: 139300000,
        data_human: "48.80 MB",
        index_human: "90.50 MB",
        total_human: "139.30 MB",
      },
    ],
  },
  connections: {
    current: 12,
    maximum: 100,
    usage_percent: 12.0,
    active: 2,
    idle: 8,
    idle_in_transaction: 0,
    waiting: 0,
    worker_leader_connections: 2,
    long_transactions_count: 0,
    oldest_transaction_seconds: null,
    long_queries_count: 0,
    oldest_query_seconds: null,
    commits: 15000,
    rollbacks: 12,
    deadlocks: 0,
    temp_files: 0,
    temp_bytes: 0,
    temp_human: "0 B",
    stats_reset: null,
  },
  locks: {
    total: 24,
    granted: 24,
    waiting: 0,
    advisory_locks: 2,
    blocked_sessions: 0,
    oldest_wait_seconds: null,
  },
  timescale: {
    available: true,
    version: "2.27.1",
    hypertables: 6,
    chunks: 377,
    continuous_aggregates: 5,
    total_jobs: 8,
    failed_jobs: 1,
    operational_failed_jobs: 0,
    telemetry_failed: true,
    last_run_status: "Success",
    last_successful_finish: "2026-09-22T11:50:00Z",
    compression_enabled: true,
    retention_configured: true,
    columnstore_maintenance: {
      enabled: true,
      candidate_chunks_count: 55,
      chunks_processed_total: 1,
      bytes_recovered_total: 15000000,
      waiting_reason: "Ocioso",
      current_chunk: null,
    },
  },
  freshness: {
    latest_sample_at: "2026-09-22T11:59:50Z",
    latest_recorded_sample_at: "2026-09-22T11:59:50Z",
    lag_seconds: 10.0,
    oldest_watermark: "2026-09-22T11:58:00Z",
    newest_watermark: "2026-09-22T11:59:00Z",
    ingestion_states: 10,
    tags_in_backoff: 0,
    tags_with_failures: 0,
    backfill_jobs_by_status: { COMPLETED: 13, RUNNING: 0, PENDING: 0 },
    expired_backfill_leases: 0,
    consecutive_backfill_failures: 0,
    last_success_at: "2026-09-22T11:59:50Z",
  },
  checks: [
    {
      name: "conectividade",
      status: "healthy",
      message: "Banco acessível (pi_analytics).",
    },
    {
      name: "timescaledb",
      status: "healthy",
      message: "TimescaleDB v2.27.1 operacional (377 chunks).",
    },
    {
      name: "telemetria",
      status: "healthy",
      message: "Informativo: telemetria externa indisponível.",
    },
  ],
  unavailable_metrics: [],
};

describe("DatabaseHealthPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.databaseHealthGet.mockResolvedValue(mockHealthResponse);
  });

  it("renderiza métricas decompostas de armazenamento e hypertable sem sobreposição", async () => {
    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    // Verify main database size is displayed
    const dbSizeEls = await screen.findAllByText("6.94 GB");
    expect(dbSizeEls.length).toBeGreaterThanOrEqual(1);

    // Verify decomposed hypertable elements
    expect(screen.getByText(/Decomposição Física da Hypertable/i)).toBeInTheDocument();
    expect(screen.getByText("900.70 MB")).toBeInTheDocument(); // Chunks Recentes
    expect(screen.getByText("4.84 GB")).toBeInTheDocument(); // Delta Rowstore Histórico
    expect(screen.getByText("460.08 MB")).toBeInTheDocument(); // Columnstore Atual
    expect(screen.getByText("3.97 GB")).toBeInTheDocument(); // Índices Rowstore

    // Verify continuous aggregates
    expect(screen.getByText("361.77 MB")).toBeInTheDocument();

    // Verify historical conversion snapshot
    expect(screen.getByText(/Conversão Inicial \(Snapshot Histórico\)/i)).toBeInTheDocument();
    expect(screen.getByText("5.23 GB")).toBeInTheDocument();
    expect(screen.getByText("338.68 MB")).toBeInTheDocument();
    expect(screen.getByText("-93.68%")).toBeInTheDocument();
  });

  it("exibe o status de saúde consolidado como saudável quando apenas a telemetria externa falhou", async () => {
    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    const badge = await screen.findByTestId("consolidated-status-badge");
    expect(badge).toHaveTextContent("Saudável");
  });

  it("exibe alerta informativo para telemetria offline na aba TimescaleDB", async () => {
    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    // Switch to TimescaleDB tab
    const textEl = await screen.findByText("TimescaleDB");
    const linkEl = textEl.closest("a") ?? textEl;
    fireEvent.click(linkEl);

    await waitFor(() => {
      const msgs = screen.getAllByText(/Informativo: telemetria externa indisponível/i);
      expect(msgs.length).toBeGreaterThanOrEqual(1);
    });

    // Check columnstore maintenance card
    expect(screen.getByText(/Manutenção de Columnstore/i)).toBeInTheDocument();
    expect(screen.getByText("55 chunks")).toBeInTheDocument();
  });
});
