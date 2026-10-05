import { useState } from "react";
import { Alert, Button, Card, Spinner, Table } from "react-bootstrap";
import { productionUnitsApi } from "../api";
import type { ProductionUnitAnalysisResponse } from "../api";
import type { DataFilterConfiguration, DynamicAnalysisFilter } from "../types";

interface Props {
  sectionId: number | null;
  equipmentId?: number;
  tagIds: number[];
  startTime: string;
  endTime: string;
  filtersEnabled: boolean;
  filterConfiguration: DataFilterConfiguration;
  analysisFilters: DynamicAnalysisFilter[];
  filtersActive: boolean;
  /** When provided, the panel renders this pre-fetched response instead of issuing its own request. */
  externalResult?: ProductionUnitAnalysisResponse | null;
}

function localTime(value: string | null) {
  return value ? new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) : "—";
}

function number(value: number | null) {
  return value === null ? "—" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 6 }).format(value);
}

export function ProductionUnitAnalysisPanel({ sectionId, equipmentId, tagIds, startTime, endTime, filtersEnabled, filterConfiguration, analysisFilters, filtersActive, externalResult }: Props) {
  const [internalResult, setInternalResult] = useState<ProductionUnitAnalysisResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const result = externalResult !== undefined ? externalResult : internalResult;

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await productionUnitsApi.analyze({
        section_id: sectionId ?? undefined, equipment_id: equipmentId, tag_ids: tagIds, start_time: startTime, end_time: endTime,
        filter_configuration: {
          filtersEnabled,
          quality: filterConfiguration.quality,
          rules: filtersEnabled ? filterConfiguration.rules.filter((rule) => rule.enabled) : [],
        },
        analysis_filters: filtersEnabled ? analysisFilters : [],
      });
      setInternalResult(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível agregar as tags por UM.");
      setInternalResult(null);
    } finally {
      setBusy(false);
    }
  };

  const showManualButton = externalResult === undefined;

  return <Card className="piad-card mb-3" data-testid="production-unit-analysis">
    <Card.Header className="d-flex justify-content-between align-items-center">
      <strong>Análise de produção por UM</strong>
      {showManualButton ? (
        <Button size="sm" variant="outline-primary" disabled={busy || tagIds.length === 0} onClick={() => void run()}>
          {busy && <Spinner size="sm" className="me-1" />} {busy ? "Agregando..." : "Calcular por UM"}
        </Button>
      ) : null}
    </Card.Header>
    <Card.Body>
      {filtersActive && <Alert variant="info" className="mb-2">Estatísticas calculadas com os filtros enviados na consulta.</Alert>}
      {!result && !error && <div className="text-muted small">Usa eventos RECORDED e aplica os filtros habilitados por amostra. A visualização temporal e as métricas atuais permanecem independentes.</div>}
      {error && <Alert variant="danger">{error}</Alert>}
      {result && <>
        <div className="small text-muted mb-2">UM: {result.um_tag_name} · {localTime(result.start_time)} – {localTime(result.end_time)}</div>
        {result.segments.map((segment) => <section className="mb-3" key={segment.segment_id} data-testid="um-segment">
          <h6 className="mb-1">{segment.um_value ?? "UNASSIGNED / UNKNOWN"} · {localTime(segment.start_time)} – {localTime(segment.end_time)}</h6>
          <div className="small text-muted mb-2">Duração: {number(segment.duration_seconds)} s · fim: {segment.end_reason}{segment.state_source_timestamp ? ` · estado lido em ${localTime(segment.state_source_timestamp)}` : ""}</div>
          <Table responsive size="sm" striped>
            <thead><tr><th>Variável</th><th>Amostras válidas</th><th>Média</th><th>Mínimo</th><th>Máximo</th><th>Primeiro / último</th></tr></thead>
            <tbody>{segment.variables.map((item) => <tr key={item.tag_id}>
              <td>{item.display_name} <span className="text-muted">({item.tag_name})</span></td>
              <td>{item.raw_sample_count !== item.filtered_sample_count ? `${item.raw_sample_count.toLocaleString("pt-BR")} → ${item.filtered_sample_count.toLocaleString("pt-BR")} após filtros · ` : ""}{item.sample_count.toLocaleString("pt-BR")} válidas{item.excluded_quality_count ? ` · ${item.excluded_quality_count} qualidade excluída` : ""}</td>
              <td>{item.average === null ? "—" : `${number(item.average)}${item.unit ? ` ${item.unit}` : ""}`}</td>
              <td>{item.minimum === null ? "—" : number(item.minimum)}</td><td>{item.maximum === null ? "—" : number(item.maximum)}</td>
              <td>{item.data_type !== "NUMERIC" ? <>{item.first_value ?? "—"} / {item.last_value ?? "—"}<br /></> : null}{localTime(item.first_timestamp)} / {localTime(item.last_timestamp)}</td>
            </tr>)}</tbody>
          </Table>
        </section>)}
      </>}
    </Card.Body>
  </Card>;
}
