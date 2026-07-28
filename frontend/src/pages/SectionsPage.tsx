import { useEffect, useMemo, useState } from "react";
import { Modal, Form, Button, Table } from "react-bootstrap";

import { equipmentsApi, sectionsApi } from "../api";
import type { Equipment, Section, SectionCreate, SectionUpdate } from "../types";
import { ActiveBadge } from "../components/ActiveBadge";
import { ConfirmModal } from "../components/ConfirmModal";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { FeedbackAlert } from "../components/FeedbackAlert";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { formatDateTime } from "../utils/format";

const PAGE_SIZE = 10;

interface FormState {
  equipment_id: string;
  code: string;
  name: string;
  description: string;
  active: boolean;
}

const EMPTY_FORM: FormState = {
  equipment_id: "",
  code: "",
  name: "",
  description: "",
  active: true,
};

export function SectionsPage() {
  const [items, setItems] = useState<Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "true" | "false">("all");
  const [equipmentFilter, setEquipmentFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);

  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [loadingEquipments, setLoadingEquipments] = useState(false);

  const [showFormModal, setShowFormModal] = useState(false);
  const [editing, setEditing] = useState<Section | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string>("");

  const [confirmDelete, setConfirmDelete] = useState<Section | null>(null);
  const [deleting, setDeleting] = useState(false);

  const activeParam = useMemo<boolean | undefined>(() => {
    if (activeFilter === "all") return undefined;
    return activeFilter === "true";
  }, [activeFilter]);

  const equipmentParam = useMemo<number | undefined>(() => {
    if (!equipmentFilter) return undefined;
    const id = Number(equipmentFilter);
    return Number.isFinite(id) ? id : undefined;
  }, [equipmentFilter]);

  const loadEquipments = async () => {
    setLoadingEquipments(true);
    try {
      const response = await equipmentsApi.list({ page: 1, page_size: 200 });
      setEquipments(response.items ?? []);
    } catch (err) {
      setError(err);
    } finally {
      setLoadingEquipments(false);
    }
  };

  const loadList = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await sectionsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        equipment_id: equipmentParam,
        active: activeParam,
      });
      setItems(response.items ?? []);
      setTotal(response.total ?? 0);
      setPages(response.pages ?? 0);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadEquipments();
  }, []);

  useEffect(() => {
    void loadList();
  }, [page]);

  useEffect(() => {
    setPage(1);
  }, [search, activeFilter, equipmentFilter]);

  useEffect(() => {
    void loadList();
  }, [search, activeParam, equipmentParam]);

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM, equipment_id: equipmentFilter || "" });
    setFormError(null);
    setShowFormModal(true);
  };

  const openEdit = (item: Section) => {
    setEditing(item);
    setForm({
      equipment_id: String(item.equipment_id),
      code: item.code,
      name: item.name,
      description: item.description ?? "",
      active: item.active,
    });
    setFormError(null);
    setShowFormModal(true);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const equipmentId = Number(form.equipment_id);
      if (!Number.isFinite(equipmentId) || equipmentId <= 0) {
        throw new Error("Selecione um equipamento valido.");
      }
      if (editing) {
        const update: SectionUpdate = {
          equipment_id: equipmentId,
          code: form.code.trim(),
          name: form.name.trim(),
          description: form.description.trim() || null,
          active: form.active,
        };
        await sectionsApi.update(editing.id, update);
        setSuccessMessage("Secao atualizada com sucesso.");
      } else {
        const payload: SectionCreate = {
          equipment_id: equipmentId,
          code: form.code.trim(),
          name: form.name.trim(),
          description: form.description.trim() || null,
          active: form.active,
        };
        await sectionsApi.create(payload);
        setSuccessMessage("Secao criada com sucesso.");
      }
      setShowFormModal(false);
      setPage(1);
      await loadList();
    } catch (err) {
      setFormError(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await sectionsApi.remove(confirmDelete.id);
      setSuccessMessage("Secao excluida com sucesso.");
      setConfirmDelete(null);
      await loadList();
    } catch (err) {
      setError(err);
    } finally {
      setDeleting(false);
    }
  };

  const toggleActive = async (item: Section) => {
    try {
      await sectionsApi.update(item.id, { active: !item.active });
      setSuccessMessage(`Secao ${!item.active ? "ativada" : "desativada"} com sucesso.`);
      await loadList();
    } catch (err) {
      setError(err);
    }
  };

  const equipmentMap = useMemo(() => {
    const map = new Map<number, Equipment>();
    equipments.forEach((equipment) => map.set(equipment.id, equipment));
    return map;
  }, [equipments]);

  return (
    <div data-testid="sections-page">
      <PageHeader
        title="Secoes"
        subtitle="Secoes vinculadas aos equipamentos"
        actions={
          <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
            <i className="bi bi-plus-lg me-1" /> Nova secao
          </Button>
        }
      />
      <FeedbackAlert variant="success" message={successMessage} />

      <div className="piad-filter-bar">
        <div className="flex-grow-1">
          <label className="form-label" htmlFor="section-search">
            Buscar
          </label>
          <input
            id="section-search"
            className="form-control"
            placeholder="Buscar por codigo ou nome"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div style={{ minWidth: 200 }}>
          <label className="form-label" htmlFor="section-equipment">
            Equipamento
          </label>
          <select
            id="section-equipment"
            className="form-select"
            value={equipmentFilter}
            onChange={(event) => setEquipmentFilter(event.target.value)}
          >
            <option value="">Todos</option>
            {equipments.map((equipment) => (
              <option key={equipment.id} value={equipment.id}>
                {equipment.code} - {equipment.name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ minWidth: 160 }}>
          <label className="form-label" htmlFor="section-active">
            Status
          </label>
          <select
            id="section-active"
            className="form-select"
            value={activeFilter}
            onChange={(event) => setActiveFilter(event.target.value as "all" | "true" | "false")}
          >
            <option value="all">Todos</option>
            <option value="true">Ativos</option>
            <option value="false">Inativos</option>
          </select>
        </div>
      </div>

      <ErrorAlert error={error} onClose={() => setError(null)} />

      <div className="card piad-card piad-table-card">
        <div className="card-body">
          {loading ? (
            <LoadingState />
          ) : items.length === 0 ? (
            <EmptyState
              title="Nenhuma secao encontrada"
              description="Cadastre uma secao vinculada a um equipamento."
              action={
                <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
                  <i className="bi bi-plus-lg me-1" /> Nova secao
                </Button>
              }
            />
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>Equipamento</th>
                  <th>Codigo</th>
                  <th>Nome</th>
                  <th>Descricao</th>
                  <th>Status</th>
                  <th>Atualizado em</th>
                  <th className="text-end">Acoes</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{equipmentMap.get(item.equipment_id)?.code ?? item.equipment_id}</td>
                    <td className="fw-semibold">{item.code}</td>
                    <td>{item.name}</td>
                    <td>{item.description || "-"}</td>
                    <td>
                      <ActiveBadge active={item.active} />
                    </td>
                    <td>{formatDateTime(item.updated_at)}</td>
                    <td>
                      <div className="piad-table-actions">
                        <Button
                          variant="outline-secondary"
                          size="sm"
                          onClick={() => toggleActive(item)}
                          title={item.active ? "Desativar" : "Ativar"}
                        >
                          <i className={`bi ${item.active ? "bi-toggle-on" : "bi-toggle-off"}`} />
                        </Button>
                        <Button
                          variant="outline-primary"
                          size="sm"
                          onClick={() => openEdit(item)}
                          title="Editar"
                        >
                          <i className="bi bi-pencil" />
                        </Button>
                        <Button
                          variant="outline-danger"
                          size="sm"
                          onClick={() => setConfirmDelete(item)}
                          title="Excluir"
                        >
                          <i className="bi bi-trash" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </div>

      <div className="piad-pagination">
        <div className="piad-pagination__info">
          {total === 0 ? "Nenhum registro" : `Exibindo ${items.length} de ${total} registro(s)`}
        </div>
        <Pagination page={page} pages={pages} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
      </div>

      <Modal show={showFormModal} onHide={() => setShowFormModal(false)} centered backdrop="static">
        <Form onSubmit={handleSubmit}>
          <Modal.Header closeButton>
            <Modal.Title>{editing ? "Editar secao" : "Nova secao"}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <ErrorAlert error={formError} onClose={() => setFormError(null)} />
            <Form.Group className="mb-3" controlId="section-equipment-form">
              <Form.Label>Equipamento</Form.Label>
              <Form.Select
                value={form.equipment_id}
                onChange={(event) => setForm((prev) => ({ ...prev, equipment_id: event.target.value }))}
                required
                disabled={loadingEquipments}
              >
                <option value="">Selecione...</option>
                {equipments.map((equipment) => (
                  <option key={equipment.id} value={equipment.id}>
                    {equipment.code} - {equipment.name}
                  </option>
                ))}
              </Form.Select>
            </Form.Group>
            <Form.Group className="mb-3" controlId="section-code">
              <Form.Label>Codigo</Form.Label>
              <Form.Control
                value={form.code}
                onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))}
                required
                maxLength={64}
              />
              <Form.Text className="text-muted">O codigo sera convertido para maiusculas.</Form.Text>
            </Form.Group>
            <Form.Group className="mb-3" controlId="section-name">
              <Form.Label>Nome</Form.Label>
              <Form.Control
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                required
                maxLength={255}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="section-description">
              <Form.Label>Descricao</Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                value={form.description}
                onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
                maxLength={500}
              />
            </Form.Group>
            <Form.Check
              type="switch"
              id="section-active"
              label="Ativo"
              checked={form.active}
              onChange={(event) => setForm((prev) => ({ ...prev, active: event.target.checked }))}
            />
          </Modal.Body>
          <Modal.Footer>
            <Button variant="outline-secondary" onClick={() => setShowFormModal(false)} disabled={submitting}>
              Cancelar
            </Button>
            <Button type="submit" variant="primary" className="btn-piad-primary" disabled={submitting}>
              {submitting ? "Salvando..." : "Salvar"}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>

      <ConfirmModal
        show={Boolean(confirmDelete)}
        title="Excluir secao"
        message={
          <span>
            Tem certeza que deseja excluir a secao <strong>{confirmDelete?.code}</strong>?
            Esta acao nao podera ser desfeita.
          </span>
        }
        busy={deleting}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
