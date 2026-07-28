import { Badge } from "react-bootstrap";

export function ActiveBadge({ active }: { active: boolean }) {
  return (
    <Badge bg="" className={active ? "piad-status-valid" : "piad-status-invalid"}>
      {active ? "Ativo" : "Inativo"}
    </Badge>
  );
}
