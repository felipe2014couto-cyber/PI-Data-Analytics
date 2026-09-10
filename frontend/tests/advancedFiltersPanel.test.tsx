import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdvancedFiltersPanel } from "../src/components/AdvancedFiltersPanel";
import type { DataFilterConfiguration } from "../src/types";

const configuration: DataFilterConfiguration = {
  quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

const tagOptions = [
  { id: 10, displayName: "Modelo Aço", tagName: "LFI_RB1_MODELO", dataType: "TEXT" },
  { id: 11, displayName: "Código UM", tagName: "LFI_RB1_UM", dataType: "TEXT" },
  { id: 12, displayName: "Grupo", tagName: "LFI_RB1_GRUPO", dataType: "TEXT" },
  { id: 13, displayName: "Turno", tagName: "LFI_RB1_TURNO", dataType: "TEXT" },
  { id: 20, displayName: "Espessura", tagName: "LFI_RB1_ESP", dataType: "NUMERIC", analysisRole: "thickness" as const },
  { id: 30, displayName: "Largura", tagName: "LFI_RB1_LARGURA", dataType: "NUMERIC", analysisRole: "width" as const },
  { id: 40, displayName: "Comprimento %", tagName: "LFI_RB1_COMP", dataType: "NUMERIC" },
];

describe("AdvancedFiltersPanel", () => {
  it("renderiza apenas os dez campos mantidos", () => {
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={vi.fn()}
        tagOptions={tagOptions}
      />,
    );
    const kept = [
      "steelModel",
      "umCode",
      "thicknessMin",
      "thicknessMax",
      "widthMin",
      "widthMax",
      "group",
      "shift",
      "lengthPercentMin",
      "lengthPercentMax",
    ];
    for (const key of kept) {
      expect(screen.getByTestId(`named-filter-${key}`)).toBeInTheDocument();
    }
  });

  it("não renderiza nenhum campo removido", () => {
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={vi.fn()}
        tagOptions={tagOptions}
      />,
    );
    const removed = [
      "umSequenceCode",
      "genealogyCode",
      "reprocess",
      "furnace",
      "deviation",
      "lineStatus",
      "backwardMaterialRemoval",
      "coilMovement",
      "reheating",
      "defectMachine",
      "defectCode",
      "defectDescription",
      "defectCriticality",
      "eventType",
      "stopCode",
      "stopNatureCode",
      "responsibleTeamCode",
      "inputThicknessMin",
      "inputThicknessMax",
      "carbonMin",
      "carbonMax",
      "lengthAbsoluteMin",
      "lengthAbsoluteMax",
    ];
    for (const key of removed) {
      expect(screen.queryByTestId(`named-filter-${key}`)).toBeNull();
    }
  });

  it("não renderiza os grupos aposentados quality, events e input", () => {
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={vi.fn()}
        tagOptions={tagOptions}
      />,
    );
    expect(screen.queryByTestId("named-filter-group-quality")).toBeNull();
    expect(screen.queryByTestId("named-filter-group-events")).toBeNull();
    expect(screen.queryByTestId("named-filter-group-input")).toBeNull();
  });

  it("o grupo production contém apenas Turno", () => {
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={vi.fn()}
        tagOptions={tagOptions}
      />,
    );
    const group = screen.getByTestId("named-filter-group-production");
    expect(group.textContent).toContain("Turno");
    expect(group.textContent).not.toContain("Reprocesso");
    expect(group.textContent).not.toContain("Forno");
    expect(group.textContent).not.toContain("Desvio");
  });

  it("o grupo length contém apenas os limites percentuais", () => {
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={vi.fn()}
        tagOptions={tagOptions}
      />,
    );
    const group = screen.getByTestId("named-filter-group-length");
    expect(group.textContent).toContain("Comprimento mínimo %");
    expect(group.textContent).toContain("Comprimento máximo %");
    expect(group.textContent).not.toContain("absoluto");
  });

  it("uses the explicitly linked width tag instead of matching a tag by name", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={[
          { id: 99, displayName: "Largura semelhante", tagName: "OTHER_WIDTH", dataType: "NUMERIC" },
          { id: 30, displayName: "LARGURA", tagName: "LFI_RB1_LARGURA_BOBINA", dataType: "NUMERIC", analysisRole: "width" },
        ]}
      />,
    );

    fireEvent.change(screen.getByTestId("named-filter-widthMin"), { target: { value: "1240" } });
    fireEvent.change(screen.getByTestId("named-filter-widthMax"), { target: { value: "1280" } });

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      rules: [expect.objectContaining({
        kind: "numeric",
        tagId: 30,
        operator: "between",
        value: 1240,
        secondValue: 1280,
      })],
    }));

    fireEvent.click(screen.getByTestId("named-filters-apply"));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      rules: [expect.objectContaining({ tagId: 30 })],
    }));
  });

  it("largura mínima e máxima geram uma única regra between", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={[{ id: 30, displayName: "LARGURA", tagName: "LFI_RB1_LARGURA", dataType: "NUMERIC", analysisRole: "width" }]}
      />,
    );
    fireEvent.change(screen.getByTestId("named-filter-widthMin"), { target: { value: "100" } });
    fireEvent.change(screen.getByTestId("named-filter-widthMax"), { target: { value: "200" } });

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as DataFilterConfiguration;
    const widthRules = lastCall.rules.filter((r) => r.id === "named-filter:widthMin");
    expect(widthRules).toHaveLength(1);
    expect(widthRules[0]).toMatchObject({ kind: "numeric", tagId: 30, operator: "between", value: 100, secondValue: 200 });
  });

  it("limpar filtros remove todas as regras", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={tagOptions}
      />,
    );
    fireEvent.change(screen.getByTestId("named-filter-umCode"), { target: { value: "ABC" } });
    fireEvent.change(screen.getByTestId("named-filter-shift"), { target: { value: "1º turno" } });
    fireEvent.click(screen.getByTestId("filter-reset"));

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as DataFilterConfiguration;
    expect(lastCall.rules).toEqual([]);
  });

  it("nenhum campo removido entra em onChange", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={tagOptions}
      />,
    );
    for (const call of onChange.mock.calls) {
      const cfg = call[0] as DataFilterConfiguration;
      for (const rule of cfg.rules) {
        expect(rule.id).not.toMatch(/^named-filter:(reprocess|defectCode|eventType|inputThicknessMin|lengthAbsoluteMin)$/);
      }
    }
  });
});