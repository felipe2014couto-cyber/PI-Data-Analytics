import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { HistoricalReloadPage } from "../src/pages/HistoricalReloadPage";
import { equipmentsApi, historicalReloadApi, piTagsApi, sectionsApi } from "../src/api";

vi.mock("../src/api", () => ({
  equipmentsApi: {
    list: vi.fn(),
  },
  piTagsApi: {
    list: vi.fn(),
  },
  sectionsApi: {
    list: vi.fn(),
  },
  historicalReloadApi: {
    list: vi.fn(),
    summary: vi.fn(),
    create: vi.fn(),
    cancelBatch: vi.fn(),
    clearTerminal: vi.fn(),
  },
}));

describe("HistoricalReloadPage Sorting", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(equipmentsApi.list).mockResolvedValue({
      items: [
        { id: 1, name: "Equipamento Alpha", code: "EQ_A", description: null, active: true, created_at: "", updated_at: "" },
        { id: 2, name: "Equipamento Zulu", code: "EQ_Z", description: null, active: true, created_at: "", updated_at: "" },
      ],
      page: 1,
      page_size: 200,
      total: 2,
      pages: 1,
    });

    vi.mocked(sectionsApi.list).mockResolvedValue({
      items: [
        {
          id: 1,
          equipment_id: 2,
          name: "Zona Sul",
          code: "ZS",
          description: null,
          active: true,
          process_type: null,
          group_code: null,
          classification_tag_ids: [],
          width_tag_id: null,
          um_tag_id: null,
          thickness_tag_id: null,
          created_at: "",
          updated_at: "",
        },
      ],
      page: 1,
      page_size: 200,
      total: 1,
      pages: 1,
    });

    vi.mocked(piTagsApi.list).mockResolvedValue({
      items: [
        {
          id: 10,
          equipment_id: 2,
          section_id: 1,
          variable_type_id: 1,
          pi_server: "PIMS",
          pi_tag_name: "TAG_BETA",
          pi_web_id: "W10",
          display_name: "Beta Sensor",
          description: null,
          engineering_unit: "C",
          data_type: "NUMERIC",
          active: true,
          validation_status: "VALID",
          validation_message: null,
          validated_at: null,
          created_at: "",
          updated_at: "",
        },
        {
          id: 20,
          equipment_id: 1,
          section_id: 1,
          variable_type_id: 1,
          pi_server: "PIMS",
          pi_tag_name: "TAG_ALPHA",
          pi_web_id: "W20",
          display_name: "Alpha Sensor",
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
      ],
      page: 1,
      page_size: 200,
      total: 2,
      pages: 1,
    });

    vi.mocked(historicalReloadApi.summary).mockResolvedValue({
      total_active_tags: 2,
      tags_with_data: 2,
      tags_without_data: 0,
      partial_tags: 0,
      modes: [],
    });

    vi.mocked(historicalReloadApi.list).mockResolvedValue([
      {
        id: 101,
        tag_id: 10, // Beta Sensor, Equipamento Zulu
        status: "RUNNING",
        stage: "FETCHING",
        next_start: null,
        attempts: 1,
        lease_owner: null,
        lease_expires_at: null,
        next_attempt_at: null,
        progress_percent: 25,
        target_start: "2026-09-01T00:00:00Z",
        target_end: "2026-09-02T00:00:00Z",
        mode: "recorded",
        interval: null,
        created_at: "2026-09-01T00:00:00Z",
        updated_at: "2026-09-01T00:00:00Z",
        heartbeat_at: "2026-09-01T00:01:00Z",
        error_message: null,
      },
      {
        id: 102,
        tag_id: 20, // Alpha Sensor, Equipamento Alpha
        status: "COMPLETED",
        stage: "DONE",
        next_start: null,
        attempts: 1,
        lease_owner: null,
        lease_expires_at: null,
        next_attempt_at: null,
        progress_percent: 100,
        target_start: "2026-09-10T00:00:00Z",
        target_end: "2026-09-11T00:00:00Z",
        mode: "recorded",
        interval: null,
        created_at: "2026-09-10T00:00:00Z",
        updated_at: "2026-09-10T00:00:00Z",
        heartbeat_at: null,
        error_message: null,
      },
    ]);
  });

  it("renders sorting dropdown and clickable column headers", async () => {
    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    const table = await screen.findByRole("table");
    await waitFor(() => {
      expect(screen.getByLabelText("Ordenar recargas")).toBeInTheDocument();
    });

    // Check table headers within table
    expect(within(table).getByRole("button", { name: /Recarga/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Equipamento/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Tag/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Progresso/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Modo/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Período/i })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /Status/i })).toBeInTheDocument();
  });

  it("sorts by Equipamento A-Z and Z-A", async () => {
    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    const table = await screen.findByRole("table");
    await waitFor(() => {
      expect(within(table).getByText("Equipamento Alpha")).toBeInTheDocument();
      expect(within(table).getByText("Equipamento Zulu")).toBeInTheDocument();
    });

    const sortSelect = screen.getByLabelText("Ordenar recargas") as HTMLSelectElement;

    // Change to Equipamento A - Z
    fireEvent.change(sortSelect, { target: { value: "equipment_asc" } });

    // Table rows
    let rows = within(table).getAllByRole("row");
    // Row 0 is thead, Row 1 is first item, Row 2 is second item
    expect(rows[1]).toHaveTextContent("Equipamento Alpha");
    expect(rows[2]).toHaveTextContent("Equipamento Zulu");

    // Click on Equipamento header to toggle to Z - A
    const eqHeader = within(table).getByRole("button", { name: /Equipamento/i });
    fireEvent.click(eqHeader);

    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Equipamento Zulu");
    expect(rows[2]).toHaveTextContent("Equipamento Alpha");
  });

  it("sorts by Tag alphabetically", async () => {
    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    const table = await screen.findByRole("table");
    await waitFor(() => {
      expect(within(table).getByText(/Alpha Sensor/i)).toBeInTheDocument();
      expect(within(table).getByText(/Beta Sensor/i)).toBeInTheDocument();
    });

    const tagHeader = within(table).getByRole("button", { name: /^Tag/i });
    // First click -> asc
    fireEvent.click(tagHeader);

    let rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Alpha Sensor");
    expect(rows[2]).toHaveTextContent("Beta Sensor");

    // Second click -> desc
    fireEvent.click(tagHeader);
    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Beta Sensor");
    expect(rows[2]).toHaveTextContent("Alpha Sensor");
  });

  it("sorts by Progresso and Status", async () => {
    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    const table = await screen.findByRole("table");
    await waitFor(() => {
      expect(within(table).getByText("100.0%")).toBeInTheDocument();
      expect(within(table).getByText("25.0%")).toBeInTheDocument();
    });

    // Sort by Progress (desc: highest first)
    const progressHeader = screen.getByRole("button", { name: /Progresso/i });
    fireEvent.click(progressHeader);

    let rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("100.0%");
    expect(rows[2]).toHaveTextContent("25.0%");

    // Toggle Progress (asc: lowest first)
    fireEvent.click(progressHeader);
    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("25.0%");
    expect(rows[2]).toHaveTextContent("100.0%");

    // Sort by Status (asc: active first)
    const statusHeader = screen.getByRole("button", { name: /Status/i });
    fireEvent.click(statusHeader);
    rows = within(table).getAllByRole("row");
    // #101 is RUNNING (isActivelyProcessing), #102 is COMPLETED
    expect(rows[1]).toHaveTextContent("#101");
    expect(rows[2]).toHaveTextContent("#102");
  });

  it("sorts by Período and Recarga ID", async () => {
    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    const table = await screen.findByRole("table");
    await waitFor(() => {
      expect(within(table).getByText(/#101/)).toBeInTheDocument();
      expect(within(table).getByText(/#102/)).toBeInTheDocument();
    });

    // Default sort: ID desc (#102 then #101)
    let rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("#102");
    expect(rows[2]).toHaveTextContent("#101");

    // Click Recarga header -> toggle to ID asc (#101 then #102)
    const idHeader = within(table).getByRole("button", { name: /Recarga/i });
    fireEvent.click(idHeader);
    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("#101");
    expect(rows[2]).toHaveTextContent("#102");

    // Sort by Período (first click -> desc: newest date first -> #102 then #101)
    const periodHeader = within(table).getByRole("button", { name: /Período/i });
    fireEvent.click(periodHeader);
    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("#102");
    expect(rows[2]).toHaveTextContent("#101");

    // Toggle Período -> asc: oldest date first -> #101 then #102
    fireEvent.click(periodHeader);
    rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("#101");
    expect(rows[2]).toHaveTextContent("#102");
  });

  it("submits reload by equipment", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(historicalReloadApi.create).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Por Equipamento (Todas as Tags)")).toBeInTheDocument();
    });

    // Select scope: equipment
    fireEvent.click(screen.getByText("Por Equipamento (Todas as Tags)"));

    // Select equipment
    const equipmentSelect = screen.getByLabelText(/Equipamento/i);
    fireEvent.change(equipmentSelect, { target: { value: "2" } });

    // Set dates
    const startInput = screen.getByLabelText(/Início \(UTC\)/i);
    const endInput = screen.getByLabelText(/Fim \(UTC\)/i);
    fireEvent.change(startInput, { target: { value: "2026-09-01T00:00" } });
    fireEvent.change(endInput, { target: { value: "2026-09-02T00:00" } });

    // Submit
    const submitBtn = screen.getByRole("button", { name: /Recarregar período/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(historicalReloadApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          equipment_id: 2,
          mode: "recorded",
          all_active: false,
        })
      );
    });
  });

  it("submits reload by section", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(historicalReloadApi.create).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <HistoricalReloadPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Por Zona / Seção")).toBeInTheDocument();
    });

    // Select scope: section
    fireEvent.click(screen.getByText("Por Zona / Seção"));

    // Select equipment
    const equipmentSelect = screen.getByLabelText(/Equipamento/i);
    fireEvent.change(equipmentSelect, { target: { value: "2" } });

    // Select section
    const sectionSelect = screen.getByLabelText(/Zona \/ Seção/i);
    fireEvent.change(sectionSelect, { target: { value: "1" } });

    // Set dates
    const startInput = screen.getByLabelText(/Início \(UTC\)/i);
    const endInput = screen.getByLabelText(/Fim \(UTC\)/i);
    fireEvent.change(startInput, { target: { value: "2026-09-01T00:00" } });
    fireEvent.change(endInput, { target: { value: "2026-09-02T00:00" } });

    // Submit
    const submitBtn = screen.getByRole("button", { name: /Recarregar período/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(historicalReloadApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          section_id: 1,
          mode: "recorded",
          all_active: false,
        })
      );
    });
  });
});

