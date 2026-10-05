import { describe, expect, it } from "vitest";
import { resolveProductionUnitScope } from "../src/utils/productionUnitScope";
import { equipmentFixture, piTagFixture, sectionFixture, variableTypeFixture } from "./mocks/api";

const umType = { ...variableTypeFixture, id: 2, code: "UM", name: "UM", filter_data_type: "STRING" as const };
const makeUm = (id: number, sectionId: number | null, active = true) => ({
  ...piTagFixture, id, equipment_id: equipmentFixture.id, section_id: sectionId, variable_type_id: umType.id,
  data_type: "NON_NUMERIC" as const, active, pi_tag_name: `UM-${id}`,
});
const sectionA = { ...sectionFixture, id: 10, equipment_id: equipmentFixture.id, um_tag_id: 12 };
const sectionB = { ...sectionFixture, id: 11, equipment_id: equipmentFixture.id, um_tag_id: 13 };

describe("Base Unidade UM scope metadata", () => {
  it("uses only the equipment-wide UM when section is Todas", () => {
    expect(resolveProductionUnitScope(1, null, [sectionA, sectionB], [makeUm(20, null), makeUm(12, 10), makeUm(13, 11)], [umType]))
      .toEqual({ tagId: 20, error: null });
  });
  it("reports missing and ambiguous equipment-wide configuration", () => {
    expect(resolveProductionUnitScope(1, null, [], [makeUm(12, 10)], [umType]).error).toMatch(/equipamento inteiro/i);
    expect(resolveProductionUnitScope(1, null, [], [makeUm(20, null), makeUm(21, null)], [umType]).error).toMatch(/ambígua/i);
  });
  it("uses the selected section UM and never falls back to another section or the global UM", () => {
    const tags = [makeUm(20, null), makeUm(12, 10), makeUm(13, 11)];
    expect(resolveProductionUnitScope(1, 10, [sectionA, sectionB], tags, [umType])).toEqual({ tagId: 12, error: null });
    expect(resolveProductionUnitScope(1, 11, [sectionA, sectionB], tags, [umType])).toEqual({ tagId: 13, error: null });
    const sectionC = { ...sectionFixture, id: 12, equipment_id: equipmentFixture.id, um_tag_id: null };
    expect(resolveProductionUnitScope(1, 12, [sectionA, sectionB, sectionC], tags, [umType]).error).toMatch(/esta seção/i);
  });
  it("honors an explicit section.um_tag_id, including an equipment tag assigned to that section", () => {
    const assignedGlobal = { ...sectionA, um_tag_id: 20 };
    expect(resolveProductionUnitScope(1, 10, [assignedGlobal], [makeUm(20, null)], [umType])).toEqual({ tagId: 20, error: null });
  });
  it("does not use inactive tags and reports duplicate tags within a section", () => {
    expect(resolveProductionUnitScope(1, null, [], [makeUm(20, null, false)], [umType]).error).toMatch(/equipamento inteiro/i);
    expect(resolveProductionUnitScope(1, 10, [sectionA], [makeUm(12, 10), makeUm(14, 10)], [umType]).error).toMatch(/ambígua/i);
  });
  it("resolves section to equipment and equipment to section changes independently", () => {
    const tags = [makeUm(20, null), makeUm(12, 10)];
    expect(resolveProductionUnitScope(1, null, [sectionA], tags, [umType]).tagId).toBe(20);
    expect(resolveProductionUnitScope(1, 10, [sectionA], tags, [umType]).tagId).toBe(12);
    expect(resolveProductionUnitScope(1, null, [sectionA], tags, [umType]).tagId).toBe(20);
  });
});
