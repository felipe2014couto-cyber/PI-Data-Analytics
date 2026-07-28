import type { TimeSeries } from "../types";

const SEPARATOR = ";";

function escapeField(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  let text: string;
  if (typeof value === "boolean") {
    text = value ? "true" : "false";
  } else {
    text = String(value);
  }
  const needsQuoting = /["\n\r;]/.test(text);
  if (needsQuoting) {
    text = `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

const COLUMNS = [
  "timestamp_utc",
  "timestamp_local",
  "tag_id",
  "tag_name",
  "display_name",
  "equipment",
  "section",
  "variable_type",
  "unit",
  "value",
  "value_type",
  "good",
  "questionable",
  "substituted",
] as const;

const COMPARISON_COLUMNS = [
  "comparison_type",
  "context_id",
  "context_label",
  "series_instance_id",
  "category",
  "elapsed_ms",
] as const;

export function buildTimeSeriesCsv(timeSeries: TimeSeries): string {
  const lines: string[] = [];
  const isComparison = timeSeries.series.some((series) => Boolean(series.comparison_type));
  lines.push([...COLUMNS, ...(isComparison ? COMPARISON_COLUMNS : [])].join(SEPARATOR));
  for (const series of timeSeries.series) {
    for (const point of series.points) {
      const utc = point.timestamp;
      const local = new Date(utc);
      const row = [
        utc,
        isNaN(local.getTime()) ? utc : local.toString(),
        series.original_tag_id ?? series.tag_id,
        series.tag_name,
        series.display_name,
        series.equipment ?? "",
        series.section ?? "",
        series.variable_type ?? "",
        series.unit ?? "",
        point.value ?? "",
        point.value === null || point.value === undefined ? "null" : typeof point.value,
        point.good ? "true" : "false",
        point.questionable ? "true" : "false",
        point.substituted ? "true" : "false",
        ...(isComparison
          ? [
              series.comparison_type ?? "",
              series.context_id ?? "",
              series.context_label ?? "",
              series.series_instance_id ?? "",
              series.category ?? "",
              point.elapsed_ms ?? "",
            ]
          : []),
      ];
      lines.push(row.map(escapeField).join(SEPARATOR));
    }
  }
  // CRLF helps Excel detect line breaks.
  return "\ufeff" + lines.join("\r\n") + "\r\n";
}

export function buildCsvFilename(timeSeries: TimeSeries, fallback: string): string {
  const equipment = timeSeries.series[0]?.equipment ?? fallback;
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const safe = (equipment || fallback).replace(/[^A-Za-z0-9._-]+/g, "_");
  return `pi-analytics-data_${safe}_${stamp}.csv`;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function downloadTimeSeriesCsv(timeSeries: TimeSeries): void {
  const csv = buildTimeSeriesCsv(timeSeries);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  downloadBlob(blob, buildCsvFilename(timeSeries, "consulta"));
}
