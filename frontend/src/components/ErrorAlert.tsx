import { Alert } from "react-bootstrap";

import { ApiError } from "../api/http";

interface ErrorAlertProps {
  error: unknown;
  fallbackMessage?: string;
  onClose?: () => void;
}

function describeError(error: unknown, fallback: string): { code: string; message: string } {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof Error) {
    return { code: "ERROR", message: error.message || fallback };
  }
  return { code: "ERROR", message: fallback };
}

export function ErrorAlert({ error, fallbackMessage = "Ocorreu um erro inesperado.", onClose }: ErrorAlertProps) {
  if (!error) {
    return null;
  }
  const { code, message } = describeError(error, fallbackMessage);
  return (
    <Alert variant="danger" dismissible={Boolean(onClose)} onClose={onClose} className="mb-3">
      <div className="fw-semibold mb-1">{message}</div>
      <div className="small text-muted">Codigo: {code}</div>
    </Alert>
  );
}
