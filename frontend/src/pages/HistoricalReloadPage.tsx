import { FormEvent, useEffect, useState } from "react";
import { Alert, Button, Card, Form, Table } from "react-bootstrap";

import { historicalReloadApi } from "../api";
import type { HistoricalReloadJob, HistoricalReloadMode, HistoricalReloadRequest, HistoricalReloadSummary } from "../types";

function isoFromInput(value: string): string {
  return new Date(value).toISOString();
}

export function HistoricalReloadPage() {
  const [scope, setScope] = useState<"tag" | "variable" | "all">("tag");
  const [scopeId, setScopeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [mode, setMode] = useState<HistoricalReloadMode>("recorded");
  const [interval, setInterval] = useState("10s");
  const [jobs, setJobs] = useState<HistoricalReloadJob[]>([]);
  const [summary, setSummary] = useState<HistoricalReloadSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    try {
      const [nextJobs, nextSummary] = await Promise.all([historicalReloadApi.list(), historicalReloadApi.summary()]);
      setJobs(nextJobs); setSummary(nextSummary); setError(null);
    } catch { setError("Não foi possível carregar o estado das recargas."); }
  };
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 10000); return () => window.clearInterval(timer); }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setMessage(null);
    if (!start || !end) { setError("Informe o período em UTC."); return; }
    if (scope === "all" && !window.confirm("A recarga de todas as tags ativas pode gerar muitas requisições. Confirmar?")) return;
    const payload: HistoricalReloadRequest = { start_time: isoFromInput(start), end_time: isoFromInput(end), mode, interval: mode === "interpolated" ? interval : undefined, all_active: scope === "all" };
    if (scope === "tag") payload.tag_id = Number(scopeId);
    if (scope === "variable") payload.variable_id = Number(scopeId);
    try { const created = await historicalReloadApi.create(payload); setMessage(`${created.length} job(s) enfileirado(s).`); await load(); }
    catch { setError("Recarga rejeitada. Verifique o período UTC, a seleção e o limite de um ano."); }
  };

  const cancel = async (job: HistoricalReloadJob) => {
    if (!window.confirm(`Cancelar o job #${job.id}?`)) return;
    try { await historicalReloadApi.cancel(job.id); await load(); } catch { setError("Não foi possível cancelar o job."); }
  };

  return <>
    <Card className="piad-card mb-3"><Card.Header>Recarga histórica TimescaleDB</Card.Header><Card.Body>
      <Alert variant="info">As datas são convertidas para UTC. O período máximo é de um ano civil; a recarga não altera o banco original.</Alert>
      {error ? <Alert variant="danger">{error}</Alert> : null}{message ? <Alert variant="success">{message}</Alert> : null}
      <Form onSubmit={submit} className="row g-2">
        <Form.Group className="col-md-3"><Form.Label>Escopo</Form.Label><Form.Select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}><option value="tag">Tag</option><option value="variable">Variável CEP</option><option value="all">Todas as tags ativas</option></Form.Select></Form.Group>
        {scope !== "all" ? <Form.Group className="col-md-3"><Form.Label>ID</Form.Label><Form.Control type="number" min={1} value={scopeId} onChange={(e) => setScopeId(e.target.value)} required /></Form.Group> : null}
        <Form.Group className="col-md-3"><Form.Label>Início (UTC)</Form.Label><Form.Control type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Fim (UTC)</Form.Label><Form.Control type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required /></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Modo</Form.Label><Form.Select value={mode} onChange={(e) => setMode(e.target.value as HistoricalReloadMode)}><option value="recorded">Recorded</option><option value="interpolated">Interpolated</option></Form.Select></Form.Group>
        {mode === "interpolated" ? <Form.Group className="col-md-3"><Form.Label>Resolução</Form.Label><Form.Control value={interval} onChange={(e) => setInterval(e.target.value)} pattern="\d+[smhd]" required /></Form.Group> : null}
        <div className="col-12"><Button type="submit">Enfileirar recarga</Button></div>
      </Form>
    </Card.Body></Card>
    {summary ? <Card className="piad-card mb-3"><Card.Body><strong>Resumo:</strong> {summary.total_active_tags} ativas, {summary.tags_with_data} com cobertura, {summary.tags_without_data} sem dados, {summary.partial_tags} parciais.</Card.Body></Card> : null}
    <Card className="piad-card"><Card.Header>Jobs recentes</Card.Header><Card.Body><Table responsive size="sm"><thead><tr><th>ID</th><th>Tag</th><th>Modo</th><th>Período</th><th>Status</th><th>Progresso</th><th /></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td>{job.id}</td><td>{job.tag_id}</td><td>{job.mode}{job.interval ? ` ${job.interval}` : ""}</td><td>{new Date(job.target_start).toLocaleString()} – {new Date(job.target_end).toLocaleString()}</td><td>{job.status}</td><td>{job.progress_percent.toFixed(1)}%</td><td>{["PENDING", "RUNNING"].includes(job.status) ? <Button size="sm" variant="outline-danger" onClick={() => void cancel(job)}>Cancelar</Button> : null}</td></tr>)}</tbody></Table></Card.Body></Card>
  </>;
}
