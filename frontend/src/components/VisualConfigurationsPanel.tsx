import { useEffect, useState } from "react";
import { Alert, Button, Card, Form, Modal } from "react-bootstrap";
import { visualConfigurationsApi } from "../api";
import { ApiError } from "../api/http";
import type { TimeSeriesMode, VisualConfiguration, VisualConfigurationVersion, VisualRulesState } from "../types";

interface Props { visualRules: VisualRulesState; mode: TimeSeriesMode; onOpen: (rules: VisualRulesState, mode: TimeSeriesMode) => void; }
const documentFor = (visualRules: VisualRulesState, mode: TimeSeriesMode) => ({ schema_version: 1 as const, visual_rules: { ...visualRules, queryMode: mode } });
const openDocument = (document: VisualConfiguration["document"], onOpen: Props["onOpen"]) => {
  if (!document) return;
  onOpen(document.visual_rules, document.visual_rules.queryMode ?? "interpolated");
};

export function VisualConfigurationsPanel({ visualRules, mode, onOpen }: Props) {
  const [items, setItems] = useState<VisualConfiguration[]>([]); const [selectedId, setSelectedId] = useState(""); const [current, setCurrent] = useState<VisualConfiguration | null>(null);
  const [name, setName] = useState(""); const [message, setMessage] = useState<string | null>(null); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<VisualConfigurationVersion[] | null>(null);
  const loadList = async () => { try { setItems(await visualConfigurationsApi.list()); } catch { setError("Não foi possível listar as configurações visuais."); } };
  useEffect(() => { void loadList(); }, []);
  const run = async (operation: () => Promise<void>) => { setBusy(true); setError(null); setMessage(null); try { await operation(); } catch (reason) { setError(reason instanceof ApiError && reason.status === 409 ? "A configuração foi alterada em outra sessão. Abra novamente antes de salvar." : "Não foi possível concluir a operação sem descartar o estado atual."); } finally { setBusy(false); } };
  const open = () => run(async () => { if (!selectedId) return; const item = await visualConfigurationsApi.get(selectedId); if (!item.document) return; setCurrent(item); setName(item.name); openDocument(item.document, onOpen); setMessage(`Configuração ${item.name} aberta.`); });
  const create = () => run(async () => { const item = await visualConfigurationsApi.create(name, documentFor(visualRules, mode)); setCurrent(item); setSelectedId(item.id); setMessage("Configuração salva."); await loadList(); });
  const save = () => run(async () => { if (!current) return; const item = await visualConfigurationsApi.update(current.id, current.current_version, documentFor(visualRules, mode)); setCurrent(item); setMessage("Nova versão salva."); await loadList(); });
  const rename = () => run(async () => { if (!current) return; const item = await visualConfigurationsApi.rename(current.id, current.current_version, name); setCurrent(item); setMessage("Configuração renomeada e versionada."); await loadList(); });
  const showHistory = () => run(async () => { if (current) setHistory(await visualConfigurationsApi.history(current.id)); });
  const restore = (version: number) => run(async () => { if (!current) return; const item = await visualConfigurationsApi.restore(current.id, current.current_version, version); setCurrent(item); openDocument(item.document, onOpen); setHistory(null); setMessage(`Versão ${version} restaurada como versão ${item.current_version}.`); await loadList(); });
  return <><Card className="mb-3"><Card.Header>Configurações visuais salvas</Card.Header><Card.Body>
    {error ? <Alert variant="danger">{error}</Alert> : null}{message ? <Alert variant="success">{message}</Alert> : null}
    <div className="d-flex flex-wrap gap-2 align-items-end"><Form.Group><Form.Label>Configuração</Form.Label><Form.Select data-testid="visual-config-select" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">Selecione</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name} (v{item.current_version})</option>)}</Form.Select></Form.Group>
      <Form.Group><Form.Label>Nome</Form.Label><Form.Control data-testid="visual-config-name" maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></Form.Group>
      <Button disabled={busy || !name.trim()} onClick={create}>Salvar nova</Button><Button disabled={busy || !selectedId} onClick={open}>Abrir</Button><Button disabled={busy || !current} onClick={save}>Salvar alterações</Button><Button disabled={busy || !current || !name.trim()} onClick={rename}>Renomear</Button><Button disabled={busy || !current} onClick={showHistory}>Histórico</Button>
    </div>{current ? <small className="d-block mt-2">Aberta: {current.name}, versão {current.current_version}</small> : null}
  </Card.Body></Card>
  <Modal show={history !== null} onHide={() => setHistory(null)}><Modal.Header closeButton><Modal.Title>Histórico de versões</Modal.Title></Modal.Header><Modal.Body>{history?.map((item) => <div key={item.id} className="d-flex justify-content-between align-items-center mb-2"><span>Versão {item.version} — {item.operation}</span><Button size="sm" disabled={item.version === current?.current_version} onClick={() => restore(item.version)}>Restaurar</Button></div>)}</Modal.Body></Modal></>;
}
