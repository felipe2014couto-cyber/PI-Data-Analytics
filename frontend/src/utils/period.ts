export type PeriodPreset =
  | "PT15M"
  | "PT1H"
  | "PT8H"
  | "P1D"
  | "P7D"
  | "CUSTOM";

export interface PeriodRange {
  start: Date;
  end: Date;
}

const PRESET_TO_DURATION: Record<Exclude<PeriodPreset, "CUSTOM">, number> = {
  PT15M: 15 * 60 * 1000,
  PT1H: 60 * 60 * 1000,
  PT8H: 8 * 60 * 60 * 1000,
  P1D: 24 * 60 * 60 * 1000,
  P7D: 7 * 24 * 60 * 60 * 1000,
};

const PRESET_LABELS: Record<PeriodPreset, string> = {
  PT15M: "Ultimos 15 minutos",
  PT1H: "Ultima hora",
  PT8H: "Ultimas 8 horas",
  P1D: "Ultimas 24 horas",
  P7D: "Ultimos 7 dias",
  CUSTOM: "Personalizado",
};

export function getPresetLabel(preset: PeriodPreset): string {
  return PRESET_LABELS[preset];
}

export function getPresetOptions(): Array<{ value: PeriodPreset; label: string }> {
  return (Object.keys(PRESET_LABELS) as PeriodPreset[]).map((value) => ({
    value,
    label: PRESET_LABELS[value],
  }));
}

export function computePeriodRange(preset: PeriodPreset, now: Date = new Date()): PeriodRange {
  if (preset === "CUSTOM") {
    return { start: new Date(now.getTime() - 60 * 60 * 1000), end: now };
  }
  const duration = PRESET_TO_DURATION[preset];
  return { start: new Date(now.getTime() - duration), end: now };
}

export function toUtcIsoString(value: Date): string {
  return value.toISOString();
}

export function toDatetimeLocalValue(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}` +
    `T${pad(value.getHours())}:${pad(value.getMinutes())}`
  );
}

export function fromDatetimeLocalValue(value: string): Date | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

export function isValidRange(start: Date, end: Date): boolean {
  return start.getTime() < end.getTime();
}
