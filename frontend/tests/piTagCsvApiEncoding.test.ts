import { afterEach, describe, expect, it, vi } from "vitest";

import { piTagsApi } from "../src/api";

describe("CSV API byte transport", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the downloaded response Blob without decoding it", async () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0xe2, 0x81, 0xa3]);
    const blob = new Blob([bytes], { type: "text/csv; charset=utf-8" });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob });
    vi.stubGlobal("fetch", fetchMock);

    const result = await piTagsApi.downloadCsvTemplate();

    expect(result).toBe(blob);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/pi-tags/csv-template"),
      { credentials: "include" },
    );
  });

  it("uploads the selected File as FormData without text conversion", async () => {
    const file = new File([new Uint8Array([0xef, 0xbb, 0xbf, 0x61, 0xe2, 0x81, 0xa3])], "template.csv", { type: "text/csv" });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ valid: true }) });
    vi.stubGlobal("fetch", fetchMock);

    await piTagsApi.validateCsv(file);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/pi-tags/import-csv/validate");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const uploaded = (init.body as FormData).get("file") as File;
    expect(uploaded.name).toBe(file.name);
    expect(uploaded.size).toBe(file.size);
    expect(uploaded.type).toBe(file.type);
    const uploadedBytes = await new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(uploaded);
    });
    expect(Array.from(new Uint8Array(uploadedBytes))).toEqual(
      [0xef, 0xbb, 0xbf, 0x61, 0xe2, 0x81, 0xa3],
    );
    expect(init.headers).toEqual({});
  });
});
