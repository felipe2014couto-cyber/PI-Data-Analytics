import type { SeriesVisualConfiguration, VisualColorRule, VisualRange } from "../types";

export const SAFE_MAX_OPACITY = 0.35;
export const EMPTY_VISUAL_CONFIGURATION = (seriesInstanceId: string): SeriesVisualConfiguration => ({
  seriesInstanceId, limits: [], ranges: [], rules: [],
});

export function isValidColor(color: string): boolean {
  return /^#[0-9a-f]{6}$/i.test(color);
}

export function parseFiniteNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function validateRange(range: Pick<VisualRange, "lower" | "upper" | "color" | "opacity">, others: readonly VisualRange[] = [], ownId?: string): string[] {
  const errors: string[] = [];
  if (!Number.isFinite(range.lower) || !Number.isFinite(range.upper)) errors.push("Os limites da faixa devem ser números finitos.");
  else if (range.lower >= range.upper) errors.push("O valor inferior deve ser menor que o superior.");
  if (!isValidColor(range.color)) errors.push("Cor inválida.");
  if (!Number.isFinite(range.opacity) || range.opacity < 0 || range.opacity > SAFE_MAX_OPACITY) errors.push(`A opacidade deve estar entre 0 e ${SAFE_MAX_OPACITY}.`);
  if (others.some((item) => item.id !== ownId && range.lower < item.upper && range.upper > item.lower)) errors.push("A faixa se sobrepõe a outra faixa.");
  return errors;
}

export function validateColorRule(rule: VisualColorRule): string[] {
  const errors: string[] = [];
  if (!isValidColor(rule.color)) errors.push("Cor inválida.");
  if (rule.operator === "between" || rule.operator === "outside") {
    if (rule.lower === null || rule.upper === null || !Number.isFinite(rule.lower) || !Number.isFinite(rule.upper)) errors.push("Informe o intervalo completo.");
    else if (rule.lower >= rule.upper) errors.push("O mínimo deve ser menor que o máximo.");
  } else if (rule.value === null || !Number.isFinite(rule.value)) errors.push("Informe um valor numérico finito.");
  return errors;
}

export function ruleMatches(value: unknown, rule: VisualColorRule): boolean {
  if (!rule.enabled || typeof value !== "number" || !Number.isFinite(value) || validateColorRule(rule).length) return false;
  switch (rule.operator) {
    case "<": return value < rule.value!;
    case "<=": return value <= rule.value!;
    case ">": return value > rule.value!;
    case ">=": return value >= rule.value!;
    case "==": return value === rule.value!;
    case "between": return value >= rule.lower! && value <= rule.upper!;
    case "outside": return value < rule.lower! || value > rule.upper!;
  }
}

export function firstMatchingRule(value: unknown, rules: readonly VisualColorRule[]): VisualColorRule | null {
  return rules.find((rule) => ruleMatches(value, rule)) ?? null;
}

export function matchingRange(value: unknown, ranges: readonly VisualRange[]): VisualRange | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return ranges.find((range) => range.visible && value >= range.lower && value <= range.upper) ?? null;
}

export function moveVisualItem<T>(items: readonly T[], index: number, direction: "up" | "down"): T[] {
  const target = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
