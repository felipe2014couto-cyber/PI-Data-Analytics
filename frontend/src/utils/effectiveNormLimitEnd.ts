/** End of the interval where the main query has usable data, in UTC. */
export function effectiveNormLimitEnd(
  requestedEnd: string,
  effectiveEnd?: string | null,
  availableUntil?: string | null,
): string {
  const candidates = [requestedEnd, effectiveEnd, availableUntil]
    .filter((value): value is string => value !== null && value !== undefined)
    .map((value) => Date.parse(value))
    .filter(Number.isFinite);
  if (candidates.length === 0) return "";
  return new Date(Math.min(...candidates)).toISOString();
}
