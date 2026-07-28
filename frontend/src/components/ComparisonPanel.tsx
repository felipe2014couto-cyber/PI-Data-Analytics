import { Alert, Col, Form, Row } from "react-bootstrap";
import { TagMultiSelect, type TagOption } from "./TagMultiSelect";
import type { ComparisonType } from "../types";

interface Props {
  type: ComparisonType | "disabled";
  onTypeChange: (value: ComparisonType | "disabled") => void;
  contextBEquipmentId: number | null;
  onContextBEquipmentChange: (value: number | null) => void;
  contextBCategoryId: number | null;
  onContextBCategoryChange: (value: number | null) => void;
  contextBTagIds: number[];
  onContextBTagsChange: (value: number[]) => void;
  contextBStart: string;
  contextBEnd: string;
  onContextBStartChange: (value: string) => void;
  onContextBEndChange: (value: string) => void;
  equipmentOptions: Array<{ id: number; code: string; name: string }>;
  categoryOptions: Array<{ id: number; code: string; name: string }>;
  tagOptions: TagOption[];
}

export function ComparisonPanel(props: Props) {
  const filteredTags = props.tagOptions.filter((tag) => {
    if (props.type === "equipments" && props.contextBEquipmentId) {
      const equipment = props.equipmentOptions.find((item) => item.id === props.contextBEquipmentId);
      return tag.equipmentCode === equipment?.code;
    }
    if (props.type === "categories" && props.contextBCategoryId) {
      const category = props.categoryOptions.find((item) => item.id === props.contextBCategoryId);
      return tag.variableTypeCode === category?.code;
    }
    return true;
  });

  return (
    <div className="border rounded p-2" data-testid="comparison-panel">
      <Form.Group>
        <Form.Label>Comparação</Form.Label>
        <Form.Select
          value={props.type}
          onChange={(event) => props.onTypeChange(event.target.value as ComparisonType | "disabled")}
          data-testid="comparison-type"
        >
          <option value="disabled">Desativada</option>
          <option value="periods">Períodos</option>
          <option value="equipments">Equipamentos</option>
          <option value="categories">Categorias</option>
        </Form.Select>
      </Form.Group>
      {props.type !== "disabled" ? (
        <>
          <div className="small fw-semibold mt-2">Contexto A — Referência</div>
          <div className="text-muted small">Utiliza a seleção principal acima.</div>
          <div className="small fw-semibold mt-3">Contexto B — Comparação</div>
        </>
      ) : null}
      {props.type === "periods" ? (
        <Row className="g-2 mt-1">
          <Col xs={12}>
            <Form.Label>Data inicial B</Form.Label>
            <Form.Control type="datetime-local" value={props.contextBStart} onChange={(event) => props.onContextBStartChange(event.target.value)} data-testid="comparison-start-b" />
          </Col>
          <Col xs={12}>
            <Form.Label>Data final B</Form.Label>
            <Form.Control type="datetime-local" value={props.contextBEnd} onChange={(event) => props.onContextBEndChange(event.target.value)} data-testid="comparison-end-b" />
          </Col>
        </Row>
      ) : null}
      {props.type === "equipments" ? (
        <Form.Group className="mt-2">
          <Form.Label>Equipamento B</Form.Label>
          <Form.Select value={props.contextBEquipmentId ?? ""} onChange={(event) => props.onContextBEquipmentChange(event.target.value ? Number(event.target.value) : null)} data-testid="comparison-equipment-b">
            <option value="">Selecione</option>
            {props.equipmentOptions.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
          </Form.Select>
        </Form.Group>
      ) : null}
      {props.type === "categories" ? (
        <Form.Group className="mt-2">
          <Form.Label>Categoria B</Form.Label>
          <Form.Select value={props.contextBCategoryId ?? ""} onChange={(event) => props.onContextBCategoryChange(event.target.value ? Number(event.target.value) : null)} data-testid="comparison-category-b">
            <option value="">Selecione</option>
            {props.categoryOptions.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
          </Form.Select>
        </Form.Group>
      ) : null}
      {(props.type === "equipments" || props.type === "categories") ? (
        <div className="mt-2">
          <Form.Label>Tags do Contexto B</Form.Label>
          <TagMultiSelect options={filteredTags} selectedIds={props.contextBTagIds} onChange={props.onContextBTagsChange} testId="comparison-tags-b" />
          {props.contextBTagIds.length === 0 ? <Alert variant="light" className="small mt-2 mb-0">Confirme ao menos uma tag para o Contexto B.</Alert> : null}
        </div>
      ) : null}
    </div>
  );
}
