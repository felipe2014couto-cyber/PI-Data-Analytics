import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { apiMock, mockApiModule } from "./mocks/api";
import type { DataFilterConfiguration } from "../src/types";

vi.mock("../src/api", () => mockApiModule());

import { AdvancedFiltersPanel } from "../src/components/AdvancedFiltersPanel";

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
    expect(screen.getByTestId("named-filter-steelModel")).toHaveValue("");
    expect(screen.getByTestId("named-filter-steelModel")).toHaveAttribute("placeholder", "Digite o aço");
  });

  it("aceita código completo e curinga na tag fixa de aço, mantendo UM independente", () => {
    const onChange = vi.fn();
    const fixedTagOptions = [
      ...tagOptions,
      { id: 80, displayName: "AÇO", tagName: "LFI_RB1_TIPO_ACO", dataType: "TEXT", analysisRole: "steelType" as const },
      { id: 51, displayName: "Código UM", tagName: "LFI.RB1.UM", dataType: "TEXT", analysisRole: "um" as const },
    ];
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={fixedTagOptions}
      />,
    );

    const steelModel = screen.getByTestId("named-filter-steelModel");
    expect(steelModel).not.toHaveAttribute("list");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByText("Use ; para vários aços e * antes, no meio ou depois. Ex.: P304A;P49*.")).toBeInTheDocument();
    fireEvent.change(steelModel, { target: { value: "P498A" } });
    expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].rules).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "named-filter:steelModel", tagId: 80, operator: "equal", value: "P498A" }),
    ]));

    fireEvent.change(steelModel, { target: { value: "P49*" } });
    for (const value of ["*98A", "P*8A"]) {
      fireEvent.change(steelModel, { target: { value } });
      expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].rules).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: "named-filter:steelModel", tagId: 80, operator: "wildcard", value }),
      ]));
    }
    fireEvent.change(steelModel, { target: { value: "P304A ; P49* ; P999Z" } });
    expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].rules).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "named-filter:steelModel", tagId: 80, operator: "wildcard", value: "P304A;P49*;P999Z" }),
    ]));
    fireEvent.change(steelModel, { target: { value: "P49*" } });
    fireEvent.change(screen.getByTestId("named-filter-umCode"), { target: { value: "UM-123" } });
    fireEvent.click(screen.getByTestId("named-filters-apply"));
    expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].rules).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "named-filter:steelModel", tagId: 80, operator: "wildcard", value: "P49*" }),
      expect.objectContaining({ id: "named-filter:umCode", tagId: 51, operator: "contains", value: "UM-123" }),
    ]));
    expect(apiMock.getDistinctValues).not.toHaveBeenCalledWith(80);
  });

  it("permite digitar aço mesmo quando a tag configurada não tem valores distintos locais", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={[...tagOptions, { id: 80, displayName: "AÇO", tagName: "LFI_RB1_TIPO_ACO", dataType: "TEXT", analysisRole: "steelType" as const }]}
      />,
    );

    const steelModel = screen.getByTestId("named-filter-steelModel");
    fireEvent.change(steelModel, { target: { value: "P304A" } });
    expect(steelModel).toHaveValue("P304A");
    expect(onChange.mock.calls[onChange.mock.calls.length - 1]?.[0].rules).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "named-filter:steelModel", tagId: 80, operator: "equal", value: "P304A" }),
    ]));
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