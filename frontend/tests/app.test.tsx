import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  connectedHealthFixture,
  makeBatchResult,
  makeValidationResult,
  mockApiModule,
  notConfiguredHealthFixture,
  paginated,
  equipmentFixture,
  piTagFixture,
  variableTypeFixture,
  sectionFixture,
} from "./mocks/api";
import { DEFAULT_PI_SERVER } from "../src/constants/pi";

vi.mock("../src/api", () => mockApiModule());

import App from "../src/App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("App layout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([]));
    apiMock.listSections.mockResolvedValue(paginated([]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([]));
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
  });

  it("renders the sidebar with the application name and menu entries", async () => {
    renderAt("/");
    const appNameElements = await screen.findAllByText("PI Analytics Data");
    expect(appNameElements.length).toBeGreaterThan(0);
    expect(screen.getAllByText("Equipamentos").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Secoes").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tipos de Variavel").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tags PI").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Visualizacao de Dados").length).toBeGreaterThan(0);
  });

  it("renders the data visualization page with empty chart state", async () => {
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
    renderAt("/analises/visualizacao");
    await waitFor(() => {
      expect(screen.getByTestId("data-visualization-page")).toBeInTheDocument();
    });
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });
});

describe("Equipments page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("loads and shows equipment list", async () => {
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(apiMock.listEquipments).toHaveBeenCalled();
    });
    expect(await screen.findByText("RB3")).toBeInTheDocument();
    expect(screen.getByText("Equipamento RB3")).toBeInTheDocument();
  });

  it("shows loading state and then empty state", async () => {
    let resolveList: (value: unknown) => void = () => undefined;
    apiMock.listEquipments.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve;
      }),
    );
    renderAt("/cadastros/equipamentos");
    expect(await screen.findByText("Carregando...")).toBeInTheDocument();
    resolveList(paginated([]));
    await waitFor(() => {
      expect(screen.getByText("Nenhum equipamento encontrado")).toBeInTheDocument();
    });
  });

  it("creates an equipment from the modal", async () => {
    apiMock.listEquipments.mockResolvedValue(paginated([]));
    apiMock.createEquipment.mockResolvedValue(equipmentFixture);
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(apiMock.listEquipments).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Novo equipamento/i });
    newButtons[0].click();
    await screen.findByRole("dialog");
    const codeInput = (await screen.findByLabelText("Codigo")) as HTMLInputElement;
    codeInput.value = "RB3";
    codeInput.dispatchEvent(new Event("input", { bubbles: true }));
    const nameInput = screen.getByLabelText("Nome") as HTMLInputElement;
    nameInput.value = "Equipamento RB3";
    nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    const form = screen.getByRole("dialog").querySelector("form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => {
      expect(apiMock.createEquipment).toHaveBeenCalled();
    });
  });
});

describe("Sections page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("filters sections when equipment changes", async () => {
    const sectionA = { ...sectionFixture, id: 1, code: "FORNO" };
    apiMock.listSections.mockResolvedValue(paginated([sectionA]));
    renderAt("/cadastros/secoes");
    await waitFor(() => {
      expect(apiMock.listSections).toHaveBeenCalled();
    });
    const initialCalls = apiMock.listSections.mock.calls.length;
    const select = (await screen.findByLabelText("Equipamento")) as HTMLSelectElement;
    select.value = "1";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => {
      expect(apiMock.listSections.mock.calls.length).toBeGreaterThan(initialCalls);
    });
    const lastCall = apiMock.listSections.mock.calls[apiMock.listSections.mock.calls.length - 1][0];
    expect(lastCall.equipment_id).toBe(1);
  });
});

describe("VariableTypes page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("creates a variable type", async () => {
    apiMock.listVariableTypes.mockResolvedValue(paginated([]));
    apiMock.createVariableType.mockResolvedValue(variableTypeFixture);
    renderAt("/cadastros/tipos-variavel");
    await waitFor(() => {
      expect(apiMock.listVariableTypes).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Novo tipo/i });
    newButtons[0].click();
    await screen.findByRole("dialog");
    const codeInput = (await screen.findByLabelText("Codigo")) as HTMLInputElement;
    codeInput.value = "TEMPERATURE";
    codeInput.dispatchEvent(new Event("input", { bubbles: true }));
    const nameInput = screen.getByLabelText("Nome") as HTMLInputElement;
    nameInput.value = "Temperatura";
    nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    const form = screen.getByRole("dialog").querySelector("form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => {
      expect(apiMock.createVariableType).toHaveBeenCalled();
    });
  });
});

describe("PiTags page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
  });

  it("creates a new tag with PENDING status by default", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.createPiTag.mockImplementation(async (payload) => ({
      ...piTagFixture,
      ...payload,
      validation_status: "PENDING",
    }));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons[0].click();
    await screen.findByRole("dialog");
    expect(screen.getByText("Status de validacao inicial:")).toBeInTheDocument();
    expect(screen.getAllByText("Pendente").length).toBeGreaterThan(0);
  });

  it("clears section when equipment changes in the form", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons[0].click();
    await screen.findByRole("dialog");
    const dialog = screen.getByRole("dialog");
    const equipmentSelect = dialog.querySelector<HTMLSelectElement>("#tag-equipment-form");
    expect(equipmentSelect).toBeTruthy();
    if (equipmentSelect) {
      equipmentSelect.value = "1";
      equipmentSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const sectionSelect = dialog.querySelector<HTMLSelectElement>("#tag-section-form");
    expect(sectionSelect).toBeTruthy();
    expect(sectionSelect?.disabled).toBe(false);
  });

  it("does not show PI Server label, input, or helper text in the create modal", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons[0].click();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("PI Server");
    expect(dialog.textContent).not.toContain("Definido automaticamente.");
    expect(dialog.textContent).not.toContain(DEFAULT_PI_SERVER);
    const piServerInput = dialog.querySelector("input#tag-server");
    expect(piServerInput).toBeNull();
  });

  it("sends DEFAULT_PI_SERVER in the create payload", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.createPiTag.mockResolvedValue(piTagFixture);
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons[0].click();
    const dialog = await screen.findByRole("dialog");
    const equipmentSelect = dialog.querySelector<HTMLSelectElement>("#tag-equipment-form");
    expect(equipmentSelect).toBeTruthy();
    if (equipmentSelect) {
      equipmentSelect.value = "1";
      equipmentSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const sectionSelect = dialog.querySelector<HTMLSelectElement>("#tag-section-form");
    if (sectionSelect) {
      await waitFor(() => expect(sectionSelect.disabled).toBe(false));
      sectionSelect.value = "1";
      sectionSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const vtSelect = dialog.querySelector<HTMLSelectElement>("#tag-vt-form");
    if (vtSelect) {
      vtSelect.value = "1";
      vtSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const nameInput = dialog.querySelector<HTMLInputElement>("#tag-pi-name");
    if (nameInput) {
      nameInput.value = "RB3.FURNO.TEMP";
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const displayInput = dialog.querySelector<HTMLInputElement>("#tag-display");
    if (displayInput) {
      displayInput.value = "Tag de teste";
      displayInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const form = dialog.querySelector("form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => {
      expect(apiMock.createPiTag).toHaveBeenCalled();
    });
    const payload = apiMock.createPiTag.mock.calls[0][0];
    expect(payload.pi_server).toBe(DEFAULT_PI_SERVER);
  });

  it("does not show PI Server info when canceling and reopening the modal", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const newButtons = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons[0].click();
    const dialog1 = await screen.findByRole("dialog");
    expect(dialog1.textContent).not.toContain("PI Server");
    expect(dialog1.textContent).not.toContain(DEFAULT_PI_SERVER);
    expect(dialog1.textContent).not.toContain("Definido automaticamente.");
    const cancelButton = screen.getByRole("button", { name: /Cancelar/i });
    cancelButton.click();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const newButtons2 = await screen.findAllByRole("button", { name: /Nova tag PI/i });
    newButtons2[0].click();
    const dialog2 = await screen.findByRole("dialog");
    expect(dialog2.textContent).not.toContain("PI Server");
    expect(dialog2.textContent).not.toContain(DEFAULT_PI_SERVER);
    expect(dialog2.textContent).not.toContain("Definido automaticamente.");
  });

  it("does not show PI Server info when editing a tag", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const editButton = await screen.findByTitle("Editar");
    editButton.click();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("PI Server");
    expect(dialog.textContent).not.toContain(DEFAULT_PI_SERVER);
    expect(dialog.textContent).not.toContain("Definido automaticamente.");
    expect(screen.getByText("Editar tag PI")).toBeInTheDocument();
    const piServerInput = dialog.querySelector("input#tag-server");
    expect(piServerInput).toBeNull();
  });

  it("preserves legacy pi_server value in the update payload when editing", async () => {
    const legacyTag = { ...piTagFixture, pi_server: "LEGACY_SRV" };
    apiMock.listPiTags.mockResolvedValue(paginated([legacyTag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.updatePiTag.mockResolvedValue(legacyTag);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const editButton = await screen.findByTitle("Editar");
    editButton.click();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("LEGACY_SRV");
    const displayInput = dialog.querySelector<HTMLInputElement>("#tag-display");
    if (displayInput) {
      fireEvent.change(displayInput, { target: { value: "Nome atualizado" } });
    }
    const form = dialog.querySelector("form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => {
      expect(apiMock.updatePiTag).toHaveBeenCalled();
    });
    const updatePayload = apiMock.updatePiTag.mock.calls[0][1];
    expect(updatePayload.pi_server).toBe("LEGACY_SRV");
    expect(updatePayload.display_name).toBe("Nome atualizado");
  });

  it("keeps pi_server unchanged in update payload when editing display_name", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.updatePiTag.mockResolvedValue(piTagFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const editButton = await screen.findByTitle("Editar");
    editButton.click();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("PI Server");
    const displayInput = dialog.querySelector<HTMLInputElement>("#tag-display");
    if (displayInput) {
      fireEvent.change(displayInput, { target: { value: "Novo nome amigavel" } });
    }
    const form = dialog.querySelector("form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => {
      expect(apiMock.updatePiTag).toHaveBeenCalled();
    });
    const updatePayload = apiMock.updatePiTag.mock.calls[0][1];
    expect(updatePayload.pi_server).toBe(DEFAULT_PI_SERVER);
    expect(updatePayload.display_name).toBe("Novo nome amigavel");
  });
});

describe("Confirm modal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("asks for confirmation before deleting an equipment", async () => {
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(apiMock.listEquipments).toHaveBeenCalled();
    });
    const deleteButton = await screen.findByTitle("Excluir");
    deleteButton.click();
    expect(await screen.findByText("Excluir equipamento")).toBeInTheDocument();
  });
});

describe("PI Web API integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
  });

  it("shows the PI connection status as not configured when no settings", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
    renderAt("/cadastros/tags-pi");
    const badge = await screen.findByTestId("pi-status");
    expect(badge.getAttribute("data-status")).toBe("not_configured");
    expect(badge.textContent).toContain("PI nao configurado");
  });

  it("shows the PI connection status as connected when healthy", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    const badge = await screen.findByTestId("pi-status");
    expect(badge.getAttribute("data-status")).toBe("connected");
    expect(badge.textContent).toContain("PI conectado");
    expect(screen.getByText("Base URL: https://pi.local/piwebapi")).toBeInTheDocument();
  });

  it("displays the PENDING badge for newly created tags", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const row = await screen.findByTestId("pi-tag-row-1");
    expect(row.getAttribute("data-status")).toBe("PENDING");
  });

  it("displays the VALID badge after successful validation", async () => {
    const validTag = { ...piTagFixture, validation_status: "VALID" as const, pi_web_id: "W-1" };
    apiMock.listPiTags.mockResolvedValue(paginated([validTag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const row = await screen.findByTestId("pi-tag-row-1");
    expect(row.getAttribute("data-status")).toBe("VALID");
    expect(row.textContent).toContain("Valida");
    expect(screen.getByTestId("pi-webid").textContent).toContain("W-1");
  });

  it("displays the INVALID badge when PI rejects the tag", async () => {
    const invalidTag = { ...piTagFixture, validation_status: "INVALID" as const, pi_web_id: null };
    apiMock.listPiTags.mockResolvedValue(paginated([invalidTag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const row = await screen.findByTestId("pi-tag-row-1");
    expect(row.getAttribute("data-status")).toBe("INVALID");
    expect(row.textContent).toContain("Invalida");
  });

  it("displays the ERROR badge when PI communication fails", async () => {
    const errorTag = { ...piTagFixture, validation_status: "ERROR" as const };
    apiMock.listPiTags.mockResolvedValue(paginated([errorTag]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const row = await screen.findByTestId("pi-tag-row-1");
    expect(row.getAttribute("data-status")).toBe("ERROR");
    expect(row.textContent).toContain("Erro");
  });

  it("validates a single tag and shows the result modal", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.validatePiTag.mockResolvedValue(
      makeValidationResult(1, "VALID", { web_id: "W-99", message: "OK" }),
    );
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const button = await screen.findByTestId("validate-1");
    fireEvent.click(button);
    await waitFor(() => {
      expect(apiMock.validatePiTag).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByText("Resultado da validacao")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getAllByTestId("pi-webid").length).toBeGreaterThan(0);
  });

  it("shows loading state while validating a tag", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    let resolveValidate: (value: unknown) => void = () => undefined;
    apiMock.validatePiTag.mockReturnValue(
      new Promise((resolve) => {
        resolveValidate = resolve;
      }),
    );
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const button = await screen.findByTestId("validate-1");
    fireEvent.click(button);
    expect(button).toBeDisabled();
    resolveValidate(makeValidationResult(1, "VALID"));
    await waitFor(() => {
      expect(apiMock.validatePiTag).toHaveBeenCalled();
    });
  });

  it("runs a batch validation and shows the summary message", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture, { ...piTagFixture, id: 2 }]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
    apiMock.validateBatchPiTags.mockResolvedValue(
      makeBatchResult([
        { tagId: 1, status: "VALID" },
        { tagId: 2, status: "INVALID" },
      ]),
    );
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const batchButton = await screen.findByTestId("validate-batch");
    fireEvent.click(batchButton);
    await waitFor(() => {
      expect(apiMock.validateBatchPiTags).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(/Validacao concluida: 1 validas, 1 invalidas, 0 com erro/),
    ).toBeInTheDocument();
  });

  it("disables validation buttons when the PI is not configured", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    const button = await screen.findByTestId("validate-1");
    expect(button).toBeDisabled();
    const batchButton = await screen.findByTestId("validate-batch");
    expect(batchButton).toBeDisabled();
  });

  it("shows an error when the backend PI health endpoint fails", async () => {
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockRejectedValue(new Error("Network error"));
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(apiMock.listPiTags).toHaveBeenCalled();
    });
    expect(await screen.findByText("Falha ao consultar /api/pi/health")).toBeInTheDocument();
  });
});
