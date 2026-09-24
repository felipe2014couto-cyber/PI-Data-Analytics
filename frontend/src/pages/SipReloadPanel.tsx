import { FormEvent, useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Form, ProgressBar, Table } from "react-bootstrap";
import { equipmentsApi, sipApi, sipReloadApi } from "../api";
import type { Equipment, SipReloadJob, SipSource } from "../types";

export function SipReloadPanel() {
  const [sources, setSources] = useState<SipSource[]>([]);
  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [jobs, setJobs] = useState<SipReloadJob[]>([]);
  const [equipmentId, setEquipmentId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const loadJobs = async () => setJobs(await sipReloadApi.list());
  useEffect(() => {
    void Promise.all([sipApi.list(), equipmentsApi.list({ page: 1, page_size: 200 }), sipReloadApi.list()])
      .then(([nextSources, nextEquipments, nextJobs]) => { setSources(nextSources); setEquipments(nextEquipments.items); setJobs(nextJobs); })
      .catch(() => setError("Não foi possível carregar as consultas SIP ou recargas."));
    const timer = window.setInterval(() => void loadJobs().catch(() => setError("Não foi possível atualizar as recargas SIP.")), 10000);
    return () => window.clearInterval(timer);
  }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setMessage("");
    if (!sourceId || !start || !end || new Date(`${start}Z`) >= new Date(`${end}Z`)) { setError("Selecione a consulta SIP e um período válido."); return; }
    setBusy(true);
    try {
      await sipReloadApi.create(Number(sourceId), new Date(`${start}Z`).toISOString(), new Date(`${end}Z`).toISOString());
      setMessage("Recarga SIP agendada. Os dados serão gravados no TimescaleDB.");
      await loadJobs();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const cancel = async (job: SipReloadJob) => {
    if (!window.confirm(`Cancelar recarga SIP #${job.id}?`)) return;
    try { await sipReloadApi.cancel(job.id); await loadJobs(); } catch (reason) { setError(String(reason)); }
  };
  const clear = async () => {
    if (!window.confirm("Limpar recargas SIP finalizadas? As amostras armazenadas permanecem no TimescaleDB.")) return;
    try { await sipReloadApi.clearTerminal(); await loadJobs(); } catch (reason) { setError(String(reason)); }
  };
  return <>
    <Card className="piad-card mb-3"><Card.Header>Recarga histórica SIP → TimescaleDB</Card.Header><Card.Body>
      <Alert variant="info">O período escolhido é aplicado à consulta SIP. A conexão Oracle faz somente leitura; as amostras são gravadas no TimescaleDB.</Alert>
      {error && <Alert variant="danger">{error}</Alert>}{message && <Alert variant="success">{message}</Alert>}
      <Form onSubmit={(event) => void submit(event)} className="row g-2">
        <Form.Group className="col-md-3"><Form.Label>Equipamento</Form.Label><Form.Select value={equipmentId} onChange={(event) => { setEquipmentId(event.target.value); setSourceId(""); }}><option value="">Todos</option>{equipments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Consulta temporal SIP</Form.Label><Form.Select required value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Selecione...</option>{sources.filter((item) => item.active && (!equipmentId || item.equipment_id === Number(equipmentId))).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Início (UTC)</Form.Label><Form.Control type="datetime-local" required value={start} onChange={(event) => setStart(event.target.value)} /></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Fim (UTC)</Form.Label><Form.Control type="datetime-local" required value={end} onChange={(event) => setEnd(event.target.value)} /></Form.Group>
        <div className="col-12"><Button type="submit" disabled={busy}>Recarregar período SIP</Button></div>
      </Form>
    </Card.Body></Card>
    <Card className="piad-card"><Card.Header className="d-flex justify-content-between align-items-center">Recargas SIP recentes<Button size="sm" variant="outline-secondary" onClick={() => void clear()}>Limpar finalizadas</Button></Card.Header><Card.Body><Table responsive size="sm"><thead><tr><th>Recarga</th><th>Consulta SIP</th><th>Período</th><th>Progresso</th><th>Amostras</th><th>Status</th><th /></tr></thead><tbody>
      {jobs.map((job) => <tr key={job.id}><td>#{job.id}</td><td>{sources.find((item) => item.id === job.source_id)?.name ?? `#${job.source_id}`}</td><td>{new Date(job.target_start).toLocaleString()} – {new Date(job.target_end).toLocaleString()}</td><td style={{ minWidth: 120 }}><ProgressBar now={job.progress_percent} label={`${job.progress_percent.toFixed(0)}%`} /></td><td>{job.rows_written}</td><td><Badge bg={job.status === "COMPLETED" ? "success" : job.status === "FAILED" ? "danger" : job.status === "CANCELLED" ? "secondary" : "primary"}>{job.status}</Badge>{job.error_message && <div className="text-danger small">{job.error_message}</div>}</td><td>{["PENDING", "RUNNING"].includes(job.status) && <Button size="sm" variant="outline-danger" onClick={() => void cancel(job)}>Cancelar</Button>}</td></tr>)}
    </tbody></Table>{jobs.length === 0 && <div className="text-muted">Nenhuma recarga SIP registrada.</div>}</Card.Body></Card>
  </>;
}
