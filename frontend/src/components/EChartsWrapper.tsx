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
  preserveDataZoom?: boolean;
  zoomKey?: string | number;
  activateAreaZoom?: boolean;
  syncGroup?: string;
  onBeforeSetOption?: () => void;
  onAfterSetOption?: () => void;
}

const connectedGroupCounts = new Map<string, number>();

function connectInstance(instance: ECharts, group: string): void {
  (instance as ECharts & { group?: string }).group = group;
  const count = connectedGroupCounts.get(group) ?? 0;
  connectedGroupCounts.set(group, count + 1);
  echarts.connect(group);
}

function disconnectInstance(group: string): void {
  const count = connectedGroupCounts.get(group) ?? 0;
  if (count <= 1) {
    connectedGroupCounts.delete(group);
    echarts.disconnect(group);
    return;
  }
  connectedGroupCounts.set(group, count - 1);
}

function activateDataZoomSelection(instance: ECharts): void {
  instance.dispatchAction({
    type: "takeGlobalCursor",
    key: "dataZoomSelect",
    dataZoomSelectActive: true,
  } as never);
}

export function EChartsWrapper({
  option,
  loading = false,
  className,
  height = 360,
  onInit,
  preserveDataZoom = true,
  zoomKey,
  activateAreaZoom = false,
  syncGroup,
  onBeforeSetOption,
  onAfterSetOption,
}: EChartsWrapperProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ECharts | null>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const lastZoomKeyRef = useRef<string | number | undefined>(undefined);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    let joinedSyncGroup = false;
    try {
      const instance = echarts.init(containerRef.current, undefined, { renderer: "canvas" }) as unknown as ECharts;
      chartRef.current = instance;
      if (syncGroup) {
        connectInstance(instance, syncGroup);
        joinedSyncGroup = true;
      }
      onBeforeSetOption?.();
      instance.setOption(option, { notMerge: true });
      onAfterSetOption?.();
      if (activateAreaZoom) {
        activateDataZoomSelection(instance);
      }
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
      if (syncGroup && joinedSyncGroup) {
        disconnectInstance(syncGroup);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (chartRef.current) {
      try {
        const currentOpt = chartRef.current.getOption() as any;
        let effectiveOption = option;

        // `zoomKey` identifies the query/domain the current zoom window belongs
        // to. When it changes (new query, new time range), reset the zoom;
        // otherwise always carry the user's window over — even though the
        // incoming option declares start: 0 / end: 100, that is just the
        // static config, not an intent to reset.
        const sameZoomKey = lastZoomKeyRef.current !== undefined && lastZoomKeyRef.current === zoomKey;

        if (preserveDataZoom && sameZoomKey) {
          const currentDz = currentOpt?.dataZoom?.[0];
          if (currentDz && Array.isArray((option as any)?.dataZoom)) {
            if (currentDz.startValue !== undefined && currentDz.endValue !== undefined) {
              effectiveOption = {
                ...option,
                dataZoom: (option as any).dataZoom.map((dzItem: any) => ({
                  ...dzItem,
                  startValue: currentDz.startValue,
                  endValue: currentDz.endValue,
                })),
              };
            } else if (currentDz.start !== undefined && currentDz.end !== undefined) {
              effectiveOption = {
                ...option,
                dataZoom: (option as any).dataZoom.map((dzItem: any) => ({
                  ...dzItem,
                  start: currentDz.start,
                  end: currentDz.end,
                })),
              };
            }
          }
        }
        lastZoomKeyRef.current = zoomKey;

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

        onBeforeSetOption?.();
        chartRef.current.setOption(effectiveOption, { notMerge: true });
        onAfterSetOption?.();
        if (activateAreaZoom) {
          activateDataZoomSelection(chartRef.current);
        }
      } catch {
        onBeforeSetOption?.();
        chartRef.current.setOption(option, { notMerge: true });
        onAfterSetOption?.();
        if (activateAreaZoom) {
          activateDataZoomSelection(chartRef.current);
        }
      }
    }
  }, [activateAreaZoom, option, preserveDataZoom, zoomKey, onBeforeSetOption, onAfterSetOption]);

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
