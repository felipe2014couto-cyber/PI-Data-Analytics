import type { TimeSeriesPoint, TimeSeriesSeries } from "../types";

export type DisplayableValue = number | string | boolean;
export type SingleValueStatus = "Bom" | "Ruim" | "Questionável" | "Substituído" | "Sem dados";
export type SingleValueVariant = "success" | "danger" | "warning" | "primary" | "secondary";

export interface DisplayableObservation {
  timestamp: number;
  timestampText: string;
  value: DisplayableValue;
  good: boolean;
  questionable: boolean;
  substituted: boolean;
}

export interface SingleValueQuality {
  status: SingleValueStatus;
  variant: SingleValueVariant;
}

export interface SingleValueEntry {
  series: TimeSeriesSeries;
  observation: DisplayableObservation | null;
  quality: SingleValueQuality;
}

export function isDisplayableValue(value: TimeSeriesPoint["value"]): value is DisplayableValue {
  if (typeof value === "number") return Number.isFinite(value);
  return typeof value === "string" || typeof value === "boolean";
}

export function latestDisplayableValue(
  series: TimeSeriesSeries,
  ignoreBadQuality: boolean,
): DisplayableObservation | null {
  let latest: DisplayableObservation | null = null;
  for (const point of series.points) {
    const timestamp = Date.parse(point.timestamp);
    if (!Number.isFinite(timestamp)) continue;
    if (ignoreBadQuality && !point.good) continue;
    if (!isDisplayableValue(point.value)) continue;
    if (!latest || timestamp > latest.timestamp) {
      latest = {
        timestamp,
        timestampText: point.timestamp,
        value: point.value,
        good: point.good,
        questionable: point.questionable,
        substituted: point.substituted,
      };
    }
  }
  return latest;
}

export function singleValueQuality(
  observation: DisplayableObservation | null,
): SingleValueQuality {
  if (!observation) return { status: "Sem dados", variant: "secondary" };
  if (!observation.good) return { status: "Ruim", variant: "danger" };
  if (observation.questionable) return { status: "Questionável", variant: "warning" };
  if (observation.substituted) return { status: "Substituído", variant: "primary" };
  return { status: "Bom", variant: "success" };
}

export function buildSingleValueEntries(
  series: readonly TimeSeriesSeries[],
  ignoreBadQuality: boolean,
): SingleValueEntry[] {
  return series.map((entry) => {
    const observation = latestDisplayableValue(entry, ignoreBadQuality);
    return { series: entry, observation, quality: singleValueQuality(observation) };
  });
}
