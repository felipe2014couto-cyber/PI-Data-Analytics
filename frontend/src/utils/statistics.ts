import type { ChartSeries } from "./chartData";
import { isNumericValue } from "./values";

export interface HistogramBin {
  lower: number;
  upper: number;
  frequency: number;
  percentage: number;
  includesUpper: boolean;
}

export interface HistogramResult {
  count: number;
  min: number | null;
  max: number | null;
  bins: HistogramBin[];
}

export interface BoxPlotResult {
  count: number;
  lowerWhisker: number;
  q1: number;
  median: number;
  q3: number;
  upperWhisker: number;
  outliers: number[];
}

export interface BoxPlotUnitGroup {
  unit: string;
  series: ChartSeries[];
}

export function finiteNumbers(values: readonly unknown[]): number[] {
  return values.filter(isNumericValue);
}

export function numericValuesFromSeries(series: ChartSeries): number[] {
  return finiteNumbers(series.points.map((point) => point[1]));
}

export function buildHistogram(values: readonly unknown[]): HistogramResult {
  const numeric = finiteNumbers(values);
  if (numeric.length === 0) {
    return { count: 0, min: null, max: null, bins: [] };
  }

  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  if (min === max) {
    return {
      count: numeric.length,
      min,
      max,
      bins: [
        {
          lower: min,
          upper: max,
          frequency: numeric.length,
          percentage: 100,
          includesUpper: true,
        },
      ],
    };
  }

  const binCount = Math.min(50, Math.max(1, Math.ceil(Math.sqrt(numeric.length))));
  const width = (max - min) / binCount;
  const frequencies = Array.from({ length: binCount }, () => 0);

  for (const value of numeric) {
    const index = value === max
      ? binCount - 1
      : Math.min(binCount - 1, Math.floor((value - min) / width));
    frequencies[index] += 1;
  }

  return {
    count: numeric.length,
    min,
    max,
    bins: frequencies.map((frequency, index) => ({
      lower: min + index * width,
      upper: index === binCount - 1 ? max : min + (index + 1) * width,
      frequency,
      percentage: (frequency / numeric.length) * 100,
      includesUpper: index === binCount - 1,
    })),
  };
}

export function quantile(sortedValues: readonly number[], probability: number): number {
  if (sortedValues.length === 0) {
    throw new Error("Quantile requires at least one value.");
  }
  const position = (sortedValues.length - 1) * probability;
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  if (lowerIndex === upperIndex) return sortedValues[lowerIndex];
  const weight = position - lowerIndex;
  return sortedValues[lowerIndex] + (sortedValues[upperIndex] - sortedValues[lowerIndex]) * weight;
}

export function buildBoxPlot(values: readonly unknown[]): BoxPlotResult | null {
  const sorted = finiteNumbers(values).sort((left, right) => left - right);
  if (sorted.length === 0) return null;

  const q1 = quantile(sorted, 0.25);
  const median = quantile(sorted, 0.5);
  const q3 = quantile(sorted, 0.75);
  const iqr = q3 - q1;
  const lowerLimit = q1 - 1.5 * iqr;
  const upperLimit = q3 + 1.5 * iqr;
  const inliers = sorted.filter((value) => value >= lowerLimit && value <= upperLimit);
  const outliers = sorted.filter((value) => value < lowerLimit || value > upperLimit);

  return {
    count: sorted.length,
    lowerWhisker: inliers[0],
    q1,
    median,
    q3,
    upperWhisker: inliers[inliers.length - 1],
    outliers,
  };
}

export function groupSeriesByUnit(series: readonly ChartSeries[]): BoxPlotUnitGroup[] {
  const groups = new Map<string, BoxPlotUnitGroup>();
  for (const entry of series) {
    const unit = entry.unit?.trim() || "Sem unidade";
    const key = unit.toLocaleLowerCase("pt-BR");
    const current = groups.get(key);
    if (current) {
      current.series.push(entry);
    } else {
      groups.set(key, { unit, series: [entry] });
    }
  }
  return Array.from(groups.values());
}
