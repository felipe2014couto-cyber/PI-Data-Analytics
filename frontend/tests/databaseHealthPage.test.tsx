import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { DatabaseHealthPage } from "../src/pages/DatabaseHealthPage";
import { databaseHealthApi } from "../src/api";
import type { DatabaseHealthResponse } from "../src/types";

vi.mock("../src/api", () => ({
  databaseHealthApi: {
    getHealth: vi.fn(),
  },
}));

const mockHealthData: DatabaseHealthResponse = {
  status: "healthy",
  checked_at: "2026-09-22T12:00:00Z",
  duration_ms: 120,
  cached: false,
  database: {
    reachable: true,
    latency_ms: 12.34,
    name: "piad_staging",
    postgresql_version: "PostgreSQL 18.4 (Ubuntu 18.4-1.pgdg22.04+1)",
    timescaledb_version: "2.27.1",
    uptime_seconds: 86400,
    alembic_revision: "f82b79a10cd3",
  },
  storage: {
    database_bytes: 5916300000,
    database_human: "5.51 GB",
    tables_bytes: 3500000000,
    tables_human: "3.26 GB",
    indexes_bytes: 2400000000,
    indexes_human: "2.24 GB",
    toast_bytes: 16300000,
    toast_human: "15.54 MB",
    pi_samples_bytes: 5450000000,
    pi_samples_human: "5.08 GB",
    pi_backfill_bytes: 20000000,
    pi_backfill_human: "19.07 MB",
    pi_ingestion_bytes: 1000000,
    pi_ingestion_human: "976.56 KB",
    filesystem_available: false,
    filesystem_reason: "Métrica do sistema operacional não disponível para o usuário da aplicação",
    largest_relations: [
      {
        schema_name: "public",
        relation_name: "pi_samples_timescale",
        relation_type: "table",
        data_bytes: 3000000000,
        index_bytes: 2000000000,
        total_bytes: 5000000000,
        data_human: "2.79 GB",
        index_human: "1.86 GB",
        total_human: "4.66 GB",
      },
    ],
  },
  connections: {
    current: 25,
    maximum: 100,
    usage_percent: 25.0,
    active: 3,
    idle: 20,
    idle_in_transaction: 1,
    waiting: 0,
    worker_leader_connections: 2,
    long_transactions_count: 0,
    oldest_transaction_seconds: null,
    long_queries_count: 0,
    oldest_query_seconds: null,
    commits: 154200,
    rollbacks: 12,
    deadlocks: 0,
    temp_files: 5,
    temp_bytes: 1048576,
    temp_human: "1.00 MB",
    stats_reset: "2026-09-01T00:00:00Z",
  },
  locks: {
    total: 18,
    granted: 18,
    waiting: 0,
    advisory_locks: 2,
    blocked_sessions: 0,
    oldest_wait_seconds: null,
  },
  timescale: {
    available: true,
    version: "2.27.1",
    hypertables: 1,
    chunks: 429,
    continuous_aggregates: 5,
    total_jobs: 8,
    failed_jobs: 0,
    last_run_status: "Success",
    last_successful_finish: "2026-09-22T11:55:00Z",
    compression_enabled: true,
    retention_configured: false,
  },
  freshness: {
    latest_sample_at: "2026-09-22T11:59:30Z",
    latest_recorded_sample_at: "2026-09-22T11:59:00Z",
    lag_seconds: 45,
    oldest_watermark: "2026-09-22T11:58:00Z",
    newest_watermark: "2026-09-22T11:59:30Z",
    ingestion_states: 120,
    tags_in_backoff: 0,
    tags_with_failures: 0,
    backfill_jobs_by_status: {
      RUNNING: 1,
      PENDING: 2,
      COMPLETED: 50,
      FAILED: 0,
      CANCELLED: 1,
    },
    expired_backfill_leases: 0,
    consecutive_backfill_failures: 0,
    last_success_at: "2026-09-22T11:59:30Z",
  },
  checks: [
    {
      name: "Conexão do Banco",
      status: "healthy",
      message: "PostgreSQL 18.4 respondendo normalmente (12.34 ms).",
    },
    {
      name: "Utilização de Conexões",
      status: "healthy",
      message: "Utilização em 25.0% (25/100).",
    },
    {
      name: "Espaço em Disco",
      status: "healthy",
      message: "Armazenamento lógico: 5.51 GB.",
    },
  ],
  unavailable_metrics: [],
};

describe("DatabaseHealthPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders page header and 8 key summary cards with healthy status", async () => {
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValue(mockHealthData);

    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    // Initial loading indicator
    expect(screen.getByText(/Carregando métricas de saúde/i)).toBeInTheDocument();

    // Wait for content to appear
    await waitFor(() => {
      expect(screen.getByText("Saúde do Banco")).toBeInTheDocument();
    });

    // Consolidated status badge
    const badge = screen.getByTestId("consolidated-status-badge");
    expect(badge).toHaveTextContent("Saudável");

    // 8 Key Cards
    expect(screen.getByText("Estado do Banco")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();

    expect(screen.getByText("Latência")).toBeInTheDocument();
    expect(screen.getByText("12.34")).toBeInTheDocument();

    expect(screen.getByText("Espaço Ocupado")).toBeInTheDocument();
    expect(screen.getAllByText("5.51 GB").length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText("Conexões")).toBeInTheDocument();
    expect(screen.getByText(/25.0% utilizado/i)).toBeInTheDocument();

    expect(screen.getByText("Último Dado")).toBeInTheDocument();
    expect(screen.getByText("Atraso Ingestão")).toBeInTheDocument();
    expect(screen.getAllByText("45s").length).toBeGreaterThanOrEqual(1);

    expect(screen.getByText("Recargas")).toBeInTheDocument();
    expect(screen.getByText("1 executando")).toBeInTheDocument();

    expect(screen.getAllByText("Locks Aguardando").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("0 sessões bloqueadas")).toBeInTheDocument();
  });

  it("navigates through tabs: storage, connections, locks, timescale, freshness, diagnostics", async () => {
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValue(mockHealthData);

    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("5.51 GB").length).toBeGreaterThanOrEqual(1);
    });

    // Storage tab should show largest relations and filesystem notice
    expect(screen.getByText(/Observação sobre Espaço Livre em Disco/i)).toBeInTheDocument();
    expect(screen.getByText("pi_samples_timescale")).toBeInTheDocument();

    // Switch to Connections & Atividade tab
    fireEvent.click(screen.getByText("Conexões & Atividade"));
    expect(screen.getByText("Ativas (Executando)")).toBeInTheDocument();
    expect(screen.getByText("154.200")).toBeInTheDocument(); // Commits formatted

    // Switch to Locks tab
    fireEvent.click(screen.getByText("Locks & Concorrência"));
    expect(screen.getByText("Total de Locks")).toBeInTheDocument();
    expect(screen.getByText(/Nota sobre Locks Consultivos/i)).toBeInTheDocument();

    // Switch to TimescaleDB tab
    fireEvent.click(screen.getByText("TimescaleDB", { selector: ".nav-link span" }));
    expect(screen.getByText("TimescaleDB 2.27.1")).toBeInTheDocument();
    expect(screen.getByText("429")).toBeInTheDocument(); // Chunks

    // Switch to Frescor dos Dados tab
    fireEvent.click(screen.getByText("Frescor dos Dados"));
    expect(screen.getByText("Ingestão Contínua")).toBeInTheDocument();
    expect(screen.getByText("Recargas Históricas (Backfill)")).toBeInTheDocument();

    // Switch to Diagnósticos tab
    fireEvent.click(screen.getByText(/Diagnósticos/i, { selector: ".nav-link span" }));
    expect(screen.getByText("Conexão do Banco")).toBeInTheDocument();
    expect(screen.getByText("Utilização de Conexões")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL 18.4 respondendo normalmente (12.34 ms).")).toBeInTheDocument();
  });

  it("handles manual refresh button click with refresh=true", async () => {
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValue(mockHealthData);

    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Saúde do Banco")).toBeInTheDocument();
    });

    expect(databaseHealthApi.getHealth).toHaveBeenCalledWith(false);

    const refreshBtn = screen.getByRole("button", { name: /Atualizar agora/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      expect(databaseHealthApi.getHealth).toHaveBeenCalledWith(true);
    });
  });

  it("retains existing data and shows warning banner if subsequent refresh fails", async () => {
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValueOnce(mockHealthData);

    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("5.51 GB").length).toBeGreaterThanOrEqual(1);
    });

    // Second call fails
    vi.mocked(databaseHealthApi.getHealth).mockRejectedValueOnce(new Error("Network timeout"));

    const refreshBtn = screen.getByRole("button", { name: /Atualizar agora/i });
    fireEvent.click(refreshBtn);

    await waitFor(() => {
      expect(screen.getByText(/Falha na atualização dos dados/i)).toBeInTheDocument();
    });

    // Existing data is still shown!
    expect(screen.getAllByText("5.51 GB").length).toBeGreaterThanOrEqual(1);
  });

  it("handles initial load failure with error message and retry button", async () => {
    vi.mocked(databaseHealthApi.getHealth).mockRejectedValueOnce(new Error("Connection refused"));

    render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Erro ao consultar o banco de dados")).toBeInTheDocument();
      expect(screen.getByText("Connection refused")).toBeInTheDocument();
    });

    // Retry succeeds
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValueOnce(mockHealthData);
    fireEvent.click(screen.getByRole("button", { name: /Tentar novamente/i }));

    await waitFor(() => {
      expect(screen.getByText("Saúde do Banco")).toBeInTheDocument();
      expect(screen.getAllByText("5.51 GB").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("cleans up auto-refresh interval on unmount", async () => {
    vi.useFakeTimers();
    vi.mocked(databaseHealthApi.getHealth).mockResolvedValue(mockHealthData);

    const { unmount } = render(
      <MemoryRouter>
        <DatabaseHealthPage />
      </MemoryRouter>
    );

    expect(databaseHealthApi.getHealth).toHaveBeenCalledTimes(1);

    // Fast-forward 30s
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(databaseHealthApi.getHealth).toHaveBeenCalledTimes(2);

    // Unmount
    unmount();

    // Fast-forward another 30s
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    // Should NOT have called getHealth again after unmount
    expect(databaseHealthApi.getHealth).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });
});
