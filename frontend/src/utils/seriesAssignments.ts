import type {
  ScatterRole,
  SeriesAssignment,
  SeriesAxis,
} from "../types";

export interface AssignmentTag {
  tagId: number;
  seriesInstanceId?: string;
  unit: string | null;
  numeric: boolean;
}

export function assignmentIdentity(value: { tagId: number; seriesInstanceId?: string }): string {
  return value.seriesInstanceId ?? `tag:${value.tagId}`;
}

export interface AssignmentValidation {
  axisErrors: string[];
  scatterErrors: string[];
  validAxes: boolean;
  validScatter: boolean;
}

function unitKey(unit: string | null): string {
  return unit?.trim().toLocaleLowerCase("pt-BR") || "(sem unidade)";
}

function initialAxis(tag: AssignmentTag, existing: SeriesAssignment[], tags: AssignmentTag[]): SeriesAxis {
  const tagById = new Map(tags.map((entry) => [assignmentIdentity(entry), entry]));
  const sameUnit = existing.find((assignment) => {
    const assignedTag = tagById.get(assignmentIdentity(assignment));
    return assignedTag && unitKey(assignedTag.unit) === unitKey(tag.unit);
  });
  if (sameUnit) return sameUnit.lineAxis;
  const occupied = new Set(existing.map((assignment) => assignment.lineAxis));
  return occupied.has("primary") ? "secondary" : "primary";
}

export function createInitialAssignments(tags: AssignmentTag[]): SeriesAssignment[] {
  const assignments: SeriesAssignment[] = [];
  for (const tag of tags) {
    assignments.push({
      tagId: tag.tagId,
      seriesInstanceId: tag.seriesInstanceId,
      order: assignments.length,
      lineAxis: initialAxis(tag, assignments, tags),
      scatterRole: "none",
    });
  }
  return assignments;
}

export function reconcileAssignments(
  current: SeriesAssignment[],
  selectedTags: AssignmentTag[],
): SeriesAssignment[] {
  const selectedIds = new Set(selectedTags.map(assignmentIdentity));
  const preserved = [...current]
    .filter((assignment) => selectedIds.has(assignmentIdentity(assignment)))
    .sort((left, right) => left.order - right.order)
    .map((assignment, order) => ({ ...assignment, order }));
  const existingIds = new Set(preserved.map(assignmentIdentity));
  for (const tag of selectedTags) {
    if (existingIds.has(assignmentIdentity(tag))) continue;
    preserved.push({
      tagId: tag.tagId,
      seriesInstanceId: tag.seriesInstanceId,
      order: preserved.length,
      lineAxis: initialAxis(tag, preserved, selectedTags),
      scatterRole: "none",
    });
  }
  return preserved;
}

export function moveAssignment(
  assignments: SeriesAssignment[],
  seriesId: string | number,
  direction: "up" | "down",
): SeriesAssignment[] {
  const ordered = [...assignments].sort((left, right) => left.order - right.order);
  const index = ordered.findIndex((assignment) =>
    typeof seriesId === "string" ? assignmentIdentity(assignment) === seriesId : assignment.tagId === seriesId,
  );
  const target = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || target < 0 || target >= ordered.length) return assignments;
  const next = ordered.map((assignment) => ({ ...assignment }));
  [next[index], next[target]] = [next[target], next[index]];
  return next.map((assignment, order) => ({ ...assignment, order }));
}

export function setLineAxis(
  assignments: SeriesAssignment[], seriesId: string | number, lineAxis: SeriesAxis,
): SeriesAssignment[] {
  return assignments.map((assignment) =>
    (typeof seriesId === "string" ? assignmentIdentity(assignment) === seriesId : assignment.tagId === seriesId)
      ? { ...assignment, lineAxis } : assignment,
  );
}

export function setScatterAxis(
  assignments: SeriesAssignment[], role: Exclude<ScatterRole, "none">, seriesId: string | number | null,
): SeriesAssignment[] {
  return assignments.map((assignment) => {
    if (assignment.scatterRole === role) return { ...assignment, scatterRole: "none" };
    if (seriesId !== null && (typeof seriesId === "string" ? assignmentIdentity(assignment) === seriesId : seriesId === assignment.tagId)) return { ...assignment, scatterRole: role };
    return assignment;
  });
}

export function initializeScatterAssignments(
  assignments: SeriesAssignment[], numericTagIds: number[],
): SeriesAssignment[] {
  if (assignments.some((assignment) => assignment.scatterRole !== "none")) return assignments;
  const orderedNumeric = assignments
    .filter((assignment) => numericTagIds.includes(assignment.tagId))
    .sort((left, right) => left.order - right.order);
  if (orderedNumeric.length < 2) return assignments;
  return assignments.map((assignment) => ({
    ...assignment,
    scatterRole: assignment.tagId === orderedNumeric[0].tagId
      ? "x"
      : assignment.tagId === orderedNumeric[1].tagId ? "y" : "none",
  }));
}

export function resolveSeriesOrder<T>(
  series: T[], assignments: SeriesAssignment[], getTagId: (entry: T) => number, getSeriesId?: (entry: T) => string | undefined,
): T[] {
  const orderById = new Map(assignments.map((assignment) => [assignmentIdentity(assignment), assignment.order]));
  return [...series].sort((left, right) =>
    (orderById.get(getSeriesId?.(left) ?? `tag:${getTagId(left)}`) ?? Number.MAX_SAFE_INTEGER) -
    (orderById.get(getSeriesId?.(right) ?? `tag:${getTagId(right)}`) ?? Number.MAX_SAFE_INTEGER),
  );
}

export function validateAssignments(
  assignments: SeriesAssignment[], tags: AssignmentTag[], requireScatter: boolean,
): AssignmentValidation {
  const tagsById = new Map(tags.map((tag) => [assignmentIdentity(tag), tag]));
  const axisErrors: string[] = [];
  for (const axis of ["primary", "secondary"] as const) {
    const axisTags = assignments
      .filter((assignment) => assignment.lineAxis === axis)
      .map((assignment) => tagsById.get(assignmentIdentity(assignment)))
      .filter((tag): tag is AssignmentTag => Boolean(tag?.numeric));
    const units = new Set(axisTags.map((tag) => unitKey(tag.unit)));
    if (units.size > 1) {
      axisErrors.push(`O eixo Y ${axis === "primary" ? "principal" : "secundário"} possui unidades incompatíveis.`);
    }
  }
  const scatterErrors: string[] = [];
  const x = assignments.find((assignment) => assignment.scatterRole === "x");
  const y = assignments.find((assignment) => assignment.scatterRole === "y");
  if (requireScatter && !x) scatterErrors.push("Selecione uma tag numérica para o eixo X.");
  if (requireScatter && !y) scatterErrors.push("Selecione uma tag numérica para o eixo Y.");
  if (x && y && assignmentIdentity(x) === assignmentIdentity(y)) scatterErrors.push("Os eixos X e Y devem usar tags diferentes.");
  for (const [label, assignment] of [["X", x], ["Y", y]] as const) {
    if (assignment && !tagsById.get(assignmentIdentity(assignment))?.numeric) {
      scatterErrors.push(`A tag do eixo ${label} deve ser numérica.`);
    }
  }
  return {
    axisErrors,
    scatterErrors,
    validAxes: axisErrors.length === 0,
    validScatter: scatterErrors.length === 0,
  };
}
