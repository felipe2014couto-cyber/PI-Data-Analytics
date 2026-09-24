import { FormEvent, useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, ButtonGroup, Card, Form, ProgressBar, Table } from "react-bootstrap";
import { useSearchParams } from "react-router-dom";

import { equipmentsApi, historicalReloadApi, piTagsApi, sectionsApi } from "../api";
import { SipReloadPanel } from "./SipReloadPanel";
import type { HistoricalReloadJob, HistoricalReloadRequest, HistoricalReloadSummary, PiTag, Section } from "../types";

type SortField = "id" | "equipment" | "tag" | "progress" | "mode" | "period" | "status";
type SortDirection = "asc" | "desc";
type ReloadScope = "equipment" | "section" | "tag";

type HistoricalReloadGroup = {
  jobs: HistoricalReloadJob[];
  representative: HistoricalReloadJob;
  cancellableJobs: HistoricalReloadJob[];
  start: string;
  end: string;
  status: string;
  progressPercent: number;
  isActivelyProcessing?: boolean;
};

function groupReloadJobs(jobs: HistoricalReloadJob[]): HistoricalReloadGroup[] {
  const runningJobs = jobs.filter((job) => job.status === "RUNNING");
  let activeJobId: number | null = null;
  if (runningJobs.length > 0) {
    const sorted = [...runningJobs].sort((a, b) => {
      const timeA = new Date(a.heartbeat_at || a.updated_at).getTime();
      const timeB = new Date(b.heartbeat_at || b.updated_at).getTime();
      return timeB - timeA;
    });
    activeJobId = sorted[0].id;
  }

  const groups: HistoricalReloadGroup[] = [];
  const ordered = [...jobs].sort((left, right) => left.id - right.id);
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
      progressPercent: job.status === "COMPLETED" ? 100 : (job.progress_percent ?? 0),
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
    group.isActivelyProcessing = group.status === "RUNNING" && group.jobs.some((job) => job.id === activeJobId);
    group.progressPercent = group.status === "COMPLETED"
      ? 100
      : Math.min(100, Math.max(0, group.jobs.reduce((total, job) => total + (job.status === "COMPLETED" ? 100 : (job.progress_percent || 0)), 0) / group.jobs.length));
  }
  return groups.sort((a, b) => b.representative.id - a.representative.id);
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
  const [reloadScope, setReloadScope] = useState<ReloadScope>("tag");
  const [server, setServer] = useState<"PIMS" | "SIP">("PIMS");
  const [equipmentId, setEquipmentId] = useState("");
  const [sectionId, setSectionId] = useState("");
  const [tagId, setTagId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [tags, setTags] = useState<PiTag[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [equipmentNames, setEquipmentNames] = useState<Record<number, string>>({});
  const [tagsLoading, setTagsLoading] = useState(false);
  const [jobs, setJobs] = useState<HistoricalReloadJob[]>([]);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<number>>(new Set());
  const [currentReloadJobIds, setCurrentReloadJobIds] = useState<Set<number>>(new Set());
  const [summary, setSummary] = useState<HistoricalReloadSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>("id");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

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
      sectionsApi.list({ page: 1, page_size: 200 }),
    ])
      .then(([tagResponse, equipmentResponse, sectionResponse]) => {
        setTags(tagResponse.items ?? []);
        setEquipmentNames(Object.fromEntries((equipmentResponse.items ?? []).map((equipment) => [equipment.id, equipment.name || equipment.code])));
        setSections(sectionResponse.items ?? []);
      })
      .catch(() => setError("Não foi possível carregar as tags e zonas ativas."))
      .finally(() => setTagsLoading(false));
  }, []);

  useEffect(() => {
    const tagIds = searchParams.get("tag_ids");
    if (tagIds) {
      setReloadScope("tag");
      setTagId(tagIds.split(",")[0].trim());
    }
    setStart(inputFromIso(searchParams.get("start_time")));
    setEnd(inputFromIso(searchParams.get("end_time")));
  }, [searchParams]);

  useEffect(() => {
    if (!tagId || !tags.length) return;
    const selected = tags.find((tag) => tag.id === Number(tagId));
    if (selected) {
      setEquipmentId(String(selected.equipment_id));
      if (selected.section_id) {
        setSectionId(String(selected.section_id));
      }
    }
  }, [tagId, tags]);

  const filteredSections = useMemo(() => {
    return sections.filter((sec) => !equipmentId || sec.equipment_id === Number(equipmentId));
  }, [sections, equipmentId]);

  const filteredTags = useMemo(() => {
    return tags.filter((tag) => !equipmentId || tag.equipment_id === Number(equipmentId));
  }, [tags, equipmentId]);
  const jobGroups = groupReloadJobs(jobs);

  const sortedJobGroups = useMemo(() => {
    return [...jobGroups].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "equipment": {
          const tagA = tags.find((t) => t.id === a.representative.tag_id);
          const tagB = tags.find((t) => t.id === b.representative.tag_id);
          const eqA = tagA ? (equipmentNames[tagA.equipment_id] ?? `#${tagA.equipment_id}`) : "";
          const eqB = tagB ? (equipmentNames[tagB.equipment_id] ?? `#${tagB.equipment_id}`) : "";
          cmp = eqA.localeCompare(eqB, "pt-BR", { sensitivity: "base", numeric: true });
          break;
        }
        case "tag": {
          const tagA = tags.find((t) => t.id === a.representative.tag_id);
          const tagB = tags.find((t) => t.id === b.representative.tag_id);
          const nameA = tagA ? `${tagA.display_name} (${tagA.pi_tag_name})` : String(a.representative.tag_id);
          const nameB = tagB ? `${tagB.display_name} (${tagB.pi_tag_name})` : String(b.representative.tag_id);
          cmp = nameA.localeCompare(nameB, "pt-BR", { sensitivity: "base", numeric: true });
          break;
        }
        case "progress": {
          cmp = a.progressPercent - b.progressPercent;
          break;
        }
        case "mode": {
          const modeA = `${a.representative.mode}${a.representative.interval ? " " + a.representative.interval : ""}`;
          const modeB = `${b.representative.mode}${b.representative.interval ? " " + b.representative.interval : ""}`;
          cmp = modeA.localeCompare(modeB, "pt-BR", { sensitivity: "base" });
          break;
        }
        case "period": {
          cmp = new Date(a.start).getTime() - new Date(b.start).getTime();
          break;
        }
        case "status": {
          const getStatusRank = (group: HistoricalReloadGroup): number => {
            if (group.isActivelyProcessing) return 0;
            if (group.status === "RUNNING") return 1;
            if (group.status === "PENDING") return 2;
            if (group.status === "COMPLETED") return 3;
            if (group.status === "FAILED") return 4;
            if (group.status === "CANCELLED") return 5;
            return 6;
          };
          cmp = getStatusRank(a) - getStatusRank(b);
          break;
        }
        case "id":
        default: {
          cmp = a.representative.id - b.representative.id;
          break;
        }
      }

      if (cmp !== 0) {
        return sortDirection === "asc" ? cmp : -cmp;
      }

      // Tiebreaker: always order by id descending to guarantee stable rows
      return b.representative.id - a.representative.id;
    });
  }, [jobGroups, sortField, sortDirection, tags, equipmentNames]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      if (["id", "progress", "period"].includes(field)) {
        setSortDirection("desc");
      } else {
        setSortDirection("asc");
      }
    }
  };

  const renderSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <i className="bi bi-arrow-down-up text-muted ms-1" style={{ fontSize: "0.75rem", opacity: 0.35 }} />;
    }
    return sortDirection === "asc" ? (
      <i className="bi bi-arrow-up text-primary ms-1" style={{ fontSize: "0.8rem" }} />
    ) : (
      <i className="bi bi-arrow-down text-primary ms-1" style={{ fontSize: "0.8rem" }} />
    );
  };

  const activeJobs = jobs.filter((job) => ["PENDING", "RUNNING"].includes(job.status));
  const activeGroups = jobGroups.filter((group) => group.cancellableJobs.length > 0);
  const activelyProcessingGroup = jobGroups.find((group) => group.isActivelyProcessing);
  const activeTag = activelyProcessingGroup ? tags.find((item) => item.id === activelyProcessingGroup.representative.tag_id) : null;
  const allSelected = activeGroups.length > 0 && activeGroups.every((group) => group.cancellableJobs.every((job) => selectedJobIds.has(job.id)));
  const selectedGroupCount = activeGroups.filter((group) => group.cancellableJobs.some((job) => selectedJobIds.has(job.id))).length;
  const progressJobs = currentReloadJobIds.size
    ? jobs.filter((job) => currentReloadJobIds.has(job.id))
    : activeJobs;
  const progressPercent = progressJobs.length
    ? Math.min(100, Math.max(0, progressJobs.reduce((total, job) => total + (job.status === "COMPLETED" ? 100 : (job.progress_percent || 0)), 0) / progressJobs.length))
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
    event.preventDefault();
    setError(null);
    setMessage(null);
    if (!start || !end) {
      setError("Informe o período em UTC.");
      return;
    }
    const nowMs = Date.now() + 60000;
    if (new Date(start).getTime() > nowMs) {
      setError("A data de início não pode ser no futuro.");
      return;
    }
    if (new Date(end).getTime() > nowMs) {
      setError("A data de término não pode ser no futuro.");
      return;
    }
    if (new Date(start).getTime() >= new Date(end).getTime()) {
      setError("A data inicial deve ser anterior à data final.");
      return;
    }
    if (!equipmentId) {
      setError("Selecione um equipamento.");
      return;
    }
    if (reloadScope === "section" && !sectionId) {
      setError("Selecione uma zona / seção.");
      return;
    }
    if (reloadScope === "tag" && !tagId) {
      setError("Selecione uma tag.");
      return;
    }

    const eqName = equipmentNames[Number(equipmentId)] || `#${equipmentId}`;
    let confirmPrompt = "";
    if (reloadScope === "equipment") {
      const count = tags.filter((t) => t.equipment_id === Number(equipmentId)).length;
      confirmPrompt = `Confirmar a criação da recarga histórica para TODAS as ${count} tags do equipamento "${eqName}"?`;
    } else if (reloadScope === "section") {
      const sec = sections.find((s) => s.id === Number(sectionId));
      const secName = sec ? (sec.name || sec.code) : `#${sectionId}`;
      const count = tags.filter((t) => t.section_id === Number(sectionId) && t.equipment_id === Number(equipmentId)).length;
      confirmPrompt = `Confirmar a criação da recarga histórica para as ${count} tags da zona/seção "${secName}" (${eqName})?`;
    } else {
      const tg = tags.find((t) => t.id === Number(tagId));
      const tgName = tg ? `${tg.display_name} (${tg.pi_tag_name})` : `#${tagId}`;
      confirmPrompt = `Confirmar a criação da recarga histórica para a tag "${tgName}"?`;
    }

    if (!window.confirm(confirmPrompt)) return;

    const payload: HistoricalReloadRequest = {
      start_time: isoFromInput(start),
      end_time: isoFromInput(end),
      mode: "recorded",
      all_active: false,
      ...(reloadScope === "equipment" ? { equipment_id: Number(equipmentId) } : {}),
      ...(reloadScope === "section" ? { section_id: Number(sectionId) } : {}),
      ...(reloadScope === "tag" ? { tag_id: Number(tagId) } : {}),
    };

    try {
      const created = await historicalReloadApi.create(payload);
      setCurrentReloadJobIds(new Set(created.map((job) => job.id)));
      setMessage(`Recarga iniciada com sucesso (${created.length} tag(s) configurada(s)).`);
      await load();
    } catch {
      setError("Recarga rejeitada. Verifique o período UTC, a seleção e o limite de um ano.");
    }
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
    <div className="mb-3"><Form.Label className="me-2">Servidor</Form.Label><ButtonGroup size="sm"><Button variant={server === "PIMS" ? "primary" : "outline-primary"} onClick={() => setServer("PIMS")}>PIMS</Button><Button variant={server === "SIP" ? "primary" : "outline-primary"} onClick={() => setServer("SIP")}>SIP</Button></ButtonGroup></div>
    {server === "SIP" ? <SipReloadPanel /> : <>
    <Card className="piad-card mb-3"><Card.Header>Recarga histórica TimescaleDB</Card.Header><Card.Body>
      <Alert variant="info">As datas são convertidas para UTC. O período máximo é de um ano civil; a recarga não altera o banco original.</Alert>
      {error ? <Alert variant="danger">{error}</Alert> : null}{message ? <Alert variant="success">{message}</Alert> : null}
      <Form onSubmit={submit} className="row g-2">
        <div className="col-12 mb-1">
          <Form.Label className="d-block fw-semibold mb-1">Escopo da Recarga</Form.Label>
          <ButtonGroup size="sm">
            <Button
              type="button"
              variant={reloadScope === "tag" ? "primary" : "outline-primary"}
              onClick={() => setReloadScope("tag")}
            >
              <i className="bi bi-tag me-1" />
              Por Tag Específica
            </Button>
            <Button
              type="button"
              variant={reloadScope === "section" ? "primary" : "outline-primary"}
              onClick={() => setReloadScope("section")}
            >
              <i className="bi bi-diagram-3 me-1" />
              Por Zona / Seção
            </Button>
            <Button
              type="button"
              variant={reloadScope === "equipment" ? "primary" : "outline-primary"}
              onClick={() => setReloadScope("equipment")}
            >
              <i className="bi bi-cpu me-1" />
              Por Equipamento (Todas as Tags)
            </Button>
          </ButtonGroup>
        </div>

        <Form.Group controlId="reload-equipment" className={reloadScope === "section" ? "col-md-3" : reloadScope === "tag" ? "col-md-3" : "col-md-4"}>
          <Form.Label>Equipamento</Form.Label>
          <Form.Select
            value={equipmentId}
            onChange={(e) => {
              setEquipmentId(e.target.value);
              setSectionId("");
              setTagId("");
            }}
            required
            disabled={tagsLoading}
          >
            <option value="">{tagsLoading ? "Carregando equipamentos..." : "Selecione um equipamento"}</option>
            {Object.entries(equipmentNames)
              .sort(([, left], [, right]) => left.localeCompare(right))
              .map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
          </Form.Select>
          {reloadScope === "equipment" && equipmentId && (
            <Form.Text className="text-muted d-block mt-1">
              {tags.filter((t) => t.equipment_id === Number(equipmentId)).length} tag(s) ativas neste equipamento.
            </Form.Text>
          )}
        </Form.Group>

        {reloadScope === "section" && (
          <Form.Group controlId="reload-section" className="col-md-3">
            <Form.Label>Zona / Seção</Form.Label>
            <Form.Select
              value={sectionId}
              onChange={(e) => {
                setSectionId(e.target.value);
                setTagId("");
              }}
              required
              disabled={tagsLoading || !equipmentId}
            >
              <option value="">
                {!equipmentId ? "Selecione primeiro o equipamento" : "Selecione uma seção/zona"}
              </option>
              {filteredSections.map((sec) => (
                <option key={sec.id} value={sec.id}>
                  {sec.name} ({sec.code})
                </option>
              ))}
            </Form.Select>
            {sectionId && (
              <Form.Text className="text-muted d-block mt-1">
                {tags.filter((t) => t.section_id === Number(sectionId) && t.equipment_id === Number(equipmentId)).length} tag(s) ativas nesta seção.
              </Form.Text>
            )}
          </Form.Group>
        )}

        {reloadScope === "tag" && (
          <Form.Group controlId="reload-tag" className="col-md-3">
            <Form.Label>Tag</Form.Label>
            <Form.Select
              value={tagId}
              onChange={(e) => setTagId(e.target.value)}
              required
              disabled={tagsLoading || !equipmentId}
            >
              <option value="">
                {!equipmentId ? "Selecione primeiro o equipamento" : tagsLoading ? "Carregando tags..." : "Selecione uma tag"}
              </option>
              {filteredTags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.display_name} · {tag.pi_tag_name} (#{tag.id})
                </option>
              ))}
            </Form.Select>
          </Form.Group>
        )}

        <Form.Group controlId="reload-start" className="col-md-3">
          <Form.Label>Início (UTC)</Form.Label>
          <Form.Control
            type="datetime-local"
            value={start}
            max={new Date().toISOString().slice(0, 16)}
            onChange={(e) => setStart(e.target.value)}
            required
          />
        </Form.Group>

        <Form.Group controlId="reload-end" className="col-md-3">
          <Form.Label>Fim (UTC)</Form.Label>
          <Form.Control
            type="datetime-local"
            value={end}
            max={new Date().toISOString().slice(0, 16)}
            onChange={(e) => setEnd(e.target.value)}
            required
          />
        </Form.Group>

        <Form.Group controlId="reload-mode" className={reloadScope === "equipment" ? "col-md-2" : "col-md-3"}>
          <Form.Label>Modo</Form.Label>
          <Form.Control value="Recorded bruto (fonte dos agregados)" readOnly />
        </Form.Group>

        <div className="col-12 mt-2">
          <Button type="submit">
            Recarregar período
          </Button>
        </div>
      </Form>
    </Card.Body></Card>
    {summary ? <Card className="piad-card mb-3"><Card.Body><strong>Resumo:</strong> {summary.total_active_tags} ativas, {summary.tags_with_data} com cobertura, {summary.tags_without_data} sem dados, {summary.partial_tags} parciais.</Card.Body></Card> : null}
    <Card className="piad-card"><Card.Header className="d-flex justify-content-between align-items-center flex-wrap gap-2">
      <div className="d-flex align-items-center gap-3 flex-wrap">
        <span className="fw-semibold">Recargas recentes</span>
        <div className="d-flex align-items-center gap-1">
          <Form.Label htmlFor="sort-select" className="mb-0 text-muted small text-nowrap">
            <i className="bi bi-sort-down me-1" />
            Ordenar por:
          </Form.Label>
          <Form.Select
            id="sort-select"
            size="sm"
            value={`${sortField}_${sortDirection}`}
            onChange={(e) => {
              const [field, direction] = e.target.value.split("_") as [SortField, SortDirection];
              setSortField(field);
              setSortDirection(direction);
            }}
            style={{ width: "auto", minWidth: "210px", fontSize: "0.85rem" }}
            aria-label="Ordenar recargas"
          >
            <option value="id_desc">Recarga (# mais recente)</option>
            <option value="id_asc">Recarga (# mais antiga)</option>
            <option value="equipment_asc">Equipamento (A – Z)</option>
            <option value="equipment_desc">Equipamento (Z – A)</option>
            <option value="tag_asc">Tag (A – Z alfabética)</option>
            <option value="tag_desc">Tag (Z – A alfabética)</option>
            <option value="progress_desc">Progresso (Maior primeiro)</option>
            <option value="progress_asc">Progresso (Menor primeiro)</option>
            <option value="mode_asc">Modo (A – Z)</option>
            <option value="mode_desc">Modo (Z – A)</option>
            <option value="period_desc">Período (Mais recente)</option>
            <option value="period_asc">Período (Mais antigo)</option>
            <option value="status_asc">Status (Ativos primeiro)</option>
            <option value="status_desc">Status (Finalizados primeiro)</option>
          </Form.Select>
        </div>
      </div>
      <div className="d-flex gap-2 flex-wrap justify-content-end">
        <Button size="sm" variant="outline-secondary" onClick={toggleSelectAll} disabled={!activeGroups.length}>{allSelected ? "Desmarcar todos" : "Selecionar todos"}</Button>
        <Button size="sm" variant="outline-danger" onClick={() => void cancelSelected()} disabled={!selectedJobIds.size}>Cancelar selecionados ({selectedGroupCount})</Button>
        <Button size="sm" variant="outline-secondary" onClick={() => void clearTerminal()}>Limpar concluídos/cancelados</Button>
      </div>
    </Card.Header><Card.Body>
      {progressJobs.length ? (
        <div className="border rounded px-3 py-2 mb-3 bg-light" data-testid="reload-progress-line">
          <div className="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-2">
            <div>
              <span>Progresso da recarga: </span>
              <strong>{progressPercent.toFixed(1)}% concluída</strong>
              {activelyProcessingGroup && (
                <span className="ms-2 text-primary fw-semibold small">
                  <span className="spinner-grow spinner-grow-sm text-primary me-1" role="status" aria-hidden="true" style={{ width: "0.55rem", height: "0.55rem" }} />
                  Processando agora: {activeTag ? `${activeTag.display_name} (${activeTag.pi_tag_name})` : `#${activelyProcessingGroup.representative.id}`}
                </span>
              )}
            </div>
            {activeGroups.length > 1 && (
              <span className="text-muted small">
                {activeGroups.length} recargas no lote (execução sequencial)
              </span>
            )}
          </div>
          <ProgressBar
            now={progressPercent}
            variant={progressPercent >= 100 ? "success" : "primary"}
            animated={progressPercent > 0 && progressPercent < 100}
            style={{ height: "6px" }}
          />
        </div>
      ) : (
        <div className="text-muted mb-3">Nenhuma recarga ativa.</div>
      )}
      <Table responsive size="sm" className="align-middle">
        <thead>
          <tr>
            <th><Form.Check type="checkbox" checked={allSelected} onChange={toggleSelectAll} disabled={!activeGroups.length} aria-label="Selecionar todas as recargas canceláveis" /></th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("id")} title="Clique para ordenar por Recarga">Recarga {renderSortIcon("id")}</th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("equipment")} title="Clique para ordenar por Equipamento">Equipamento {renderSortIcon("equipment")}</th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("tag")} title="Clique para ordenar por Tag (ordem alfabética)">Tag {renderSortIcon("tag")}</th>
            <th role="button" style={{ minWidth: "150px", cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("progress")} title="Clique para ordenar por Progresso">Progresso {renderSortIcon("progress")}</th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("mode")} title="Clique para ordenar por Modo">Modo {renderSortIcon("mode")}</th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("period")} title="Clique para ordenar por Período">Período {renderSortIcon("period")}</th>
            <th role="button" style={{ cursor: "pointer", userSelect: "none" }} onClick={() => handleSort("status")} title="Clique para ordenar por Status">Status {renderSortIcon("status")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sortedJobGroups.map((group) => {
            const job = group.representative;
            const tag = tags.find((item) => item.id === job.tag_id);
            const cancellable = group.cancellableJobs.length > 0;
            const percent = Math.max(0, Math.min(100, group.progressPercent));
            const isActivelyProcessing = Boolean(group.isActivelyProcessing);
            const isCompleted = group.status === "COMPLETED";
            const isQueued = group.status === "RUNNING" && !isActivelyProcessing;
            const isPending = group.status === "PENDING";
            const isFailed = group.status === "FAILED";
            const isCancelled = group.status === "CANCELLED";
            const variant = isCompleted
              ? "success"
              : isActivelyProcessing
                ? "primary"
                : isFailed
                  ? "danger"
                  : isCancelled
                    ? "secondary"
                    : isQueued
                      ? "info"
                      : "secondary";

            return (
              <tr
                key={job.id}
                className={isActivelyProcessing ? "table-primary" : undefined}
              >
                <td>{cancellable ? <Form.Check type="checkbox" checked={group.cancellableJobs.every((item) => selectedJobIds.has(item.id))} onChange={() => toggleGroupSelection(group)} aria-label={`Selecionar recarga ${job.id}`} /> : null}</td>
                <td>#{job.id}</td>
                <td>
                  {tag ? (equipmentNames[tag.equipment_id] ?? `#${tag.equipment_id}`) : "—"}
                  {tag?.section_id ? (
                    <div className="text-muted" style={{ fontSize: "0.75rem" }}>
                      {sections.find((s) => s.id === tag.section_id)?.name || ""}
                    </div>
                  ) : null}
                </td>
                <td>{tag ? `${tag.display_name} (${tag.pi_tag_name})` : job.tag_id}</td>
                <td>
                  <div className="d-flex align-items-center gap-2" style={{ minWidth: "130px" }}>
                    <ProgressBar
                      now={percent}
                      variant={variant}
                      animated={isActivelyProcessing}
                      striped={isActivelyProcessing}
                      className="flex-grow-1 mb-0"
                      style={{ height: "10px", borderRadius: "5px" }}
                      aria-label={`Progresso: ${percent.toFixed(1)}%`}
                    />
                    <span
                      className={`small font-monospace ${isCompleted ? "fw-bold text-success" : isActivelyProcessing ? "fw-bold text-primary" : "text-muted"}`}
                      style={{ minWidth: "44px", textAlign: "right", fontSize: "0.8rem" }}
                    >
                      {percent.toFixed(1)}%
                    </span>
                  </div>
                </td>
                <td>{job.mode}{job.interval ? ` ${job.interval}` : ""}</td>
                <td>{new Date(group.start).toLocaleString()} – {new Date(group.end).toLocaleString()}</td>
                <td>
                  {isCompleted ? (
                    <Badge bg="success">Concluído</Badge>
                  ) : isActivelyProcessing ? (
                    <Badge bg="primary" className="d-inline-flex align-items-center gap-1">
                      <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" style={{ width: "0.55rem", height: "0.55rem" }} />
                      Executando agora
                    </Badge>
                  ) : isQueued ? (
                    <Badge bg="info" text="dark">Na fila</Badge>
                  ) : isPending ? (
                    <Badge bg="warning" text="dark">Pendente</Badge>
                  ) : isFailed ? (
                    <Badge bg="danger">Falhou</Badge>
                  ) : isCancelled ? (
                    <Badge bg="secondary">Cancelado</Badge>
                  ) : (
                    <Badge bg="secondary">{group.status}</Badge>
                  )}
                </td>
                <td>{cancellable ? <Button size="sm" variant="outline-danger" onClick={() => void cancelGroup(group)}>Cancelar</Button> : null}</td>
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Card.Body></Card>
    </>}
  </>;
}
