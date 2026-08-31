import { buildMatchPagesFromResults, dedupePageNumbers } from "./viewerSearchUtils";

describe("viewer search match page helpers", () => {
  it("dedupes and sorts page numbers without invalid values", () => {
    expect(dedupePageNumbers([5, 2, 5, null, "7", "2", 0])).toEqual([2, 5, 7]);
  });

  it("keeps only matches for the current PDF and normalizes page numbers", () => {
    const results = [
      { pdf_id: "pdf-a", viewer_page: 3 },
      { pdf_id: "pdf-a", viewer_page: "3" },
      { pdf_id: "pdf-b", viewer_page: 9 },
      { pdf_id: "pdf-a", viewer_page: null },
    ];

    expect(buildMatchPagesFromResults(results, "pdf-a")).toEqual([3]);
  });
});
