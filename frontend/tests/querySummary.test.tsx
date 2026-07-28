import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QuerySummary } from "../src/components/QuerySummary";

describe("QuerySummary recorded exato", () => {
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
    expect(screen.getByTestId("recorded-exact-info")).toHaveTextContent("não foram interpolados nem reduzidos");
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
});
