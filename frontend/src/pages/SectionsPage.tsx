import { useEffect, useMemo, useState } from "react";
import { Modal, Form, Button, Table } from "react-bootstrap";

import { equipmentsApi, piTagsApi, sectionsApi, variableTypesApi } from "../api";
import type { Equipment, PiTag, Section, SectionCreate, SectionUpdate, VariableType } from "../types";
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
type AnalysisTagKind = "width" | "um" | "thickness";

const ANALYSIS_TAG_TYPE_ALIASES: Record<AnalysisTagKind, string[]> = {
  width: ["largura", "width"],
  um: ["um", "codigo um", "código um", "unidade material"],
  thickness: ["espessura", "thickness"],
};

function normalizeTypeLabel(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function isFixedVariableType(vt: VariableType): boolean {
  const labels = [vt.code, vt.name].map(normalizeTypeLabel);
  return (
    ANALYSIS_TAG_TYPE_ALIASES.width.some((alias) => labels.includes(normalizeTypeLabel(alias))) ||
    ANALYSIS_TAG_TYPE_ALIASES.um.some((alias) => labels.includes(normalizeTypeLabel(alias))) ||
    ANALYSIS_TAG_TYPE_ALIASES.thickness.some((alias) => labels.includes(normalizeTypeLabel(alias)))
  );
}

function getDynamicTagLabel(vt?: VariableType): string {
  if (!vt) return "Tag de análise";
  const nameLower = vt.name.trim().toLowerCase();
  return `Tag de ${nameLower}`;
}

interface DynamicAnalysisTagState {
  variable_type_id: number;
  pi_tag_id: string;
}

interface FormState {
  equipment_id: string;
  code: string;
  name: string;
  description: string;
  active: boolean;
  process_type: string;
  group_code: string;
  classification_tag_ids: number[];
  width_tag_id: string;
  um_tag_id: string;
  thickness_tag_id: string;
  analysis_tags: DynamicAnalysisTagState[];
}

const EMPTY_FORM: FormState = {
  equipment_id: "",
  code: "",
  name: "",
  description: "",
  active: true,
  process_type: "",
  group_code: "",
  classification_tag_ids: [],
  width_tag_id: "",
  um_tag_id: "",
  thickness_tag_id: "",
  analysis_tags: [],
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
  const [piTags, setPiTags] = useState<PiTag[]>([]);
  const [loadingPiTags, setLoadingPiTags] = useState(false);
  const [variableTypes, setVariableTypes] = useState<VariableType[]>([]);


  const [showFormModal, setShowFormModal] = useState(false);
  const [showAddTagModal, setShowAddTagModal] = useState(false);
  const [selectedVariableTypeId, setSelectedVariableTypeId] = useState<string>("");
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

  const loadPiTags = async () => {
    setLoadingPiTags(true);
    try {
      const response = await piTagsApi.list({ page: 1, page_size: 200, active: true });
      setPiTags(response.items ?? []);
    } catch (err) {
      setError(err);
    } finally {
      setLoadingPiTags(false);
    }
  };



  const loadVariableTypes = async () => {
    try {
      const response = await variableTypesApi.list({ page: 1, page_size: 200, active: true });
      setVariableTypes(response.items ?? []);
    } catch (err) {
      setError(err);
    }
  };

  useEffect(() => {
    void loadEquipments();
    void loadPiTags();
    void loadVariableTypes();
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
    setForm({ ...EMPTY_FORM, equipment_id: equipmentFilter || "", analysis_tags: [] });
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
      process_type: item.process_type ?? "",
      group_code: item.group_code ?? "",
      classification_tag_ids: item.classification_tag_ids ?? [],
      width_tag_id: item.width_tag_id ? String(item.width_tag_id) : "",
      um_tag_id: item.um_tag_id ? String(item.um_tag_id) : "",
      thickness_tag_id: item.thickness_tag_id ? String(item.thickness_tag_id) : "",
      analysis_tags: (item.analysis_tags ?? []).map((at) => ({
        variable_type_id: at.variable_type_id,
        pi_tag_id: String(at.pi_tag_id),
      })),
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
      for (const tagItem of form.analysis_tags) {
        if (!tagItem.pi_tag_id || Number(tagItem.pi_tag_id) <= 0) {
          const vt = variableTypes.find((v) => v.id === tagItem.variable_type_id);
          throw new Error(`Selecione uma tag para ${vt?.name ?? "o tipo de variável"}.`);
        }
      }
      const dynamicPayload = form.analysis_tags.map((at) => ({
        variable_type_id: at.variable_type_id,
        pi_tag_id: Number(at.pi_tag_id),
      }));

      if (editing) {
        const update: SectionUpdate = {
          equipment_id: equipmentId,
          code: form.code.trim(),
          name: form.name.trim(),
          description: form.description.trim() || null,
          active: form.active,
          process_type: form.process_type || null,
          group_code: form.group_code || null,
          classification_tag_ids: form.classification_tag_ids,
          width_tag_id: form.width_tag_id ? Number(form.width_tag_id) : null,
          um_tag_id: form.um_tag_id ? Number(form.um_tag_id) : null,
          thickness_tag_id: form.thickness_tag_id ? Number(form.thickness_tag_id) : null,
          analysis_tags: dynamicPayload,
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
          process_type: form.process_type || null,
          group_code: form.group_code || null,
          classification_tag_ids: form.classification_tag_ids,
          width_tag_id: null,
          um_tag_id: null,
          thickness_tag_id: null,
          analysis_tags: [],
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

  const analysisTagOptions = useMemo(() => {
    const equipmentId = Number(form.equipment_id);
    const sectionId = editing?.id;
    const selectedIds = new Set([form.width_tag_id, form.um_tag_id, form.thickness_tag_id].filter(Boolean));
    const variableTypeById = new Map(variableTypes.map((type) => [type.id, type]));
    const tagMatchesKind = (tag: PiTag, kind: AnalysisTagKind) => {
      const variableType = variableTypeById.get(tag.variable_type_id);
      if (!variableType) return false;
      const labels = [variableType.code, variableType.name].map(normalizeTypeLabel);
      return ANALYSIS_TAG_TYPE_ALIASES[kind].some((alias) => labels.includes(normalizeTypeLabel(alias)));
    };
    const tagOptionsFor = (kind: AnalysisTagKind) => piTags.filter((tag) =>
      tag.equipment_id === equipmentId &&
      (tag.section_id === null || tag.section_id === sectionId || selectedIds.has(String(tag.id))) &&
      tagMatchesKind(tag, kind),
    );
    return {
      width: tagOptionsFor("width"),
      um: tagOptionsFor("um"),
      thickness: tagOptionsFor("thickness"),
    };
  }, [editing?.id, form.equipment_id, form.thickness_tag_id, form.um_tag_id, form.width_tag_id, piTags, variableTypes]);

  const getDynamicTagOptions = (variableTypeId: number, currentSelectedTagId: string) => {
    const equipmentId = Number(form.equipment_id);
    const sectionId = editing?.id;
    return piTags.filter(
      (tag) =>
        tag.equipment_id === equipmentId &&
        (tag.section_id === null || tag.section_id === sectionId || String(tag.id) === currentSelectedTagId) &&
        tag.variable_type_id === variableTypeId,
    );
  };

  const handleEquipmentChange = (newEquipmentId: string) => {
    setForm((prev) => {
      const eqNum = Number(newEquipmentId);
      const validTagIds = new Set(
        piTags
          .filter((t) => t.equipment_id === eqNum && (t.section_id === null || t.section_id === editing?.id))
          .map((t) => String(t.id)),
      );
      return {
        ...prev,
        equipment_id: newEquipmentId,
        width_tag_id: validTagIds.has(prev.width_tag_id) ? prev.width_tag_id : "",
        um_tag_id: validTagIds.has(prev.um_tag_id) ? prev.um_tag_id : "",
        thickness_tag_id: validTagIds.has(prev.thickness_tag_id) ? prev.thickness_tag_id : "",
        analysis_tags: prev.analysis_tags.map((at) => ({
          ...at,
          pi_tag_id: validTagIds.has(at.pi_tag_id) ? at.pi_tag_id : "",
        })),
      };
    });
  };

  const removeAnalysisTag = (variableTypeId: number) => {
    setForm((prev) => ({
      ...prev,
      analysis_tags: prev.analysis_tags.filter((at) => at.variable_type_id !== variableTypeId),
    }));
  };

  const updateAnalysisTag = (variableTypeId: number, piTagId: string) => {
    setForm((prev) => ({
      ...prev,
      analysis_tags: prev.analysis_tags.map((at) =>
        at.variable_type_id === variableTypeId ? { ...at, pi_tag_id: piTagId } : at,
      ),
    }));
  };

  const tagLabel = (tagId: number | null) => {
    if (!tagId) return "—";
    const tag = piTags.find((item) => item.id === tagId);
    return tag?.display_name ?? tag?.pi_tag_name ?? `Tag #${tagId}`;
  };

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
                  <th>Tags de análise</th>
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
                    <td className="small">
                      <div><strong>Largura:</strong> {tagLabel(item.width_tag_id)}</div>
                      <div><strong>UM:</strong> {tagLabel(item.um_tag_id)}</div>
                      <div><strong>Espessura:</strong> {tagLabel(item.thickness_tag_id)}</div>
                    </td>
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
                onChange={(event) => handleEquipmentChange(event.target.value)}
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

            <div className="border rounded p-3 mb-3 bg-light">
              <h6 className="mb-1">Tags para análise da seção</h6>
              <Form.Text className="d-block text-muted mb-3">
                Selecione as tags PI de largura, UM e espessura usadas nas análises desta seção.
              </Form.Text>
              {!editing ? (
                <div className="small text-muted mb-0">
                  Salve a seção primeiro; depois abra a edição para vincular as tags cadastradas nela.
                </div>
              ) : loadingPiTags ? (
                <div className="small text-muted">Carregando tags...</div>
              ) : (
                <>
                  <Form.Group className="mb-3" controlId="section-width-tag">
                    <Form.Label>Tag de largura</Form.Label>
                    <Form.Select
                      value={form.width_tag_id}
                      onChange={(event) => setForm((prev) => ({ ...prev, width_tag_id: event.target.value }))}
                    >
                      <option value="">Não selecionar</option>
                      {analysisTagOptions.width.map((tag) => (
                        <option key={tag.id} value={tag.id}>{tag.display_name} — {tag.pi_tag_name}</option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                  <Form.Group className="mb-3" controlId="section-um-tag">
                    <Form.Label>Tag de UM</Form.Label>
                    <Form.Select
                      value={form.um_tag_id}
                      onChange={(event) => setForm((prev) => ({ ...prev, um_tag_id: event.target.value }))}
                    >
                      <option value="">Não selecionar</option>
                      {analysisTagOptions.um.map((tag) => (
                        <option key={tag.id} value={tag.id}>{tag.display_name} — {tag.pi_tag_name}</option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                  <Form.Group className="mb-3" controlId="section-thickness-tag">
                    <Form.Label>Tag de espessura</Form.Label>
                    <Form.Select
                      value={form.thickness_tag_id}
                      onChange={(event) => setForm((prev) => ({ ...prev, thickness_tag_id: event.target.value }))}
                    >
                      <option value="">Não selecionar</option>
                      {analysisTagOptions.thickness.map((tag) => (
                        <option key={tag.id} value={tag.id}>{tag.display_name} — {tag.pi_tag_name}</option>
                      ))}
                    </Form.Select>
                  </Form.Group>

                  {form.analysis_tags.map((item) => {
                    const varType = variableTypes.find((vt) => vt.id === item.variable_type_id);
                    const options = getDynamicTagOptions(item.variable_type_id, item.pi_tag_id);
                    return (
                      <Form.Group
                        key={item.variable_type_id}
                        className="mb-3"
                        controlId={`section-analysis-tag-${item.variable_type_id}`}
                      >
                        <div className="d-flex justify-content-between align-items-center mb-1">
                          <Form.Label className="mb-0">{getDynamicTagLabel(varType)}</Form.Label>
                          <Button
                            variant="link"
                            size="sm"
                            className="text-danger p-0 text-decoration-none"
                            onClick={() => removeAnalysisTag(item.variable_type_id)}
                          >
                            Remover
                          </Button>
                        </div>
                        <Form.Select
                          value={item.pi_tag_id}
                          onChange={(event) => updateAnalysisTag(item.variable_type_id, event.target.value)}
                        >
                          <option value="">Selecione uma PI Tag</option>
                          {options.map((tag) => (
                            <option key={tag.id} value={tag.id}>
                              {varType ? `${varType.code} — ` : ""}{tag.pi_tag_name}
                            </option>
                          ))}
                        </Form.Select>
                      </Form.Group>
                    );
                  })}

                  <div className="mt-2">
                    <Button
                      variant="outline-primary"
                      size="sm"
                      onClick={() => {
                        setSelectedVariableTypeId("");
                        setShowAddTagModal(true);
                      }}
                    >
                      <i className="bi bi-plus-lg me-1" /> Adicionar tag de análise
                    </Button>
                  </div>
                </>
              )}
            </div>
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

      <Modal show={showAddTagModal} onHide={() => setShowAddTagModal(false)} centered backdrop="static">
        <Modal.Header closeButton>
          <Modal.Title>Adicionar tag de análise</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Form.Group controlId="modal-add-analysis-tag-type">
            <Form.Label>Tipo de variável</Form.Label>
            <Form.Select
              value={selectedVariableTypeId}
              onChange={(e) => setSelectedVariableTypeId(e.target.value)}
            >
              <option value="">Selecionar...</option>
              {variableTypes
                .filter((vt) => !isFixedVariableType(vt))
                .map((vt) => {
                  const isAdded = form.analysis_tags.some((at) => at.variable_type_id === vt.id);
                  return (
                    <option key={vt.id} value={vt.id} disabled={isAdded}>
                      {vt.name} — {vt.code}{isAdded ? " (já adicionada)" : ""}
                    </option>
                  );
                })}
            </Form.Select>
          </Form.Group>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline-secondary" onClick={() => setShowAddTagModal(false)}>
            Cancelar
          </Button>
          <Button
            variant="primary"
            className="btn-piad-primary"
            disabled={
              !selectedVariableTypeId ||
              form.analysis_tags.some((at) => at.variable_type_id === Number(selectedVariableTypeId))
            }
            onClick={() => {
              const vtId = Number(selectedVariableTypeId);
              if (vtId && !form.analysis_tags.some((at) => at.variable_type_id === vtId)) {
                setForm((prev) => ({
                  ...prev,
                  analysis_tags: [...prev.analysis_tags, { variable_type_id: vtId, pi_tag_id: "" }],
                }));
              }
              setShowAddTagModal(false);
              setSelectedVariableTypeId("");
            }}
          >
            Adicionar
          </Button>
        </Modal.Footer>
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
