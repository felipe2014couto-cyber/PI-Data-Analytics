const DEFAULT_FORMATTER = new Intl.NumberFormat("pt-BR", {
  maximumFractionDigits: 3,
});

export function formatNumericValue(value: number | string | boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return DEFAULT_FORMATTER.format(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

export function isNumericValue(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function qualityFlags(
  point: { good?: boolean; questionable?: boolean; substituted?: boolean },
): string {
  if (point.good) {
    return "OK";
  }
  if (point.substituted) {
    return "Substituido";
  }
  if (point.questionable) {
    return "Questionavel";
  }
  return "Ruim";
}
