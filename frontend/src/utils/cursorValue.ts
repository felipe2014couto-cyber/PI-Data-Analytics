export type CursorValueSource = "RECORDED" | "LINEAR_BETWEEN_RECORDED" | "STEP_STATE" | "GAP";

export interface CursorValueResult {
  value: number | null;
  source: CursorValueSource | null;
}

/** Resolve a cursor value from rendered RECORDED vertices without creating a sample. */
export function resolveNumericCursorValue(
  points: Array<[number, number | null]>,
  timestamp: number,
  step: boolean | null | undefined,
  quality?: Array<[number, number]>,
): CursorValueResult {
  if (!Number.isFinite(timestamp) || points.length === 0) return { value: null, source: null };
  let low = 0;
  let high = points.length - 1;
  let previous = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (points[mid][0] <= timestamp) {
      previous = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (previous >= 0 && points[previous][0] === timestamp) {
    const value = points[previous][1];
    return typeof value === "number" && Number.isFinite(value)
      ? { value, source: "RECORDED" }
      : { value: null, source: "GAP" };
  }
  const next = previous + 1;
  if (previous < 0 || next >= points.length) return { value: null, source: null };
  const [previousTs, previousValue] = points[previous];
  const [nextTs, nextValue] = points[next];
  if (
    typeof previousValue !== "number" || !Number.isFinite(previousValue) ||
    typeof nextValue !== "number" || !Number.isFinite(nextValue) || nextTs <= previousTs
  ) return { value: null, source: "GAP" };
  const qualityAt = (ts: number) => quality?.find((item) => item[0] === ts)?.[1];
  if (quality && (qualityAt(previousTs) !== 0 || qualityAt(nextTs) !== 0)) {
    return { value: null, source: "GAP" };
  }
  if (step === true) return { value: previousValue, source: "STEP_STATE" };
  if (step !== false) return { value: null, source: null };
  const ratio = (timestamp - previousTs) / (nextTs - previousTs);
  return {
    value: previousValue + (nextValue - previousValue) * ratio,
    source: "LINEAR_BETWEEN_RECORDED",
  };
}
