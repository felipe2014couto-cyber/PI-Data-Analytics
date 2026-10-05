import { describe, expect, it } from "vitest";
import { ANALYSIS_MODEL_OPTIONS } from "../src/constants/analysisModels";
import { buildProductionUnitTimeSeries, productionUnitTooltip, findProductionUnitSegment, formatOocValue } from "../src/utils/productionUnitChart";
import { buildChartData } from "../src/utils/chartData";
import { buildTimeSeriesChartOption } from "../src/components/TimeSeriesChart";
import { unitResponse, unitVariable, UNIT_START as T, UNIT_DURATION as D } from "./fixtures/productionUnits";

function response() {
  const result = unitResponse([unitVariable({ attended_percent: 96.4, attended_sample_count: 482, eligible_sample_count: 500 }),unitVariable({tag_id:21,unit:'°C',attended_percent:80,attended_sample_count:4,eligible_sample_count:5})]);
  result.segments[1].variables.forEach(v => Object.assign(v,{ attended_percent: null, attended_sample_count: 0, eligible_sample_count:0 }));
  result.segments[2].variables.forEach(v => Object.assign(v,{ attended_percent: 50, attended_sample_count: 1, eligible_sample_count:2 }));
  return result;
}

describe("OOC as a metric of Base Unidade", () => {
  it("does not introduce an OOC model or base", () => {
    expect(ANALYSIS_MODEL_OPTIONS.some(option => String(option.value) === 'ooc' || option.label === 'Base OOC')).toBe(false);
  });
  it("renders independent percentages and null gaps per UM without numeric UM codes", () => {
    const result = buildProductionUnitTimeSeries(response(),'OOC',[20,21,29]);
    expect(result.series.map(s => s.tag_id)).toEqual([20,21]);
    expect(result.series.every(s => s.unit === '%')).toBe(true);
    expect(result.series[0].points.map(p => [Date.parse(p.timestamp),p.value])).toEqual([[T,96.4],[T+D,96.4],[T+D,null],[T+2*D,null],[T+2*D,50],[T+3*D,50]]);
    expect(result.series[1].points[0].value).toBe(80);
    expect(result.series[0].unit_aggregation?.segments[0].um).toBe('600304J2000B');
  });
  it("does not turn an all-null OOC variable into a zero line and keeps valid variables visible", () => {
    const source = response();
    source.segments[0].variables[0].attended_percent = 100;
    source.segments[2].variables[0].attended_percent = 100;
    source.segments.forEach(segment => {
      const zone = segment.variables.find(variable => variable.tag_id === 21)!;
      Object.assign(zone, { attended_percent: null, eligible_sample_count: 0, attended_sample_count: 0 });
    });
    const timeSeries = buildProductionUnitTimeSeries(source,'OOC',[20,21]);
    const chart = buildChartData(timeSeries,{ignoreBadQuality:false});
    const nullVariable = chart.series.find(series => series.tagId === 21)!;
    expect(nullVariable.points.length).toBeGreaterThan(0);
    expect(nullVariable.points.every(([,value]) => value === null)).toBe(true);
    expect(nullVariable.points.some(([,value]) => value === 0)).toBe(false);

    const option = buildTimeSeriesChartOption({ chart, equipment:'RB1', start:new Date(T),end:new Date(T+3*D),mode:'recorded' });
    const rendered = option.series as Array<{id:string;data:Array<[number,number|null]>;connectNulls:boolean}>;
    expect(rendered.find(series => series.id === 'tag:21')?.data).toEqual([]);
    expect(rendered.find(series => series.id === 'tag:20')?.data).toEqual(chart.series.find(series => series.tagId === 20)?.points);
    expect(rendered.find(series => series.id === 'tag:20')?.data.some(([,value]) => value === 100)).toBe(true);
    expect(rendered.find(series => series.id === 'tag:21')?.connectNulls).toBe(false);
  });
  it("has a percent axis, no interpolation, and an OOC tooltip with exact counters", () => {
    const result = buildProductionUnitTimeSeries(response(),'OOC',[20]);
    const chart = buildChartData(result,{ignoreBadQuality:false});
    const option = buildTimeSeriesChartOption({ chart, equipment:'RB1', start:new Date(T),end:new Date(T+3*D),mode:'recorded' });
    expect((option.yAxis as any[])[0]).toMatchObject({min:0,max:100,axisLabel:{formatter:'{value}%'}});
    expect((option.series as any[])[0]).toMatchObject({step:'end',connectNulls:false});
    const tooltip = productionUnitTooltip(result.series[0].unit_aggregation!,T+1,'Velocidade','%');
    expect(tooltip).toContain('UM:');
    expect(tooltip).toContain('600304J2000B');
    expect(tooltip).toContain('Atendido: 96,4% (482/500 amostras)');
    expect(tooltip).not.toContain('Média da UM');
  });
  it("marker lookup remains constant, respects half-open transitions and reports empty UMs", () => {
    const segments = buildProductionUnitTimeSeries(response(),'OOC',[20]).series[0].unit_aggregation!.segments;
    for (const time of [T,T+1,T+D-1]) expect(formatOocValue(findProductionUnitSegment(segments,time))).toBe('96,4% (482/500 amostras)');
    expect(findProductionUnitSegment(segments,T+D)?.value).toBeNull();
    expect(formatOocValue(findProductionUnitSegment(segments,T+D))).toBe('sem amostras elegíveis');
    expect(formatOocValue(findProductionUnitSegment(segments,T+2*D))).toBe('50% (1/2 amostras)');
  });
  it("keeps real 0% and 100% without changing the backend response", () => {
    const original = response();
    original.segments[0].variables[0].attended_percent=0;
    original.segments[2].variables[0].attended_percent=100;
    const json = JSON.stringify(original);
    const result = buildProductionUnitTimeSeries(original,'OOC',[20]);
    expect(result.series[0].points[0].value).toBe(0);
    expect(result.series[0].points[4].value).toBe(100);
    expect(JSON.stringify(original)).toBe(json);
  });
  it.each([['MEDIA','average'],['MIN','minimum'],['MAXIMO','maximum']] as const)("%s preserves its existing statistics when OOC counters are present", (rule,field) => {
    const original = response();
    const result = buildProductionUnitTimeSeries(original,rule,[20]);
    expect(result.series[0].points[0].value).toBe(original.segments[0].variables[0][field]);
    expect(result.series[0].unit).toBe('m/min');
  });
});
