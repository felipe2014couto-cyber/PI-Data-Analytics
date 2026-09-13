import { FormEvent, useEffect, useState } from "react";
import { Alert, Button, Card, Form, Table } from "react-bootstrap";
import { useSearchParams } from "react-router-dom";

import { equipmentsApi, historicalReloadApi, piTagsApi } from "../api";
import type { HistoricalReloadJob, HistoricalReloadRequest, HistoricalReloadSummary, PiTag } from "../types";

type HistoricalReloadGroup = {
  jobs: HistoricalReloadJob[];
  representative: HistoricalReloadJob;
  cancellableJobs: HistoricalReloadJob[];
  start: string;
  end: string;
  status: string;
  progressPercent: number;
};

function groupReloadJobs(jobs: HistoricalReloadJob[]): HistoricalReloadGroup[] {
  const groups: HistoricalReloadGroup[] = [];
  const ordered = [...jobs].sort((left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime());
  for (const job of ordered) {
    const createdAt = new Date(job.created_at).getTime();
    const group = groups.find((candidate) => {
      const latest = candidate.jobs[candidate.jobs.length - 1];
      return latest
        && latest.tag_id === job.tag_id
        && latest.mode === job.mode
        && latest.interval === job.interval
        && Math.abs(createdAt - new Date(latest.created_at).getTime()) <= 2_000;
    });
    if (group) {
      group.jobs.push(job);
      group.start = new Date(group.start).getTime() <= new Date(job.target_start).getTime() ? group.start : job.target_start;
      group.end = new Date(group.end).getTime() >= new Date(job.target_end).getTime() ? group.end : job.target_end;
      continue;
    }
    groups.push({
      jobs: [job],
      representative: job,
      cancellableJobs: [],
      start: job.target_start,
      end: job.target_end,
      status: job.status,
      progressPercent: job.progress_percent,
    });
  }
  for (const group of groups) {
    group.cancellableJobs = group.jobs.filter((job) => ["PENDING", "RUNNING"].includes(job.status));
    group.status = group.jobs.some((job) => job.status === "RUNNING")
      ? "RUNNING"
      : group.jobs.some((job) => job.status === "PENDING")
        ? "PENDING"
        : group.jobs.every((job) => job.status === "COMPLETED")
          ? "COMPLETED"
          : group.jobs[0].status;
    group.progressPercent = group.jobs.reduce((total, job) => total + job.progress_percent, 0) / group.jobs.length;
  }
  return groups.reverse();
}

function isoFromInput(value: string): string {
  return new Date(value).toISOString();
}

function inputFromIso(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 16);
}

export function HistoricalReloadPage() {
  const [searchParams] = useSearchParams();
  const [equipmentId, setEquipmentId] = useState("");
  const [tagId, setTagId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [tags, setTags] = useState<PiTag[]>([]);
  const [equipmentNames, setEquipmentNames] = useState<Record<number, string>>({});
  const [tagsLoading, setTagsLoading] = useState(false);
  const [jobs, setJobs] = useState<HistoricalReloadJob[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<number>>(new Set());
  const [currentReloadJobIds, setCurrentReloadJobIds] = useState<Set<number>>(new Set());
  const [summary, setSummary] = useState<HistoricalReloadSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    try {
      const [nextJobs, nextSummary] = await Promise.all([historicalReloadApi.list(), historicalReloadApi.summary()]);
      setJobs(nextJobs); setSummary(nextSummary); setError(null);
      setSelectedJobIds((previous) => new Set([...previous].filter((id) => nextJobs.some((job) => job.id === id && ["PENDING", "RUNNING"].includes(job.status)))));
    } catch { setError("Não foi possível carregar o estado das recargas."); }
  };
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 10000); return () => window.clearInterval(timer); }, []);

  useEffect(() => {
    setTagsLoading(true);
    void Promise.all([
      piTagsApi.list({ active: true, include_dependencies: true, page: 1, page_size: 200 }),
      equipmentsApi.list({ active: true, page: 1, page_size: 200 }),
    ])
      .then(([tagResponse, equipmentResponse]) => {
        setTags(tagResponse.items ?? []);
        setEquipmentNames(Object.fromEntries((equipmentResponse.items ?? []).map((equipment) => [equipment.id, equipment.name || equipment.code])));
      })
      .catch(() => setError("Não foi possível carregar as tags ativas."))
      .finally(() => setTagsLoading(false));
  }, []);

  useEffect(() => {
    const tagIds = searchParams.get("tag_ids");
    if (tagIds) setTagId(tagIds.split(",")[0].trim());
    setStart(inputFromIso(searchParams.get("start_time")));
    setEnd(inputFromIso(searchParams.get("end_time")));
  }, [searchParams]);

  useEffect(() => {
    if (!tagId || !tags.length) return;
    const selected = tags.find((tag) => tag.id === Number(tagId));
    if (selected) setEquipmentId(String(selected.equipment_id));
  }, [tagId, tags]);

  const filteredTags = tags.filter((tag) => !equipmentId || tag.equipment_id === Number(equipmentId));
  const jobGroups = groupReloadJobs(jobs);
  const activeJobs = jobs.filter((job) => ["PENDING", "RUNNING"].includes(job.status));
  const activeGroups = jobGroups.filter((group) => group.cancellableJobs.length > 0);
  const allSelected = activeGroups.length > 0 && activeGroups.every((group) => group.cancellableJobs.every((job) => selectedJobIds.has(job.id)));
  const selectedGroupCount = activeGroups.filter((group) => group.cancellableJobs.some((job) => selectedJobIds.has(job.id))).length;
  const progressJobs = currentReloadJobIds.size
    ? jobs.filter((job) => currentReloadJobIds.has(job.id))
    : activeJobs;
  const progressPercent = progressJobs.length
    ? progressJobs.reduce((total, job) => total + job.progress_percent, 0) / progressJobs.length
    : 0;

  const toggleGroupSelection = (group: HistoricalReloadGroup) => {
    setSelectedJobIds((previous) => {
      const next = new Set(previous);
      const selected = group.cancellableJobs.every((job) => next.has(job.id));
      group.cancellableJobs.forEach((job) => {
        if (selected) next.delete(job.id); else next.add(job.id);
      });
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedJobIds(allSelected ? new Set() : new Set(activeGroups.flatMap((group) => group.cancellableJobs.map((job) => job.id))));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setMessage(null);
    if (!start || !end) { setError("Informe o período em UTC."); return; }
    if (!equipmentId) { setError("Selecione um equipamento."); return; }
    if (!tagId) { setError("Selecione uma tag."); return; }
    if (!window.confirm("Confirmar a criação da recarga histórica?")) return;
    const payload: HistoricalReloadRequest = { start_time: isoFromInput(start), end_time: isoFromInput(end), mode: "recorded", tag_id: Number(tagId), all_active: false };
    try {
      const created = await historicalReloadApi.create(payload);
      setCurrentReloadJobIds(new Set(created.map((job) => job.id)));
      setMessage("Recarga iniciada.");
      await load();
    }
    catch { setError("Recarga rejeitada. Verifique o período UTC, a seleção e o limite de um ano."); }
  };

  const cancelGroup = async (group: HistoricalReloadGroup) => {
    const ids = group.cancellableJobs.map((job) => job.id);
    if (!ids.length) return;
    if (!window.confirm("Cancelar esta recarga?")) return;
    try {
      await historicalReloadApi.cancelBatch(ids);
      setSelectedJobIds((previous) => new Set([...previous].filter((id) => !ids.includes(id))));
      await load();
    } catch { setError("Não foi possível cancelar a recarga."); }
  };

  const cancelSelected = async () => {
    const ids = [...selectedJobIds];
    if (!ids.length) return;
    if (!window.confirm(`Cancelar ${ids.length} job(s) selecionado(s)?`)) return;
    setError(null); setMessage(null);
    try {
      const cancelled = await historicalReloadApi.cancelBatch(ids);
      const count = cancelled.filter((job) => job.status === "CANCELLED").length;
      setSelectedJobIds(new Set());
      setMessage(`${count} job(s) cancelado(s).`);
      await load();
    } catch { setError("Não foi possível cancelar os jobs selecionados."); }
  };

  const clearTerminal = async () => {
    if (!window.confirm("Remover todos os jobs COMPLETED e CANCELLED? Amostras e coverage não serão alterados.")) return;
    setError(null); setMessage(null);
    try {
      const result = await historicalReloadApi.clearTerminal();
      setMessage(`${result.deleted} job(s) concluído(s)/cancelado(s) removido(s).`);
      await load();
    } catch { setError("Não foi possível limpar os jobs finalizados."); }
  };

  return <>
    <Card className="piad-card mb-3"><Card.Header>Recarga histórica TimescaleDB</Card.Header><Card.Body>
      <Alert variant="info">As datas são convertidas para UTC. O período máximo é de um ano civil; a recarga não altera o banco original.</Alert>
      {error ? <Alert variant="danger">{error}</Alert> : null}{message ? <Alert variant="success">{message}</Alert> : null}
      <Form onSubmit={submit} className="row g-2">
        <Form.Group className="col-md-3"><Form.Label>Equipamento</Form.Label><Form.Select value={equipmentId} onChange={(e) => { setEquipmentId(e.target.value); setTagId(""); }} required disabled={tagsLoading}><option value="">{tagsLoading ? "Carregando equipamentos..." : "Selecione um equipamento"}</option>{Object.entries(equipmentNames).sort(([, left], [, right]) => left.localeCompare(right)).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</Form.Select></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Tag</Form.Label><Form.Select value={tagId} onChange={(e) => setTagId(e.target.value)} required disabled={tagsLoading || !equipmentId}><option value="">{!equipmentId ? "Selecione primeiro o equipamento" : tagsLoading ? "Carregando tags..." : "Selecione uma tag"}</option>{filteredTags.map((tag) => <option key={tag.id} value={tag.id}>{tag.display_name} · {tag.pi_tag_name} (#{tag.id})</option>)}</Form.Select></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Início (UTC)</Form.Label><Form.Control type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Fim (UTC)</Form.Label><Form.Control type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required /></Form.Group>
        <Form.Group className="col-md-3"><Form.Label>Modo</Form.Label><Form.Control value="Recorded bruto (fonte dos agregados)" readOnly /></Form.Group>
        <div className="col-12"><Button type="submit">Recarregar período</Button></div>
      </Form>
    </Card.Body></Card>
    {summary ? <Card className="piad-card mb-3"><Card.Body><strong>Resumo:</strong> {summary.total_active_tags} ativas, {summary.tags_with_data} com cobertura, {summary.tags_without_data} sem dados, {summary.partial_tags} parciais.</Card.Body></Card> : null}
    <Card className="piad-card"><Card.Header className="d-flex justify-content-between align-items-center flex-wrap gap-2"><span>Recargas recentes</span><div className="d-flex gap-2 flex-wrap justify-content-end"><Button size="sm" variant="outline-secondary" onClick={toggleSelectAll} disabled={!activeGroups.length}>{allSelected ? "Desmarcar todos" : "Selecionar todos"}</Button><Button size="sm" variant="outline-danger" onClick={() => void cancelSelected()} disabled={!selectedJobIds.size}>Cancelar selecionados ({selectedGroupCount})</Button><Button size="sm" variant="outline-secondary" onClick={() => void clearTerminal()}>Limpar concluídos/cancelados</Button></div></Card.Header><Card.Body>
      {progressJobs.length ? <div className="border rounded px-3 py-2 mb-3" data-testid="reload-progress-line">Progresso da recarga: <strong>{progressPercent.toFixed(1)}% concluída</strong></div> : <div className="text-muted mb-3">Nenhuma recarga ativa.</div>}
      <Table responsive size="sm"><thead><tr><th><Form.Check type="checkbox" checked={allSelected} onChange={toggleSelectAll} disabled={!activeGroups.length} aria-label="Selecionar todas as recargas canceláveis" /></th><th>Recarga</th><th>Equipamento</th><th>Tag</th><th>Modo</th><th>Período</th><th>Status</th><th /></tr></thead><tbody>{jobGroups.map((group) => { const job = group.representative; const tag = tags.find((item) => item.id === job.tag_id); const cancellable = group.cancellableJobs.length > 0; return <tr key={`${job.id}-${job.created_at}`}><td>{cancellable ? <Form.Check type="checkbox" checked={group.cancellableJobs.every((item) => selectedJobIds.has(item.id))} onChange={() => toggleGroupSelection(group)} aria-label={`Selecionar recarga ${job.id}`} /> : null}</td><td>#{job.id}</td><td>{tag ? (equipmentNames[tag.equipment_id] ?? `#${tag.equipment_id}`) : "—"}</td><td>{tag ? `${tag.display_name} (${tag.pi_tag_name})` : job.tag_id}</td><td>{job.mode}{job.interval ? ` ${job.interval}` : ""}</td><td>{new Date(group.start).toLocaleString()} – {new Date(group.end).toLocaleString()}</td><td>{group.status}</td><td>{cancellable ? <Button size="sm" variant="outline-danger" onClick={() => void cancelGroup(group)}>Cancelar</Button> : null}</td></tr>; })}</tbody></Table>
    </Card.Body></Card>
  </>;
}
