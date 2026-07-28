import { useEffect, useMemo, useState } from "react";
import { Modal, Form, Button, Table } from "react-bootstrap";

import { equipmentsApi, piTagsApi, sectionsApi, variableTypesApi } from "../api";
import { DEFAULT_PI_SERVER } from "../constants/pi";
import type {
  Equipment,
  PiConnectionStatus,
  PiTag,
  PiTagCreate,
  PiTagDataType,
  PiTagUpdate,
  PiTagValidationResult,
  Section,
  VariableType,
} from "../types";
import { ActiveBadge } from "../components/ActiveBadge";
import { ConfirmModal } from "../components/ConfirmModal";
import { EmptyState } from "../components/EmptyState";
import { ErrorAlert } from "../components/ErrorAlert";
import { FeedbackAlert } from "../components/FeedbackAlert";
import { LoadingState } from "../components/LoadingState";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import {
  PiConnectionStatusBadge,
  usePiHealth,
} from "../components/PiConnectionStatus";
import { StatusBadge } from "../components/StatusBadge";
import { WebIdDisplay } from "../components/WebIdDisplay";
import { formatDateTime } from "../utils/format";

const PAGE_SIZE = 10;

interface FormState {
  equipment_id: string;
  section_id: string;
  variable_type_id: string;
  pi_server: string;
  pi_tag_name: string;
  display_name: string;
  description: string;
  engineering_unit: string;
  data_type: PiTagDataType;
  active: boolean;
}

const EMPTY_FORM: FormState = {
  equipment_id: "",
  section_id: "",
  variable_type_id: "",
  pi_server: DEFAULT_PI_SERVER,
  pi_tag_name: "",
  display_name: "",
  description: "",
  engineering_unit: "",
  data_type: "NUMERIC",
  active: true,
};

const DATA_TYPE_OPTIONS: { value: PiTagDataType; label: string }[] = [
  { value: "NUMERIC", label: "Numerico" },
  { value: "NON_NUMERIC", label: "Nao numerico" },
];

export function PiTagsPage() {
  const [items, setItems] = useState<PiTag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "true" | "false">("all");
  const [equipmentFilter, setEquipmentFilter] = useState<string>("");
  const [sectionFilter, setSectionFilter] = useState<string>("");
  const [variableTypeFilter, setVariableTypeFilter] = useState<string>("");
  const [validationFilter, setValidationFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);

  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [variableTypes, setVariableTypes] = useState<VariableType[]>([]);

  const [showFormModal, setShowFormModal] = useState(false);
  const [editing, setEditing] = useState<PiTag | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formSections, setFormSections] = useState<Section[]>([]);
  const [formError, setFormError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string>("");

  const [confirmDelete, setConfirmDelete] = useState<PiTag | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [validatingId, setValidatingId] = useState<number | null>(null);
  const [validatingAll, setValidatingAll] = useState(false);
  const [batchSelection, setBatchSelection] = useState<Set<number>>(new Set());
  const [validationResult, setValidationResult] = useState<PiTagValidationResult | null>(null);
  const [showValidationModal, setShowValidationModal] = useState(false);

  const piHealth = usePiHealth(true);
  const piStatus: PiConnectionStatus = piHealth.health?.status ?? "not_configured";

  const activeParam = useMemo<boolean | undefined>(() => {
    if (activeFilter === "all") return undefined;
    return activeFilter === "true";
  }, [activeFilter]);

  const equipmentParam = useMemo<number | undefined>(() => {
    if (!equipmentFilter) return undefined;
    const id = Number(equipmentFilter);
    return Number.isFinite(id) ? id : undefined;
  }, [equipmentFilter]);

  const sectionParam = useMemo<number | undefined>(() => {
    if (!sectionFilter) return undefined;
    const id = Number(sectionFilter);
    return Number.isFinite(id) ? id : undefined;
  }, [sectionFilter]);

  const variableTypeParam = useMemo<number | undefined>(() => {
    if (!variableTypeFilter) return undefined;
    const id = Number(variableTypeFilter);
    return Number.isFinite(id) ? id : undefined;
  }, [variableTypeFilter]);

  const validationParam = useMemo(() => {
    if (!validationFilter) return undefined;
    return validationFilter as PiTag["validation_status"];
  }, [validationFilter]);

  const loadLookups = async () => {
    try {
      const [equipmentResp, sectionsResp, variableTypesResp] = await Promise.all([
        equipmentsApi.list({ page: 1, page_size: 200 }),
        sectionsApi.list({ page: 1, page_size: 200 }),
        variableTypesApi.list({ page: 1, page_size: 200 }),
      ]);
      setEquipments(equipmentResp.items ?? []);
      setSections(sectionsResp.items ?? []);
      setVariableTypes(variableTypesResp.items ?? []);
    } catch (err) {
      setError(err);
    }
  };

  const loadList = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await piTagsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        equipment_id: equipmentParam,
        section_id: sectionParam,
        variable_type_id: variableTypeParam,
        active: activeParam,
        validation_status: validationParam,
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
    void loadLookups();
  }, []);

  useEffect(() => {
    void loadList();
  }, [page]);

  useEffect(() => {
    setPage(1);
  }, [search, activeFilter, equipmentFilter, sectionFilter, variableTypeFilter, validationFilter]);

  useEffect(() => {
    void loadList();
  }, [search, activeParam, equipmentParam, sectionParam, variableTypeParam, validationParam]);

  const activeEquipments = useMemo(
    () => equipments.filter((equipment) => equipment.active || String(equipment.id) === form.equipment_id),
    [equipments, form.equipment_id],
  );

  const activeVariableTypes = useMemo(
    () =>
      variableTypes.filter(
        (variableType) => variableType.active || String(variableType.id) === form.variable_type_id,
      ),
    [variableTypes, form.variable_type_id],
  );

  const filterSectionsByEquipment = (equipmentId: string): Section[] => {
    if (!equipmentId) {
      return [];
    }
    const id = Number(equipmentId);
    return sections.filter(
      (section) => section.equipment_id === id || String(section.id) === form.section_id,
    );
  };

  const listSectionsForFilter = useMemo(() => filterSectionsByEquipment(equipmentFilter), [
    equipmentFilter,
    sections,
    form.section_id,
  ]);

  useEffect(() => {
    if (!form.equipment_id) {
      setFormSections([]);
      return;
    }
    setFormSections(filterSectionsByEquipment(form.equipment_id));
  }, [form.equipment_id, sections]);

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM });
    setFormSections([]);
    setFormError(null);
    setShowFormModal(true);
  };

  const openEdit = (item: PiTag) => {
    setEditing(item);
    setForm({
      equipment_id: String(item.equipment_id),
      section_id: String(item.section_id),
      variable_type_id: String(item.variable_type_id),
      pi_server: item.pi_server,
      pi_tag_name: item.pi_tag_name,
      display_name: item.display_name,
      description: item.description ?? "",
      engineering_unit: item.engineering_unit ?? "",
      data_type: item.data_type,
      active: item.active,
    });
    setFormError(null);
    setShowFormModal(true);
  };

  const handleEquipmentChange = (value: string) => {
    setForm((prev) => {
      if (prev.equipment_id === value) {
        return prev;
      }
      return { ...prev, equipment_id: value, section_id: "" };
    });
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const equipmentId = Number(form.equipment_id);
      const sectionId = Number(form.section_id);
      const variableTypeId = Number(form.variable_type_id);
      if (!Number.isFinite(equipmentId) || equipmentId <= 0) {
        throw new Error("Selecione um equipamento valido.");
      }
      if (!Number.isFinite(sectionId) || sectionId <= 0) {
        throw new Error("Selecione uma secao valida.");
      }
      if (!Number.isFinite(variableTypeId) || variableTypeId <= 0) {
        throw new Error("Selecione um tipo de variavel valido.");
      }
      if (editing) {
        const update: PiTagUpdate = {
          equipment_id: equipmentId,
          section_id: sectionId,
          variable_type_id: variableTypeId,
          pi_server: form.pi_server.trim() || DEFAULT_PI_SERVER,
          pi_tag_name: form.pi_tag_name.trim(),
          display_name: form.display_name.trim(),
          description: form.description.trim() || null,
          engineering_unit: form.engineering_unit.trim() || null,
          data_type: form.data_type,
          active: form.active,
        };
        await piTagsApi.update(editing.id, update);
        setSuccessMessage("Tag PI atualizada com sucesso.");
      } else {
        const payload: PiTagCreate = {
          equipment_id: equipmentId,
          section_id: sectionId,
          variable_type_id: variableTypeId,
          pi_server: DEFAULT_PI_SERVER,
          pi_tag_name: form.pi_tag_name.trim(),
          display_name: form.display_name.trim(),
          description: form.description.trim() || null,
          engineering_unit: form.engineering_unit.trim() || null,
          data_type: form.data_type,
          active: form.active,
        };
        await piTagsApi.create(payload);
        setSuccessMessage("Tag PI criada com sucesso.");
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
      await piTagsApi.remove(confirmDelete.id);
      setSuccessMessage("Tag PI excluida com sucesso.");
      setConfirmDelete(null);
      await loadList();
    } catch (err) {
      setError(err);
    } finally {
      setDeleting(false);
    }
  };

  const toggleActive = async (item: PiTag) => {
    try {
      await piTagsApi.update(item.id, { active: !item.active });
      setSuccessMessage(`Tag PI ${!item.active ? "ativada" : "desativada"} com sucesso.`);
      await loadList();
    } catch (err) {
      setError(err);
    }
  };

  const validateOne = async (item: PiTag) => {
    if (piStatus === "not_configured") {
      setError({ message: "PI Web API nao configurado no backend." });
      return;
    }
    setValidatingId(item.id);
    setError(null);
    try {
      const result = await piTagsApi.validate(item.id);
      setValidationResult(result);
      setShowValidationModal(true);
      await loadList();
    } catch (err) {
      setError(err);
    } finally {
      setValidatingId(null);
    }
  };

  const validateBatch = async () => {
    if (piStatus === "not_configured") {
      setError({ message: "PI Web API nao configurado no backend." });
      return;
    }
    setValidatingAll(true);
    setError(null);
    try {
      const ids = Array.from(batchSelection);
      const result = await piTagsApi.validateBatch(ids.length > 0 ? ids : undefined);
      const summary = `Validacao concluida: ${result.valid} validas, ${result.invalid} invalidas, ${result.error} com erro.`;
      setSuccessMessage(summary);
      setBatchSelection(new Set());
      await loadList();
    } catch (err) {
      setError(err);
    } finally {
      setValidatingAll(false);
    }
  };

  const toggleBatchSelection = (id: number) => {
    setBatchSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const equipmentMap = useMemo(() => {
    const map = new Map<number, Equipment>();
    equipments.forEach((equipment) => map.set(equipment.id, equipment));
    return map;
  }, [equipments]);

  const sectionMap = useMemo(() => {
    const map = new Map<number, Section>();
    sections.forEach((section) => map.set(section.id, section));
    return map;
  }, [sections]);

  const variableTypeMap = useMemo(() => {
    const map = new Map<number, VariableType>();
    variableTypes.forEach((variableType) => map.set(variableType.id, variableType));
    return map;
  }, [variableTypes]);

  const batchSelectionCount = batchSelection.size;
  const canValidate = piStatus === "connected" || piStatus === "unavailable";

  return (
    <div data-testid="pi-tags-page">
      <PageHeader
        title="Tags PI"
        subtitle="Cadastro administrativo de tags do PI Web API"
        actions={
          <>
            <Button
              variant="outline-secondary"
              onClick={() => void piHealth.reload()}
              data-testid="pi-status-refresh"
            >
              <i className="bi bi-arrow-repeat me-1" /> Verificar PI
            </Button>
            <Button
              variant="outline-primary"
              onClick={() => void validateBatch()}
              disabled={!canValidate || validatingAll}
              data-testid="validate-batch"
            >
              <i className="bi bi-shield-check me-1" />{" "}
              {validatingAll
                ? "Validando..."
                : batchSelectionCount > 0
                ? `Validar ${batchSelectionCount} tag(s)`
                : "Validar todas ativas"}
            </Button>
            <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
              <i className="bi bi-plus-lg me-1" /> Nova tag PI
            </Button>
          </>
        }
      />

      <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
        <PiConnectionStatusBadge health={piHealth.health} loading={piHealth.loading} />
        {piHealth.health?.base_url ? (
          <span className="text-muted small">Base URL: {piHealth.health.base_url}</span>
        ) : null}
        {piHealth.health?.data_server ? (
          <span className="text-muted small">Data Archive: {piHealth.health.data_server}</span>
        ) : null}
        {piHealth.health?.response_time_ms !== null && piHealth.health?.response_time_ms !== undefined ? (
          <span className="text-muted small">Resposta: {piHealth.health.response_time_ms} ms</span>
        ) : null}
        {piHealth.error ? (
          <span className="text-danger small">Falha ao consultar /api/pi/health</span>
        ) : null}
      </div>

      <FeedbackAlert variant="success" message={successMessage} />

      <div className="piad-filter-bar">
        <div className="flex-grow-1">
          <label className="form-label" htmlFor="tag-search">
            Buscar
          </label>
          <input
            id="tag-search"
            className="form-control"
            placeholder="Buscar por tag, nome amigavel ou servidor"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div style={{ minWidth: 180 }}>
          <label className="form-label" htmlFor="tag-equipment">
            Equipamento
          </label>
          <select
            id="tag-equipment"
            className="form-select"
            value={equipmentFilter}
            onChange={(event) => {
              setEquipmentFilter(event.target.value);
              setSectionFilter("");
            }}
          >
            <option value="">Todos</option>
            {equipments.map((equipment) => (
              <option key={equipment.id} value={equipment.id}>
                {equipment.code} - {equipment.name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ minWidth: 180 }}>
          <label className="form-label" htmlFor="tag-section">
            Secao
          </label>
          <select
            id="tag-section"
            className="form-select"
            value={sectionFilter}
            onChange={(event) => setSectionFilter(event.target.value)}
            disabled={!equipmentFilter}
          >
            <option value="">Todas</option>
            {listSectionsForFilter.map((section) => (
              <option key={section.id} value={section.id}>
                {section.code} - {section.name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ minWidth: 180 }}>
          <label className="form-label" htmlFor="tag-vt">
            Tipo de variavel
          </label>
          <select
            id="tag-vt"
            className="form-select"
            value={variableTypeFilter}
            onChange={(event) => setVariableTypeFilter(event.target.value)}
          >
            <option value="">Todos</option>
            {variableTypes.map((variableType) => (
              <option key={variableType.id} value={variableType.id}>
                {variableType.code} - {variableType.name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ minWidth: 160 }}>
          <label className="form-label" htmlFor="tag-validation">
            Validacao
          </label>
          <select
            id="tag-validation"
            className="form-select"
            value={validationFilter}
            onChange={(event) => setValidationFilter(event.target.value)}
          >
            <option value="">Todas</option>
            <option value="PENDING">Pendente</option>
            <option value="VALID">Valida</option>
            <option value="INVALID">Invalida</option>
            <option value="ERROR">Erro</option>
          </select>
        </div>
        <div style={{ minWidth: 140 }}>
          <label className="form-label" htmlFor="tag-active">
            Status
          </label>
          <select
            id="tag-active"
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
              title="Nenhuma tag PI encontrada"
              description="Cadastre uma tag para representar uma variavel do processo."
              action={
                <Button variant="primary" className="btn-piad-primary" onClick={openCreate}>
                  <i className="bi bi-plus-lg me-1" /> Nova tag PI
                </Button>
              }
            />
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input
                      type="checkbox"
                      aria-label="Selecionar todas"
                      checked={items.length > 0 && items.every((item) => batchSelection.has(item.id))}
                      onChange={(event) => {
                        if (event.target.checked) {
                          setBatchSelection(new Set(items.map((item) => item.id)));
                        } else {
                          setBatchSelection(new Set());
                        }
                      }}
                    />
                  </th>
                  <th>Equipamento</th>
                  <th>Secao</th>
                  <th>Tipo de variavel</th>
                  <th>PI Server</th>
                  <th>Tag PI</th>
                  <th>Nome amigavel</th>
                  <th>WebId</th>
                  <th>Validacao</th>
                  <th>Mensagem</th>
                  <th>Validado em</th>
                  <th>Status</th>
                  <th className="text-end">Acoes</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} data-testid={`pi-tag-row-${item.id}`} data-status={item.validation_status}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Selecionar tag ${item.id}`}
                        checked={batchSelection.has(item.id)}
                        onChange={() => toggleBatchSelection(item.id)}
                      />
                    </td>
                    <td>{equipmentMap.get(item.equipment_id)?.code ?? item.equipment_id}</td>
                    <td>{sectionMap.get(item.section_id)?.code ?? item.section_id}</td>
                    <td>{variableTypeMap.get(item.variable_type_id)?.code ?? item.variable_type_id}</td>
                    <td>{item.pi_server}</td>
                    <td className="fw-semibold">{item.pi_tag_name}</td>
                    <td>{item.display_name}</td>
                    <td>
                      <WebIdDisplay webId={item.pi_web_id} />
                    </td>
                    <td>
                      <StatusBadge status={item.validation_status} />
                    </td>
                    <td className="small text-muted">{item.validation_message || "-"}</td>
                    <td className="small text-muted">{formatDateTime(item.validated_at)}</td>
                    <td>
                      <ActiveBadge active={item.active} />
                    </td>
                    <td>
                      <div className="piad-table-actions">
                        <Button
                          variant="outline-success"
                          size="sm"
                          onClick={() => void validateOne(item)}
                          disabled={!canValidate || validatingId === item.id}
                          title="Validar no PI"
                          data-testid={`validate-${item.id}`}
                        >
                          <i className="bi bi-shield-check" />
                        </Button>
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

      <Modal show={showFormModal} onHide={() => setShowFormModal(false)} centered backdrop="static" size="lg">
        <Form onSubmit={handleSubmit}>
          <Modal.Header closeButton>
            <Modal.Title>{editing ? "Editar tag PI" : "Nova tag PI"}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <ErrorAlert error={formError} onClose={() => setFormError(null)} />
            <div className="row g-3">
              <div className="col-md-4">
                <Form.Group controlId="tag-equipment-form">
                  <Form.Label>Equipamento</Form.Label>
                  <Form.Select
                    value={form.equipment_id}
                    onChange={(event) => handleEquipmentChange(event.target.value)}
                    required
                  >
                    <option value="">Selecione...</option>
                    {activeEquipments.map((equipment) => (
                      <option key={equipment.id} value={equipment.id}>
                        {equipment.code} - {equipment.name}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </div>
              <div className="col-md-4">
                <Form.Group controlId="tag-section-form">
                  <Form.Label>Secao</Form.Label>
                  <Form.Select
                    value={form.section_id}
                    onChange={(event) => setForm((prev) => ({ ...prev, section_id: event.target.value }))}
                    required
                    disabled={!form.equipment_id}
                  >
                    <option value="">Selecione...</option>
                    {formSections.map((section) => (
                      <option key={section.id} value={section.id}>
                        {section.code} - {section.name}
                      </option>
                    ))}
                  </Form.Select>
                  <Form.Text className="text-muted">
                    Apenas secoes do equipamento selecionado.
                  </Form.Text>
                </Form.Group>
              </div>
              <div className="col-md-4">
                <Form.Group controlId="tag-vt-form">
                  <Form.Label>Tipo de variavel</Form.Label>
                  <Form.Select
                    value={form.variable_type_id}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, variable_type_id: event.target.value }))
                    }
                    required
                  >
                    <option value="">Selecione...</option>
                    {activeVariableTypes.map((variableType) => (
                      <option key={variableType.id} value={variableType.id}>
                        {variableType.code} - {variableType.name}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </div>
            </div>
            <hr />
            <div className="row g-3">
              <div className="col-md-12">
                <Form.Group controlId="tag-pi-name">
                  <Form.Label>Nome da tag no PI</Form.Label>
                  <Form.Control
                    value={form.pi_tag_name}
                    onChange={(event) => setForm((prev) => ({ ...prev, pi_tag_name: event.target.value }))}
                    required
                    maxLength={255}
                  />
                </Form.Group>
              </div>
            </div>
            <div className="row g-3 mt-1">
              <div className="col-md-6">
                <Form.Group controlId="tag-display">
                  <Form.Label>Nome amigavel</Form.Label>
                  <Form.Control
                    value={form.display_name}
                    onChange={(event) => setForm((prev) => ({ ...prev, display_name: event.target.value }))}
                    required
                    maxLength={255}
                  />
                </Form.Group>
              </div>
              <div className="col-md-3">
                <Form.Group controlId="tag-unit">
                  <Form.Label>Unidade de engenharia</Form.Label>
                  <Form.Control
                    value={form.engineering_unit}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, engineering_unit: event.target.value }))
                    }
                    maxLength={32}
                  />
                </Form.Group>
              </div>
              <div className="col-md-3">
                <Form.Group controlId="tag-data-type">
                  <Form.Label>Tipo de dado</Form.Label>
                  <Form.Select
                    value={form.data_type}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, data_type: event.target.value as PiTagDataType }))
                    }
                  >
                    {DATA_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </div>
            </div>
            <Form.Group className="mt-3" controlId="tag-description">
              <Form.Label>Descricao</Form.Label>
              <Form.Control
                as="textarea"
                rows={3}
                value={form.description}
                onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
                maxLength={500}
              />
            </Form.Group>
            <div className="d-flex justify-content-between align-items-center mt-3">
              <Form.Check
                type="switch"
                id="tag-active"
                label="Ativo"
                checked={form.active}
                onChange={(event) => setForm((prev) => ({ ...prev, active: event.target.checked }))}
              />
              <div className="piad-disabled-note">
                Validacao automatica no PI Web API disponivel na Fase 2.
              </div>
            </div>
            {!editing ? (
              <div className="mt-3">
                <span className="text-muted small">Status de validacao inicial:</span>{" "}
                <StatusBadge status="PENDING" />
              </div>
            ) : null}
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

      <Modal
        show={showValidationModal}
        onHide={() => setShowValidationModal(false)}
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>Resultado da validacao</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {validationResult ? (
            <div>
              <p className="mb-2">
                <strong>Tag ID:</strong> {validationResult.tag_id}
              </p>
              <p className="mb-2">
                <strong>Status:</strong> <StatusBadge status={validationResult.status} />
              </p>
              <p className="mb-2">
                <strong>WebId:</strong>{" "}
                {validationResult.web_id ? (
                  <WebIdDisplay webId={validationResult.web_id} />
                ) : (
                  <span className="text-muted small">-</span>
                )}
              </p>
              <p className="mb-2">
                <strong>Mensagem:</strong> {validationResult.message || "-"}
              </p>
              <p className="mb-0">
                <strong>Validado em:</strong> {formatDateTime(validationResult.validated_at)}
              </p>
            </div>
          ) : null}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline-secondary" onClick={() => setShowValidationModal(false)}>
            Fechar
          </Button>
        </Modal.Footer>
      </Modal>

      <ConfirmModal
        show={Boolean(confirmDelete)}
        title="Excluir tag PI"
        message={
          <span>
            Tem certeza que deseja excluir a tag <strong>{confirmDelete?.pi_tag_name}</strong>?
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
