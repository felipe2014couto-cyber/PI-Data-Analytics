import { Spinner } from "react-bootstrap";

interface LoadingStateProps {
  label?: string;
}

export function LoadingState({ label = "Carregando..." }: LoadingStateProps) {
  return (
    <div className="piad-loading" role="status" aria-live="polite">
      <Spinner animation="border" role="status" size="sm" className="me-2" />
      <span>{label}</span>
    </div>
  );
}
