import type {
  DataFilterConfiguration,
  DataFilterRule,
  FilterApplicationResult,
  FilterApplicationSummary,
  FilterRuleError,
  FilterRuleResult,
  NumericFilterOperator,
  TextFilterOperator,
  TimeSeries,
  TimeSeriesPoint,
  TimeSeriesSeries,
  Weekday,
} from "../types";
import { APPLICATION_TIMEZONE } from "./timePeriod";

const WEEKDAY_NAMES: Record<Weekday, number> = {
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
  sunday: 0,
};

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

function getSaoPauloWeekday(timestamp: string): number {
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return -1;
  const parts = Object.fromEntries(
    zonedFormatter.formatToParts(date).map((part) => [part.type, part.value]),
  );
  const localDate = new Date(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
  );
  return localDate.getDay();
}

function getSaoPauloHourMinutes(timestamp: string): { hour: number; minute: number } {
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return { hour: -1, minute: -1 };
  const parts = Object.fromEntries(
    zonedFormatter.formatToParts(date).map((part) => [part.type, part.value]),
  );
  return {
    hour: Number(parts.hour),
    minute: Number(parts.minute),
  };
}

function parseTime(timeStr: string): { hour: number; minute: number } | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(timeStr);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return { hour, minute };
}

function isValidNumericConfig(rule: DataFilterRule): rule is DataFilterRule & { kind: "numeric"; value: number; secondValue: number | null } {
  if (rule.kind !== "numeric") return false;
  if (rule.value === null || !Number.isFinite(rule.value)) return false;
  if (rule.operator === "between" || rule.operator === "outside") {
    if (rule.secondValue === null || !Number.isFinite(rule.secondValue)) return false;
    if (rule.value > rule.secondValue) return false;
  }
  return true;
}

function isValidTextConfig(rule: DataFilterRule): rule is DataFilterRule & { kind: "text"; value: string } {
  if (rule.kind !== "text") return false;
  return rule.value.trim().length > 0;
}

function isValidWeekdayConfig(rule: DataFilterRule | undefined): rule is DataFilterRule & { kind: "weekday" } {
  if (!rule || rule.kind !== "weekday") return false;
  return rule.days.length > 0;
}

function isValidTimeRangeConfig(rule: DataFilterRule | undefined): rule is DataFilterRule & { kind: "timeRange" } {
  if (!rule || rule.kind !== "timeRange") return false;
  const parsed = parseTime(rule.startTime);
  const parsedEnd = parseTime(rule.endTime);
  return parsed !== null && parsedEnd !== null;
}

function isValidExcludeConfig(rule: DataFilterRule): rule is DataFilterRule & { kind: "excludeValue" } {
  if (rule.kind !== "excludeValue") return false;
  if (rule.valueType === "number" && typeof rule.value !== "number") return false;
  if (rule.valueType === "string" && typeof rule.value !== "string") return false;
  if (rule.valueType === "boolean" && typeof rule.value !== "boolean") return false;
  if (rule.valueType === "string" && typeof rule.value === "string" && rule.value.trim().length === 0) return false;
  return true;
}

function numericMatches(value: number, operator: NumericFilterOperator, ruleValue: number, secondValue: number | null): boolean {
  switch (operator) {
    case "equal": return value === ruleValue;
    case "notEqual": return value !== ruleValue;
    case "greaterThan": return value > ruleValue;
    case "greaterThanOrEqual": return value >= ruleValue;
    case "lessThan": return value < ruleValue;
    case "lessThanOrEqual": return value <= ruleValue;
    case "between": return value >= ruleValue && value <= (secondValue ?? ruleValue);
    case "outside": return value < ruleValue || value > (secondValue ?? ruleValue);
  }
}

function textMatches(value: string, operator: TextFilterOperator, ruleValue: string, caseSensitive: boolean): boolean {
  const subject = caseSensitive ? value : value.toLocaleLowerCase("pt-BR");
  const pattern = caseSensitive ? ruleValue : ruleValue.toLocaleLowerCase("pt-BR");
  switch (operator) {
    case "equal": return subject === pattern;
    case "notEqual": return subject !== pattern;
    case "contains": return subject.includes(pattern);
    case "startsWith": return subject.startsWith(pattern);
    case "endsWith": return subject.endsWith(pattern);
  }
}

function isTimeInRange(
  hour: number,
  minute: number,
  startHour: number,
  startMinute: number,
  endHour: number,
  endMinute: number,
): boolean {
  const timeMinutes = hour * 60 + minute;
  const startMinutes = startHour * 60 + startMinute;
  const endMinutes = endHour * 60 + endMinute;
  if (startMinutes <= endMinutes) {
    return timeMinutes >= startMinutes && timeMinutes <= endMinutes;
  }
  return timeMinutes >= startMinutes || timeMinutes <= endMinutes;
}

export function validateFilterConfiguration(
  configuration: DataFilterConfiguration,
): FilterRuleError[] {
  const errors: FilterRuleError[] = [];
  for (const rule of configuration.rules) {
    if (!rule.enabled) continue;
    switch (rule.kind) {
      case "numeric":
        if (rule.value === null || !Number.isFinite(rule.value)) {
          errors.push({ ruleId: rule.id, message: "Valor numérico inválido ou não finito." });
        } else if ((rule.operator === "between" || rule.operator === "outside") && (rule.secondValue === null || !Number.isFinite(rule.secondValue))) {
          errors.push({ ruleId: rule.id, message: "Segundo valor inválido ou não finito." });
        } else if ((rule.operator === "between" || rule.operator === "outside") && rule.value !== null && rule.secondValue !== null && rule.value > rule.secondValue) {
          errors.push({ ruleId: rule.id, message: "O primeiro limite deve ser menor ou igual ao segundo." });
        }
        break;
      case "text":
        if (rule.value.trim().length === 0) {
          errors.push({ ruleId: rule.id, message: "O termo de busca não pode ser vazio." });
        }
        break;
      case "weekday":
        if (rule.days.length === 0) {
          errors.push({ ruleId: rule.id, message: "Selecione ao menos um dia da semana." });
        }
        break;
      case "timeRange":
        if (!parseTime(rule.startTime) || !parseTime(rule.endTime)) {
          errors.push({ ruleId: rule.id, message: "Horário inválido. Use HH:mm." });
        }
        break;
      case "excludeValue":
        if (rule.valueType === "number" && typeof rule.value !== "number") {
          errors.push({ ruleId: rule.id, message: "Valor de exclusão inválido." });
        } else if (rule.valueType === "string" && (typeof rule.value !== "string" || rule.value.trim().length === 0)) {
          errors.push({ ruleId: rule.id, message: "Valor de exclusão não pode ser vazio." });
        } else if (rule.valueType === "boolean" && typeof rule.value !== "boolean") {
          errors.push({ ruleId: rule.id, message: "Valor de exclusão deve ser true ou false." });
        }
        break;
    }
  }
  return errors;
}

export function applyDataFilters(
  timeSeries: TimeSeries,
  configuration: DataFilterConfiguration,
): FilterApplicationResult {
  const errors: FilterRuleError[] = validateFilterConfiguration(configuration);
  const validRuleIds = new Set(
    configuration.rules
      .filter((rule) => rule.enabled)
      .map((rule) => rule.id),
  );
  for (const err of errors) {
    if (err.ruleId) validRuleIds.delete(err.ruleId);
  }

  const quality = configuration.quality;
  const activeRules = configuration.rules.filter(
    (rule) => rule.enabled && validRuleIds.has(rule.id),
  );

  const weekdayRule = activeRules.find((r) => r.kind === "weekday");
  const timeRangeRule = activeRules.find((r) => r.kind === "timeRange");

  const numericRules = activeRules.filter((r) => r.kind === "numeric") as Array<DataFilterRule & { kind: "numeric" }>;
  const textRules = activeRules.filter((r) => r.kind === "text") as Array<DataFilterRule & { kind: "text" }>;
  const excludeRules = activeRules.filter((r) => r.kind === "excludeValue") as Array<DataFilterRule & { kind: "excludeValue" }>;

  const rulesByTag = new Map<string, DataFilterRule[]>();
  for (const rule of [...numericRules, ...textRules, ...excludeRules]) {
    if (rule.kind === "excludeValue" || rule.kind === "numeric" || rule.kind === "text") {
      const key = rule.seriesInstanceId ?? `tag:${rule.tagId}`;
      const list = rulesByTag.get(key) ?? [];
      list.push(rule);
      rulesByTag.set(key, list);
    }
  }

  const filteredSeries: TimeSeriesSeries[] = [];
  const ruleResultsMap = new Map<string, number>();
  for (const rule of configuration.rules) {
    ruleResultsMap.set(rule.id, 0);
  }

  let totalReceived = 0;
  let totalRemaining = 0;
  let removedByQuality = 0;
  let removedByNumeric = 0;
  let removedByText = 0;
  let removedByDateTime = 0;
  let removedByExclusion = 0;

  for (const series of timeSeries.series) {
    const seriesKey = series.series_instance_id ?? `tag:${series.tag_id}`;
    const tagRules = rulesByTag.get(seriesKey) ?? [];
    const newPoints: TimeSeriesPoint[] = [];
    const excludedPoints: TimeSeriesPoint[] = [];

    for (const point of series.points) {
      totalReceived += 1;
      let removed = false;

      if (quality.excludeBad && !point.good) {
        removed = true;
        removedByQuality += 1;
        excludedPoints.push(point);
      }
      if (!removed && quality.excludeQuestionable && point.questionable) {
        removed = true;
        removedByQuality += 1;
        excludedPoints.push(point);
      }
      if (!removed && quality.excludeSubstituted && point.substituted) {
        removed = true;
        removedByQuality += 1;
        excludedPoints.push(point);
      }

      if (!removed && weekdayRule && isValidWeekdayConfig(weekdayRule)) {
        const day = getSaoPauloWeekday(point.timestamp);
        if (!weekdayRule.days.some((d) => WEEKDAY_NAMES[d] === day)) {
          removed = true;
          removedByDateTime += 1;
          const count = ruleResultsMap.get(weekdayRule.id) ?? 0;
          ruleResultsMap.set(weekdayRule.id, count + 1);
          excludedPoints.push(point);
        }
      }

      if (!removed && timeRangeRule && isValidTimeRangeConfig(timeRangeRule)) {
        const { hour, minute } = getSaoPauloHourMinutes(point.timestamp);
        if (hour === -1) {
          excludedPoints.push(point);
          continue;
        }
        const start = parseTime(timeRangeRule.startTime)!;
        const end = parseTime(timeRangeRule.endTime)!;
        if (!isTimeInRange(hour, minute, start.hour, start.minute, end.hour, end.minute)) {
          removed = true;
          removedByDateTime += 1;
          const count = ruleResultsMap.get(timeRangeRule.id) ?? 0;
          ruleResultsMap.set(timeRangeRule.id, count + 1);
          excludedPoints.push(point);
        }
      }

      if (!removed) {
        for (const rule of tagRules) {
          if (rule.kind === "numeric" && isValidNumericConfig(rule)) {
            if (typeof point.value === "number" && Number.isFinite(point.value)) {
              if (!numericMatches(point.value, rule.operator, rule.value, rule.secondValue)) {
                removed = true;
                removedByNumeric += 1;
                const count = ruleResultsMap.get(rule.id) ?? 0;
                ruleResultsMap.set(rule.id, count + 1);
                excludedPoints.push(point);
                break;
              }
            }
          }
          if (rule.kind === "text" && isValidTextConfig(rule)) {
            if (typeof point.value === "string") {
              if (!textMatches(point.value, rule.operator, rule.value, rule.caseSensitive)) {
                removed = true;
                removedByText += 1;
                const count = ruleResultsMap.get(rule.id) ?? 0;
                ruleResultsMap.set(rule.id, count + 1);
                excludedPoints.push(point);
                break;
              }
            }
          }
        }
      }

      if (!removed) {
        for (const rule of excludeRules) {
          if (rule.kind === "excludeValue" && isValidExcludeConfig(rule) &&
              (rule.seriesInstanceId ? rule.seriesInstanceId === series.series_instance_id : rule.tagId === series.tag_id)) {
            if (rule.valueType === "number" && typeof point.value === "number") {
              if (point.value === rule.value) {
                removed = true;
                removedByExclusion += 1;
                const count = ruleResultsMap.get(rule.id) ?? 0;
                ruleResultsMap.set(rule.id, count + 1);
                excludedPoints.push(point);
                break;
              }
            }
            if (rule.valueType === "string" && typeof point.value === "string") {
              const matches = rule.caseSensitive
                ? point.value === rule.value
                : point.value.toLocaleLowerCase("pt-BR") === (rule.value as string).toLocaleLowerCase("pt-BR");
              if (matches) {
                removed = true;
                removedByExclusion += 1;
                const count = ruleResultsMap.get(rule.id) ?? 0;
                ruleResultsMap.set(rule.id, count + 1);
                excludedPoints.push(point);
                break;
              }
            }
            if (rule.valueType === "boolean" && typeof point.value === "boolean") {
              if (point.value === rule.value) {
                removed = true;
                removedByExclusion += 1;
                const count = ruleResultsMap.get(rule.id) ?? 0;
                ruleResultsMap.set(rule.id, count + 1);
                excludedPoints.push(point);
                break;
              }
            }
          }
        }
      }

      if (!removed) {
        newPoints.push(point);
        totalRemaining += 1;
      }
    }

    filteredSeries.push({
      ...series,
      points: newPoints,
    });
  }

  const totalRemoved = totalReceived - totalRemaining;

  const summary: FilterApplicationSummary = {
    receivedPoints: totalReceived,
    remainingPoints: totalRemaining,
    removedPoints: totalRemoved,
    removedByQuality,
    removedByNumeric,
    removedByText,
    removedByDateTime,
    removedByExclusion,
  };

  const ruleResults: FilterRuleResult[] = Array.from(ruleResultsMap.entries()).map(([ruleId, removedPoints]) => ({
    ruleId,
    removedPoints,
  }));

  return {
    filteredTimeSeries: {
      ...timeSeries,
      series: filteredSeries,
    },
    summary,
    ruleResults,
    errors,
  };
}

