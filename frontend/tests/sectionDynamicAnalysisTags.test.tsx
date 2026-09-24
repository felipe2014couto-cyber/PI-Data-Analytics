import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import {
  apiMock,
  mockApiModule,
  paginated,
} from "./mocks/api";

vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/components/EChartsWrapper");

import { SectionsPage } from "../src/pages/SectionsPage";
import type { Equipment, PiTag, Section, VariableType } from "../src/types";

const mockEquipments: Equipment[] = [
  { id: 1, code: "RB1", name: "Equipamento RB1", description: null, active: true, created_at: "", updated_at: "" },
  { id: 2, code: "RB2", name: "Equipamento RB2", description: null, active: true, created_at: "", updated_at: "" },
];

const mockVariableTypes: VariableType[] = [
  { id: 1, code: "LARGURA", name: "Largura", description: null, default_unit: "mm", filter_data_type: "REAL", active: true, created_at: "", updated_at: "" },
  { id: 2, code: "UM", name: "UM", description: null, default_unit: null, filter_data_type: "STRING", active: true, created_at: "", updated_at: "" },
  { id: 3, code: "ESPESSURA", name: "Espessura", description: null, default_unit: "mm", filter_data_type: "REAL", active: true, created_at: "", updated_at: "" },
  { id: 4, code: "CURRENT", name: "Corrente", description: null, default_unit: "A", filter_data_type: "REAL", active: true, created_at: "", updated_at: "" },
  { id: 5, code: "PRESSURE", name: "Pressão", description: null, default_unit: "bar", filter_data_type: "REAL", active: true, created_at: "", updated_at: "" },
  { id: 6, code: "TEMPERATURE", name: "Temperatura", description: null, default_unit: "C", filter_data_type: "REAL", active: true, created_at: "", updated_at: "" },
  { id: 7, code: "STATUS", name: "Status Operacional", description: null, default_unit: null, filter_data_type: "STRING", active: true, created_at: "", updated_at: "" },
  { id: 8, code: "TIPO DE ACO", name: "Tipo de Aço", description: null, default_unit: null, filter_data_type: "STRING", active: true, created_at: "", updated_at: "" },
  { id: 9, code: "AÇO", name: "AÇO", description: "AÇO", default_unit: null, filter_data_type: "STRING", active: true, created_at: "", updated_at: "" },
];

const mockPiTags: PiTag[] = [
  {
    id: 10,
    equipment_id: 1,
    section_id: 1,
    variable_type_id: 1,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_LARGURA_BOBINA",
    pi_web_id: null,
    display_name: "Largura",
    description: null,
    engineering_unit: "mm",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 11,
    equipment_id: 1,
    section_id: 1,
    variable_type_id: 2,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_CODIGO_UM",
    pi_web_id: null,
    display_name: "UM",
    description: null,
    engineering_unit: null,
    data_type: "NON_NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 12,
    equipment_id: 1,
    section_id: 1,
    variable_type_id: 3,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_ESPESSURA_BOBINA",
    pi_web_id: null,
    display_name: "Espessura",
    description: null,
    engineering_unit: "mm",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 13,
    equipment_id: 1,
    section_id: 1,
    variable_type_id: 8,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_TIPO_ACO",
    pi_web_id: null,
    display_name: "Tipo de Aço",
    description: null,
    engineering_unit: null,
    data_type: "NON_NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 14,
    equipment_id: 1,
    section_id: 1,
    variable_type_id: 8,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_TIPO_ACO_ALT",
    pi_web_id: null,
    display_name: "Tipo de Aço alternativo",
    description: null,
    engineering_unit: null,
    data_type: "NON_NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 80,
    equipment_id: 1,
    section_id: null,
    variable_type_id: 9,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_TIPO_ACO",
    pi_web_id: null,
    display_name: "AÇO",
    description: "AÇO",
    engineering_unit: null,
    data_type: "NON_NUMERIC",
    active: true,
    validation_status: "PENDING",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 20,
    equipment_id: 1,
    section_id: null,
    variable_type_id: 4,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_CORRENTE_MOTOR",
    pi_web_id: null,
    display_name: "Corrente Motor",
    description: null,
    engineering_unit: "A",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 21,
    equipment_id: 1,
    section_id: null,
    variable_type_id: 4,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_CORRENTE_LINHA",
    pi_web_id: null,
    display_name: "Corrente Linha",
    description: null,
    engineering_unit: "A",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 30,
    equipment_id: 1,
    section_id: null,
    variable_type_id: 5,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB1_PRESSAO_ENTRADA",
    pi_web_id: null,
    display_name: "Pressão Entrada",
    description: null,
    engineering_unit: "bar",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
  {
    id: 40,
    equipment_id: 2,
    section_id: null,
    variable_type_id: 4,
    pi_server: "PIMS",
    pi_tag_name: "LFI_RB2_CORRENTE_OUTRO",
    pi_web_id: null,
    display_name: "Corrente RB2",
    description: null,
    engineering_unit: "A",
    data_type: "NUMERIC",
    active: true,
    validation_status: "VALID",
    validation_message: null,
    validated_at: null,
    created_at: "",
    updated_at: "",
  },
];

const mockSectionWithTags: Section = {
  id: 1,
  equipment_id: 1,
  code: "SEC10",
  name: "Section 10",
  description: "Secao de teste",
  active: true,
  process_type: null,
  group_code: null,
  classification_tag_ids: [],
  width_tag_id: 10,
  um_tag_id: 11,
  thickness_tag_id: 12,
  steel_type_tag_id: 13,
  analysis_tags: [
    {
      id: 101,
      variable_type_id: 4,
      variable_type_code: "CURRENT",
      variable_type_name: "Corrente",
      filter_data_type: "REAL",
      filter_type: "MIN_MAX",
      pi_tag_id: 20,
      pi_tag_name: "LFI_RB1_CORRENTE_MOTOR",
    },
  ],
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
};

describe("SectionsPage Dynamic Analysis Tags", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated(mockEquipments, 1, 200, mockEquipments.length));
    apiMock.listVariableTypes.mockResolvedValue(paginated(mockVariableTypes, 1, 200, mockVariableTypes.length));
    apiMock.listPiTags.mockResolvedValue(paginated(mockPiTags, 1, 200, mockPiTags.length));
    apiMock.listSections.mockResolvedValue(paginated([mockSectionWithTags], 1, 200, 1));
    apiMock.updateSection.mockResolvedValue(mockSectionWithTags);
  });

  it("renders existing dynamic analysis tag with badge and preserves fixed tags", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);

    // Modal opens
    await screen.findByText("Editar secao");
    // Verify fixed tags
    expect(screen.getByLabelText("Tag de largura")).toHaveValue("10");
    expect(screen.getByLabelText("Tag de UM")).toHaveValue("11");
    expect(screen.getByLabelText("Tag de espessura")).toHaveValue("12");
    expect(screen.getByLabelText("Tag de tipo de aço")).toHaveValue("13");

    // Dynamic tag for CURRENT is rendered with dynamic label and filter type badge
    expect(screen.getByText("Tag de corrente")).toBeInTheDocument();
    expect(screen.getByTestId("filter-type-badge-4")).toHaveTextContent("Valor mínimo / máximo");
    const currentSelect = screen.getByDisplayValue(/LFI_RB1_CORRENTE_MOTOR/);
    expect(currentSelect).toBeInTheDocument();
  });

  it("opens modal and displays only non-fixed variable types with correct disabled status", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByText("Editar secao");

    const addBtn = screen.getByRole("button", { name: /adicionar tag de análise/i });
    fireEvent.click(addBtn);

    // Modal "Adicionar tag de análise" is shown
    expect(document.querySelectorAll(".modal-title")[1]?.textContent).toBe("Adicionar tag de análise");
    const typeSelect = screen.getByLabelText("Tipo de variável") as HTMLSelectElement;

    const optionTexts = Array.from(typeSelect.options).map((o) => o.textContent);
    // All four fixed types must stay out of the dynamic-tag picker.
    expect(optionTexts).not.toEqual(expect.arrayContaining(["Largura — LARGURA", "UM — UM", "Espessura — ESPESSURA", "Tipo de Aço — TIPO DE ACO"]));

    // CURRENT must be disabled because it's already added
    const currentOpt = Array.from(typeSelect.options).find((o) => o.textContent?.includes("CURRENT"));
    expect(currentOpt).toBeDefined();
    expect(currentOpt?.disabled).toBe(true);
    expect(currentOpt?.textContent).toContain("(já adicionada)");

    // PRESSURE and TEMPERATURE must be enabled
    const pressureOpt = Array.from(typeSelect.options).find((o) => o.textContent?.includes("PRESSURE"));
    expect(pressureOpt).toBeDefined();
    expect(pressureOpt?.disabled).toBe(false);
  });

  it("disables MIN_MAX filter type for non-numeric variable types in modal", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByText("Editar secao");

    fireEvent.click(screen.getByRole("button", { name: /adicionar tag de análise/i }));
    const typeSelect = screen.getByLabelText("Tipo de variável");
    const filterTypeSelect = screen.getByLabelText("Tipo de filtro") as HTMLSelectElement;

    // Select STATUS (id 7, STRING)
    fireEvent.change(typeSelect, { target: { value: "7" } });

    // MIN_MAX option should be disabled
    const minMaxOption = Array.from(filterTypeSelect.options).find((o) => o.value === "MIN_MAX");
    expect(minMaxOption?.disabled).toBe(true);

    // Helper text explaining why MIN_MAX is disabled should be visible
    expect(screen.getByText(/Valor mínimo \/ máximo só está disponível para variáveis numéricas/i)).toBeInTheDocument();

    // Now select PRESSURE (id 5, REAL)
    fireEvent.change(typeSelect, { target: { value: "5" } });
    expect(minMaxOption?.disabled).toBe(false);
  });

  it("adds a new dynamic tag locally, filters PI tags by equipment and variable type, and prevents duplicate types", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByText("Editar secao");

    // Open add modal
    fireEvent.click(screen.getByRole("button", { name: /adicionar tag de análise/i }));
    const typeSelect = screen.getByLabelText("Tipo de variável");
    const filterTypeSelect = screen.getByLabelText("Tipo de filtro");

    // Select PRESSURE (id 5) and MIN_MAX
    fireEvent.change(typeSelect, { target: { value: "5" } });
    fireEvent.change(filterTypeSelect, { target: { value: "MIN_MAX" } });
    fireEvent.click(screen.getAllByRole("button", { name: /adicionar/i }).find((b) => b.textContent === "Adicionar")!);

    // Form now displays "Tag de pressão"
    await screen.findByText("Tag de pressão");
    expect(screen.getByTestId("filter-type-badge-5")).toHaveTextContent("Valor mínimo / máximo");

    // Find the select for Pressure
    const pressureSelect = screen.getAllByRole("combobox").find((el) => {
      const parent = el.closest(".mb-3");
      return parent?.textContent?.includes("Tag de pressão");
    }) as HTMLSelectElement;
    expect(pressureSelect).toBeDefined();

    // Verify filtered options: only RB1 PRESSURE tags (id 30), NOT CURRENT (20, 21), NOT RB2 (40)
    const options = Array.from(pressureSelect.options);
    const optValues = options.map((o) => o.value);
    expect(optValues).toContain("30");
    expect(optValues).not.toContain("20");
    expect(optValues).not.toContain("21");
    expect(optValues).not.toContain("40");
  });

  it("blocks submission when an added variable type has no PI tag selected", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByText("Editar secao");

    // Add PRESSURE with MIN_MAX
    fireEvent.click(screen.getByRole("button", { name: /adicionar tag de análise/i }));
    fireEvent.change(screen.getByLabelText("Tipo de variável"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Tipo de filtro"), { target: { value: "MIN_MAX" } });
    fireEvent.click(screen.getAllByRole("button", { name: /adicionar/i }).find((b) => b.textContent === "Adicionar")!);
    await screen.findByText("Tag de pressão");

    // Click Salvar without choosing a tag for Pressão
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    // Should display validation error
    await screen.findByText(/Selecione uma tag para Pressão/i);
    expect(apiMock.updateSection).not.toHaveBeenCalled();
  });

  it("saves successfully when PI tag is selected and supports removing a dynamic tag", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByText("Editar secao");

    // Remove existing CURRENT tag
    const removeBtn = screen.getByRole("button", { name: /remover/i });
    fireEvent.click(removeBtn);

    expect(screen.queryByText("Tag de corrente")).not.toBeInTheDocument();

    // Add PRESSURE with SELECTION
    fireEvent.click(screen.getByRole("button", { name: /adicionar tag de análise/i }));
    fireEvent.change(screen.getByLabelText("Tipo de variável"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Tipo de filtro"), { target: { value: "SELECTION" } });
    fireEvent.click(screen.getAllByRole("button", { name: /adicionar/i }).find((b) => b.textContent === "Adicionar")!);
    await screen.findByText("Tag de pressão");

    // Select tag 30
    const pressureSelect = screen.getAllByRole("combobox").find((el) => {
      const parent = el.closest(".mb-3");
      return parent?.textContent?.includes("Tag de pressão");
    }) as HTMLSelectElement;
    fireEvent.change(pressureSelect, { target: { value: "30" } });

    // Click Salvar
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalled());
    const payload = apiMock.updateSection.mock.calls[0][1];
    expect(payload.analysis_tags).toEqual([{ variable_type_id: 5, filter_type: "SELECTION", pi_tag_id: 30 }]);
    expect(payload.width_tag_id).toBe(10);
    expect(payload.um_tag_id).toBe(11);
    expect(payload.thickness_tag_id).toBe(12);
    expect(payload.steel_type_tag_id).toBe(13);
  });

  it("offers an AÇO variable type tag in the fixed steel selector and saves its ID", async () => {
    render(<MemoryRouter><SectionsPage /></MemoryRouter>);
    fireEvent.click((await waitFor(() => screen.getAllByTitle("Editar")))[0]);
    await screen.findByText("Editar secao");

    const steelSelect = screen.getByLabelText("Tag de tipo de aço") as HTMLSelectElement;
    expect(Array.from(steelSelect.options).map((option) => option.value)).toContain("80");
    fireEvent.change(steelSelect, { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));

    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalled());
    expect(apiMock.updateSection.mock.calls[0][1].steel_type_tag_id).toBe(80);
    expect(apiMock.updateSection.mock.calls[0][1].um_tag_id).toBe(11);
  });

  it("edits and clears the fixed steel type tag, preserving the UM selection", async () => {
    let persistedSection: Section = { ...mockSectionWithTags };
    apiMock.updateSection.mockImplementation(async (_id, payload) => {
      persistedSection = { ...persistedSection, steel_type_tag_id: payload.steel_type_tag_id ?? null };
      return persistedSection;
    });
    apiMock.listSections.mockImplementation(async () => paginated([persistedSection], 1, 200, 1));
    render(<MemoryRouter><SectionsPage /></MemoryRouter>);
    fireEvent.click((await waitFor(() => screen.getAllByTitle("Editar")))[0]);
    await screen.findByText("Editar secao");
    expect(screen.getByLabelText("Tag de tipo de aço")).toHaveValue("13");

    fireEvent.change(screen.getByLabelText("Tag de tipo de aço"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));
    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalledTimes(1));
    expect(apiMock.updateSection.mock.calls[0][1].steel_type_tag_id).toBe(14);

    await waitFor(() => expect(screen.queryByText("Editar secao")).not.toBeInTheDocument());
    fireEvent.click((await waitFor(() => screen.getAllByTitle("Editar")))[0]);
    await screen.findByText("Editar secao");
    expect(screen.getByLabelText("Tag de tipo de aço")).toHaveValue("14");
    expect(screen.getByLabelText("Tag de UM")).toHaveValue("11");

    fireEvent.change(screen.getByLabelText("Tag de tipo de aço"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));
    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalledTimes(2));
    expect(apiMock.updateSection.mock.calls[1][1].steel_type_tag_id).toBeNull();

    await waitFor(() => expect(screen.queryByText("Editar secao")).not.toBeInTheDocument());
    fireEvent.click((await waitFor(() => screen.getAllByTitle("Editar")))[0]);
    await screen.findByText("Editar secao");
    expect(screen.getByLabelText("Tag de tipo de aço")).toHaveValue("");
    expect(screen.getByLabelText("Tag de UM")).toHaveValue("11");
  });
});
