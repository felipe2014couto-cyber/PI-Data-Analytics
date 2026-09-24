import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DatabaseTagsPage } from "../src/pages/DatabaseTagsPage";
import { SipReloadPanel } from "../src/pages/SipReloadPanel";
import { equipmentsApi, sectionsApi, sipApi, sipDatabaseTagsApi, sipReloadApi, variableTypesApi } from "../src/api";

vi.mock("../src/api", () => ({
  equipmentsApi: { list: vi.fn() },
  sectionsApi: { list: vi.fn() },
  variableTypesApi: { list: vi.fn() },
  sipApi: { list: vi.fn(), inspectColumns: vi.fn() },
  sipDatabaseTagsApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), value: vi.fn() },
  sipReloadApi: { list: vi.fn(), create: vi.fn(), cancel: vi.fn(), clearTerminal: vi.fn() },
}));

const page = (items: unknown[]) => ({ items, page: 1, page_size: 200, total: items.length, pages: 1 });
const equipment = { id: 1, name: "RB1", code: "RB1", active: true };
const variable = { id: 2, name: "Aço", code: "ACO", active: true };
const source = { id: 3, equipment_id: 1, section_id: null, variable_type_id: 2,
  name: "Aço SIP", sql_text: "SELECT TS, PV FROM T", timestamp_column: "TS", value_column: "PV", active: true };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(equipmentsApi.list).mockResolvedValue(page([equipment]) as never);
  vi.mocked(sectionsApi.list).mockResolvedValue(page([]) as never);
  vi.mocked(variableTypesApi.list).mockResolvedValue(page([variable]) as never);
  vi.mocked(sipApi.list).mockResolvedValue([source] as never);
  vi.mocked(sipDatabaseTagsApi.list).mockResolvedValue([]);
  vi.mocked(sipReloadApi.list).mockResolvedValue([]);
});

describe("SIP pages", () => {
  it("registers a database tag with Value and no timestamp", async () => {
    vi.mocked(sipApi.inspectColumns).mockResolvedValue({ columns: ["VALUE"] });
    vi.mocked(sipDatabaseTagsApi.create).mockResolvedValue({ id: 4 } as never);
    render(<DatabaseTagsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Nova Tag de Banco/ }));
    expect(screen.queryByText("Coluna Timestamp")).not.toBeInTheDocument();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "1" } });
    fireEvent.change(selects[2], { target: { value: "2" } });
    const name = screen.getAllByRole("textbox")[0];
    fireEvent.change(name, { target: { value: "Lote atual" } });
    fireEvent.change(document.querySelector("textarea")!, { target: { value: "SELECT 42 AS VALUE FROM DUAL" } });
    fireEvent.click(screen.getByRole("button", { name: "Ler colunas do SQL" }));
    await waitFor(() => expect(sipApi.inspectColumns).toHaveBeenCalled());
    fireEvent.change(screen.getAllByRole("combobox")[3], { target: { value: "VALUE" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(sipDatabaseTagsApi.create).toHaveBeenCalledWith(expect.objectContaining({
      equipment_id: 1, variable_type_id: 2, name: "Lote atual", value_column: "VALUE",
    })));
    expect(vi.mocked(sipDatabaseTagsApi.create).mock.calls[0][0]).not.toHaveProperty("timestamp_column");
  });

  it("submits the chosen SIP period in UTC", async () => {
    vi.mocked(sipReloadApi.create).mockResolvedValue({ id: 1 } as never);
    render(<SipReloadPanel />);
    await screen.findByRole("option", { name: "Aço SIP" });
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "3" } });
    const dates = document.querySelectorAll('input[type="datetime-local"]');
    fireEvent.change(dates[0], { target: { value: "2026-09-20T12:00" } });
    fireEvent.change(dates[1], { target: { value: "2026-09-20T13:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Recarregar período SIP" }));
    await waitFor(() => expect(sipReloadApi.create).toHaveBeenCalledWith(3, "2026-09-20T12:00:00.000Z", "2026-09-20T13:00:00.000Z"));
  });
});
