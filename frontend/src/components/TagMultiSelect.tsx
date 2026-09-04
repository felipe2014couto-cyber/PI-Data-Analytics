import { Form, ListGroup, Badge } from "react-bootstrap";

import { StatusBadge } from "./StatusBadge";
import type { PiTag, PiTagValidationStatus } from "../types";

export interface TagOption {
  id: number;
  displayName: string;
  tagName: string;
  equipmentCode: string;
  sectionId: number | null;
  sectionCode: string;
  variableTypeCode: string;
  unit: string | null;
  validationStatus: PiTagValidationStatus;
  active: boolean;
}

interface TagMultiSelectProps {
  options: TagOption[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  emptyMessage?: string;
  testId?: string;
}

export function buildTagOption(
  tag: PiTag,
  equipment: { code: string } | undefined,
  section: { code: string } | undefined,
  variableType: { code: string } | undefined,
): TagOption {
  return {
    id: tag.id,
    displayName: tag.display_name,
    tagName: tag.pi_tag_name,
    equipmentCode: equipment?.code ?? `EQ-${tag.equipment_id}`,
    sectionId: tag.section_id,
    sectionCode: section?.code ?? (tag.section_id === null ? "EQUIPAMENTO" : `SEC-${tag.section_id}`),
    variableTypeCode: variableType?.code ?? `VT-${tag.variable_type_id}`,
    unit: tag.engineering_unit,
    validationStatus: tag.validation_status,
    active: tag.active,
  };
}

function isSelectable(option: TagOption): boolean {
  if (!option.active) return false;
  if (option.validationStatus !== "VALID" && option.validationStatus !== "PENDING") return false;
  return true;
}

export function TagMultiSelect({
  options,
  selectedIds,
  onChange,
  disabled,
  emptyMessage = "Nenhuma tag disponivel para os filtros selecionados.",
  testId = "tag-multi-select",
}: TagMultiSelectProps) {
  const selected = new Set(selectedIds);
  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onChange(Array.from(next));
  };

  return (
    <div data-testid={testId}>
      {options.length === 0 ? (
        <div className="text-muted small py-3 text-center">{emptyMessage}</div>
      ) : (
        <ListGroup className="tag-multi-select-list" style={{ maxHeight: 260, overflowY: "auto" }}>
          {options.map((option) => {
            const selectable = isSelectable(option);
            const isSelected = selected.has(option.id);
            return (
              <ListGroup.Item
                key={option.id}
                action
                disabled={!selectable || disabled}
                onClick={() => selectable && toggle(option.id)}
                data-testid={`tag-option-${option.id}`}
                data-selectable={selectable}
                data-selected={isSelected}
                className={isSelected ? "tag-multi-select-item-selected" : undefined}
              >
                <Form.Check
                  type="checkbox"
                  id={`tag-option-${option.id}-check`}
                  checked={isSelected}
                  disabled={!selectable || disabled}
                  onChange={() => toggle(option.id)}
                  label={
                    <div className="d-flex flex-column">
                      <div className="d-flex align-items-center gap-2">
                        <span className="fw-semibold">{option.displayName}</span>
                        <StatusBadge status={option.validationStatus} />
                        {!option.active ? <Badge bg="secondary">Inativo</Badge> : null}
                      </div>
                      <span className="text-muted small">
                        {option.tagName} | {option.equipmentCode} / {option.sectionCode} / {option.variableTypeCode}
                        {option.unit ? ` | ${option.unit}` : ""}
                      </span>
                    </div>
                  }
                />
              </ListGroup.Item>
            );
          })}
        </ListGroup>
      )}
    </div>
  );
}
