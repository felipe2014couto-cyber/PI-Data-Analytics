import { describe, expect, it } from "vitest";

import type { SeriesAssignment } from "../src/types";
import {
  createInitialAssignments,
  initializeScatterAssignments,
  moveAssignment,
  reconcileAssignments,
  resolveSeriesOrder,
  setLineAxis,
  setScatterAxis,
  validateAssignments,
  type AssignmentTag,
} from "../src/utils/seriesAssignments";

const tags: AssignmentTag[] = [
  { tagId: 10, unit: "°C", numeric: true },
  { tagId: 20, unit: "°C", numeric: true },
  { tagId: 30, unit: "bar", numeric: true },
];

describe("series assignments", () => {
  it("keeps the same tag independent by series instance identity", () => {
    const compared = createInitialAssignments([
      { tagId: 7, seriesInstanceId: "A-7", unit: "C", numeric: true },
      { tagId: 7, seriesInstanceId: "B-7", unit: "C", numeric: true },
    ]);
    const changed = setLineAxis(compared, "A-7", "secondary");
    expect(changed.find((item) => item.seriesInstanceId === "A-7")?.lineAxis).toBe("secondary");
    expect(changed.find((item) => item.seriesInstanceId === "B-7")?.lineAxis).toBe("primary");
  });
  it("creates one stable assignment per tag ID", () => {
    expect(createInitialAssignments(tags).map((entry) => entry.tagId)).toEqual([10, 20, 30]);
  });

  it("uses contiguous explicit order", () => {
    expect(createInitialAssignments(tags).map((entry) => entry.order)).toEqual([0, 1, 2]);
  });

  it("places the first unit on the primary axis", () => {
    expect(createInitialAssignments(tags)[0].lineAxis).toBe("primary");
  });

  it("keeps equal units on the same initial axis", () => {
    expect(createInitialAssignments(tags)[1].lineAxis).toBe("primary");
  });

  it("places the second unit on the secondary axis", () => {
    expect(createInitialAssignments(tags)[2].lineAxis).toBe("secondary");
  });

  it("adds a new tag deterministically", () => {
    const current = createInitialAssignments(tags.slice(0, 2));
    const result = reconcileAssignments(current, tags);
    expect(result.map((entry) => entry.tagId)).toEqual([10, 20, 30]);
    expect(result[2].lineAxis).toBe("secondary");
  });

  it("removes only the deselected tag", () => {
    const result = reconcileAssignments(createInitialAssignments(tags), [tags[0], tags[2]]);
    expect(result.map((entry) => entry.tagId)).toEqual([10, 30]);
  });

  it("preserves existing manual axes and roles", () => {
    const configured = setScatterAxis(setLineAxis(createInitialAssignments(tags), 10, "secondary"), "x", 10);
    expect(reconcileAssignments(configured, tags).find((entry) => entry.tagId === 10)).toMatchObject({ lineAxis: "secondary", scatterRole: "x" });
  });

  it("uses IDs rather than duplicate display names", () => {
    const result = reconcileAssignments(createInitialAssignments(tags.slice(0, 2)), [tags[1]]);
    expect(result).toHaveLength(1);
    expect(result[0].tagId).toBe(20);
  });

  it("does not change assignments when API series arrive in another order", () => {
    const assignments = createInitialAssignments(tags);
    const apiSeries = [{ tag_id: 30 }, { tag_id: 10 }, { tag_id: 20 }];
    expect(resolveSeriesOrder(apiSeries, assignments, (entry) => entry.tag_id).map((entry) => entry.tag_id)).toEqual([10, 20, 30]);
    expect(assignments.map((entry) => entry.tagId)).toEqual([10, 20, 30]);
  });

  it("moves a middle tag up", () => {
    expect(moveAssignment(createInitialAssignments(tags), 20, "up").map((entry) => entry.tagId)).toEqual([20, 10, 30]);
  });

  it("moves a middle tag down", () => {
    expect(moveAssignment(createInitialAssignments(tags), 20, "down").map((entry) => entry.tagId)).toEqual([10, 30, 20]);
  });

  it("does not move the first tag above the boundary", () => {
    const current = createInitialAssignments(tags);
    expect(moveAssignment(current, 10, "up")).toBe(current);
  });

  it("does not move the last tag below the boundary", () => {
    const current = createInitialAssignments(tags);
    expect(moveAssignment(current, 30, "down")).toBe(current);
  });

  it("changes a tag to the primary axis immutably", () => {
    const current = createInitialAssignments(tags);
    const next = setLineAxis(current, 30, "primary");
    expect(next[2].lineAxis).toBe("primary");
    expect(current[2].lineAxis).toBe("secondary");
  });

  it("changes a tag to the secondary axis", () => {
    expect(setLineAxis(createInitialAssignments(tags), 10, "secondary")[0].lineAxis).toBe("secondary");
  });

  it("accepts compatible units on one axis", () => {
    expect(validateAssignments(createInitialAssignments(tags.slice(0, 2)), tags.slice(0, 2), false).validAxes).toBe(true);
  });

  it("rejects incompatible units on one axis", () => {
    const assignments = setLineAxis(createInitialAssignments(tags), 30, "primary");
    expect(validateAssignments(assignments, tags, false).axisErrors[0]).toContain("incompatíveis");
  });

  it("allows tags without units together", () => {
    const noUnit = [{ tagId: 1, unit: null, numeric: true }, { tagId: 2, unit: " ", numeric: true }];
    expect(validateAssignments(createInitialAssignments(noUnit), noUnit, false).validAxes).toBe(true);
  });

  it("initializes X and Y from the configured order once", () => {
    const initialized = initializeScatterAssignments(createInitialAssignments(tags), [10, 20, 30]);
    expect(initialized.find((entry) => entry.scatterRole === "x")?.tagId).toBe(10);
    expect(initialized.find((entry) => entry.scatterRole === "y")?.tagId).toBe(20);
  });

  it("does not overwrite an existing manual scatter role", () => {
    const manual = setScatterAxis(createInitialAssignments(tags), "x", 30);
    expect(initializeScatterAssignments(manual, [10, 20, 30])).toBe(manual);
  });

  it("reports a missing X", () => {
    const configured = setScatterAxis(createInitialAssignments(tags), "y", 20);
    expect(validateAssignments(configured, tags, true).scatterErrors).toContain("Selecione uma tag numérica para o eixo X.");
  });

  it("reports a missing Y", () => {
    const configured = setScatterAxis(createInitialAssignments(tags), "x", 10);
    expect(validateAssignments(configured, tags, true).scatterErrors).toContain("Selecione uma tag numérica para o eixo Y.");
  });

  it("rejects the same stable tag ID in X and Y", () => {
    const invalid: SeriesAssignment[] = [
      { tagId: 10, order: 0, lineAxis: "primary", scatterRole: "x" },
      { tagId: 10, order: 1, lineAxis: "primary", scatterRole: "y" },
    ];
    expect(validateAssignments(invalid, tags, true).scatterErrors).toContain("Os eixos X e Y devem usar tags diferentes.");
  });

  it("clears X when its tag is removed without replacing it", () => {
    const configured = initializeScatterAssignments(createInitialAssignments(tags), [10, 20]);
    const reconciled = reconcileAssignments(configured, [tags[1], tags[2]]);
    expect(reconciled.some((entry) => entry.scatterRole === "x")).toBe(false);
    expect(reconciled.find((entry) => entry.scatterRole === "y")?.tagId).toBe(20);
  });

  it("clears Y when its tag is removed without replacing it", () => {
    const configured = initializeScatterAssignments(createInitialAssignments(tags), [10, 20]);
    const reconciled = reconcileAssignments(configured, [tags[0], tags[2]]);
    expect(reconciled.some((entry) => entry.scatterRole === "y")).toBe(false);
    expect(reconciled.find((entry) => entry.scatterRole === "x")?.tagId).toBe(10);
  });

  it.each(["textual", "boolean"])("rejects a %s series in scatter", () => {
    const nonNumeric = [{ tagId: 10, unit: null, numeric: false }, tags[1]];
    const configured = setScatterAxis(createInitialAssignments(nonNumeric), "x", 10);
    expect(validateAssignments(configured, nonNumeric, true).scatterErrors).toContain("A tag do eixo X deve ser numérica.");
  });

  it("returns new objects without mutating configured assignments", () => {
    const current = createInitialAssignments(tags);
    const snapshot = JSON.stringify(current);
    reconcileAssignments(current, tags);
    moveAssignment(current, 20, "up");
    setScatterAxis(current, "x", 10);
    expect(JSON.stringify(current)).toBe(snapshot);
  });
});
