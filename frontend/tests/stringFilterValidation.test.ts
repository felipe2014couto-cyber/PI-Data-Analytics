import { describe, expect, it } from "vitest";
import { validateStringFilter } from "../src/utils/stringFilter";

describe("validateStringFilter", () => {
  it("accepts empty or whitespace-only expressions", () => {
    expect(validateStringFilter("").isValid).toBe(true);
    expect(validateStringFilter("   ").isValid).toBe(true);
  });

  it("accepts single values and disjunctions", () => {
    expect(validateStringFilter("P99").isValid).toBe(true);
    expect(validateStringFilter("P99;P100;ABC").isValid).toBe(true);
    expect(validateStringFilter("P99;;P100;").isValid).toBe(true);
  });

  it("accepts wildcards", () => {
    expect(validateStringFilter("P*").isValid).toBe(true);
    expect(validateStringFilter("*99").isValid).toBe(true);
    expect(validateStringFilter("P*99*").isValid).toBe(true);
    expect(validateStringFilter("P*;X*").isValid).toBe(true);
  });

  it("accepts valid ranges", () => {
    expect(validateStringFilter("P1:P100").isValid).toBe(true);
    expect(validateStringFilter("P100:P1").isValid).toBe(true);
    expect(validateStringFilter("ABC001:ABC050").isValid).toBe(true);
    expect(validateStringFilter("P1:P100;P150;X*").isValid).toBe(true);
  });

  it("rejects ranges with multiple colons", () => {
    const res = validateStringFilter("P1:P50:P100");
    expect(res.isValid).toBe(false);
    expect(res.error).toContain("Formato de intervalo inválido. Use INICIO:FIM.");
  });

  it("rejects incomplete ranges", () => {
    const res1 = validateStringFilter("P1:");
    expect(res1.isValid).toBe(false);
    expect(res1.error).toContain("Ambas as extremidades devem ser informadas");

    const res2 = validateStringFilter(":P100");
    expect(res2.isValid).toBe(false);
  });

  it("rejects ranges without ending numbers", () => {
    const res = validateStringFilter("ABC:XYZ");
    expect(res.isValid).toBe(false);
    expect(res.error).toContain("deve terminar com números");
  });

  it("rejects ranges with mismatched prefixes", () => {
    const res = validateStringFilter("P1:X100");
    expect(res.isValid).toBe(false);
    expect(res.error).toContain("prefixos das duas extremidades devem ser iguais");
  });

  it("rejects ranges with mismatched zero padding", () => {
    const res = validateStringFilter("P01:P005");
    expect(res.isValid).toBe(false);
    expect(res.error).toContain("preenchimento de zeros deve ser igual");
  });

  it("rejects ranges exceeding 10,000 count", () => {
    const res = validateStringFilter("P1:P20000");
    expect(res.isValid).toBe(false);
    expect(res.error).toContain("10.000");
  });
});
