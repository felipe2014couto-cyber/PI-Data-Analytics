import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ErrorBoundary } from "../src/components/ErrorBoundary";

function BuggyComponent(): React.ReactElement {
  throw new Error("Test error");
}

function GoodComponent() {
  return <div data-testid="good-child">Content</div>;
}

function renderWithRouter(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    renderWithRouter(
      <ErrorBoundary>
        <GoodComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("good-child")).toBeInTheDocument();
  });

  it("renders error UI when child throws", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithRouter(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Algo deu errado")).toBeInTheDocument();
    expect(screen.getByText("Tentar novamente")).toBeInTheDocument();
    expect(screen.getByText("Voltar ao inicio")).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  it("renders custom fallback when provided", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithRouter(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Fallback</div>}>
        <BuggyComponent />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("custom-fallback")).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  it("resets error state when 'Tentar novamente' is clicked", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let shouldError = true;

    function ConditionalBuggy() {
      if (shouldError) {
        throw new Error("Test error");
      }
      return <div data-testid="recovered">Recovered</div>;
    }

    const { rerender } = renderWithRouter(
      <ErrorBoundary>
        <ConditionalBuggy />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Algo deu errado")).toBeInTheDocument();

    shouldError = false;
    fireEvent.click(screen.getByText("Tentar novamente"));

    rerender(
      <MemoryRouter>
        <ErrorBoundary>
          <ConditionalBuggy />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("recovered")).toBeInTheDocument();
    consoleSpy.mockRestore();
  });

  it("displays error details in collapsible section", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithRouter(
      <ErrorBoundary>
        <BuggyComponent />
      </ErrorBoundary>,
    );
    const details = screen.getByText("Detalhes do erro");
    fireEvent.click(details);
    expect(screen.getByText("Test error")).toBeInTheDocument();
    consoleSpy.mockRestore();
  });
});
