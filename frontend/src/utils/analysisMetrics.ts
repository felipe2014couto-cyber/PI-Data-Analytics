import type {
  AnalysisMetric,
  MetricConfiguration,
  MetricResult,
  TimeSeriesSeries,
} from "../types";
import { alignSeriesByTimestamp, numericObservations } from "./comparison";

export type MetricCategory = "basic" | "capability" | "error" | "control";
export type MetricUnitRule = "none" | "source" | "sourceSquared" | "percent";

export interface MetricDefinition {
  id: AnalysisMetric;
  name: string;
  description: string;
  category: MetricCategory;
  minimumPoints: number;
  requirements: string;
  unitRule: MetricUnitRule;
  requiresActualReference: boolean;
  requiresSpecificationLimits: boolean;
  requiresControlLimits: boolean;
}

const METRIC_DEFINITIONS: readonly Omit<MetricDefinition, "requiresActualReference" | "requiresSpecificationLimits" | "requiresControlLimits">[] = [
  { id: "cp", name: "Cp", description: "Capacidade potencial do processo.", category: "capability", minimumPoints: 2, requirements: "LIE, LSE e desvio-padrão amostral não nulo", unitRule: "none" },
  { id: "cpk", name: "Cpk", description: "Capacidade do processo considerando sua centralização.", category: "capability", minimumPoints: 2, requirements: "LIE, LSE e desvio-padrão amostral não nulo", unitRule: "none" },
  { id: "cpkError", name: "Cpk do erro", description: "Capacidade dos erros pareados frente aos limites de especificação.", category: "error", minimumPoints: 2, requirements: "Séries real/referência e LIE/LSE do erro", unitRule: "none" },
  { id: "count", name: "Contagem", description: "Quantidade de valores numéricos finitos.", category: "basic", minimumPoints: 1, requirements: "Uma série numérica", unitRule: "none" },
  { id: "standardDeviation", name: "Desvio-padrão", description: "Desvio-padrão amostral (n − 1).", category: "basic", minimumPoints: 2, requirements: "Ao menos dois valores", unitRule: "source" },
  { id: "standardDeviationError", name: "Desvio-padrão do erro", description: "Desvio-padrão amostral dos erros real − referência.", category: "error", minimumPoints: 2, requirements: "Ao menos dois pares temporais", unitRule: "source" },
  { id: "meanAbsoluteError", name: "Erro absoluto médio", description: "Média dos valores absolutos dos erros pareados.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "source" },
  { id: "meanSquaredError", name: "Erro quadrático médio", description: "Média dos quadrados dos erros pareados.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "sourceSquared" },
  { id: "maximum", name: "Máximo", description: "Maior valor da série.", category: "basic", minimumPoints: 1, requirements: "Uma série numérica", unitRule: "source" },
  { id: "maximumError", name: "Erro máximo", description: "Maior erro assinado real − referência.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "source" },
  { id: "mean", name: "Média", description: "Média aritmética dos valores.", category: "basic", minimumPoints: 1, requirements: "Uma série numérica", unitRule: "source" },
  { id: "meanError", name: "Erro médio", description: "Média assinada dos erros real − referência.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "source" },
  { id: "minimum", name: "Mínimo", description: "Menor valor da série.", category: "basic", minimumPoints: 1, requirements: "Uma série numérica", unitRule: "source" },
  { id: "minimumError", name: "Erro mínimo", description: "Menor erro assinado real − referência.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "source" },
  { id: "ooc", name: "Fora de controle", description: "Quantidade de valores estritamente fora de LIC e LSC.", category: "control", minimumPoints: 1, requirements: "LIC e LSC", unitRule: "none" },
  { id: "oocMaeMaximum", name: "Erro absoluto máximo fora de controle", description: "Maior erro absoluto quando o valor real está fora de controle.", category: "control", minimumPoints: 1, requirements: "Séries real/referência e LIC/LSC", unitRule: "source" },
  { id: "oocMaeMean", name: "Erro absoluto médio fora de controle", description: "Média do erro absoluto quando o valor real está fora de controle.", category: "control", minimumPoints: 1, requirements: "Séries real/referência e LIC/LSC", unitRule: "source" },
  { id: "pc", name: "Percentual conforme", description: "Percentual inclusivo de valores entre LIE e LSE.", category: "capability", minimumPoints: 1, requirements: "LIE e LSE", unitRule: "percent" },
  { id: "rootMeanSquaredError", name: "Raiz do erro quadrático médio", description: "Raiz quadrada da média dos erros ao quadrado.", category: "error", minimumPoints: 1, requirements: "Séries real e referência", unitRule: "source" },
  { id: "total", name: "Total", description: "Soma dos valores numéricos finitos.", category: "basic", minimumPoints: 1, requirements: "Uma série numérica", unitRule: "source" },
] as const;

export const ANALYSIS_METRICS: readonly MetricDefinition[] = METRIC_DEFINITIONS.map((definition) => ({
  ...definition,
  requiresActualReference: definition.category === "error" || definition.id === "oocMaeMaximum" || definition.id === "oocMaeMean",
  requiresSpecificationLimits: definition.id === "cp" || definition.id === "cpk" || definition.id === "cpkError" || definition.id === "pc",
  requiresControlLimits: definition.id === "ooc" || definition.id === "oocMaeMaximum" || definition.id === "oocMaeMean",
}));

export const METRIC_BY_ID = new Map(ANALYSIS_METRICS.map((metric) => [metric.id, metric]));

const errorMetrics = new Set<AnalysisMetric>(["standardDeviationError", "meanAbsoluteError", "meanSquaredError", "maximumError", "meanError", "minimumError", "rootMeanSquaredError"]);

const seriesIdentity = (entry: TimeSeriesSeries): string => entry.series_instance_id ?? `tag:${entry.tag_id}`;

function configuredSeries(series: readonly TimeSeriesSeries[], instanceId: string | null | undefined, tagId: number | null): TimeSeriesSeries | undefined {
  if (instanceId) return series.find((entry) => seriesIdentity(entry) === instanceId);
  return tagId === null ? undefined : series.find((entry) => entry.tag_id === tagId);
}

export function createMetricConfiguration(metric: AnalysisMetric | null): MetricConfiguration {
  if (!metric) return { kind: "none" };
  if (metric === "count" || metric === "standardDeviation" || metric === "maximum" || metric === "mean" || metric === "minimum" || metric === "total") return { kind: "single", metric };
  if (metric === "cp" || metric === "cpk" || metric === "pc") return { kind: "specification", metric, lowerSpecification: null, upperSpecification: null };
  if (metric === "ooc") return { kind: "control", metric, lowerControl: null, upperControl: null };
  if (errorMetrics.has(metric)) return { kind: "error", metric: metric as Extract<MetricConfiguration, { kind: "error" }>["metric"], actualTagId: null, referenceTagId: null };
  if (metric === "cpkError") return { kind: "errorCapability", metric, actualTagId: null, referenceTagId: null, lowerSpecification: null, upperSpecification: null };
  if (metric === "oocMaeMaximum" || metric === "oocMaeMean") return { kind: "oocError", metric, actualTagId: null, referenceTagId: null, lowerControl: null, upperControl: null };
  return { kind: "none" };
}

export function validateMetricConfiguration(configuration: MetricConfiguration, series: readonly TimeSeriesSeries[]): string[] {
  if (configuration.kind === "none" || configuration.kind === "single") return [];
  const errors: string[] = [];
  const validateLimits = (lower: number | null, upper: number | null, names: string) => {
    if (lower === null || upper === null || !Number.isFinite(lower) || !Number.isFinite(upper)) errors.push(`Informe ${names}.`);
    else if (lower >= upper) errors.push(`O limite inferior deve ser menor que o superior (${names}).`);
  };
  if (configuration.kind === "specification" || configuration.kind === "errorCapability") validateLimits(configuration.lowerSpecification, configuration.upperSpecification, "LIE e LSE");
  if (configuration.kind === "control" || configuration.kind === "oocError") validateLimits(configuration.lowerControl, configuration.upperControl, "LIC e LSC");
  if ("actualTagId" in configuration) {
    const actualIdentity = configuration.actualSeriesInstanceId ?? (configuration.actualTagId === null ? null : `tag:${configuration.actualTagId}`);
    const referenceIdentity = configuration.referenceSeriesInstanceId ?? (configuration.referenceTagId === null ? null : `tag:${configuration.referenceTagId}`);
    if (!actualIdentity || !referenceIdentity) errors.push("Selecione as séries real e de referência.");
    else if (actualIdentity === referenceIdentity) errors.push("As séries real e de referência devem ser diferentes.");
    else {
      const actual = configuredSeries(series, configuration.actualSeriesInstanceId, configuration.actualTagId);
      const reference = configuredSeries(series, configuration.referenceSeriesInstanceId, configuration.referenceTagId);
      if (!actual || !reference) errors.push("As séries real e de referência não estão disponíveis.");
      else if (normalizeUnit(actual.unit) !== normalizeUnit(reference.unit)) errors.push("As séries real e de referência devem possuir a mesma unidade.");
    }
  }
  return errors;
}

function normalizeUnit(unit: string | null): string { return unit?.trim().toLocaleLowerCase("pt-BR") ?? ""; }
function displayUnit(unit: string | null): string | null { return unit?.trim() || null; }
function mean(values: readonly number[]): number { return values.reduce((sum, value) => sum + value, 0) / values.length; }
function sampleDeviation(values: readonly number[]): number | null {
  if (values.length < 2) return null;
  let average = 0; let m2 = 0; let count = 0;
  for (const value of values) { count += 1; const delta = value - average; average += delta / count; m2 += delta * (value - average); }
  const result = Math.sqrt(m2 / (count - 1));
  return Number.isFinite(result) ? result : null;
}

function result(configuration: Exclude<MetricConfiguration, { kind: "none" }>, status: MetricResult["status"], value: number | null, unit: string | null, sampleCount: number, excludedCount: number, message: string, seriesTagId: number | null, referenceTagId: number | null = null, oocCount?: number, seriesInstanceId?: string | null, referenceSeriesInstanceId?: string | null): MetricResult {
  const base = { metric: configuration.metric, seriesTagId, referenceTagId, seriesInstanceId, referenceSeriesInstanceId, unit, sampleCount, excludedCount, message, ...(oocCount === undefined ? {} : { oocCount }) };
  if (status === "ok" && value !== null && Number.isFinite(value)) return { ...base, status, value };
  if (status === "ok" || (value !== null && !Number.isFinite(value))) return { ...base, status: "calculationError", value: null, message: "O cálculo produziu um resultado não finito." };
  return { ...base, status, value: null };
}

function valuesAndExcluded(series: TimeSeriesSeries, ignoreBadQuality: boolean) {
  const observations = numericObservations(series, ignoreBadQuality);
  return { values: observations.map((item) => item.value), excluded: Math.max(0, series.points.length - observations.length) };
}

function individualValue(metric: AnalysisMetric, values: readonly number[], lower?: number, upper?: number): number | null {
  if (!values.length) return null;
  if (metric === "count") return values.length;
  if (metric === "total") return values.reduce((sum, value) => sum + value, 0);
  if (metric === "mean") return mean(values);
  if (metric === "minimum") return Math.min(...values);
  if (metric === "maximum") return Math.max(...values);
  if (metric === "standardDeviation") return sampleDeviation(values);
  if (metric === "pc") return values.filter((value) => value >= lower! && value <= upper!).length / values.length * 100;
  if (metric === "ooc") return values.filter((value) => value < lower! || value > upper!).length;
  const deviation = sampleDeviation(values);
  if (deviation === null || deviation === 0) return null;
  if (metric === "cp") return (upper! - lower!) / (6 * deviation);
  if (metric === "cpk") return Math.min((upper! - mean(values)) / (3 * deviation), (mean(values) - lower!) / (3 * deviation));
  return null;
}

function unitFor(metric: AnalysisMetric, unit: string | null): string | null {
  const rule = METRIC_BY_ID.get(metric)?.unitRule;
  if (rule === "percent") return "%";
  if (rule === "none") return null;
  const source = displayUnit(unit);
  return rule === "sourceSquared" && source ? `${source}²` : source;
}

export function calculateMetricResults(series: readonly TimeSeriesSeries[], configuration: MetricConfiguration, ignoreBadQuality: boolean): MetricResult[] {
  if (configuration.kind === "none") return [];
  const validation = validateMetricConfiguration(configuration, series);
  if (validation.length) return [result(configuration, "invalidConfiguration", null, null, 0, 0, validation.join(" "), "actualTagId" in configuration ? configuration.actualTagId : null, "referenceTagId" in configuration ? configuration.referenceTagId : null)];

  if (configuration.kind === "single" || configuration.kind === "specification" || configuration.kind === "control") {
    return series.map((entry) => {
      const { values, excluded } = valuesAndExcluded(entry, ignoreBadQuality);
      const minimum = METRIC_BY_ID.get(configuration.metric)?.minimumPoints ?? 1;
      if (values.length < minimum) return result(configuration, "insufficientData", null, unitFor(configuration.metric, entry.unit), values.length, excluded, `São necessários ao menos ${minimum} valores numéricos.`, entry.tag_id, null, undefined, seriesIdentity(entry));
      const lower = configuration.kind === "specification" ? configuration.lowerSpecification! : configuration.kind === "control" ? configuration.lowerControl! : undefined;
      const upper = configuration.kind === "specification" ? configuration.upperSpecification! : configuration.kind === "control" ? configuration.upperControl! : undefined;
      const value = individualValue(configuration.metric, values, lower, upper);
      if (value === null) return result(configuration, "insufficientData", null, unitFor(configuration.metric, entry.unit), values.length, excluded, "O desvio-padrão amostral deve ser diferente de zero.", entry.tag_id, null, undefined, seriesIdentity(entry));
      const oocCount = configuration.metric === "ooc" ? value : undefined;
      return result(configuration, "ok", value, unitFor(configuration.metric, entry.unit), values.length, excluded, "Cálculo concluído.", entry.tag_id, null, oocCount, seriesIdentity(entry));
    });
  }

  const actual = configuredSeries(series, configuration.actualSeriesInstanceId, configuration.actualTagId)!;
  const reference = configuredSeries(series, configuration.referenceSeriesInstanceId, configuration.referenceTagId)!;
  const pairs = alignSeriesByTimestamp(actual, reference, ignoreBadQuality);
  const errors = pairs.map((pair) => pair.x.value - pair.y.value);
  const availableActual = numericObservations(actual, ignoreBadQuality).length;
  const availableReference = numericObservations(reference, ignoreBadQuality).length;
  const excluded = actual.points.length + reference.points.length - pairs.length * 2;
  const minimum = METRIC_BY_ID.get(configuration.metric)?.minimumPoints ?? 1;
  if (errors.length < minimum) return [result(configuration, "insufficientData", null, unitFor(configuration.metric, actual.unit), errors.length, excluded, `São necessários ao menos ${minimum} pares no mesmo timestamp; disponíveis: ${availableActual} e ${availableReference}.`, actual.tag_id, reference.tag_id, undefined, seriesIdentity(actual), seriesIdentity(reference))];

  let values = errors;
  let oocCount: number | undefined;
  if (configuration.kind === "oocError") {
    values = pairs.filter((pair) => pair.x.value < configuration.lowerControl! || pair.x.value > configuration.upperControl!).map((pair) => Math.abs(pair.x.value - pair.y.value));
    oocCount = values.length;
    if (!values.length) return [result(configuration, "ok", 0, unitFor(configuration.metric, actual.unit), errors.length, excluded, "Nenhum valor real ficou fora dos limites de controle.", actual.tag_id, reference.tag_id, 0, seriesIdentity(actual), seriesIdentity(reference))];
  }
  let value: number | null;
  switch (configuration.metric) {
    case "standardDeviationError": value = sampleDeviation(errors); break;
    case "meanAbsoluteError": value = mean(errors.map(Math.abs)); break;
    case "meanSquaredError": value = mean(errors.map((entry) => entry ** 2)); break;
    case "rootMeanSquaredError": value = Math.sqrt(mean(errors.map((entry) => entry ** 2))); break;
    case "maximumError": value = Math.max(...errors); break;
    case "meanError": value = mean(errors); break;
    case "minimumError": value = Math.min(...errors); break;
    case "oocMaeMaximum": value = Math.max(...values); break;
    case "oocMaeMean": value = mean(values); break;
    case "cpkError": {
      const deviation = sampleDeviation(errors);
      value = deviation && deviation !== 0 ? Math.min((configuration.upperSpecification! - mean(errors)) / (3 * deviation), (mean(errors) - configuration.lowerSpecification!) / (3 * deviation)) : null;
      break;
    }
    default: value = null;
  }
  if (value === null) return [result(configuration, "insufficientData", null, unitFor(configuration.metric, actual.unit), errors.length, excluded, "O desvio-padrão amostral deve ser diferente de zero.", actual.tag_id, reference.tag_id, oocCount, seriesIdentity(actual), seriesIdentity(reference))];
  return [result(configuration, "ok", value, unitFor(configuration.metric, actual.unit), errors.length, excluded, "Cálculo concluído.", actual.tag_id, reference.tag_id, oocCount, seriesIdentity(actual), seriesIdentity(reference))];
}
