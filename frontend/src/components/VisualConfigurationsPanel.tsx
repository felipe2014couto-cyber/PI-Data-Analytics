import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Dropdown, Form, Modal, Overlay, Popover } from "react-bootstrap";
import { visualConfigurationsApi } from "../api";
import { ApiError } from "../api/http";
import type { VisualConfiguration, VisualConfigurationDocument, VisualConfigurationVersion } from "../types";

interface Props { document: VisualConfigurationDocument; onOpen: (document: VisualConfigurationDocument) => void; }
type NameAction = "create" | "rename" | null;

const openDocument = (document: VisualConfiguration["document"], onOpen: Props["onOpen"]) => {
  if (!document) return;
  onOpen(document);
};

export function VisualConfigurationsPanel({ document, onOpen }: Props) {
  const [items, setItems] = useState<VisualConfiguration[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [versions, setVersions] = useState<VisualConfigurationVersion[]>([]);
  const [current, setCurrent] = useState<VisualConfiguration | null>(null);
  const [opened, setOpened] = useState<{ id: string; name: string; version: number } | null>(null);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<VisualConfigurationVersion[] | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [nameAction, setNameAction] = useState<NameAction>(null);
  const [deleteTarget, setDeleteTarget] = useState<VisualConfiguration | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const versionRequestRef = useRef(0);

  const loadList = async () => { try { setItems(await visualConfigurationsApi.list()); } catch { setError("Não foi possível listar as configurações visuais."); } };
  useEffect(() => { void loadList(); }, []);
  useEffect(() => { if (searchOpen) window.setTimeout(() => searchInputRef.current?.focus(), 0); }, [searchOpen]);
  useEffect(() => {
    if (!message) return;
    const timeout = window.setTimeout(() => setMessage(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [message]);

  const run = async (operation: () => Promise<void>) => {
    setBusy(true); setError(null); setMessage(null);
    try { await operation(); }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 409 ? "A configuração foi alterada em outra sessão. Abra novamente antes de salvar." : "Não foi possível concluir a operação sem descartar o estado atual."); }
    finally { setBusy(false); }
  };
  const loadVersions = async (id: string, preferredVersion?: number) => {
    const request = ++versionRequestRef.current;
    try {
      const loaded = await visualConfigurationsApi.history(id);
      if (request !== versionRequestRef.current) return;
      setVersions(loaded);
      setSelectedVersion((currentVersion) => preferredVersion ?? currentVersion ?? loaded[0]?.version ?? null);
    } catch { if (request === versionRequestRef.current) setError("Não foi possível listar as versões da configuração."); }
  };
  const selectConfiguration = (id: string) => {
    setSelectedId(id); setVersions([]);
    const item = items.find((candidate) => candidate.id === id);
    setSelectedVersion(item?.current_version ?? null);
    if (id) void loadVersions(id, item?.current_version);
  };
  const open = () => run(async () => {
    if (!selectedId) return;
    const item = await visualConfigurationsApi.get(selectedId);
    const version = selectedVersion ?? item.current_version;
    const selectedDocument = version === item.current_version ? item.document : (await visualConfigurationsApi.getVersion(selectedId, version)).document;
    if (!selectedDocument) return;
    setCurrent(item); setOpened({ id: item.id, name: item.name, version }); setName(item.name); openDocument(selectedDocument, onOpen); setMessage(`Configuração ${item.name}, versão ${version}, aberta.`);
  });
  const create = () => run(async () => { const item = await visualConfigurationsApi.create(name, document); setCurrent(item); setOpened({ id: item.id, name: item.name, version: item.current_version }); setSelectedId(item.id); setSelectedVersion(item.current_version); setVersions([]); setMessage("Configuração salva."); setNameAction(null); await loadList(); });
  const save = () => run(async () => { if (!current) return; const item = await visualConfigurationsApi.update(current.id, current.current_version, document); setCurrent(item); setOpened({ id: item.id, name: item.name, version: item.current_version }); setSelectedVersion(item.current_version); setMessage("Nova versão salva."); await Promise.all([loadList(), loadVersions(item.id, item.current_version)]); });
  const rename = () => run(async () => { if (!current) return; const item = await visualConfigurationsApi.rename(current.id, current.current_version, name); setCurrent(item); setOpened((value) => value?.id === item.id ? { ...value, name: item.name } : value); setSelectedVersion(item.current_version); setMessage("Configuração renomeada e versionada."); setNameAction(null); await Promise.all([loadList(), loadVersions(item.id, item.current_version)]); });
  const showHistory = () => run(async () => { if (current) setHistory(await visualConfigurationsApi.history(current.id)); });
  const openHistoryVersion = (version: number) => run(async () => { if (!selectedId) return; const [item, historical] = await Promise.all([visualConfigurationsApi.get(selectedId), visualConfigurationsApi.getVersion(selectedId, version)]); setCurrent(item); setOpened({ id: item.id, name: item.name, version }); setSelectedVersion(version); openDocument(historical.document, onOpen); setHistory(null); setMessage(`Configuração ${item.name}, versão ${version}, aberta.`); });
  const restore = (version: number) => run(async () => { if (!current) return; const item = await visualConfigurationsApi.restore(current.id, current.current_version, version); setCurrent(item); setOpened({ id: item.id, name: item.name, version: item.current_version }); setSelectedVersion(item.current_version); openDocument(item.document, onOpen); setHistory(null); setMessage(`Versão ${version} restaurada como versão ${item.current_version}.`); await Promise.all([loadList(), loadVersions(item.id, item.current_version)]); });
  const remove = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true); setDeleteError(null);
    try {
      await visualConfigurationsApi.remove(deleteTarget.id);
      setItems((loaded) => loaded.filter((item) => item.id !== deleteTarget.id));
      setSelectedId(""); setSelectedVersion(null); setVersions([]);
      if (current?.id === deleteTarget.id) { setCurrent(null); setName(""); }
      if (opened?.id === deleteTarget.id) setOpened(null);
      setError(null); setMessage("Configuração excluída."); setDeleteTarget(null);
    } catch (reason) {
      setDeleteError(reason instanceof ApiError ? reason.message : "Não foi possível excluir a configuração. Tente novamente.");
    } finally { setDeleting(false); }
  };

  const selected = items.find((item) => item.id === selectedId);
  const filteredItems = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return term ? items.filter((item) => item.name.toLocaleLowerCase().includes(term)) : items;
  }, [items, search]);
  const startNameAction = (action: Exclude<NameAction, null>) => { setName(action === "rename" ? current?.name ?? "" : ""); setNameAction(action); };

  return <div className="visual-config-control" data-testid="visual-config-control">
    <div className="visual-config-control__main">
      <Form.Label htmlFor="visual-config-select" className="mb-0 text-nowrap">Configuração:</Form.Label>
      <Form.Select id="visual-config-select" size="sm" data-testid="visual-config-select" value={selectedId} onChange={(event) => selectConfiguration(event.target.value)} aria-label="Configuração visual salva">
        <option value="">Selecione</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name} (v{item.current_version})</option>)}
      </Form.Select>
      {selected ? <Form.Select size="sm" className="visual-config-control__version" data-testid="visual-config-version-select" value={selectedVersion ?? selected.current_version} onChange={(event) => setSelectedVersion(Number(event.target.value))} aria-label="Versão da configuração">
        {(versions.length ? versions : [{ version: selected.current_version }]).map((item) => <option key={item.version} value={item.version}>v{item.version}</option>)}
      </Form.Select> : null}
      <Button ref={searchButtonRef} variant="outline-secondary" size="sm" className="visual-config-control__icon" title="Pesquisar configuração" aria-label="Pesquisar configuração" aria-expanded={searchOpen} onClick={() => setSearchOpen((open) => !open)}>
        <i className="bi bi-search" aria-hidden="true" />
      </Button>
      <Dropdown align="end">
        <Dropdown.Toggle variant="outline-secondary" size="sm" className="visual-config-control__icon visual-config-control__menu" aria-label="Ações da configuração"><i className="bi bi-three-dots-vertical" aria-hidden="true" /></Dropdown.Toggle>
        <Dropdown.Menu>
          <Dropdown.Item disabled={busy || !selectedId} onClick={() => void open()}>Abrir</Dropdown.Item>
          <Dropdown.Item disabled={busy} onClick={() => startNameAction("create")}>Salvar nova</Dropdown.Item>
          <Dropdown.Item disabled={busy || !current || current.id !== selectedId} onClick={() => void save()}>Salvar alterações</Dropdown.Item>
          <Dropdown.Item disabled={busy || !current || current.id !== selectedId} onClick={() => startNameAction("rename")}>Renomear</Dropdown.Item>
          <Dropdown.Item disabled={busy || !current || current.id !== selectedId} onClick={() => void showHistory()}>Histórico</Dropdown.Item>
          <Dropdown.Divider />
          <Dropdown.Item className="text-danger" disabled={busy || deleting || !selected} onClick={() => { if (selected) { setDeleteError(null); setDeleteTarget(selected); } }}><i className="bi bi-trash me-2" aria-hidden="true" />Excluir configuração</Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown>
    </div>
    {opened ? <small className="visual-config-control__current">Aberta: {opened.name}, versão {opened.version}</small> : selected ? <small className="visual-config-control__current">Selecionada: {selected.name}, versão {selectedVersion ?? selected.current_version}</small> : null}
    {error ? <Alert variant="danger" className="visual-config-control__feedback">{error}</Alert> : null}
    {message ? <Alert variant="success" className="visual-config-control__feedback">{message}</Alert> : null}

    <Overlay target={searchButtonRef.current} show={searchOpen} placement="bottom" rootClose onHide={() => setSearchOpen(false)}>
      <Popover className="visual-config-search" data-testid="visual-config-search-popover">
        <Popover.Header as="h3">Pesquisar configuração</Popover.Header>
        <Popover.Body>
          <div className="visual-config-search__input mb-2"><i className="bi bi-search" aria-hidden="true" /><Form.Control ref={searchInputRef} size="sm" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Pesquisar pelo nome" aria-label="Pesquisar pelo nome da configuração" /></div>
          <div className="visual-config-search__results">
            {filteredItems.length ? filteredItems.map((item) => <button key={item.id} type="button" className={`visual-config-search__result${opened?.id === item.id ? " is-current" : ""}`} onClick={() => { selectConfiguration(item.id); setSearchOpen(false); }}>
              <span>{item.name}</span><small>v{item.current_version}{opened?.id === item.id ? ` · aberta v${opened.version}` : ""}</small>
            </button>) : <div className="text-muted small py-2 text-center">Nenhuma configuração encontrada</div>}
          </div>
        </Popover.Body>
      </Popover>
    </Overlay>

    <Modal size="sm" centered show={nameAction !== null} onHide={() => setNameAction(null)}>
      <Modal.Header closeButton><Modal.Title>{nameAction === "create" ? "Salvar nova configuração" : "Renomear configuração"}</Modal.Title></Modal.Header>
      <Modal.Body><Form.Group><Form.Label>Nome</Form.Label><Form.Control autoFocus data-testid="visual-config-name" maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></Form.Group></Modal.Body>
      <Modal.Footer><Button variant="secondary" onClick={() => setNameAction(null)}>Cancelar</Button><Button disabled={busy || !name.trim()} onClick={() => void (nameAction === "create" ? create() : rename())}>{nameAction === "create" ? "Salvar nova" : "Renomear"}</Button></Modal.Footer>
    </Modal>
    <Modal centered show={deleteTarget !== null} onHide={() => { if (!deleting) { setDeleteTarget(null); setDeleteError(null); } }}>
      <Modal.Header closeButton={!deleting}><Modal.Title>Excluir configuração?</Modal.Title></Modal.Header>
      <Modal.Body>
        <p>A configuração &quot;{deleteTarget?.name}&quot; e todas as suas versões serão excluídas permanentemente.</p>
        <p className="mb-0">Esta ação não poderá ser desfeita.</p>
        {deleteError ? <Alert variant="danger" className="mt-3 mb-0" data-testid="visual-config-delete-error">{deleteError}</Alert> : null}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" disabled={deleting} onClick={() => { setDeleteTarget(null); setDeleteError(null); }}>Cancelar</Button>
        <Button variant="danger" disabled={deleting} onClick={() => void remove()}>{deleting ? <><span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />Excluindo...</> : "Excluir configuração"}</Button>
      </Modal.Footer>
    </Modal>
    <Modal show={history !== null} onHide={() => setHistory(null)}><Modal.Header closeButton><Modal.Title>Histórico de versões</Modal.Title></Modal.Header><Modal.Body>{history?.map((item) => <div key={item.id} className="d-flex justify-content-between align-items-center gap-2 mb-2"><span className="me-auto">Versão {item.version} — {item.operation}</span><Button size="sm" variant="outline-primary" onClick={() => void openHistoryVersion(item.version)}>Abrir</Button><Button size="sm" disabled={item.version === current?.current_version} onClick={() => void restore(item.version)}>Restaurar</Button></div>)}</Modal.Body></Modal>
  </div>;
}
