import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QuerySummary } from "../src/components/QuerySummary";

describe("QuerySummary recorded", () => {
  const metadata = {
    resolution_mode: "manual",
    sampled: false,
    partial: false,
    strategy: "streamset-recorded-batch",
    streamset_used: true,
    batch_used: true,
    batch_count: 2,
    batch_subrequest_count: 7,
    window_split_count: 3,
    pi_points_received: 12000,
    points_returned: 11998,
    complete: true,
    truncated: false,
  };

  it("exibe estrategia, metadados, status completo e aviso de volume", () => {
    render(
      <QuerySummary
        chart={null}
        startLocal="2026-07-01"
        endLocal="2026-07-02"
        durationMs={100}
        seriesCount={2}
        partial={false}
        mode="recorded"
        queryExecution={metadata}
      />,
    );
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("StreamSet Recorded + Batch");
    expect(screen.getByTestId("metric-batch-subrequests")).toHaveTextContent("7");
    expect(screen.getByTestId("metric-window-splits")).toHaveTextContent("3");
    expect(screen.getByTestId("metric-status")).toHaveTextContent("Completo");
    expect(screen.getByTestId("recorded-source-info")).toHaveTextContent("Histórico PI RECORDED");
    expect(screen.getByTestId("recorded-volume-warning")).toBeInTheDocument();
  });

  it("exibe parcial e aviso de truncamento", () => {
    render(
      <QuerySummary
        chart={null}
        startLocal="2026-07-01"
        endLocal="2026-07-02"
        durationMs={100}
        seriesCount={1}
        partial
        mode="recorded"
        queryExecution={{ ...metadata, partial: true, complete: false, truncated: true }}
      />,
    );
    expect(screen.getByTestId("metric-status")).toHaveTextContent("Parcial");
    expect(screen.getByTestId("truncated-warning")).toHaveTextContent("pode não conter todos os eventos");
  });

  it("separa sentinelas de renderização de medições descartadas", () => {
    render(
      <QuerySummary
        chart={{
          series: [], units: [], yAxisLabels: [], totalSeries: 1, totalPoints: 1370,
          totalNumericPoints: 1366, totalDroppedPoints: 0, totalRenderSentinels: 4,
          totalNonNumericPoints: 0, valueKind: "numeric", categories: [], comparisonType: null,
        }}
        startLocal="2026-09-29"
        endLocal="2026-09-30"
        durationMs={100}
        seriesCount={1}
        partial={false}
        mode="recorded"
        queryExecution={metadata}
      />,
    );
    expect(screen.getByTestId("metric-points")).toHaveTextContent("1370");
    expect(screen.getByTestId("metric-numeric")).toHaveTextContent("1366");
    expect(screen.getByTestId("metric-dropped")).toHaveTextContent("0");
    expect(screen.getByTestId("metric-render-gaps")).toHaveTextContent("4");
  });

  it("exibe TimescaleDB como fonte e TimescaleDB Direto como estrategia", () => {
    render(
      <QuerySummary
        chart={null}
        startLocal="2026-09-03"
        endLocal="2026-09-10"
        durationMs={25}
        seriesCount={1}
        partial={false}
        mode="recorded"
        queryExecution={{
          ...metadata,
          strategy: "timescaledb_direct",
          streamset_used: false,
          cache_hit: false,
        }}
      />,
    );
    expect(screen.getByTestId("metric-source")).toHaveTextContent("TimescaleDB");
    expect(screen.getByTestId("metric-strategy")).toHaveTextContent("TimescaleDB Direto");
  });

  it("explicita cobertura parcial sem sugerir preenchimento artificial", () => {
    render(
      <QuerySummary
        chart={null}
        startLocal="2026-07-01"
        endLocal="2026-07-02"
        durationMs={25}
        seriesCount={1}
        partial
        mode="recorded"
        queryExecution={{
          ...metadata,
          status: "PARTIAL",
          complete: false,
          real_points: 42,
          null_points: 3,
        }}
      />,
    );
    expect(screen.getByTestId("partial-coverage-warning")).toHaveTextContent("mantidos como lacunas");
    expect(screen.getByTestId("partial-coverage-warning")).toHaveTextContent("nenhum valor foi inventado");
  });
});
