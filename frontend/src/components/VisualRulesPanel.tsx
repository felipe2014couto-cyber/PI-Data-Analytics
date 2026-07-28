import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import type { ColorRuleOperator, SeriesVisualConfiguration, VisualColorRule, VisualLimitLine, VisualRange, VisualRulesState } from "../types";
import { EMPTY_VISUAL_CONFIGURATION, moveVisualItem, parseFiniteNumber, SAFE_MAX_OPACITY, validateColorRule, validateRange } from "../utils/visualRules";

export interface VisualSeriesOption { seriesInstanceId: string; label: string; numeric: boolean; }
interface Props { state: VisualRulesState; series: readonly VisualSeriesOption[]; onChange: (state: VisualRulesState) => void; }
const id = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export function VisualRulesPanel({ state, series, onChange }: Props) {
  const [error, setError] = useState<string | null>(null);
  const selected = series.find((entry) => entry.seriesInstanceId === state.selectedSeriesInstanceId) ?? null;
  const config = selected ? state.bySeries[selected.seriesInstanceId] ?? EMPTY_VISUAL_CONFIGURATION(selected.seriesInstanceId) : null;
  const setConfig = (next: SeriesVisualConfiguration) => onChange({ ...state, bySeries: { ...state.bySeries, [next.seriesInstanceId]: next } });
  const finite = (raw: string, apply: (value: number) => void) => { const value = parseFiniteNumber(raw); if (value === null) setError("Informe um valor numérico finito."); else { setError(null); apply(value); } };
  const addLimit = () => config && setConfig({ ...config, limits: [...config.limits, { id: id(), value: 0, label: "Limite", color: "#d32f2f", lineStyle: "dashed", width: 2, visible: true }] });
  const addRange = () => {
    if (!config) return;
    const lower = config.ranges.length ? Math.max(...config.ranges.map((item) => item.upper)) : 0;
    const range: VisualRange = { id: id(), lower, upper: lower + 1, label: "Faixa", color: "#ffc107", opacity: 0.18, visible: true };
    const errors = validateRange(range, config.ranges);
    if (errors.length) return setError(errors.join(" "));
    setError(null); setConfig({ ...config, ranges: [...config.ranges, range] });
  };
  const addRule = () => config && setConfig({ ...config, rules: [...config.rules, { id: id(), operator: ">=", value: 0, lower: null, upper: null, color: "#d32f2f", label: "Regra", enabled: true }] });
  const updateLimit = (index: number, patch: Partial<VisualLimitLine>) => config && setConfig({ ...config, limits: config.limits.map((item, i) => i === index ? { ...item, ...patch } : item) });
  const updateRange = (index: number, patch: Partial<VisualRange>) => {
    if (!config) return;
    const next = { ...config.ranges[index], ...patch }; const errors = validateRange(next, config.ranges, next.id);
    if (errors.length) return setError(errors.join(" "));
    setError(null); setConfig({ ...config, ranges: config.ranges.map((item, i) => i === index ? next : item) });
  };
  const updateRule = (index: number, patch: Partial<VisualColorRule>) => {
    if (!config) return;
    const next = { ...config.rules[index], ...patch }; const errors = validateColorRule(next);
    if (errors.length && next.enabled) setError(errors.join(" ")); else setError(null);
    setConfig({ ...config, rules: config.rules.map((item, i) => i === index ? next : item) });
  };
  return <section data-testid="visual-rules-panel" aria-labelledby="visual-rules-title">
    <h6 id="visual-rules-title">Limites e cores</h6>
    <Form.Check type="switch" id="visual-rules-enabled" label={state.enabled ? "Ativado" : "Desativado"} checked={state.enabled} data-testid="visual-rules-enabled" onChange={(event) => onChange({ ...state, enabled: event.target.checked })} />
    {!state.enabled ? <div className="small text-muted">Nenhuma regra visual será avaliada.</div> : <>
      <Form.Group className="mt-2"><Form.Label>Série</Form.Label><Form.Select data-testid="visual-series" value={state.selectedSeriesInstanceId ?? ""} onChange={(event) => onChange({ ...state, selectedSeriesInstanceId: event.target.value || null })}>
        <option value="">Selecione...</option>{series.map((entry) => <option key={entry.seriesInstanceId} value={entry.seriesInstanceId}>{entry.label}</option>)}
      </Form.Select></Form.Group>
      {selected && !selected.numeric ? <Alert variant="secondary" className="py-2 mt-2">Limites numéricos não estão disponíveis para esta série.</Alert> : null}
      {config && selected?.numeric ? <div className="mt-3 d-flex flex-column gap-3">
        <Editor title="Linhas de limite" addLabel="Adicionar limite" onAdd={addLimit} onClear={() => setConfig({ ...config, limits: [] })}>
          {config.limits.map((item, index) => <div className="border rounded p-2" key={item.id} data-testid="visual-limit">
            <div className="row g-2"><Field label="Valor"><Form.Control defaultValue={item.value} onBlur={(e) => finite(e.target.value, (value) => updateLimit(index, { value }))} /></Field><Field label="Rótulo"><Form.Control value={item.label} onChange={(e) => updateLimit(index, { label: e.target.value })} /></Field></div>
            <div className="row g-2 mt-1"><Field label="Cor"><Form.Control type="color" value={item.color} onChange={(e) => updateLimit(index, { color: e.target.value })} /></Field><Field label="Estilo"><Form.Select value={item.lineStyle} onChange={(e) => updateLimit(index, { lineStyle: e.target.value as VisualLimitLine["lineStyle"] })}><option value="solid">Sólida</option><option value="dashed">Tracejada</option><option value="dotted">Pontilhada</option></Form.Select></Field><Field label="Espessura"><Form.Control type="number" min="1" max="8" value={item.width} onChange={(e) => finite(e.target.value, (width) => updateLimit(index, { width: Math.min(8, Math.max(1, width)) }))} /></Field></div>
            <Actions visible={item.visible} onVisible={(visible) => updateLimit(index, { visible })} onRemove={() => setConfig({ ...config, limits: config.limits.filter((_, i) => i !== index) })} />
          </div>)}
        </Editor>
        <Editor title="Faixas coloridas" addLabel="Adicionar faixa" onAdd={addRange} onClear={() => setConfig({ ...config, ranges: [] })}>
          {config.ranges.map((item, index) => <div className="border rounded p-2" key={item.id} data-testid="visual-range">
            <div className="row g-2"><Field label="Inferior"><Form.Control defaultValue={item.lower} onBlur={(e) => finite(e.target.value, (lower) => updateRange(index, { lower }))} /></Field><Field label="Superior"><Form.Control defaultValue={item.upper} onBlur={(e) => finite(e.target.value, (upper) => updateRange(index, { upper }))} /></Field><Field label="Rótulo"><Form.Control value={item.label} onChange={(e) => updateRange(index, { label: e.target.value })} /></Field></div>
            <div className="row g-2 mt-1"><Field label="Cor"><Form.Control type="color" value={item.color} onChange={(e) => updateRange(index, { color: e.target.value })} /></Field><Field label="Opacidade"><Form.Control type="number" min="0" max={SAFE_MAX_OPACITY} step="0.05" value={item.opacity} onChange={(e) => finite(e.target.value, (opacity) => updateRange(index, { opacity }))} /></Field></div>
            <Actions visible={item.visible} onVisible={(visible) => updateRange(index, { visible })} onRemove={() => setConfig({ ...config, ranges: config.ranges.filter((_, i) => i !== index) })} onMove={(direction) => setConfig({ ...config, ranges: moveVisualItem(config.ranges, index, direction) })} />
          </div>)}
        </Editor>
        <Editor title="Regras de cores" addLabel="Adicionar regra" onAdd={addRule} onClear={() => setConfig({ ...config, rules: [] })}>
          {config.rules.map((item, index) => <div className="border rounded p-2" key={item.id} data-testid="visual-rule"><div className="small fw-semibold">Prioridade {index + 1}</div>
            <div className="row g-2"><Field label="Operador"><Form.Select value={item.operator} onChange={(e) => updateRule(index, { operator: e.target.value as ColorRuleOperator })}>{[["<","<"],["<=","≤"],[">",">"],[">=","≥"],["==","="],["between","Entre"],["outside","Fora do intervalo"]].map(([value,label]) => <option key={value} value={value}>{label}</option>)}</Form.Select></Field>
            {item.operator === "between" || item.operator === "outside" ? <><Field label="Mínimo"><Form.Control defaultValue={item.lower ?? ""} onBlur={(e) => finite(e.target.value, (lower) => updateRule(index, { lower }))} /></Field><Field label="Máximo"><Form.Control defaultValue={item.upper ?? ""} onBlur={(e) => finite(e.target.value, (upper) => updateRule(index, { upper }))} /></Field></> : <Field label="Valor"><Form.Control defaultValue={item.value ?? ""} onBlur={(e) => finite(e.target.value, (value) => updateRule(index, { value }))} /></Field>}</div>
            <div className="row g-2 mt-1"><Field label="Rótulo"><Form.Control value={item.label} onChange={(e) => updateRule(index, { label: e.target.value })} /></Field><Field label="Cor"><Form.Control type="color" value={item.color} onChange={(e) => updateRule(index, { color: e.target.value })} /></Field></div>
            <Actions visible={item.enabled} onVisible={(enabled) => updateRule(index, { enabled })} onRemove={() => setConfig({ ...config, rules: config.rules.filter((_, i) => i !== index) })} onMove={(direction) => setConfig({ ...config, rules: moveVisualItem(config.rules, index, direction) })} />
          </div>)}
        </Editor>
        <Button variant="outline-danger" size="sm" onClick={() => setConfig(EMPTY_VISUAL_CONFIGURATION(config.seriesInstanceId))}>Restaurar esta série</Button>
      </div> : null}
      {Object.keys(state.bySeries).length ? <Button className="mt-3" variant="outline-danger" size="sm" onClick={() => { if (window.confirm("Restaurar todas as configurações visuais?")) onChange({ ...state, bySeries: {} }); }}>Restaurar tudo</Button> : null}
    </>}
    {error ? <Alert variant="warning" className="py-2 mt-2" role="alert">{error}</Alert> : null}
    <div className="small text-muted mt-2">Configuração mantida somente nesta página até a Fase 5.7.</div>
  </section>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <Form.Group className="col"><Form.Label className="small mb-1">{label}</Form.Label>{children}</Form.Group>; }
function Editor({ title, addLabel, onAdd, onClear, children }: { title: string; addLabel: string; onAdd: () => void; onClear: () => void; children: React.ReactNode }) { return <section><div className="d-flex justify-content-between"><strong>{title}</strong><span><Button size="sm" variant="outline-primary" onClick={onAdd}>{addLabel}</Button>{children ? <Button className="ms-1" size="sm" variant="outline-secondary" onClick={onClear}>Limpar</Button> : null}</span></div><div className="d-flex flex-column gap-2 mt-2">{children}</div></section>; }
function Actions({ visible, onVisible, onRemove, onMove }: { visible: boolean; onVisible: (value: boolean) => void; onRemove: () => void; onMove?: (direction: "up" | "down") => void }) { return <div className="d-flex align-items-center gap-1 mt-2"><Form.Check checked={visible} label={visible ? "Ativo" : "Inativo"} onChange={(e) => onVisible(e.target.checked)} />{onMove ? <><Button size="sm" variant="outline-secondary" onClick={() => onMove("up")}>↑</Button><Button size="sm" variant="outline-secondary" onClick={() => onMove("down")}>↓</Button></> : null}<Button size="sm" variant="outline-danger" onClick={onRemove}>Remover</Button></div>; }
