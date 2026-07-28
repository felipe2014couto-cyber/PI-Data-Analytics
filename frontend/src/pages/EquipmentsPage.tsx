import { useEffect, useMemo, useState } from "react";
import { Modal, Form, Button, Table } from "react-bootstrap";

import { equipmentsApi } from "../api";
import type { Equipment, EquipmentCreate, EquipmentUpdate } from "../types";
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
  code: string;
  name: string;
  description: string;
  active: boolean;
}

const EMPTY_FORM: FormState = { code: "", name: "", description: "", active: true };

export function EquipmentsPage() {
  const [items, setItems] = useState<Equipment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "true" | "false">("all");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [showFormModal, setShowFormModal] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string>("");
  const [confirmDelete, setConfirmDelete] = useState<Equipment | null>(null);
  const [deleting, setDeleting] = useState(false);

  const activeParam = useMemo<boolean | undefined>(() => {
    if (activeFilter === "all") return undefined;
    return activeFilter === "true";
  }, [activeFilter]);

  const loadList = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await equipmentsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
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
    void loadList();
  }, [page]);

  useEffect(() => {
    setPage(1);
  }, [search, activeFilter]);

  useEffect(() => {
    void loadList();
  }, [search, activeParam]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowFormModal(true);
  };

  const openEdit = (item: Equipment) => {
    setEditing(item);
    setForm({
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
      const payload = {
        code: form.code.trim(),
        name: form.name.trim(),
        description: form.description.trim() || null,
        active: form.active,
      } satisfies EquipmentCreate;
      if (editing) {
        const update: EquipmentUpdate = {
          code: form.code.trim(),
          name: form.name.trim(),
          description: form.description.trim() || null,
          active: form.active,
        };
        await equipmentsApi.update(editing.id, update);
        setSuccessMessage("Equipamento atualizado com sucesso.");
      } else {
        await equipmentsApi.create(payload);
        setSuccessMessage("Equipamento criado com sucesso.");
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
      await equipmentsApi.remove(confirmDelete.id);
      setSuccessMessage("Equipamento excluido com sucesso.");
      setConfirmDelete(null);
      await loadList();
    } catch (err) {
      setError(err);
    } finally {
      setDeleting(false);
    }
  };

  const toggleActive = async (item: Equipment) => {
    try {
      await equipmentsApi.update(item.id, { active: !item.active });
      setSuccessMessage(`Equipamento ${!item.active ? "ativado" : "desativado"} com sucesso.`);
      await loadList();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div data-testid="equipments-page">
      <PageHeader
        title="Equipamentos"
        subtitle="Cadastro de equipamentos industriais"
        actions={
          <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
            <i className="bi bi-plus-lg me-1" /> Novo equipamento
          </Button>
        }
      />
      <FeedbackAlert variant="success" message={successMessage} />

      <div className="piad-filter-bar">
        <div className="flex-grow-1">
          <label className="form-label" htmlFor="equipment-search">
            Buscar
          </label>
          <input
            id="equipment-search"
            className="form-control"
            placeholder="Buscar por codigo ou nome"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div style={{ minWidth: 180 }}>
          <label className="form-label" htmlFor="equipment-active">
            Status
          </label>
          <select
            id="equipment-active"
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
              title="Nenhum equipamento encontrado"
              description="Cadastre um equipamento para iniciar."
              action={
                <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
                  <i className="bi bi-plus-lg me-1" /> Novo equipamento
                </Button>
              }
            />
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
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
          {total === 0
            ? "Nenhum registro"
            : `Exibindo ${items.length} de ${total} registro(s)`}
        </div>
        <Pagination page={page} pages={pages} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
      </div>

      <Modal show={showFormModal} onHide={() => setShowFormModal(false)} centered backdrop="static">
        <Form onSubmit={handleSubmit}>
          <Modal.Header closeButton>
            <Modal.Title>{editing ? "Editar equipamento" : "Novo equipamento"}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <ErrorAlert error={formError} onClose={() => setFormError(null)} />
            <Form.Group className="mb-3" controlId="equipment-code">
              <Form.Label>Codigo</Form.Label>
              <Form.Control
                value={form.code}
                onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))}
                required
                maxLength={64}
              />
              <Form.Text className="text-muted">O codigo sera convertido para maiusculas.</Form.Text>
            </Form.Group>
            <Form.Group className="mb-3" controlId="equipment-name">
              <Form.Label>Nome</Form.Label>
              <Form.Control
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                required
                maxLength={255}
              />
            </Form.Group>
            <Form.Group className="mb-3" controlId="equipment-description">
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
              id="equipment-active"
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
        title="Excluir equipamento"
        message={
          <span>
            Tem certeza que deseja excluir o equipamento <strong>{confirmDelete?.code}</strong>?
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
