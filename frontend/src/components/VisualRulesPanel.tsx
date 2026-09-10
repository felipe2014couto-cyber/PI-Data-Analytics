import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import type {
  PiTag,
  SeriesVisualConfiguration,
  VisualLimitLine,
  VisualLineStyle,
  VisualNormLimitConfiguration,
  VisualRulesState,
} from "../types";
import {
  EMPTY_VISUAL_CONFIGURATION,
  defaultNormLimitConfig,
  parseFiniteNumber,
} from "../utils/visualRules";

export interface VisualSeriesOption {
  seriesInstanceId: string;
  label: string;
  numeric: boolean;
}

export interface NormLimitRuntime {
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  lowerTagName: string | null;
  upperTagName: string | null;
}

interface Props {
  state: VisualRulesState;
  series: readonly VisualSeriesOption[];
  onChange: (state: VisualRulesState) => void;
  onSearchTags?: (query: string) => Promise<PiTag[]>;
  normLimits?: Record<string, NormLimitRuntime>;
  onAddNormLimit?: (seriesInstanceId: string) => void;
  onRemoveNormLimit?: (seriesInstanceId: string) => void;
  selectedPiTag?: {
    id: number | null;
    lowerLimitTag: string | null;
    upperLimitTag: string | null;
  } | null;
}

const id = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export function VisualRulesPanel({
  state,
  series,
  onChange,
  normLimits,
  onAddNormLimit,
  onRemoveNormLimit,
  selectedPiTag,
}: Props) {
  const [error, setError] = useState<string | null>(null);
  const selected = series.find((entry) => entry.seriesInstanceId === state.selectedSeriesInstanceId) ?? null;
  const config = selected
    ? state.bySeries[selected.seriesInstanceId] ?? EMPTY_VISUAL_CONFIGURATION(selected.seriesInstanceId)
    : null;
  const setConfig = (next: SeriesVisualConfiguration) =>
    onChange({ ...state, bySeries: { ...state.bySeries, [next.seriesInstanceId]: next } });
  const finite = (raw: string, apply: (value: number) => void) => {
    const value = parseFiniteNumber(raw);
    if (value === null) setError("Informe um valor numérico finito.");
    else {
      setError(null);
      apply(value);
    }
  };
  const addFixedLimit = () => {
    if (!config) return;
    const base: VisualLimitLine = {
      id: id(),
      label: "Limite",
      value: 0,
      color: "#d32f2f",
      lineStyle: "dashed",
      width: 2,
      visible: true,
    };
    setConfig({ ...config, limits: [...config.limits, base] });
  };
  const updateLimit = (index: number, patch: Partial<VisualLimitLine>) =>
    config && setConfig({
      ...config,
      limits: config.limits.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    });
  const removeLimit = (index: number) =>
    config && setConfig({ ...config, limits: config.limits.filter((_, i) => i !== index) });

  const updateNorm = (patch: Partial<VisualNormLimitConfiguration>) =>
    config && setConfig({
      ...config,
      normLimit: { ...(config.normLimit ?? defaultNormLimitConfig()), ...patch },
    });

  const normRuntime = selected ? normLimits?.[selected.seriesInstanceId] : undefined;
  const hasLower = !!selectedPiTag?.lowerLimitTag;
  const hasUpper = !!selectedPiTag?.upperLimitTag;
  const bothTagsSet = hasLower && hasUpper;
  const hasPiTag = !!selectedPiTag?.id;
  const normEnabled = config?.normLimit?.enabled ?? false;
  const canAddNorm = !!selected?.numeric && bothTagsSet && !normEnabled && !!(onAddNormLimit);
  const normMessage = !hasPiTag
    ? "Selecione uma serie com tag PI correspondente."
    : !selected?.numeric
      ? "Limites de norma estao disponiveis apenas para series numericas."
      : !bothTagsSet
        ? "A serie selecionada nao possui tags de limite cadastradas."
        : null;

  return (
    <section data-testid="visual-rules-panel" aria-labelledby="visual-rules-title">
      <h6 id="visual-rules-title">Limites</h6>
      <Form.Check
        type="switch"
        id="visual-rules-enabled"
        label={state.enabled ? "Ativado" : "Desativado"}
        checked={state.enabled}
        data-testid="visual-rules-enabled"
        onChange={(event) => onChange({ ...state, enabled: event.target.checked })}
      />
      {!state.enabled ? (
        <div className="small text-muted">Nenhuma regra visual será avaliada.</div>
      ) : (
        <>
          <Form.Group className="mt-2">
            <Form.Label>Série</Form.Label>
            <Form.Select
              data-testid="visual-series"
              value={state.selectedSeriesInstanceId ?? ""}
              onChange={(event) =>
                onChange({ ...state, selectedSeriesInstanceId: event.target.value || null })
                }
            >
              <option value="">Selecione...</option>
              {series.map((entry) => (
                <option key={entry.seriesInstanceId} value={entry.seriesInstanceId}>
                  {entry.label}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
          {selected && !selected.numeric ? (
            <Alert variant="secondary" className="py-2 mt-2">
              Limites numéricos não estão disponíveis para esta série.
            </Alert>
          ) : null}
          {config && selected?.numeric ? (
            <div className="mt-3 d-flex flex-column gap-3" data-testid="visual-limits-section">
              <section data-testid="visual-fixed-limits">
                <div className="d-flex justify-content-between align-items-center">
                  <strong>Limites fixos</strong>
                  <span>
                    <Button
                      size="sm"
                      variant="outline-primary"
                      data-testid="add-fixed-limit"
                      onClick={addFixedLimit}
                    >
                      Adicionar limite fixo
                    </Button>
                    {config.limits.length ? (
                      <Button
                        className="ms-1"
                        size="sm"
                        variant="outline-secondary"
                        onClick={() => setConfig({ ...config, limits: [] })}
                      >
                        Limpar
                      </Button>
                    ) : null}
                  </span>
                </div>
                <div className="d-flex flex-column gap-2 mt-2">
                  {config.limits.map((item, index) => (
                    <div className="border rounded p-2" key={item.id} data-testid="visual-limit">
                      <div className="row g-2">
                        <Field label="Rótulo">
                          <Form.Control
                            value={item.label}
                            onChange={(e) => updateLimit(index, { label: e.target.value })}
                          />
                        </Field>
                        <Field label="Valor">
                          <Form.Control
                            defaultValue={item.value}
                            onBlur={(e) =>
                              finite(e.target.value, (value) => updateLimit(index, { value }))
                            }
                          />
                        </Field>
                      </div>
                      <div className="row g-2 mt-2">
                        <Field label="Cor">
                          <Form.Control
                            type="color"
                            value={item.color}
                            onChange={(e) => updateLimit(index, { color: e.target.value })}
                          />
                        </Field>
                        <Field label="Estilo">
                          <Form.Select
                            value={item.lineStyle}
                            onChange={(e) =>
                              updateLimit(index, { lineStyle: e.target.value as VisualLineStyle })
                            }
                          >
                            <option value="solid">Sólida</option>
                            <option value="dashed">Tracejada</option>
                            <option value="dotted">Pontilhada</option>
                          </Form.Select>
                        </Field>
                        <Field label="Espessura">
                          <Form.Control
                            type="number"
                            min="1"
                            max="8"
                            value={item.width}
                            onChange={(e) =>
                              finite(e.target.value, (width) =>
                                updateLimit(index, { width: Math.min(8, Math.max(1, width)) }),
                              )
                            }
                          />
                        </Field>
                      </div>
                      <LimitActions
                        visible={item.visible}
                        onVisible={(visible) => updateLimit(index, { visible })}
                        onRemove={() => removeLimit(index)}
                      />
                    </div>
                  ))}
                </div>
              </section>

              <section data-testid="visual-norm-limit">
                <div className="d-flex justify-content-between align-items-center">
                  <strong>Limites de norma</strong>
                  <span>
                    {normEnabled ? (
                      <Button
                        size="sm"
                        variant="outline-danger"
                        data-testid="remove-norm-limit"
                        onClick={() => {
                          if (config.normLimit) {
                            setConfig({ ...config, normLimit: { ...config.normLimit, enabled: false } });
                          }
                          if (onRemoveNormLimit) onRemoveNormLimit(selected.seriesInstanceId);
                        }}
                      >
                        Remover limite de norma
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline-primary"
                        data-testid="add-norm-limit"
                        onClick={() => {
                          if (!canAddNorm) return;
                          setConfig({ ...config, normLimit: defaultNormLimitConfig() });
                          if (onAddNormLimit) onAddNormLimit(selected.seriesInstanceId);
                        }}
                        disabled={!canAddNorm}
                      >
                        Adicionar limite de norma
                      </Button>
                    )}
                  </span>
                </div>
                {normMessage ? (
                  <div className="small text-muted mt-2" data-testid="norm-limit-message">
                    {normMessage}
                  </div>
                ) : null}
                {normEnabled && selectedPiTag ? (
                  <div className="small text-muted mt-2" data-testid="norm-limit-tags">
                    Limite inferior: <code>{selectedPiTag.lowerLimitTag ?? "—"}</code> · Limite
                    superior: <code>{selectedPiTag.upperLimitTag ?? "—"}</code>
                  </div>
                ) : null}
                {normRuntime?.status === "loading" ? (
                  <div className="small text-muted mt-2" data-testid="norm-limit-loading">
                    Carregando limites de norma...
                  </div>
                ) : null}
                {normRuntime?.status === "error" && normRuntime.error ? (
                  <Alert
                    variant="warning"
                    className="py-2 mt-2 mb-0"
                    data-testid="norm-limit-error"
                  >
                    {normRuntime.error}
                  </Alert>
                ) : null}
                {normEnabled && config.normLimit ? (
                  <div className="row g-2 mt-2">
                    <Field label="Cor inferior">
                      <Form.Control
                        type="color"
                        value={config.normLimit.lowerColor}
                        onChange={(e) => updateNorm({ lowerColor: e.target.value })}
                      />
                    </Field>
                    <Field label="Cor superior">
                      <Form.Control
                        type="color"
                        value={config.normLimit.upperColor}
                        onChange={(e) => updateNorm({ upperColor: e.target.value })}
                      />
                    </Field>
                    <Field label="Estilo">
                      <Form.Select
                        value={config.normLimit.lineStyle}
                        onChange={(e) => updateNorm({ lineStyle: e.target.value as VisualLineStyle })}
                      >
                        <option value="solid">Sólida</option>
                        <option value="dashed">Tracejada</option>
                        <option value="dotted">Pontilhada</option>
                      </Form.Select>
                    </Field>
                    <Field label="Espessura">
                      <Form.Control
                        type="number"
                        min="1"
                        max="8"
                        value={config.normLimit.width}
                        onChange={(e) =>
                          finite(e.target.value, (width) =>
                            updateNorm({ width: Math.min(8, Math.max(1, width)) }),
                          )
                        }
                      />
                    </Field>
                  </div>
                ) : null}
              </section>

              <Button
                variant="outline-danger"
                size="sm"
                data-testid="reset-series"
                onClick={() => setConfig(EMPTY_VISUAL_CONFIGURATION(config.seriesInstanceId))}
              >
                Restaurar esta série
              </Button>
            </div>
          ) : null}
          {Object.keys(state.bySeries).length ? (
            <Button
              className="mt-3"
              variant="outline-danger"
              size="sm"
              data-testid="reset-all"
              onClick={() => {
                if (window.confirm("Restaurar todas as configurações visuais?"))
                  onChange({ ...state, bySeries: {} });
              }}
            >
              Restaurar tudo
            </Button>
          ) : null}
        </>
      )}
      {error ? (
        <Alert variant="warning" className="py-2 mt-2" role="alert">
          {error}
        </Alert>
      ) : null}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Form.Group className="col">
      <Form.Label className="small mb-1">{label}</Form.Label>
      {children}
    </Form.Group>
  );
}

function LimitActions({
  visible,
  onVisible,
  onRemove,
}: {
  visible: boolean;
  onVisible: (value: boolean) => void;
  onRemove: () => void;
}) {
  return (
    <div className="d-flex align-items-center gap-1 mt-2">
      <Form.Check
        checked={visible}
        label={visible ? "Ativo" : "Inativo"}
        onChange={(e) => onVisible(e.target.checked)}
      />
      <Button size="sm" variant="outline-danger" onClick={onRemove}>
        Remover
      </Button>
    </div>
  );
}