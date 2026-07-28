import { useEffect, useState } from "react";
import { Spinner } from "react-bootstrap";

import { piApi } from "../api";
import type { PiHealth, PiConnectionStatus } from "../types";

interface PiConnectionStatusProps {
  health?: PiHealth | null;
  loading?: boolean;
}

const STATUS_META: Record<PiConnectionStatus, { label: string; className: string; icon: string }> = {
  connected: { label: "PI conectado", className: "bg-success", icon: "bi-check-circle" },
  verifying: { label: "Verificando PI...", className: "bg-info", icon: "bi-arrow-repeat" },
  not_configured: { label: "PI nao configurado", className: "bg-secondary", icon: "bi-slash-circle" },
  unavailable: { label: "PI indisponivel", className: "bg-danger", icon: "bi-exclamation-triangle" },
};

export function PiConnectionStatusBadge({ health, loading }: PiConnectionStatusProps) {
  if (loading) {
    return (
      <span className="badge bg-info d-inline-flex align-items-center gap-1" data-testid="pi-status-loading">
        <Spinner animation="border" size="sm" role="status" aria-hidden="true" />
        Verificando PI
      </span>
    );
  }
  const status: PiConnectionStatus = health?.status ?? "not_configured";
  const meta = STATUS_META[status];
  return (
    <span
      className={`badge ${meta.className} d-inline-flex align-items-center gap-1`}
      data-testid="pi-status"
      data-status={status}
      title={health?.message ?? ""}
    >
      <i className={`bi ${meta.icon}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

export function usePiHealth(autoLoad = true) {
  const [health, setHealth] = useState<PiHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await piApi.health();
      setHealth(data);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (autoLoad) {
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad]);

  return { health, loading, error, reload: load };
}
