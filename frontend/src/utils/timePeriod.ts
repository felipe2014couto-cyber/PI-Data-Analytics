import type {
  RelativeTimeReference,
  RelativeTimeUnit,
  TimePeriod,
  TimePreset,
  TimezoneId,
} from "../types";

export const APPLICATION_TIMEZONE: TimezoneId = "America/Sao_Paulo";

export interface ResolvedTimePeriod {
  startTime: string;
  endTime: string;
  timezone: TimezoneId;
  referenceTime: string;
}

export class TimePeriodError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TimePeriodError";
  }
}

const PRESET_MS: Record<TimePreset, number> = {
  PT15M: 15 * 60_000,
  PT1H: 60 * 60_000,
  PT8H: 8 * 60 * 60_000,
  P1D: 24 * 60 * 60_000,
  P7D: 7 * 24 * 60 * 60_000,
};

interface CivilDateTime {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  millisecond: number;
}

const zonedFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: APPLICATION_TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function civilFromInstant(date: Date): CivilDateTime {
  const parts = Object.fromEntries(
    zonedFormatter.formatToParts(date).map((part) => [part.type, part.value]),
  );
  return {
    year: Number(parts.year), month: Number(parts.month), day: Number(parts.day),
    hour: Number(parts.hour), minute: Number(parts.minute), second: Number(parts.second),
    millisecond: date.getUTCMilliseconds(),
  };
}

function sameCivil(left: CivilDateTime, right: CivilDateTime): boolean {
  return left.year === right.year && left.month === right.month && left.day === right.day &&
    left.hour === right.hour && left.minute === right.minute && left.second === right.second &&
    left.millisecond === right.millisecond;
}

function utcGuess(civil: CivilDateTime): number {
  return Date.UTC(civil.year, civil.month - 1, civil.day, civil.hour, civil.minute, civil.second, civil.millisecond);
}

export function civilToUtc(civil: CivilDateTime): Date {
  const guess = utcGuess(civil);
  let candidate = guess;
  for (let iteration = 0; iteration < 4; iteration += 1) {
    const represented = civilFromInstant(new Date(candidate));
    const difference = utcGuess(civil) - utcGuess(represented);
    if (difference === 0) break;
    candidate += difference;
  }
  const resolved = new Date(candidate);
  if (!Number.isFinite(resolved.getTime()) || !sameCivil(civilFromInstant(resolved), civil)) {
    throw new TimePeriodError(`A data informada não existe no fuso ${APPLICATION_TIMEZONE}.`);
  }
  return resolved;
}

export function normalizeDateTimeInput(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";

  // 1. Brazilian format: DD/MM/YYYY[ ,T]HH:mm(:ss)?
  const brMatch = /^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:[ ,T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(trimmed);
  if (brMatch) {
    const day = brMatch[1].padStart(2, "0");
    const month = brMatch[2].padStart(2, "0");
    const year = brMatch[3];
    const hour = (brMatch[4] ?? "00").padStart(2, "0");
    const minute = (brMatch[5] ?? "00").padStart(2, "0");
    const second = brMatch[6] !== undefined ? brMatch[6].padStart(2, "0") : undefined;
    return second !== undefined
      ? `${year}-${month}-${day}T${hour}:${minute}:${second}`
      : `${year}-${month}-${day}T${hour}:${minute}`;
  }

  // 2. ISO with space instead of T: YYYY-MM-DD HH:mm(:ss)?
  const isoSpaceMatch = /^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(trimmed);
  if (isoSpaceMatch) {
    const second = isoSpaceMatch[6];
    return second !== undefined
      ? `${isoSpaceMatch[1]}-${isoSpaceMatch[2]}-${isoSpaceMatch[3]}T${isoSpaceMatch[4]}:${isoSpaceMatch[5]}:${second}`
      : `${isoSpaceMatch[1]}-${isoSpaceMatch[2]}-${isoSpaceMatch[3]}T${isoSpaceMatch[4]}:${isoSpaceMatch[5]}`;
  }

  // 3. ISO with trailing 'Z' or milliseconds: YYYY-MM-DDTHH:mm(:ss)?(\.\d+)?Z?
  const isoFullMatch = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?Z?$/.exec(trimmed);
  if (isoFullMatch) {
    return isoFullMatch[1];
  }

  return trimmed;
}

function parseCivil(value: string, label: "inicial" | "final"): CivilDateTime {
  if (!value.trim()) throw new TimePeriodError(`Informe a data e hora ${label}.`);
  const normalized = normalizeDateTimeInput(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(normalized);
  if (!match) throw new TimePeriodError(`A data informada não existe no fuso ${APPLICATION_TIMEZONE}.`);
  const civil: CivilDateTime = {
    year: Number(match[1]), month: Number(match[2]), day: Number(match[3]),
    hour: Number(match[4]), minute: Number(match[5]), second: Number(match[6] ?? 0), millisecond: 0,
  };
  const parsed = new Date(utcGuess(civil));
  if (parsed.getUTCFullYear() !== civil.year || parsed.getUTCMonth() + 1 !== civil.month ||
      parsed.getUTCDate() !== civil.day || civil.hour > 23 || civil.minute > 59 || civil.second > 59) {
    throw new TimePeriodError(`A data informada não existe no fuso ${APPLICATION_TIMEZONE}.`);
  }
  return civil;
}

function shiftCivilDays(civil: CivilDateTime, days: number): CivilDateTime {
  const shifted = new Date(Date.UTC(civil.year, civil.month - 1, civil.day + days, civil.hour, civil.minute, civil.second, civil.millisecond));
  return {
    year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(), minute: shifted.getUTCMinutes(), second: shifted.getUTCSeconds(),
    millisecond: shifted.getUTCMilliseconds(),
  };
}

function referenceEnd(now: Date, reference: RelativeTimeReference): Date {
  if (reference === "now") return new Date(now.getTime());
  const civil = civilFromInstant(now);
  return civilToUtc({
    ...civil,
    hour: reference === "startOfDay" ? 0 : 23,
    minute: reference === "startOfDay" ? 0 : 59,
    second: reference === "startOfDay" ? 0 : 59,
    millisecond: reference === "startOfDay" ? 0 : 999,
  });
}

function relativeStart(end: Date, amount: number, unit: RelativeTimeUnit): Date {
  if (unit === "minute") return new Date(end.getTime() - amount * 60_000);
  if (unit === "hour") return new Date(end.getTime() - amount * 60 * 60_000);
  const days = unit === "week" ? amount * 7 : amount;
  return civilToUtc(shiftCivilDays(civilFromInstant(end), -days));
}

export function resolveTimePeriod(period: TimePeriod, now: Date = new Date()): ResolvedTimePeriod {
  const captured = new Date(now.getTime());
  if (!Number.isFinite(captured.getTime())) throw new TimePeriodError("Instante de referência inválido.");
  let start: Date;
  let end: Date;
  if (period.kind === "preset") {
    end = captured;
    start = new Date(end.getTime() - PRESET_MS[period.preset]);
  } else if (period.kind === "absolute") {
    start = civilToUtc(parseCivil(period.start, "inicial"));
    end = civilToUtc(parseCivil(period.end, "final"));
  } else {
    if (!Number.isInteger(period.amount) || period.amount < 1 || !Number.isFinite(period.amount)) {
      throw new TimePeriodError("Informe uma quantidade inteira maior ou igual a 1.");
    }
    end = referenceEnd(captured, period.reference);
    start = relativeStart(end, period.amount, period.unit);
  }
  if (end.getTime() <= start.getTime()) {
    throw new TimePeriodError("A data final deve ser posterior à data inicial.");
  }
  return {
    startTime: start.toISOString(), endTime: end.toISOString(),
    timezone: APPLICATION_TIMEZONE, referenceTime: captured.toISOString(),
  };
}

export function timePeriodError(period: TimePeriod, now?: Date): string | null {
  try { resolveTimePeriod(period, now); return null; }
  catch (error) { return error instanceof Error ? error.message : "Período inválido."; }
}

export function formatDateTimeLocal(date: Date | string, timezone: string = APPLICATION_TIMEZONE): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (!Number.isFinite(d.getTime())) return "—";
  const formatter = new Intl.DateTimeFormat("pt-BR", {
    timeZone: timezone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  return formatter.format(d);
}

export function formatResolvedTimePeriod(resolved: ResolvedTimePeriod): string {
  return `${formatDateTimeLocal(resolved.startTime, resolved.timezone)} até ${formatDateTimeLocal(resolved.endTime, resolved.timezone)}`;
}

export const TIME_PRESET_OPTIONS: Array<{ value: TimePreset; label: string }> = [
  { value: "PT15M", label: "Últimos 15 minutos" },
  { value: "PT1H", label: "Última 1 hora" },
  { value: "PT8H", label: "Últimas 8 horas" },
  { value: "P1D", label: "Últimas 24 horas" },
  { value: "P7D", label: "Últimos 7 dias" },
];
