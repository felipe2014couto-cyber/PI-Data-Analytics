import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiMock, mockApiModule } from "./mocks/api";
vi.mock("../src/api", () => mockApiModule());
import { VisualConfigurationsPanel } from "../src/components/VisualConfigurationsPanel";

const rules = { enabled: false, selectedSeriesInstanceId: null, bySeries: {} };
const saved = { id: "c1", name: "Teste", description: null, current_version: 1, created_at: "2026-01-01", updated_at: "2026-01-01", document: { schema_version: 1 as const, visual_rules: rules } };
const panel = (onOpen = vi.fn(), mode: "recorded" | "interpolated" = "interpolated") =>
  <VisualConfigurationsPanel visualRules={rules} mode={mode} onOpen={onOpen} />;

describe("persistência visual", () => {
  beforeEach(() => { vi.clearAllMocks(); apiMock.visualConfigList.mockResolvedValue([]); });
  it("salva sem consultar o PI", async () => {
    apiMock.visualConfigCreate.mockResolvedValue(saved); render(panel());
    fireEvent.change(screen.getByTestId("visual-config-name"), { target: { value: "Teste" } }); fireEvent.click(screen.getByText("Salvar nova"));
    await waitFor(() => expect(apiMock.visualConfigCreate).toHaveBeenCalledWith("Teste", { schema_version: 1, visual_rules: { ...rules, queryMode: "interpolated" } }));
    expect(apiMock.timeSeriesQuery).not.toHaveBeenCalled(); expect(apiMock.cancelQuery).not.toHaveBeenCalled();
  });
  it("abre uma configuração sem perder o estado antes da resposta", async () => {
    let resolve!: (value: typeof saved) => void; apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigGet.mockReturnValue(new Promise((done) => { resolve = done; })); const onOpen = vi.fn();
    render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); fireEvent.click(screen.getByText("Abrir")); expect(onOpen).not.toHaveBeenCalled(); resolve(saved); await waitFor(() => expect(onOpen).toHaveBeenCalledWith(rules, "interpolated"));
  });
  it("respeita o modo armazenado ao abrir uma configuração", async () => {
    const recorded = { ...saved, document: { ...saved.document, visual_rules: { ...rules, queryMode: "recorded" as const } } };
    apiMock.visualConfigList.mockResolvedValue([recorded]); apiMock.visualConfigGet.mockResolvedValue(recorded); const onOpen = vi.fn();
    render(panel(onOpen)); await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); fireEvent.click(screen.getByText("Abrir"));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(recorded.document.visual_rules, "recorded"));
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
    fireEvent.click(screen.getByText("Abrir"));
    await waitFor(() => expect(onOpen).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Histórico"));
    fireEvent.click(await screen.findByText("Restaurar"));
    await waitFor(() => expect(onOpen).toHaveBeenLastCalledWith(restored.document.visual_rules, "recorded"));
  });
  it("informa conflito e preserva o estado visual", async () => {
    apiMock.visualConfigList.mockResolvedValue([saved]); apiMock.visualConfigGet.mockResolvedValue(saved); apiMock.visualConfigUpdate.mockRejectedValue({ status: 409 }); const onOpen = vi.fn(); render(panel(onOpen));
    await waitFor(() => expect(apiMock.visualConfigList).toHaveBeenCalled()); fireEvent.change(screen.getByTestId("visual-config-select"), { target: { value: "c1" } }); fireEvent.click(screen.getByText("Abrir")); await waitFor(() => expect(onOpen).toHaveBeenCalled()); fireEvent.click(screen.getByText("Salvar alterações")); expect(await screen.findByText(/Não foi possível concluir/)).toBeInTheDocument(); expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
