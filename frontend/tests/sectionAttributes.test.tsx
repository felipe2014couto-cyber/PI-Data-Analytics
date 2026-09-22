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
  apiMock.listPiTags.mockResolvedValue(paginated([], 1, 200, 0));
  apiMock.listClassificationTags.mockResolvedValue([classificationTagFixture, classificationTagFixture2]);
});



describe("Data visualization filters without attribute dropdowns", () => {
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
    await screen.findByTestId("equipment-select");
  }

  it("does not render process, group or classification tag filters", async () => {
    await renderVisualization();
    expect(screen.queryByTestId("process-type-filter")).toBeNull();
    expect(screen.queryByTestId("group-code-filter")).toBeNull();
    expect(screen.queryByTestId("classification-tag-filter")).toBeNull();
  });

  it("filters section options by selected equipment", async () => {
    await renderVisualization();
    const sectionSelect = () => screen.getByTestId("section-select") as HTMLSelectElement;
    expect(sectionSelect().disabled).toBe(true);
    fireEvent.change(screen.getByTestId("equipment-select"), { target: { value: "1" } });
    await waitFor(() => {
      expect(sectionSelect().disabled).toBe(false);
      const labels = Array.from(sectionSelect().options).map((o) => o.textContent);
      expect(labels).toEqual(expect.arrayContaining(["Todas", "SA - Forno"]));
    });
  });
});

