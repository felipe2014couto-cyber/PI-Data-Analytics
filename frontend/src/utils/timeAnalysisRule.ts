import type { TimeAnalysisRule, TimeSeries, TimeSeriesPoint, TimeSeriesSeries } from "../types";
import { isNumericValue } from "./values";

export function aggregateSeriesByMinute(
  seriesEntry: TimeSeriesSeries,
  rule: TimeAnalysisRule,
): TimeSeriesSeries {
  if (rule === "DEFAULT" || rule === "OOC") {
    return seriesEntry;
  }

  // Se a série não possui pontos ou não tem valores numéricos, mantemos como está
  const hasNumeric = seriesEntry.points.some((p) => isNumericValue(p.value));
  if (!hasNumeric || seriesEntry.points.length === 0) {
    return seriesEntry;
  }

  // Agrupamento por balde de 1 minuto (60.000 ms)
  const buckets = new Map<
    number,
    {
      bucketMs: number;
      bucketTimestamp: string;
      elapsedMs?: number;
      points: TimeSeriesPoint[];
    }
  >();

  for (const point of seriesEntry.points) {
    const timeMs = Date.parse(point.timestamp);
    if (!Number.isFinite(timeMs)) {
      continue;
    }

    const bucketMs = Math.floor(timeMs / 60000) * 60000;
    let bucket = buckets.get(bucketMs);
    if (!bucket) {
      const bucketTimestamp = new Date(bucketMs).toISOString();
      const elapsedMs =
        point.elapsed_ms != null
          ? Math.floor(point.elapsed_ms / 60000) * 60000
          : undefined;
      bucket = {
        bucketMs,
        bucketTimestamp,
        elapsedMs,
        points: [],
      };
      buckets.set(bucketMs, bucket);
    }
    bucket.points.push(point);
  }

  const aggregatedPoints: TimeSeriesPoint[] = [];

  for (const bucket of buckets.values()) {
    const validNumericPoints = bucket.points.filter(
      (p) => isNumericValue(p.value) && !p.filtered_out,
    );

    if (validNumericPoints.length === 0) {
      const nonNullPoint = bucket.points.find((p) => p.value !== null && !p.filtered_out);
      aggregatedPoints.push({
        timestamp: bucket.bucketTimestamp,
        value: nonNullPoint ? nonNullPoint.value : null,
        good: bucket.points.some((p) => p.good),
        filtered_out: bucket.points.some((p) => p.filtered_out),
        questionable: bucket.points.some((p) => Boolean(p.questionable)),
        substituted: bucket.points.some((p) => Boolean(p.substituted)),
        elapsed_ms: bucket.elapsedMs,
      });
      continue;
    }

    const numericValues = validNumericPoints.map((p) => Number(p.value));
    let aggregatedValue: number;

    switch (rule) {
      case "MEDIA": {
        const sum = numericValues.reduce((acc, val) => acc + val, 0);
        aggregatedValue = sum / numericValues.length;
        break;
      }
      case "MAXIMO": {
        aggregatedValue = Math.max(...numericValues);
        break;
      }
      case "MIN": {
        aggregatedValue = Math.min(...numericValues);
        break;
      }
      default:
        aggregatedValue = numericValues[0];
    }

    aggregatedPoints.push({
      timestamp: bucket.bucketTimestamp,
      value: aggregatedValue,
      good: validNumericPoints.some((p) => p.good),
      questionable: validNumericPoints.some((p) => Boolean(p.questionable)),
      substituted: validNumericPoints.some((p) => Boolean(p.substituted)),
      filtered_out: false,
      elapsed_ms: bucket.elapsedMs,
    });
  }

  return {
    ...seriesEntry,
    points: aggregatedPoints,
  };
}

export function applyTimeAnalysisRule(
  timeSeries: TimeSeries,
  rule: TimeAnalysisRule,
): TimeSeries {
  if (rule === "DEFAULT" || rule === "OOC") {
    return timeSeries;
  }

  return {
    ...timeSeries,
    series: timeSeries.series.map((seriesEntry) => aggregateSeriesByMinute(seriesEntry, rule)),
  };
}
