import { Badge } from "react-bootstrap";
import type { PiTagLifecycleStatus } from "../types";

interface ActiveBadgeProps {
  active: boolean;
  lifecycleStatus?: PiTagLifecycleStatus;
}

export function ActiveBadge({ active, lifecycleStatus }: ActiveBadgeProps) {
  if (lifecycleStatus === "DELETION_PENDING") {
    return (
      <Badge bg="warning" text="dark" title="Exclusao assincrona em segundo plano">
        Excluindo...
      </Badge>
    );
  }
  return (
    <Badge bg="" className={active ? "piad-status-valid" : "piad-status-invalid"}>
      {active ? "Ativo" : "Inativo"}
    </Badge>
  );
}
