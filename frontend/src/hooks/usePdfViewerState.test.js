import { detectVisiblePage, shouldIgnoreScrollPageSync } from "./usePdfViewerState";
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

  it("keeps the page stable when a blank page is zero-height in the DOM", () => {
    const refs = {
      current: {
        1: { offsetTop: 0, offsetHeight: 1400 },
        2: { offsetTop: 1400, offsetHeight: 0 },
        3: { offsetTop: 2000, offsetHeight: 1400 },
      },
    };

    expect(detectVisiblePage(1600, () => 100, refs, 3, 1200)).toBe(2);
  });

  it("ignores stale scroll sync while a blank target page is settling", () => {
    const refs = {
      current: {
        1: { offsetTop: 0, offsetHeight: 1400 },
        2: { offsetTop: 1400, offsetHeight: 0 },
        3: { offsetTop: 2000, offsetHeight: 1400 },
      },
    };

    expect(shouldIgnoreScrollPageSync({
      currentPage: 2,
      detectedPage: 1,
      targetPage: 2,
      pageRefs: refs,
    })).toBe(true);

    expect(shouldIgnoreScrollPageSync({
      currentPage: 2,
      detectedPage: 2,
      targetPage: 2,
      pageRefs: refs,
    })).toBe(false);
  });
});
