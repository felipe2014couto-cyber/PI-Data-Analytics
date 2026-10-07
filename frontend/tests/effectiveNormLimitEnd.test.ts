import { describe, expect, it } from "vitest";
import { effectiveNormLimitEnd } from "../src/utils/effectiveNormLimitEnd";

describe("effective norm limit query range", () => {
  it("clamps a short requested tail to the main query watermark", () => {
    expect(effectiveNormLimitEnd(
      "2026-10-07T14:46:18.160Z",
      "2026-10-07T14:46:00.000Z",
      "2026-10-07T14:46:00.000Z",
    )).toBe("2026-10-07T14:46:00.000Z");
  });

  it("keeps an earlier requested or effective end", () => {
    expect(effectiveNormLimitEnd(
      "2026-10-07T14:46:00.000Z",
      "2026-10-07T14:46:10.000Z",
      "2026-10-07T14:46:20.000Z",
    )).toBe("2026-10-07T14:46:00.000Z");
  });
});
