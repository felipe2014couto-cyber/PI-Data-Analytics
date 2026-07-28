import type { TimeSeriesPoint, TimeSeriesSeries } from "../types";
import { isNumericValue } from "./values";

export interface NumericObservation {
  timestamp: number;
  timestampText: string;
  value: number;
  good: boolean;
  questionable: boolean;
  substituted: boolean;
}

export interface ScatterPair {
  timestamp: number;
  timestampText: string;
  x: NumericObservation;
  y: NumericObservation;
}

export interface LatestValueEntry {
  tagId: number;
  tagName: string;
  displayName: string;
  unit: string;
  observation: NumericObservation;
}

export interface LatestValueGroup {
  unit: string;
  entries: LatestValueEntry[];
}

function toObservation(
  point: TimeSeriesPoint,
  ignoreBadQuality: boolean,
): NumericObservation | null {
  if (ignoreBadQuality && !point.good) return null;
  const timestamp = Date.parse(point.timestamp);
  if (!Number.isFinite(timestamp) || !isNumericValue(point.value)) return null;
  return {
    timestamp,
    timestampText: point.timestamp,
    value: point.value,
    good: point.good,
    questionable: point.questionable,
    substituted: point.substituted,
  };
}

export function numericObservations(
  series: TimeSeriesSeries,
  ignoreBadQuality: boolean,
): NumericObservation[] {
  return series.points
    .map((point) => toObservation(point, ignoreBadQuality))
    .filter((point): point is NumericObservation => point !== null);
}

export function alignSeriesByTimestamp(
  xSeries: TimeSeriesSeries,
  ySeries: TimeSeriesSeries,
  ignoreBadQuality: boolean,
): ScatterPair[] {
  const xByTimestamp = new Map<number, NumericObservation[]>();
  const yByTimestamp = new Map<number, NumericObservation[]>();
  for (const observation of numericObservations(xSeries, ignoreBadQuality)) {
    const values = xByTimestamp.get(observation.timestamp) ?? [];
    values.push(observation);
    xByTimestamp.set(observation.timestamp, values);
  }
  for (const observation of numericObservations(ySeries, ignoreBadQuality)) {
    const values = yByTimestamp.get(observation.timestamp) ?? [];
    values.push(observation);
    yByTimestamp.set(observation.timestamp, values);
  }

  const timestamps = Array.from(xByTimestamp.keys())
    .filter((timestamp) => yByTimestamp.has(timestamp))
    .sort((left, right) => left - right);
  const pairs: ScatterPair[] = [];
  for (const timestamp of timestamps) {
    const xValues = xByTimestamp.get(timestamp) ?? [];
    const yValues = yByTimestamp.get(timestamp) ?? [];
    const count = Math.min(xValues.length, yValues.length);
    for (let index = 0; index < count; index += 1) {
      pairs.push({
        timestamp,
        timestampText: new Date(timestamp).toISOString(),
        x: xValues[index],
        y: yValues[index],
      });
    }
  }
  return pairs;
}

export function pearsonCorrelation(pairs: readonly ScatterPair[]): number | null {
  if (pairs.length < 2) return null;
  const meanX = pairs.reduce((sum, pair) => sum + pair.x.value, 0) / pairs.length;
  const meanY = pairs.reduce((sum, pair) => sum + pair.y.value, 0) / pairs.length;
  let covariance = 0;
  let varianceX = 0;
  let varianceY = 0;
  for (const pair of pairs) {
    const deltaX = pair.x.value - meanX;
    const deltaY = pair.y.value - meanY;
    covariance += deltaX * deltaY;
    varianceX += deltaX * deltaX;
    varianceY += deltaY * deltaY;
  }
  const denominator = Math.sqrt(varianceX * varianceY);
  if (!Number.isFinite(denominator) || denominator === 0) return null;
  const correlation = covariance / denominator;
  if (!Number.isFinite(correlation)) return null;
  return Math.max(-1, Math.min(1, correlation));
}

export function latestNumericValue(
  series: TimeSeriesSeries,
  ignoreBadQuality: boolean,
): NumericObservation | null {
  let latest: NumericObservation | null = null;
  for (const observation of numericObservations(series, ignoreBadQuality)) {
    if (!latest || observation.timestamp > latest.timestamp) latest = observation;
  }
  return latest;
}

export function groupLatestValuesByUnit(
  series: readonly TimeSeriesSeries[],
  ignoreBadQuality: boolean,
): LatestValueGroup[] {
  const groups = new Map<string, LatestValueGroup>();
  for (const entry of series) {
    const observation = latestNumericValue(entry, ignoreBadQuality);
    if (!observation) continue;
    const unit = entry.unit?.trim() || "Sem unidade";
    const key = unit.toLocaleLowerCase("pt-BR");
    const group = groups.get(key) ?? { unit, entries: [] };
    group.entries.push({
      tagId: entry.tag_id,
      tagName: entry.tag_name,
      displayName: entry.display_name,
      unit,
      observation,
    });
    groups.set(key, group);
  }
  return Array.from(groups.values());
}
