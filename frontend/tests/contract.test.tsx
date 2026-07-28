import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import {
  apiMock,
  mockApiModule,
  connectedHealthFixture,
  notConfiguredHealthFixture,
  paginated,
  equipmentFixture,
  piTagFixture,
  variableTypeFixture,
  sectionFixture,
} from "./mocks/api";

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

describe("Paginated API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([]));
    apiMock.listSections.mockResolvedValue(paginated([]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([]));
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
  });

  it("renders empty state when API returns items: []", async () => {
    apiMock.listEquipments.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      total: 0,
      pages: 0,
    });
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(screen.getByText("Nenhum equipamento encontrado")).toBeInTheDocument();
    });
  });

  it("renders item table when API returns equipment", async () => {
    apiMock.listEquipments.mockResolvedValue({
      items: [equipmentFixture],
      page: 1,
      page_size: 20,
      total: 1,
      pages: 1,
    });
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(screen.getByText("RB3")).toBeInTheDocument();
      expect(screen.getByText("Equipamento RB3")).toBeInTheDocument();
    });
  });

  it("renders empty state when items is undefined (defensive)", async () => {
    apiMock.listEquipments.mockResolvedValue({
      page: 1,
      page_size: 20,
      total: 0,
      pages: 0,
    } as any);
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(screen.getByText("Nenhum equipamento encontrado")).toBeInTheDocument();
    });
  });

  it("handles error from API gracefully", async () => {
    apiMock.listEquipments.mockRejectedValue(new Error("Network error"));
    renderAt("/cadastros/equipamentos");
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });
});

describe("Sections page paginated contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
  });

  it("renders empty state when items is empty", async () => {
    apiMock.listSections.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    });
    renderAt("/cadastros/secoes");
    await waitFor(() => {
      expect(screen.getByText("Nenhuma secao encontrada")).toBeInTheDocument();
    });
  });

  it("renders item when items is non-empty", async () => {
    apiMock.listSections.mockResolvedValue({
      items: [sectionFixture],
      page: 1,
      page_size: 10,
      total: 1,
      pages: 1,
    });
    renderAt("/cadastros/secoes");
    await waitFor(() => {
      expect(screen.getByText("FORNO")).toBeInTheDocument();
      expect(screen.getByText("Forno")).toBeInTheDocument();
    });
  });

  it("renders empty state when items is undefined (defensive)", async () => {
    apiMock.listSections.mockResolvedValue({
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    } as any);
    renderAt("/cadastros/secoes");
    await waitFor(() => {
      expect(screen.getByText("Nenhuma secao encontrada")).toBeInTheDocument();
    });
  });

  it("handles API error gracefully", async () => {
    apiMock.listSections.mockRejectedValue(new Error("Server error"));
    renderAt("/cadastros/secoes");
    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeInTheDocument();
    });
  });
});

describe("VariableTypes page paginated contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([]));
    apiMock.listPiTags.mockResolvedValue(paginated([piTagFixture]));
    apiMock.piHealth.mockResolvedValue(notConfiguredHealthFixture);
  });

  it("renders empty state when items is empty", async () => {
    apiMock.listVariableTypes.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    });
    renderAt("/cadastros/tipos-variavel");
    await waitFor(() => {
      expect(screen.getByText("Nenhum tipo de variavel encontrado")).toBeInTheDocument();
    });
  });

  it("renders item when items is non-empty", async () => {
    apiMock.listVariableTypes.mockResolvedValue({
      items: [variableTypeFixture],
      page: 1,
      page_size: 10,
      total: 1,
      pages: 1,
    });
    renderAt("/cadastros/tipos-variavel");
    await waitFor(() => {
      expect(screen.getByText("TEMPERATURE")).toBeInTheDocument();
    });
  });

  it("renders empty state when items is undefined (defensive)", async () => {
    apiMock.listVariableTypes.mockResolvedValue({
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    } as any);
    renderAt("/cadastros/tipos-variavel");
    await waitFor(() => {
      expect(screen.getByText("Nenhum tipo de variavel encontrado")).toBeInTheDocument();
    });
  });

  it("handles API error gracefully", async () => {
    apiMock.listVariableTypes.mockRejectedValue(new Error("Connection refused"));
    renderAt("/cadastros/tipos-variavel");
    await waitFor(() => {
      expect(screen.getByText("Connection refused")).toBeInTheDocument();
    });
  });
});

describe("PiTags page paginated contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listEquipments.mockResolvedValue(paginated([equipmentFixture]));
    apiMock.listSections.mockResolvedValue(paginated([sectionFixture]));
    apiMock.listVariableTypes.mockResolvedValue(paginated([variableTypeFixture]));
    apiMock.listPiTags.mockResolvedValue(paginated([]));
    apiMock.piHealth.mockResolvedValue(connectedHealthFixture);
  });

  it("renders empty state when items is empty", async () => {
    apiMock.listPiTags.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    });
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(screen.getByText("Nenhuma tag PI encontrada")).toBeInTheDocument();
    });
  });

  it("renders item when items is non-empty", async () => {
    apiMock.listPiTags.mockResolvedValue({
      items: [piTagFixture],
      page: 1,
      page_size: 10,
      total: 1,
      pages: 1,
    });
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(screen.getByText("RB3.FURNO.TEMP")).toBeInTheDocument();
    });
  });

  it("renders empty state when items is undefined (defensive)", async () => {
    apiMock.listPiTags.mockResolvedValue({
      page: 1,
      page_size: 10,
      total: 0,
      pages: 0,
    } as any);
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(screen.getByText("Nenhuma tag PI encontrada")).toBeInTheDocument();
    });
  });

  it("handles API error gracefully", async () => {
    apiMock.listPiTags.mockRejectedValue(new Error("Internal server error"));
    renderAt("/cadastros/tags-pi");
    await waitFor(() => {
      expect(screen.getByText("Internal server error")).toBeInTheDocument();
    });
  });
});
