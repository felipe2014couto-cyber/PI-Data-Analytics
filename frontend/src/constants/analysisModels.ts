import type { AnalysisModel } from "../types";

export interface AnalysisModelOption {
  value: AnalysisModel;
  label: string;
  disabled?: boolean;
}

export const DEFAULT_ANALYSIS_MODEL: AnalysisModel = "cyclic";

export const RAW_ANALYSIS_MODEL_OPTIONS: readonly AnalysisModelOption[] = [
  { value: "cyclic", label: "Base Cíclica" },
  { value: "unit", label: "Base Unidade" },
  { value: "oee", label: "Base OEE — Disponível em uma fase futura.", disabled: true },
  { value: "downtime", label: "Base Paradas — Disponível em uma fase futura.", disabled: true },
  { value: "quality", label: "Base Qualidade — Disponível em uma fase futura.", disabled: true },
] as const;

export function sortAnalysisModelOptions(options: readonly AnalysisModelOption[]): AnalysisModelOption[] {
  const available = options.filter((opt) => !opt.disabled);
  const unavailable = options.filter((opt) => !!opt.disabled);
  available.sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
  unavailable.sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
  return [...available, ...unavailable];
}

export const ANALYSIS_MODEL_OPTIONS: readonly AnalysisModelOption[] = sortAnalysisModelOptions(RAW_ANALYSIS_MODEL_OPTIONS);
