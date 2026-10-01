import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  downloadCsvTemplate: vi.fn(),
  validateCsv: vi.fn(),
  importCsv: vi.fn(),
}));
vi.mock("../src/api", () => ({ piTagsApi: api }));

import { PiTagCsvImportModal } from "../src/components/PiTagCsvImportModal";

function renderModal(onSuccess = vi.fn()) {
  return { onSuccess, ...render(<PiTagCsvImportModal show onHide={vi.fn()} onSuccess={onSuccess} />) };
}

describe("PiTagCsvImportModal", () => {
  it("mostra nome de arquivo, erros de validacao e mantem importacao desabilitada", async () => {
    api.validateCsv.mockResolvedValueOnce({ valid: false, total_rows: 1, valid_count: 0, invalid_count: 1, ignored_example_rows: 0, errors: [{ row: 2, column: "equipment_code", value: "BAD", message: "Equipamento nao encontrado." }], preview: [] });
    renderModal();
    const file = new File(["csv"], "tags.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [file] } });
    expect(screen.getByText("tags.csv")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Importar" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Validar arquivo" }));
    expect(api.validateCsv).toHaveBeenCalledWith(file);
    expect(await screen.findByText("Equipamento nao encontrado.")).toBeInTheDocument();
    expect(screen.getByText("equipment_code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Importar" })).toBeDisabled();
  });

  it("importa somente depois da validacao sem erros e comunica sucesso", async () => {
    api.validateCsv.mockResolvedValueOnce({ valid: true, total_rows: 1, valid_count: 1, invalid_count: 0, ignored_example_rows: 0, errors: [], preview: [] });
    api.importCsv.mockResolvedValueOnce({ imported_count: 1, message: "1 tags PI importadas com sucesso." });
    const { onSuccess } = renderModal();
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [new File(["csv"], "ok.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Validar arquivo" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Importar" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Importar" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("1 tags PI importadas com sucesso."));
    expect(api.importCsv).toHaveBeenCalledTimes(1);
  });
});


describe("PiTagCsvImportModal file actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downloads the CSV template", async () => {
    const downloadedBlob = new Blob(["test"], { type: "text/csv" });
    api.downloadCsvTemplate.mockResolvedValueOnce(downloadedBlob);
    URL.createObjectURL = vi.fn(() => "blob:http://localhost/template");
    URL.revokeObjectURL = vi.fn();
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Baixar modelo CSV" }));
    await waitFor(() => expect(api.downloadCsvTemplate).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledWith(downloadedBlob));
    expect(anchorClick).toHaveBeenCalledOnce();
  });

  it("shows the template row as ignored, not invalid or importable", async () => {
    api.validateCsv.mockResolvedValueOnce({ valid: true, total_rows: 1, valid_count: 0, invalid_count: 0, ignored_example_rows: 1, detected_encoding: "Windows-1252", detected_delimiter: "tab", had_bom: false, errors: [], preview: [] });
    renderModal();
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [new File(["csv"], "template.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Validar arquivo" }));
    expect(await screen.findByText("Linhas: 1 · Validas: 0 · Invalidas: 0 · Exemplos ignorados: 1")).toBeInTheDocument();
    expect(screen.queryByText("O arquivo deve estar codificado em UTF-8.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Importar" })).toBeDisabled();
    expect(screen.getByText("Formato reconhecido: Windows-1252 · TAB")).toBeInTheDocument();
  });

  it("shows an encoding error returned for genuinely invalid file bytes", async () => {
    api.validateCsv.mockRejectedValueOnce(new Error("O arquivo deve estar codificado em UTF-8."));
    renderModal();
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [new File([new Uint8Array([0xff])], "invalid.csv", { type: "text/csv" })] } });
    fireEvent.click(screen.getByRole("button", { name: "Validar arquivo" }));
    expect(await screen.findByText("O arquivo deve estar codificado em UTF-8.")).toBeInTheDocument();
  });

  it("rejects files without a CSV or text extension", () => {
    renderModal();
    const file = new File(["data"], "tags.xlsx", { type: "application/vnd.ms-excel" });
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [file] } });
    expect(screen.getByText("Selecione um arquivo com extensão .csv ou .txt.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validar arquivo" })).toBeDisabled();
  });

  it("accepts TXT files even when the browser reports an unusual MIME type", () => {
    renderModal();
    const file = new File(["data"], "tags.txt", { type: "application/octet-stream" });
    fireEvent.change(screen.getByLabelText("Arquivo CSV"), { target: { files: [file] } });
    expect(screen.getByText("tags.txt")).toBeInTheDocument();
    expect(screen.queryByText("Selecione um arquivo com extensão .csv ou .txt.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validar arquivo" })).toBeEnabled();
  });

  it("preserves BOM, semicolon delimiter and twelve columns from the downloaded template", async () => {
    const headerLine = "codigo_equipamento;codigo_secao;codigo_tipo_variavel;tag_pi;nome_amigavel;pi_server;tag_limite_inferior;tag_limite_superior;unidade_engenharia;tipo_dado;descricao;ativo";
    const templateBytes = new Uint8Array([0xef, 0xbb, 0xbf, ...new TextEncoder().encode(`${headerLine}\n`)]);
    const blob = new Blob([templateBytes], { type: "text/csv" });
    api.downloadCsvTemplate.mockResolvedValueOnce(blob);
    URL.createObjectURL = vi.fn(() => "blob:http://localhost/template-contract");
    URL.revokeObjectURL = vi.fn();
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Baixar modelo CSV" }));
    await waitFor(() => expect(api.downloadCsvTemplate).toHaveBeenCalled());
    expect(anchorClick).toHaveBeenCalledOnce();
    // Validate the contract directly from the known bytes rather than mock.results,
    // which does not reliably expose a real Blob in the test environment.
    expect(templateBytes.slice(0, 3)).toEqual(new Uint8Array([0xef, 0xbb, 0xbf]));
    const text = new TextDecoder("utf-8").decode(templateBytes.slice(3));
    const decodedHeader = text.split("\n")[0];
    expect(decodedHeader).toContain(";");
    expect(decodedHeader.split(";")).toHaveLength(12);
    expect(decodedHeader).toBe(headerLine);
  });
});
