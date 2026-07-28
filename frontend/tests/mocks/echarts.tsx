// Mock the EChartsWrapper to avoid canvas/ResizeObserver dependencies.
import { vi } from "vitest";

vi.mock("../src/components/EChartsWrapper", () => ({
  EChartsWrapper: ({ option, loading, height }: { option: unknown; loading?: boolean; height?: number | string }) => {
    // Render a JSON dump of the option for inspection in tests.
    const summary = JSON.stringify(option, (_key, value) =>
      typeof value === "function" ? "[fn]" : value,
    ).slice(0, 2000);
    return (
      <div
        data-testid="echarts-wrapper"
        data-loading={Boolean(loading)}
        data-height={height ?? 0}
        data-option={summary}
      />
    );
  },
}));
