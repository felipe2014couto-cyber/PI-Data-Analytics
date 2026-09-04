import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdvancedFiltersPanel } from "../src/components/AdvancedFiltersPanel";
import type { DataFilterConfiguration } from "../src/types";

const configuration: DataFilterConfiguration = {
  quality: { excludeBad: false, excludeQuestionable: false, excludeSubstituted: false },
  rules: [],
};

describe("AdvancedFiltersPanel", () => {
  it("uses the explicitly linked width tag instead of matching a tag by name", () => {
    const onChange = vi.fn();
    render(
      <AdvancedFiltersPanel
        configuration={configuration}
        enabled
        hasData={false}
        summary={null}
        ruleResults={[]}
        onChange={onChange}
        tagOptions={[
          { id: 99, displayName: "Largura semelhante", tagName: "OTHER_WIDTH", dataType: "NUMERIC" },
          { id: 30, displayName: "LARGURA", tagName: "LFI_RB1_LARGURA_BOBINA", dataType: "NUMERIC", analysisRole: "width" },
        ]}
      />,
    );

    fireEvent.change(screen.getByTestId("named-filter-widthMin"), { target: { value: "1240" } });
    fireEvent.change(screen.getByTestId("named-filter-widthMax"), { target: { value: "1280" } });

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      rules: [expect.objectContaining({
        kind: "numeric",
        tagId: 30,
        operator: "between",
        value: 1240,
        secondValue: 1280,
      })],
    }));

    fireEvent.click(screen.getByTestId("named-filters-apply"));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      rules: [expect.objectContaining({ tagId: 30 })],
    }));
  });
});
