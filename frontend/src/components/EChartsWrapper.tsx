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
    try {
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
    } catch {
      // Gracefully handle environments without native canvas (e.g. headless jsdom)
    }
    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
        observerRef.current = null;
      }
      try {
        chartRef.current?.dispose();
      } catch {
        // ignore dispose error
      }
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chartRef.current) {
      try {
        const currentOpt = chartRef.current.getOption() as any;
        let effectiveOption = option;

        // Preserve user's active zoom window (start/end or startValue/endValue) across option updates
        if (
          currentOpt?.dataZoom &&
          Array.isArray(currentOpt.dataZoom) &&
          Array.isArray((option as any)?.dataZoom)
        ) {
          const currentDz = currentOpt.dataZoom[0];
          if (
            currentDz &&
            (currentDz.start !== undefined || currentDz.startValue !== undefined)
          ) {
            effectiveOption = {
              ...option,
              dataZoom: (option as any).dataZoom.map((dzItem: any) => ({
                ...dzItem,
                ...(currentDz.start !== undefined ? { start: currentDz.start } : {}),
                ...(currentDz.end !== undefined ? { end: currentDz.end } : {}),
                ...(currentDz.startValue !== undefined ? { startValue: currentDz.startValue } : {}),
                ...(currentDz.endValue !== undefined ? { endValue: currentDz.endValue } : {}),
              })),
            };
          }
        }

        // Also preserve user's legend selection if present
        if (
          currentOpt?.legend?.[0]?.selected &&
          (effectiveOption as any)?.legend
        ) {
          const currentSelected = currentOpt.legend[0].selected;
          const legendConfig = Array.isArray((effectiveOption as any).legend)
            ? (effectiveOption as any).legend[0]
            : (effectiveOption as any).legend;
          if (legendConfig) {
            legendConfig.selected = { ...currentSelected, ...legendConfig.selected };
          }
        }

        chartRef.current.setOption(effectiveOption, { notMerge: true });
      } catch {
        chartRef.current.setOption(option, { notMerge: true });
      }
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
