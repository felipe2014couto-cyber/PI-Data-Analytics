/**
 * Utility functions for validating string filter expressions in the frontend.
 * Provides immediate UX validation matching the backend string_filter_parser.
 */

export interface ValidationResult {
  isValid: boolean;
  error?: string;
}

const RANGE_REGEX = /^([A-Za-z0-9_.\s-]*?)(\d+)$/;
const MAX_RANGE_COUNT = 10000;

export function validateStringFilter(expression: string): ValidationResult {
  if (!expression || !expression.trim()) {
    return { isValid: true };
  }

  const tokens = expression.split(";").map((t) => t.trim()).filter(Boolean);
  if (tokens.length === 0) {
    return { isValid: true };
  }

  for (const token of tokens) {
    if (token.includes(":")) {
      const colons = (token.match(/:/g) || []).length;
      if (colons > 1) {
        return {
          isValid: false,
          error: "Formato de intervalo inválido. Use INICIO:FIM.",
        };
      }

      const parts = token.split(":");
      const startStr = parts[0].trim();
      const endStr = parts[1].trim();

      if (!startStr || !endStr) {
        return {
          isValid: false,
          error: "Formato de intervalo inválido. Ambas as extremidades devem ser informadas.",
        };
      }

      const match1 = startStr.match(RANGE_REGEX);
      const match2 = endStr.match(RANGE_REGEX);

      if (!match1 || !match2) {
        return {
          isValid: false,
          error: "Intervalo inválido: cada extremidade deve terminar com números.",
        };
      }

      const prefix1 = match1[1].toLowerCase();
      const prefix2 = match2[1].toLowerCase();

      if (prefix1 !== prefix2) {
        return {
          isValid: false,
          error: "Intervalo inválido: os prefixos das duas extremidades devem ser iguais.",
        };
      }

      const num1Str = match1[2];
      const num2Str = match2[2];
      const pad1 = num1Str.length > 1 && num1Str.startsWith("0") ? num1Str.length : 0;
      const pad2 = num2Str.length > 1 && num2Str.startsWith("0") ? num2Str.length : 0;

      if (pad1 > 0 && pad2 > 0 && pad1 !== pad2) {
        return {
          isValid: false,
          error: "Intervalo inválido: o preenchimento de zeros deve ser igual nas duas extremidades.",
        };
      }

      const val1 = parseInt(num1Str, 10);
      const val2 = parseInt(num2Str, 10);
      const count = Math.abs(val2 - val1) + 1;

      if (count > MAX_RANGE_COUNT) {
        return {
          isValid: false,
          error: `O intervalo excede o limite máximo de ${MAX_RANGE_COUNT.toLocaleString("pt-BR")} valores.`,
        };
      }
    }
  }

  return { isValid: true };
}
