import { describe, it, expect } from "vitest";
import {
  buildProductionUnitTimeSeries,
  isProductionUnitRule,
  isLegacyProductionUnitRule,
  productionUnitRuleLabel,
  productionUnitTooltip,
} from "../src/utils/productionUnitChart";
import {
  validateMetricConfiguration,
} from "../src/utils/analysisMetrics";
import { applyDataFilters, validateFilterConfiguration } from "../src/utils/dataFilters";
import type { ProductionUnitAnalysisResponse } from "../src/api";
import type {
  TimeSeries,
  MetricConfiguration,
  DataFilterConfiguration,
} from "../src/types";

describe("Production unit metrics calculation and lifecycle", () => {
  const T = 1784080800000; // 2026-07-15T00:00:00Z
  const D = 1800000; // 30 minutes in ms

  const multiUmResponse: ProductionUnitAnalysisResponse = {
    start_time: new Date(T).toISOString(),
    end_time: new Date(T + 3 * D).toISOString(),
    um_tag_id: 10,
    equipment_id: 1,
    section_id: null,
    total_segments: 3,
    filtered_segments: 3,
    strategy: "timescaledb_segments",
    segments: [
      {
        segment_index: 0,
        um_value: "UM-101",
        start_time: new Date(T).toISOString(),
        end_time: new Date(T + D).toISOString(),
        duration_seconds: 1800,
        total_sample_count: 100,
        filtered_sample_count: 100,
        variables: [
          {
            tag_id: 1,
            tag_name: "REAL_TAG_1",
            display_name: "Temperatura A",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 10,
            filtered_sample_count: 10,
            sample_count: 10,
            average: 100,
            minimum: 80,
            maximum: 120,
            attended_percent: 95.5,
          },
          {
            tag_id: 2,
            tag_name: "REF_TAG_2",
            display_name: "Temperatura Ref",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 10,
            filtered_sample_count: 10,
            sample_count: 10,
            average: 90,
            minimum: 85,
            maximum: 95,
            attended_percent: 100,
          },
        ],
      },
      {
        segment_index: 1,
        um_value: "UM-102",
        start_time: new Date(T + D).toISOString(),
        end_time: new Date(T + 2 * D).toISOString(),
        duration_seconds: 1800,
        total_sample_count: 100,
        filtered_sample_count: 100,
        variables: [
          {
            tag_id: 1,
            tag_name: "REAL_TAG_1",
            display_name: "Temperatura A",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 8,
            filtered_sample_count: 8,
            sample_count: 8,
            average: 200,
            minimum: 190,
            maximum: 210,
            attended_percent: 88.0,
          },
          {
            tag_id: 2,
            tag_name: "REF_TAG_2",
            display_name: "Temperatura Ref",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 8,
            filtered_sample_count: 8,
            sample_count: 8,
            average: 195,
            minimum: 190,
            maximum: 200,
            attended_percent: 100,
          },
        ],
      },
      {
        segment_index: 2,
        um_value: "UM-103",
        start_time: new Date(T + 2 * D).toISOString(),
        end_time: new Date(T + 3 * D).toISOString(),
        duration_seconds: 1800,
        total_sample_count: 100,
        filtered_sample_count: 100,
        variables: [
          {
            tag_id: 1,
            tag_name: "REAL_TAG_1",
            display_name: "Temperatura A",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 0,
            filtered_sample_count: 0,
            sample_count: 0,
            average: null,
            minimum: null,
            maximum: null,
            attended_percent: null,
          },
          {
            tag_id: 2,
            tag_name: "REF_TAG_2",
            display_name: "Temperatura Ref",
            unit: "°C",
            data_type: "NUMERIC",
            raw_sample_count: 0,
            filtered_sample_count: 0,
            sample_count: 0,
            average: null,
            minimum: null,
            maximum: null,
            attended_percent: null,
          },
        ],
      },
    ],
  } as any;

  const rawTimeSeries: TimeSeries = {
    start_time: new Date(T).toISOString(),
    end_time: new Date(T + 3 * D).toISOString(),
    mode: "recorded",
    series: [
      {
        tag_id: 1,
        tag_name: "REAL_TAG_1",
        display_name: "Temperatura A",
        equipment: "EQ1",
        section: "SEC1",
        variable_type: "TEMP",
        unit: "°C",
        points: [
          // UM-101: 5 points: values: 10, 20, 30, 40, 50
          { timestamp: new Date(T).toISOString(), value: 10, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 300000).toISOString(), value: 20, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 600000).toISOString(), value: 30, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 900000).toISOString(), value: 40, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 1200000).toISOString(), value: 50, good: true, questionable: false, substituted: false },
          // Boundary check: exactly at T + D (10:30) belongs to UM-102, NOT UM-101
          // UM-102: 4 points: values: 100, 110, 120, 130
          { timestamp: new Date(T + D).toISOString(), value: 100, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 300000).toISOString(), value: 110, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 600000).toISOString(), value: 120, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 900000).toISOString(), value: 130, good: true, questionable: false, substituted: false },
          // UM-103: 0 points
        ],
      },
      {
        tag_id: 2,
        tag_name: "REF_TAG_2",
        display_name: "Temperatura Ref",
        equipment: "EQ1",
        section: "SEC1",
        variable_type: "TEMP",
        unit: "°C",
        points: [
          // UM-101: pairs with tag 1:
          // errors = actual - ref = (10-8)=2, (20-18)=2, (30-26)=4, (40-34)=6, (50-42)=8
          { timestamp: new Date(T).toISOString(), value: 8, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 300000).toISOString(), value: 18, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 600000).toISOString(), value: 26, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 900000).toISOString(), value: 34, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + 1200000).toISOString(), value: 42, good: true, questionable: false, substituted: false },
          // UM-102:
          // errors = (100-95)=5, (110-105)=5, (120-115)=5, (130-125)=5
          { timestamp: new Date(T + D).toISOString(), value: 95, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 300000).toISOString(), value: 105, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 600000).toISOString(), value: 115, good: true, questionable: false, substituted: false },
          { timestamp: new Date(T + D + 900000).toISOString(), value: 125, good: true, questionable: false, substituted: false },
        ],
      },
    ],
    errors: [],
  };

  describe("Preservation of 4 legacy Base Unidade rules", () => {
    it("preserves MEDIA, MIN, MAXIMO, OOC results and behavior", () => {
      for (const rule of ["MEDIA", "MIN", "MAXIMO", "OOC"] as const) {
        expect(isLegacyProductionUnitRule(rule)).toBe(true);
        expect(isProductionUnitRule(rule)).toBe(true);
      }

      // MEDIA
      const mediaResult = buildProductionUnitTimeSeries(multiUmResponse, "MEDIA", [1]);
      const mediaIntervals = mediaResult.series[0].unit_aggregation?.segments!;
      expect(mediaIntervals[0].value).toBe(100);
      expect(mediaIntervals[1].value).toBe(200);
      expect(mediaIntervals[2].value).toBeNull();

      // MIN
      const minResult = buildProductionUnitTimeSeries(multiUmResponse, "MIN", [1]);
      const minIntervals = minResult.series[0].unit_aggregation?.segments!;
      expect(minIntervals[0].value).toBe(80);
      expect(minIntervals[1].value).toBe(190);
      expect(minIntervals[2].value).toBeNull();

      // MAXIMO
      const maxResult = buildProductionUnitTimeSeries(multiUmResponse, "MAXIMO", [1]);
      const maxIntervals = maxResult.series[0].unit_aggregation?.segments!;
      expect(maxIntervals[0].value).toBe(120);
      expect(maxIntervals[1].value).toBe(210);
      expect(maxIntervals[2].value).toBeNull();

      // OOC (attended_percent)
      const oocResult = buildProductionUnitTimeSeries(multiUmResponse, "OOC", [1]);
      const oocIntervals = oocResult.series[0].unit_aggregation?.segments!;
      expect(oocIntervals[0].value).toBe(95.5);
      expect(oocIntervals[1].value).toBe(88.0);
      expect(oocIntervals[2].value).toBeNull();
      expect(oocResult.series[0].unit).toBe("%");
    });
  });

  describe("Distinction between OOC (% atendido) and ooc (contagem fora de controle)", () => {
    it("distinguishes OOC and ooc in rule labels, outputs and tooltips", () => {
      expect(productionUnitRuleLabel("OOC")).toBe("Atendido");
      expect(productionUnitRuleLabel("ooc")).toBe("Fora de controle");

      // ooc counts observations outside LIC and LSC
      const config: MetricConfiguration = {
        kind: "control",
        metric: "ooc",
        lowerControl: 15,
        upperControl: 45,
      };

      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "ooc",
        [1],
        null,
        rawTimeSeries,
        config,
      );

      const intervals = result.series[0].unit_aggregation?.segments!;
      // UM-101 has points: 10, 20, 30, 40, 50. Outside [15, 45]: 10 and 50 -> count is 2
      expect(intervals[0].value).toBe(2);
      expect(intervals[0].oocCount).toBe(2);

      // UM-102 has points: 100, 110, 120, 130. All 4 are > 45 -> count is 4
      expect(intervals[1].value).toBe(4);
      expect(intervals[1].oocCount).toBe(4);

      // UM-103 has 0 points -> null
      expect(intervals[2].value).toBeNull();

      const tooltipOoc = productionUnitTooltip(
        result.series[0].unit_aggregation!,
        T + 1000,
        "Temperatura A",
        "amostras",
      );
      expect(tooltipOoc).toContain("Fora de controle: 2");
    });
  });

  describe("Single-series metrics calculated per UM interval", () => {
    it("calculates count and total per UM", () => {
      // count
      const countResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "count",
        [1],
        null,
        rawTimeSeries,
      );
      const countIntervals = countResult.series[0].unit_aggregation?.segments!;
      expect(countIntervals[0].value).toBe(5);
      expect(countIntervals[1].value).toBe(4);
      expect(countIntervals[2].value).toBeNull();

      // total
      const totalResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "total",
        [1],
        null,
        rawTimeSeries,
      );
      const totalIntervals = totalResult.series[0].unit_aggregation?.segments!;
      expect(totalIntervals[0].value).toBe(150); // 10 + 20 + 30 + 40 + 50
      expect(totalIntervals[1].value).toBe(460); // 100 + 110 + 120 + 130
      expect(totalIntervals[2].value).toBeNull();
    });

    it("calculates standardDeviation per UM", () => {
      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "standardDeviation",
        [1],
        null,
        rawTimeSeries,
      );
      const intervals = result.series[0].unit_aggregation?.segments!;
      // UM-101: [10, 20, 30, 40, 50] -> std dev = sqrt(1000/4) = sqrt(250) ≈ 15.8113883
      expect(intervals[0].value).toBeCloseTo(Math.sqrt(250), 4);
      // UM-102: [100, 110, 120, 130] -> std dev = sqrt(500/3) ≈ 12.90994
      expect(intervals[1].value).toBeCloseTo(Math.sqrt(500 / 3), 4);
      // UM-103: 0 points -> null
      expect(intervals[2].value).toBeNull();
    });

    it("calculates Cp and Cpk per UM respecting specification limits", () => {
      const config: MetricConfiguration = {
        kind: "specification",
        metric: "cp",
        lowerSpecification: 0,
        upperSpecification: 60,
      };

      // Cp for UM-101: (60 - 0) / (6 * 15.8113883) = 60 / 94.8683298 ≈ 0.6324555
      const cpResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "cp",
        [1],
        null,
        rawTimeSeries,
        config,
      );
      const cpIntervals = cpResult.series[0].unit_aggregation?.segments!;
      expect(cpIntervals[0].value).toBeCloseTo(60 / (6 * Math.sqrt(250)), 4);
      // UM-103 has 0 points -> null
      expect(cpIntervals[2].value).toBeNull();

      // Cpk for UM-101: mean = 30. min((60-30)/(3*sd), (30-0)/(3*sd)) = 30 / (3*sd) = 10 / sd ≈ 0.6324555
      const cpkConfig: MetricConfiguration = {
        kind: "specification",
        metric: "cpk",
        lowerSpecification: 0,
        upperSpecification: 60,
      };
      const cpkResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "cpk",
        [1],
        null,
        rawTimeSeries,
        cpkConfig,
      );
      const cpkIntervals = cpkResult.series[0].unit_aggregation?.segments!;
      expect(cpkIntervals[0].value).toBeCloseTo(10 / Math.sqrt(250), 4);
    });

    it("calculates percentual conforme (pc) per UM", () => {
      const config: MetricConfiguration = {
        kind: "specification",
        metric: "pc",
        lowerSpecification: 15,
        upperSpecification: 45,
      };
      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "pc",
        [1],
        null,
        rawTimeSeries,
        config,
      );
      const intervals = result.series[0].unit_aggregation?.segments!;
      // UM-101: 5 points: 10, 20, 30, 40, 50. In [15, 45]: 20, 30, 40 -> 3/5 = 60%
      expect(intervals[0].value).toBe(60);
      // UM-102: points 100, 110, 120, 130. In [15, 45]: 0 -> 0%
      expect(intervals[1].value).toBe(0);
      // UM-103: 0 points -> null
      expect(intervals[2].value).toBeNull();
    });
  });

  describe("Dual-series error metrics calculated per UM interval", () => {
    it("pairs actual and reference series per UM and calculates error metrics", () => {
      const config: MetricConfiguration = {
        kind: "error",
        metric: "meanError",
        actualTagId: 1,
        referenceTagId: 2,
      };

      // meanError: UM-101 errors are [2, 2, 4, 6, 8] -> mean = 22 / 5 = 4.4
      // UM-102 errors are [5, 5, 5, 5] -> mean = 5.0
      const meanErrResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "meanError",
        [1, 2],
        null,
        rawTimeSeries,
        config,
      );
      const intervals = meanErrResult.series[0].unit_aggregation?.segments!;
      expect(intervals[0].value).toBeCloseTo(4.4, 4);
      expect(intervals[1].value).toBe(5.0);
      expect(intervals[2].value).toBeNull();
      expect(meanErrResult.series[0].points[0].value).toBeCloseTo(4.4, 4);

      // minimumError & maximumError
      const minErr = buildProductionUnitTimeSeries(
        multiUmResponse,
        "minimumError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "minimumError" },
      );
      expect(minErr.series[0].unit_aggregation?.segments[0].value).toBe(2);

      const maxErr = buildProductionUnitTimeSeries(
        multiUmResponse,
        "maximumError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "maximumError" },
      );
      expect(maxErr.series[0].unit_aggregation?.segments[0].value).toBe(8);

      // meanAbsoluteError: errors are [2, 2, 4, 6, 8] -> abs mean = 4.4
      const mae = buildProductionUnitTimeSeries(
        multiUmResponse,
        "meanAbsoluteError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "meanAbsoluteError" },
      );
      expect(mae.series[0].unit_aggregation?.segments[0].value).toBeCloseTo(4.4, 4);

      // meanSquaredError: (4 + 4 + 16 + 36 + 64) / 5 = 124 / 5 = 24.8
      const mse = buildProductionUnitTimeSeries(
        multiUmResponse,
        "meanSquaredError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "meanSquaredError" },
      );
      expect(mse.series[0].unit_aggregation?.segments[0].value).toBeCloseTo(24.8, 4);

      // rootMeanSquaredError: sqrt(24.8) ≈ 4.97996
      const rmse = buildProductionUnitTimeSeries(
        multiUmResponse,
        "rootMeanSquaredError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "rootMeanSquaredError" },
      );
      expect(rmse.series[0].unit_aggregation?.segments[0].value).toBeCloseTo(Math.sqrt(24.8), 4);

      // standardDeviationError: sample deviation of [2, 2, 4, 6, 8]
      // mean = 4.4. deltas = [-2.4, -2.4, -0.4, 1.6, 3.6]. squared = [5.76, 5.76, 0.16, 2.56, 12.96] -> sum = 27.2
      // sample deviation = sqrt(27.2 / 4) = sqrt(6.8) ≈ 2.60768
      const sde = buildProductionUnitTimeSeries(
        multiUmResponse,
        "standardDeviationError",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "standardDeviationError" },
      );
      expect(sde.series[0].unit_aggregation?.segments[0].value).toBeCloseTo(Math.sqrt(6.8), 4);
    });

    it("calculates cpkError per UM", () => {
      const config: MetricConfiguration = {
        kind: "errorCapability",
        metric: "cpkError",
        actualTagId: 1,
        referenceTagId: 2,
        lowerSpecification: -5,
        upperSpecification: 15,
      };

      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "cpkError",
        [1, 2],
        null,
        rawTimeSeries,
        config,
      );
      const intervals = result.series[0].unit_aggregation?.segments!;
      // errors: mean = 4.4, sd = sqrt(6.8) ≈ 2.60768
      // upper = (15 - 4.4) / (3 * 2.60768) = 10.6 / 7.823 = 1.3549
      // lower = (4.4 - (-5)) / (3 * 2.60768) = 9.4 / 7.823 = 1.2015
      // min = 1.2015
      expect(intervals[0].value).toBeCloseTo(9.4 / (3 * Math.sqrt(6.8)), 4);
      // UM-102 has errors [5, 5, 5, 5], sd = 0 -> cpkError returns null (division by 0 prevented)
      expect(intervals[1].value).toBeNull();
    });

    it("calculates oocMaeMaximum and oocMaeMean per UM", () => {
      const config: MetricConfiguration = {
        kind: "oocError",
        metric: "oocMaeMaximum",
        actualTagId: 1,
        referenceTagId: 2,
        lowerControl: 15,
        upperControl: 45,
      };

      // In UM-101, actual values are 10, 20, 30, 40, 50. Outside [15, 45]:
      // pair 1: actual = 10 (ref = 8, error = 2)
      // pair 5: actual = 50 (ref = 42, error = 8)
      // ooc errors: [2, 8] -> max = 8, mean = 5
      const maxResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "oocMaeMaximum",
        [1, 2],
        null,
        rawTimeSeries,
        config,
      );
      expect(maxResult.series[0].unit_aggregation?.segments[0].value).toBe(8);

      const meanResult = buildProductionUnitTimeSeries(
        multiUmResponse,
        "oocMaeMean",
        [1, 2],
        null,
        rawTimeSeries,
        { ...config, metric: "oocMaeMean" },
      );
      expect(meanResult.series[0].unit_aggregation?.segments[0].value).toBe(5);
    });
  });

  describe("Data quality and filter application per UM", () => {
    it("excludes points marked as filtered_out and handles ignoreBadQuality", () => {
      const filteredSeries: TimeSeries = {
        ...rawTimeSeries,
        series: [
          {
            ...rawTimeSeries.series[0],
            points: [
              // Point 1: good
              { timestamp: new Date(T).toISOString(), value: 10, good: true, questionable: false, substituted: false },
              // Point 2: filtered out by dynamic filter
              { timestamp: new Date(T + 300000).toISOString(), value: 20, good: true, questionable: false, substituted: false, filtered_out: true },
              // Point 3: bad quality
              { timestamp: new Date(T + 600000).toISOString(), value: 30, good: false, questionable: false, substituted: false },
            ],
          },
        ],
      };

      // When ignoreBadQuality is false: bad quality points are NOT ignored (retained) -> Point 1 (good) and Point 3 (bad) -> count = 2
      const resWithoutIgnore = buildProductionUnitTimeSeries(
        multiUmResponse,
        "count",
        [1],
        null,
        filteredSeries,
        undefined,
        false,
      );
      expect(resWithoutIgnore.series[0].unit_aggregation?.segments[0].value).toBe(2);

      // When ignoreBadQuality is true: bad quality points ARE ignored (discarded) -> only Point 1 remains -> count = 1
      const resWithIgnore = buildProductionUnitTimeSeries(
        multiUmResponse,
        "count",
        [1],
        null,
        filteredSeries,
        undefined,
        true,
      );
      expect(resWithIgnore.series[0].unit_aggregation?.segments[0].value).toBe(1);
    });
  });

  describe("Validation of limits and insufficient data", () => {
    it("returns null when specification limits are missing or invalid (LIE >= LSE)", () => {
      const invalidLimits: MetricConfiguration = {
        kind: "specification",
        metric: "cp",
        lowerSpecification: 50,
        upperSpecification: 20, // LIE > LSE
      };

      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "cp",
        [1],
        null,
        rawTimeSeries,
        invalidLimits,
      );
      expect(result.series[0].unit_aggregation?.segments[0].value).toBeNull();

      const validationErrors = validateMetricConfiguration(invalidLimits, rawTimeSeries.series);
      expect(validationErrors).toContain("O limite inferior deve ser menor que o superior (LIE e LSE).");
    });

    it("returns null when sample size is insufficient for standard deviation (< 2 points)", () => {
      const singlePointSeries: TimeSeries = {
        ...rawTimeSeries,
        series: [
          {
            ...rawTimeSeries.series[0],
            points: [
              { timestamp: new Date(T).toISOString(), value: 10, good: true, questionable: false, substituted: false },
            ],
          },
        ],
      };

      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "standardDeviation",
        [1],
        null,
        singlePointSeries,
      );
      expect(result.series[0].unit_aggregation?.segments[0].value).toBeNull();
    });

    it("returns null for cpk when standard deviation is zero (division by zero)", () => {
      const constantSeries: TimeSeries = {
        ...rawTimeSeries,
        series: [
          {
            ...rawTimeSeries.series[0],
            points: [
              { timestamp: new Date(T).toISOString(), value: 10, good: true, questionable: false, substituted: false },
              { timestamp: new Date(T + 300000).toISOString(), value: 10, good: true, questionable: false, substituted: false },
              { timestamp: new Date(T + 600000).toISOString(), value: 10, good: true, questionable: false, substituted: false },
            ],
          },
        ],
      };

      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "cpk",
        [1],
        null,
        constantSeries,
        {
          kind: "specification",
          metric: "cpk",
          lowerSpecification: 5,
          upperSpecification: 15,
        },
      );
      expect(result.series[0].unit_aggregation?.segments[0].value).toBeNull();
    });
  });

  describe("Draft and filter configuration resilience in Base Unidade", () => {
    it("does not throw 'configuration.rules is not iterable' when filter configuration has missing or uninitialized rules", () => {
      // Scenario: draft state with missing rules or uninitialized object
      const draftConfigMissingRules = {
        quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
      } as unknown as DataFilterConfiguration;

      expect(() => validateFilterConfiguration(draftConfigMissingRules)).not.toThrow();
      expect(() => applyDataFilters(rawTimeSeries, draftConfigMissingRules)).not.toThrow();

      const filtered = applyDataFilters(rawTimeSeries, draftConfigMissingRules);
      expect(filtered.timeSeries).toBeDefined();
    });

    it("handles configuration passed as rules array defensively without throwing", () => {
      const rulesArray = [
        {
          id: "rule-1",
          kind: "numeric" as const,
          enabled: true,
          tagId: 1,
          operator: "greaterThan" as const,
          value: 25,
        },
      ];

      expect(() => applyDataFilters(rawTimeSeries, rulesArray as unknown as DataFilterConfiguration)).not.toThrow();
      const filtered = applyDataFilters(rawTimeSeries, rulesArray as unknown as DataFilterConfiguration);
      expect(filtered.timeSeries).toBeDefined();
    });

    it("correctly filters points and calculates UM metrics during consultation with draft active filters", () => {
      // Draft filter: only points where value >= 30 are retained
      const draftFilterConfig: DataFilterConfiguration = {
        quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
        rules: [
          {
            id: "draft-rule-1",
            kind: "numeric",
            enabled: true,
            tagId: 1,
            operator: "greaterThanOrEqual",
            value: 30,
            secondValue: null,
          },
        ],
      };

      const filtered = applyDataFilters(rawTimeSeries, draftFilterConfig);
      // In UM-101 (points 10, 20, 30, 40, 50), points 10 and 20 are marked filtered_out
      const result = buildProductionUnitTimeSeries(
        multiUmResponse,
        "count",
        [1],
        null,
        filtered.timeSeries,
      );

      const intervals = result.series[0].unit_aggregation?.segments!;
      // Points 30, 40, 50 -> count is 3
      expect(intervals[0].value).toBe(3);
      // UM-102 (points 100, 110, 120, 130): all >= 30 -> count is 4
      expect(intervals[1].value).toBe(4);
    });
  });
});
