import { shouldShowIndexedSearchContext } from "./PdfViewer";

describe("indexed search context visibility", () => {
  it("keeps OCR context visible when only indexed text is available", () => {
    expect(shouldShowIndexedSearchContext(true, { has_indexed_text: true, snippet: "" })).toBe(true);
  });

  it("does not show context when search is inactive and no snippet exists", () => {
    expect(shouldShowIndexedSearchContext(false, { has_indexed_text: true, snippet: "" })).toBe(false);
    expect(shouldShowIndexedSearchContext(true, { has_indexed_text: false, snippet: "" })).toBe(false);
  });
});
