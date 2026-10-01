import { useState } from "react";
import { Alert, Button, Form, Modal, Spinner, Table } from "react-bootstrap";

import { piTagsApi } from "../api";
import type { PiTagCsvValidationResponse } from "../api";

interface Props { show: boolean; onHide: () => void; onSuccess: (message: string) => void; }

export function PiTagCsvImportModal({ show, onHide, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [validation, setValidation] = useState<PiTagCsvValidationResponse | null>(null);
  const [busy, setBusy] = useState<"validate" | "import" | null>(null);
  const [error, setError] = useState("");

  const close = () => { setFile(null); setValidation(null); setError(""); setBusy(null); onHide(); };
  const selectFile = (next: File | null) => {
    if (next && !next.name.toLowerCase().endsWith(".csv") && !next.name.toLowerCase().endsWith(".txt")) {
      setError("Selecione um arquivo com extensão .csv ou .txt.");
      setFile(null);
      setValidation(null);
      return;
    }
    setFile(next);
    setValidation(null);
    setError("");
  };
  const downloadTemplate = async () => {
    try {
      const blob = await piTagsApi.downloadCsvTemplate();
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "pi_tags_template.csv"; anchor.click(); URL.revokeObjectURL(url);
    } catch (err) { setError(err instanceof Error ? err.message : "Erro ao baixar modelo."); }
  };
  const validate = async () => {
    if (!file) return; setBusy("validate"); setError("");
    try { setValidation(await piTagsApi.validateCsv(file)); }
    catch (err) { setError(err instanceof Error ? err.message : "Erro ao validar CSV."); }
    finally { setBusy(null); }
  };
  const importFile = async () => {
    if (!file || !validation?.valid || validation.errors.length) return; setBusy("import"); setError("");
    try { const result = await piTagsApi.importCsv(file); onSuccess(result.message); close(); }
    catch (err) { setError(err instanceof Error ? err.message : "Erro ao importar CSV."); }
    finally { setBusy(null); }
  };

  return <Modal show={show} onHide={close} size="lg" centered>
    <Modal.Header closeButton><Modal.Title>Importar tags PI por CSV</Modal.Title></Modal.Header>
    <Modal.Body>
      <p>Selecione um CSV para validar as tags antes da importacao. A validacao nao grava dados.</p>
      <Button variant="outline-secondary" className="mb-3" onClick={() => void downloadTemplate()}>Baixar modelo CSV</Button>
      <Form.Group controlId="pi-tag-csv-file">
        <Form.Label>Arquivo CSV ou texto</Form.Label>
        <Form.Control type="file" accept=".csv,.txt,text/csv,text/plain" aria-label="Arquivo CSV" onChange={(event) => selectFile((event.currentTarget as HTMLInputElement).files?.[0] ?? null)} />
        {file && <Form.Text>{file.name}</Form.Text>}
      </Form.Group>
      {error && <Alert variant="danger" className="mt-3">{error}</Alert>}
      {validation && <div className="mt-3" aria-live="polite">
        <Alert variant={validation.valid ? "success" : "warning"}>Linhas: {validation.total_rows} · Validas: {validation.valid_count} · Invalidas: {validation.invalid_count}{validation.ignored_example_rows > 0 ? ` · Exemplos ignorados: ${validation.ignored_example_rows}` : ""}{validation.detected_encoding && validation.detected_delimiter ? <div className="small mt-1">Formato reconhecido: {validation.detected_encoding} · {validation.detected_delimiter.toUpperCase()}</div> : ""}</Alert>
        {validation.errors.length > 0 && <Table responsive size="sm" striped>
          <thead><tr><th>Linha</th><th>Coluna</th><th>Valor</th><th>Erro</th></tr></thead>
          <tbody>{validation.errors.map((item, index) => <tr key={`${item.row}-${item.column}-${index}`}><td>{item.row}</td><td>{item.column ?? "—"}</td><td>{item.value ?? "—"}</td><td>{item.message}</td></tr>)}</tbody>
        </Table>}
      </div>}
    </Modal.Body>
    <Modal.Footer>
      <Button variant="secondary" onClick={close}>Cancelar</Button>
      <Button variant="outline-primary" disabled={!file || busy !== null} onClick={() => void validate()}>{busy === "validate" && <Spinner size="sm" className="me-1" />}Validar arquivo</Button>
      <Button variant="primary" disabled={!validation?.valid || validation.valid_count === 0 || validation.errors.length > 0 || busy !== null} onClick={() => void importFile()}>{busy === "import" && <Spinner size="sm" className="me-1" />}Importar</Button>
    </Modal.Footer>
  </Modal>;
}
