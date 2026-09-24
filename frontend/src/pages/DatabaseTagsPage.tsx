import { FormEvent, useEffect, useState } from "react";
import { Alert, Button, Card, Form, Modal, Table } from "react-bootstrap";
import { equipmentsApi, sectionsApi, sipApi, sipDatabaseTagsApi, variableTypesApi } from "../api";
import type { Equipment, Section, SipDatabaseTag, SipDatabaseTagCreate, VariableType } from "../types";

const empty: SipDatabaseTagCreate = { equipment_id: 0, section_id: null, variable_type_id: 0, name: "", sql_text: "", value_column: "", active: true };

export function DatabaseTagsPage() {
  const [tags, setTags] = useState<SipDatabaseTag[]>([]);
  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [variables, setVariables] = useState<VariableType[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [form, setForm] = useState<SipDatabaseTagCreate>(empty);
  const [columns, setColumns] = useState<string[]>([]);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [values, setValues] = useState<Record<number, string>>({});

  const load = async () => {
    const [nextTags, eq, sec, vars] = await Promise.all([
      sipDatabaseTagsApi.list(), equipmentsApi.list({ page: 1, page_size: 200 }),
      sectionsApi.list({ page: 1, page_size: 200 }), variableTypesApi.list({ page: 1, page_size: 200 }),
    ]);
    setTags(nextTags); setEquipments(eq.items); setSections(sec.items); setVariables(vars.items);
  };
  useEffect(() => { void load().catch(() => setError("Não foi possível carregar as Tags de Banco.")); }, []);
  const open = (tag?: SipDatabaseTag) => {
    setEditing(tag?.id ?? null);
    setForm(tag ? { equipment_id: tag.equipment_id, section_id: tag.section_id, variable_type_id: tag.variable_type_id,
      name: tag.name, sql_text: tag.sql_text, value_column: tag.value_column, active: tag.active } : empty);
    setColumns(tag ? [tag.value_column] : []); setError(""); setShow(true);
  };
  const inspect = async () => {
    setBusy(true); setError("");
    try { setColumns((await sipApi.inspectColumns(form.sql_text)).columns); }
    catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      if (editing) await sipDatabaseTagsApi.update(editing, form);
      else await sipDatabaseTagsApi.create(form);
      setShow(false); await load();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const remove = async (tag: SipDatabaseTag) => {
    if (!window.confirm(`Excluir a Tag de Banco "${tag.name}"?`)) return;
    try { await sipDatabaseTagsApi.remove(tag.id); await load(); }
    catch (reason) { setError(String(reason)); }
  };
  const read = async (tag: SipDatabaseTag) => {
    try { const result = await sipDatabaseTagsApi.value(tag.id); setValues((current) => ({ ...current, [tag.id]: String(result.value ?? "—") })); }
    catch (reason) { setError(String(reason)); }
  };
  return <>
    <div className="d-flex justify-content-between align-items-center mb-3"><div><h1 className="h4 mb-1">Tags de Banco</h1><div className="text-muted small">Valores atuais do SIP, sem Timestamp.</div></div><Button onClick={() => open()}>+ Nova Tag de Banco</Button></div>
    {error && !show && <Alert variant="danger">{error}</Alert>}
    <Card className="piad-card"><Card.Body><Table responsive size="sm"><thead><tr><th>Nome</th><th>Equipamento</th><th>Seção</th><th>Coluna Value</th><th>Valor atual</th><th>Ações</th></tr></thead><tbody>
      {tags.map((tag) => <tr key={tag.id}><td>{tag.name}</td><td>{equipments.find((item) => item.id === tag.equipment_id)?.name ?? tag.equipment_id}</td><td>{sections.find((item) => item.id === tag.section_id)?.name ?? "Equipamento inteiro"}</td><td>{tag.value_column}</td><td>{values[tag.id] ?? "—"}</td><td className="text-nowrap"><Button size="sm" variant="outline-primary" className="me-1" onClick={() => void read(tag)}>Ler valor</Button><Button size="sm" variant="outline-secondary" className="me-1" onClick={() => open(tag)}>Editar</Button><Button size="sm" variant="outline-danger" onClick={() => void remove(tag)}>Excluir</Button></td></tr>)}
    </tbody></Table>{tags.length === 0 && <div className="text-muted">Nenhuma Tag de Banco cadastrada.</div>}</Card.Body></Card>
    <Modal show={show} onHide={() => setShow(false)} size="lg"><Form onSubmit={(event) => void save(event)}><Modal.Header closeButton><Modal.Title>{editing ? "Editar" : "Nova"} Tag de Banco SIP</Modal.Title></Modal.Header><Modal.Body>
      {error && <Alert variant="danger">{error}</Alert>}
      <div className="row g-3"><Form.Group className="col-md-4"><Form.Label>Equipamento</Form.Label><Form.Select required value={form.equipment_id || ""} onChange={(e) => setForm({ ...form, equipment_id: Number(e.target.value), section_id: null })}><option value="">Selecione...</option>{equipments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Form.Group>
      <Form.Group className="col-md-4"><Form.Label>Seção</Form.Label><Form.Select value={form.section_id ?? ""} onChange={(e) => setForm({ ...form, section_id: e.target.value ? Number(e.target.value) : null })}><option value="">Equipamento inteiro</option>{sections.filter((item) => item.equipment_id === form.equipment_id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Form.Group>
      <Form.Group className="col-md-4"><Form.Label>Tipo de variável</Form.Label><Form.Select required value={form.variable_type_id || ""} onChange={(e) => setForm({ ...form, variable_type_id: Number(e.target.value) })}><option value="">Selecione...</option>{variables.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Form.Group>
      <Form.Group className="col-12"><Form.Label>Nome</Form.Label><Form.Control required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Form.Group>
      <Form.Group className="col-12"><Form.Label>SQL de leitura (SELECT)</Form.Label><Form.Control as="textarea" rows={7} required value={form.sql_text} onChange={(e) => { setForm({ ...form, sql_text: e.target.value, value_column: "" }); setColumns([]); }} /><Form.Text>O SQL deve retornar um único valor atual. Nenhuma coluna Timestamp é necessária.</Form.Text></Form.Group>
      <div className="col-12"><Button type="button" variant="outline-primary" disabled={busy || !form.sql_text} onClick={() => void inspect()}>Ler colunas do SQL</Button></div>
      <Form.Group className="col-md-6"><Form.Label>Coluna Value</Form.Label><Form.Select required value={form.value_column} onChange={(e) => setForm({ ...form, value_column: e.target.value })}><option value="">Selecione...</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</Form.Select></Form.Group>
      <div className="col-12"><Form.Check type="switch" label="Ativo" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /></div></div>
    </Modal.Body><Modal.Footer><Button variant="outline-secondary" onClick={() => setShow(false)}>Cancelar</Button><Button type="submit" disabled={busy}>Salvar</Button></Modal.Footer></Form></Modal>
  </>;
}
