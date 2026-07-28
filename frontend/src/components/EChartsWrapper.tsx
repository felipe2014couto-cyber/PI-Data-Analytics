import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, BoxplotChart, LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  TitleComponent,
  ToolboxComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption, ECharts } from "echarts";

echarts.use([
  LineChart,
  BarChart,
  BoxplotChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  TitleComponent,
  ToolboxComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

export interface EChartsWrapperProps {
  option: EChartsOption;
  loading?: boolean;
  className?: string;
  height?: number | string;
  onInit?: (instance: ECharts) => void;
}

export function EChartsWrapper({
  option,
  loading = false,
  className,
  height = 360,
  onInit,
}: EChartsWrapperProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ECharts | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const instance = echarts.init(containerRef.current, undefined, { renderer: "canvas" }) as unknown as ECharts;
    chartRef.current = instance;
    instance.setOption(option, { notMerge: true });
    if (onInit) {
      onInit(instance);
    }
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => {
        instance.resize();
      });
      observer.observe(containerRef.current);
      observerRef.current = observer;
    } else {
      const handle = () => instance.resize();
      window.addEventListener("resize", handle);
      observerRef.current = { disconnect: () => window.removeEventListener("resize", handle) } as unknown as ResizeObserver;
    }
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
      instance.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.setOption(option, { notMerge: true });
    }
  }, [option]);

  useEffect(() => {
    if (chartRef.current) {
      if (loading) {
        chartRef.current.showLoading("default", { text: "Carregando..." });
      } else {
        chartRef.current.hideLoading();
      }
    }
  }, [loading]);

  return (
    <div
      ref={containerRef}
      className={className}
      data-testid="echarts-wrapper"
      style={{ width: "100%", height }}
    />
  );
}
