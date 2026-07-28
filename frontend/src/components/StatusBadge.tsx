import { Badge } from "react-bootstrap";

import type { PiTagValidationStatus } from "../types";

const LABELS: Record<PiTagValidationStatus, string> = {
  PENDING: "Pendente",
  VALID: "Valida",
  INVALID: "Invalida",
  ERROR: "Erro",
};

export function StatusBadge({ status }: { status: PiTagValidationStatus }) {
  return <Badge bg="" className={`piad-status-${status.toLowerCase()}`}>{LABELS[status]}</Badge>;
}
