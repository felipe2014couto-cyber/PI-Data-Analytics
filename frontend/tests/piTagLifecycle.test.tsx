import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActiveBadge } from "../src/components/ActiveBadge";

describe("ActiveBadge lifecycle and status rendering", () => {
  it("renders 'Ativo' when active is true", () => {
    render(<ActiveBadge active={true} lifecycleStatus="ACTIVE" />);
    expect(screen.getByText("Ativo")).toBeInTheDocument();
  });

  it("renders 'Inativo' when active is false", () => {
    render(<ActiveBadge active={false} lifecycleStatus="INACTIVE" />);
    expect(screen.getByText("Inativo")).toBeInTheDocument();
  });

  it("renders 'Excluindo...' when lifecycleStatus is DELETION_PENDING", () => {
    render(<ActiveBadge active={false} lifecycleStatus="DELETION_PENDING" />);
    expect(screen.getByText("Excluindo...")).toBeInTheDocument();
  });
});
