import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiMock, mockApiModule } from "./mocks/api";
vi.mock("../src/api", () => mockApiModule());
import { VisualConfigurationsPanel } from "../src/components/VisualConfigurationsPanel";

const rules = { enabled: false, selectedSeriesInstanceId: null, bySeries: {} };
const saved = { id: "c1", name: "Teste", description: null, current_version: 1, created_at: "2026-01-01", updated_at: "2026-01-01", document: { schema_version: 1 as const, visual_rules: rules } };
const panel = (onOpen = vi.fn(), mode: "recorded" | "interpolated" = "interpolated") =>
  <VisualConfigurationsPanel document={{ schema_version: 1, visual_rules: { ...rules, queryMode: mode } }} onOpen={onOpen} />;
const chooseAction = (label: string) => {
  fireEvent.click(screen.getByRole("button", { name: "Ações da configuração" }));
  fireEvent.click(screen.getByText(label));
};

describe("persistência visual", () => {
  beforeEach(() => { vi.clearAllMocks(); apiMock.visualConfigList.mockResolvedValue([]); apiMock.visualConfigHistory.mockResolvedValue([]); });
  it("salva sem consultar o PI", async () => {
    apiMock.visualConfigCreate.mockResolvedValue(saved); render(panel());
    chooseAction("Salvar nova");
    fireEvent.change(screen.getByTestId("visual-config-name"), { target: { value: "Teste" } }); fireEvent.click(within(screen.getByRole("dialog")).getByText("Salvar nova"));
    await waitFor(() => expect(apiMock.visualConfigCreate).toHaveBeenCalledWith("Teste", { schema_version: 1, visual_rules: { ...rules, queryMode: "interpolated" } }));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled(); expect(apiMock.cancelQuery).not.toHaveBeenCalled();
  });
  it("abre uma configuração sem perder o estado antes da resposta", async () => {
    let resolve!: (value: typeof saved) => void; apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigGet.mockReturnValue(new Promise((done) => { resolve = done; })); const onOpen = vi.fn();
    render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Abrir"); expect(onOpen).not.toHaveBeenCalled(); resolve(saved); await waitFor(() => expect(onOpen).toHaveBeenCalledWith(saved.document));
  });
  it("respeita o modo armazenado ao abrir uma configuração", async () => {
    const recorded = { ...saved, document: { ...saved.document, visual_rules: { ...rules, queryMode: "recorded" as const } } };
    apiMock.visualConfigList.mockResolvedValue([recorded]); apiMock.visualConfigGet.mockResolvedValue(recorded); const onOpen = vi.fn();
    render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Abrir");
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(recorded.document));
  });
  it("usa o mesmo documento completo para criar e salvar uma nova versão", async () => {
    const completeDocument = { ...saved.document, sidebar_state: { filters: { analysisModel: "unit" as const, equipmentId: 1, sectionId: 2, variableTypeId: 3, timePeriod: { kind: "preset" as const, preset: "PT1H" as const }, timezone: "America/Sao_Paulo" as const, mode: "recorded" as const, interval: "5m", maxCount: 2000, resolutionMode: "manual", targetPointsPerTag: 5000, ignoreBadQuality: false, visualization: "line" as const, filterConfiguration: { quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false }, rules: [] } }, selectedTagIds: [2, 1], seriesAssignments: [], metricConfiguration: { kind: "none" as const }, comparison: { type: "disabled" as const, contextBEquipmentId: null, contextBCategoryId: null, contextBTagIds: [], contextBStart: "", contextBEnd: "" } } };
    apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigCreate.mockResolvedValue(saved); apiMock.visualConfigGet.mockResolvedValue(saved); apiMock.visualConfigUpdate.mockResolvedValue({ ...saved, current_version: 2 });
    render(<VisualConfigurationsPanel document={completeDocument} onOpen={vi.fn()} />); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    chooseAction("Salvar nova"); fireEvent.change(screen.getByTestId("visual-config-name"), { target: { value: "Completa" } }); fireEvent.click(within(screen.getByRole("dialog")).getByText("Salvar nova"));
    await waitFor(() => expect(apiMock.visualConfigCreate).toHaveBeenCalledWith("Completa", completeDocument));
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Abrir"); await waitFor(() => expect(apiMock.visualConfigGet).toHaveBeenCalled());
    chooseAction("Salvar alterações"); await waitFor(() => expect(apiMock.visualConfigUpdate).toHaveBeenCalledWith("c1", 1, completeDocument));
  });
  it("respeita o modo da versão restaurada", async () => {
    const current = { ...saved, current_version: 2 };
    const restored = { ...saved, current_version: 3, document: { ...saved.document, visual_rules: { ...rules, queryMode: "recorded" as const } } };
    apiMock.visualConfigList.mockResolvedValue([current]);
    apiMock.visualConfigGet.mockResolvedValue(current);
    apiMock.visualConfigHistory.mockResolvedValue([{ id: "v1", version: 1, document: restored.document, operation: "create", created_at: "2026-01-01" }]);
    apiMock.visualConfigRestore.mockResolvedValue(restored);
    const onOpen = vi.fn();
    render(panel(onOpen));
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } });
    chooseAction("Abrir");
    await waitFor(() => expect(onOpen).toHaveBeenCalled());
    chooseAction("Histórico");
    fireEvent.click(await screen.findByText("Restaurar"));
    await waitFor(() => expect(onOpen).toHaveBeenLastCalledWith(restored.document));
  });
  it("abre uma versão histórica sem criar ou restaurar outra versão", async () => {
    const current = { ...saved, current_version: 2 };
    const historical = { id: "v1", version: 1, document: saved.document, operation: "create", created_at: "2026-01-01" };
    apiMock.visualConfigList.mockResolvedValue([current]); apiMock.visualConfigHistory.mockResolvedValue([{ ...historical, version: 2 }, historical]);
    apiMock.visualConfigGet.mockResolvedValue(current); apiMock.visualConfigGetVersion.mockResolvedValue(historical);
    const onOpen = vi.fn(); render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } });
    await waitFor(() => expect(screen.getByTestId("visual-config-version-select")).toHaveValue("2"));
    fireEvent.change(screen.getByTestId("visual-config-version-select"), { target: { value: "1" } }); chooseAction("Abrir");
    await waitFor(() => expect(apiMock.visualConfigGetVersion).toHaveBeenCalledWith("c1", 1));
    expect(onOpen).toHaveBeenCalledWith(historical.document);
    expect(apiMock.visualConfigRestore).not.toHaveBeenCalled();
    expect(apiMock.visualConfigUpdate).not.toHaveBeenCalled();
    expect(screen.getByText("Aberta: Teste, versão 1")).toBeInTheDocument();
  });
  it("informa conflito e preserva o estado visual", async () => {
    apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigGet.mockResolvedValue(saved); apiMock.visualConfigUpdate.mockRejectedValue({ status: 409 }); const onOpen = vi.fn(); render(panel(onOpen));
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled()); fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Abrir"); await waitFor(() => expect(onOpen).toHaveBeenCalled()); chooseAction("Salvar alterações"); expect(await screen.findByText(/Não foi possível concluir/)).toBeInTheDocument(); expect(onOpen).toHaveBeenCalledTimes(1);
  });
  it("pesquisa localmente sem abrir nem consultar novamente a API", async () => {
    const other = { ...saved, id: "c2", name: "Outro modelo", current_version: 3 };
    apiMock.visualConfigList.mockResolvedValue([saved, other]);
    const onOpen = vi.fn(); render(panel(onOpen));
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Pesquisar configuração" }));
    const input = await screen.findByRole("textbox", { name: "Pesquisar pelo nome da configuração" });
    fireEvent.change(input, { target: { value: "OUTRO" } });
    expect(screen.queryByText("Teste")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Outro modelo"));
    expect(screen.getByTestId("visual-config-select")).toHaveValue("c2");
    expect(apiMock.visualConfigList).toHaveBeenCalledTimes(1);
    expect(apiMock.visualConfigGet).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });
  it("exibe a exclusão desabilitada sem seleção", async () => {
    render(panel()); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Ações da configuração" }));
    expect(screen.getByText("Excluir configuração")).toHaveClass("disabled", "text-danger");
  });
  it("abre confirmação e cancelar não exclui", async () => {
    apiMock.visualConfigList.mockResolvedValue([saved]); render(panel());
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } });
    chooseAction("Excluir configuração");
    expect(screen.getByRole("dialog")).toHaveTextContent('A configuração "Teste" e todas as suas versões');
    expect(apiMock.visualConfigRemove).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancelar"));
    expect(apiMock.visualConfigRemove).not.toHaveBeenCalled();
    expect(screen.getByTestId("visual-config-select")).toHaveValue("c1");
  });
  it("exclui uma única vez, remove o item e limpa seleção e configuração aberta", async () => {
    let resolve!: () => void;
    apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigGet.mockResolvedValue(saved);
    apiMock.visualConfigRemove.mockReturnValue(new Promise<void>((done) => { resolve = done; }));
    const onOpen = vi.fn(); render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Abrir");
    await screen.findByText("Aberta: Teste, versão 1"); chooseAction("Excluir configuração");
    const confirm = within(screen.getByRole("dialog")).getByText("Excluir configuração");
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(apiMock.visualConfigRemove).toHaveBeenCalledTimes(1); expect(confirm).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByTestId("visual-config-select")).toHaveValue("");
    expect(screen.queryByRole("option", { name: "Teste (v1)" })).not.toBeInTheDocument();
    expect(screen.queryByText("Aberta: Teste, versão 1")).not.toBeInTheDocument();
    expect(screen.getByText("Configuração excluída.")).toBeInTheDocument();
  });
  it("mantém item, seleção e confirmação quando a exclusão falha", async () => {
    apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigRemove.mockRejectedValue(new Error("falha")); render(panel());
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); chooseAction("Excluir configuração");
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Excluir configuração"));
    expect(await screen.findByTestId("visual-config-delete-error")).toHaveTextContent("Não foi possível excluir");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("visual-config-select")).toHaveValue("c1");
    expect(screen.getByRole("option", { name: "Teste (v1)" })).toBeInTheDocument();
  });
});
