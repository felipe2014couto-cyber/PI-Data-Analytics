import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  classificationTagFixture,
  classificationTagFixture2,
  mockApiModule,
  paginated,
  sectionFixture,
} from "./mocks/api";
vi.mock("../src/api", () => mockApiModule());
vi.mock("../src/components/EChartsWrapper");
import { SectionsPage } from "../src/pages/SectionsPage";
import App from "../src/App";
import type { Section } from "../src/types";

const sectionsWithAttributes: Section[] = [
  { ...sectionFixture, id: 1, code: "SA", process_type: "COM_FORNO", group_code: "BQ", classification_tag_ids: [1] },
  { ...sectionFixture, id: 2, code: "SB", process_type: "COM_FORNO", group_code: "BF", classification_tag_ids: [2] },
  { ...sectionFixture, id: 3, code: "SC", process_type: "SEM_FORNO", group_code: "BQ", classification_tag_ids: [1] },
  { ...sectionFixture, id: 4, code: "LEG", process_type: null, group_code: null, classification_tag_ids: [] },
];

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listSections.mockResolvedValue(paginated(sectionsWithAttributes, 1, 200, sectionsWithAttributes.length));
  apiMock.updateSection.mockResolvedValue(sectionFixture);
  apiMock.createSection.mockResolvedValue(sectionFixture);
  apiMock.listEquipments.mockResolvedValue(
    paginated([{ id: 1, code: "RB3", name: "Equipamento RB3" }], 1, 200, 1),
  );
  apiMock.listVariableTypes.mockResolvedValue(paginated([], 1, 200, 0));
  apiMock.listClassificationTags.mockResolvedValue([classificationTagFixture, classificationTagFixture2]);
});

describe("SectionsPage classification tags", () => {
  it("loads the selected tags in the edit modal", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    const options = await screen.findByTestId("section-tag-options");
    const tag304 = options.querySelector("input#section-tag-1") as HTMLInputElement;
    const tag430 = options.querySelector("input#section-tag-2") as HTMLInputElement;
    expect(tag304.checked).toBe(true);
    expect(tag430.checked).toBe(false);
  });

  it("sends the associated tag ids when saving", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByTestId("section-tag-options");
    fireEvent.click(screen.getByText("430"));
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));
    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalled());
    const payload = apiMock.updateSection.mock.calls[0][1];
    expect(payload.classification_tag_ids).toEqual([1, 2]);
  });

  it("removes an association without deleting the global tag", async () => {
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByTestId("section-tag-options");
    fireEvent.click(screen.getByText("304"));
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));
    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalled());
    expect(apiMock.updateSection.mock.calls[0][1].classification_tag_ids).toEqual([]);
    expect(apiMock.removeClassificationTag).not.toHaveBeenCalled();
  });

  it("creates a new tag inline and associates it", async () => {
    apiMock.createClassificationTag.mockResolvedValue({
      id: 3,
      name: "5CR",
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    });
    render(
      <MemoryRouter>
        <SectionsPage />
      </MemoryRouter>,
    );
    const editButtons = await waitFor(() => screen.getAllByTitle("Editar"));
    fireEvent.click(editButtons[0]);
    await screen.findByTestId("section-tag-options");
    fireEvent.change(screen.getByTestId("section-new-tag-name"), { target: { value: "5cr" } });
    fireEvent.click(screen.getByTestId("section-create-tag"));
    await waitFor(() => expect(apiMock.createClassificationTag).toHaveBeenCalledWith({ name: "5CR" }));
    fireEvent.click(screen.getByRole("button", { name: /salvar/i }));
    await waitFor(() => expect(apiMock.updateSection).toHaveBeenCalled());
    expect(apiMock.updateSection.mock.calls[0][1].classification_tag_ids).toContain(3);
  });
});

describe("Data visualization classification tag filter", () => {
  beforeEach(() => {
    apiMock.listPiTags.mockResolvedValue(paginated([], 1, 200, 0));
    apiMock.piHealth.mockResolvedValue({
      status: "available",
      base_url: null,
      data_server: null,
      response_time_ms: null,
      message: null,
    });
  });

  async function renderVisualization() {
    render(
      <MemoryRouter initialEntries={["/analises/visualizacao"]}>
        <Routes>
          <Route path="/*" element={<App />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTestId("classification-tag-filter");
  }

  it("lists available classification tags in the filter", async () => {
    await renderVisualization();
    const filter = screen.getByTestId("classification-tag-filter") as HTMLSelectElement;
    expect(Array.from(filter.options).map((o) => o.textContent)).toEqual(["Todas", "304", "430"]);
  });

  it("combines filters with AND logic on section options", async () => {
    await renderVisualization();
    fireEvent.change(screen.getByTestId("equipment-select"), { target: { value: "1" } });
    const sectionSelect = () => screen.getByTestId("section-select") as HTMLSelectElement;
    fireEvent.change(screen.getByTestId("process-type-filter"), { target: { value: "COM_FORNO" } });
    await waitFor(() => {
      const labels = Array.from(sectionSelect().options).map((o) => o.textContent);
      expect(labels).toEqual(expect.arrayContaining(["SA - Forno", "SB - Forno"]));
      expect(labels).not.toContain("SC - Forno");
    });
    fireEvent.change(screen.getByTestId("group-code-filter"), { target: { value: "BQ" } });
    fireEvent.change(screen.getByTestId("classification-tag-filter"), { target: { value: "1" } });
    await waitFor(() => {
      expect(Array.from(sectionSelect().options).map((o) => o.textContent)).toEqual(
        expect.arrayContaining(["Todas", "SA - Forno"]),
      );
      expect(sectionSelect().options.length).toBe(2);
    });
  });

  it("clears the filters via the clear button", async () => {
    await renderVisualization();
    fireEvent.change(screen.getByTestId("process-type-filter"), { target: { value: "SEM_FORNO" } });
    fireEvent.change(screen.getByTestId("classification-tag-filter"), { target: { value: "1" } });
    await waitFor(() =>
      expect((screen.getByTestId("process-type-filter") as HTMLSelectElement).value).toBe("SEM_FORNO"),
    );
    fireEvent.click(screen.getByTestId("filters-clear"));
    await waitFor(() =>
      expect((screen.getByTestId("process-type-filter") as HTMLSelectElement).value).toBe(""),
    );
    expect((screen.getByTestId("classification-tag-filter") as HTMLSelectElement).value).toBe("");
    expect((screen.getByTestId("group-code-filter") as HTMLSelectElement).value).toBe("");
  });
});
