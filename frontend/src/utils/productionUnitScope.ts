import type { PiTag, Section, VariableType } from "../types";

export type ProductionUnitScopeResolution =
  | { tagId: number; error: null }
  | { tagId: null; error: string };

function isUmTag(tag: PiTag, variableTypes: VariableType[]): boolean {
  if (!tag.active || tag.data_type !== "NON_NUMERIC") return false;
  const type = variableTypes.find((entry) => entry.id === tag.variable_type_id);
  if (!type?.active) return false;
  const labels = [type.code, type.name].map((value) => value.trim().toLocaleUpperCase("pt-BR").replace(/[_-]+/g, " ").replace(/\s+/g, " "));
  return labels.some((label) => ["UM", "CODIGO UM", "UNIDADE MATERIAL"].includes(label));
}

/** UI metadata preview only; the API independently resolves and validates the authoritative UM. */
export function resolveProductionUnitScope(
  equipmentId: number,
  sectionId: number | null,
  sections: Section[],
  tags: PiTag[],
  variableTypes: VariableType[],
): ProductionUnitScopeResolution {
  if (sectionId === null) {
    const candidates = tags.filter((tag) => tag.equipment_id === equipmentId && tag.section_id === null && isUmTag(tag, variableTypes));
    if (candidates.length > 1) return { tagId: null, error: "Configuração ambígua: há mais de uma tag UM ativa para o equipamento inteiro." };
    if (candidates.length === 0) return { tagId: null, error: "Não há tag UM configurada para o equipamento inteiro." };
    return { tagId: candidates[0].id, error: null };
  }

  const section = sections.find((item) => item.id === sectionId && item.equipment_id === equipmentId && item.active);
  if (!section) return { tagId: null, error: "A seção selecionada não está disponível para este equipamento." };
  const sectionTags = tags.filter((tag) => tag.equipment_id === equipmentId && tag.section_id === sectionId && isUmTag(tag, variableTypes));
  const configured = section.um_tag_id === null ? undefined : tags.find((tag) => tag.id === section.um_tag_id);
  if (section.um_tag_id !== null && (!configured || !isUmTag(configured, variableTypes) || configured.equipment_id !== equipmentId || configured.section_id !== null && configured.section_id !== sectionId)) {
    return { tagId: null, error: "A tag UM configurada para esta seção está ausente, inativa ou fora do escopo." };
  }
  const candidates = [...sectionTags];
  if (configured && !candidates.some((tag) => tag.id === configured.id)) candidates.push(configured);
  if (candidates.length > 1) return { tagId: null, error: "Configuração ambígua: há mais de uma tag UM ativa para esta seção." };
  if (candidates.length === 0) return { tagId: null, error: "Não há tag UM configurada para esta seção." };
  return { tagId: candidates[0].id, error: null };
}
