export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return value;
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString("pt-BR");
  } catch {
    return value;
  }
}
