export function normalizePageNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? Math.trunc(numeric) : null;
}

export function dedupePageNumbers(values) {
  const seen = new Set();
  return values
    .map((value) => normalizePageNumber(value))
    .filter((page) => page !== null && !seen.has(page) && seen.add(page))
    .sort((a, b) => a - b);
}

export function buildMatchPagesFromResults(results, pdfId) {
  if (!Array.isArray(results) || !pdfId) return [];

  const pages = results
    .filter((item) => String(item?.pdf_id ?? "") === String(pdfId))
    .map((item) => normalizePageNumber(item?.viewer_page ?? item?.actual_page ?? item?.page))
    .filter(Boolean);

  return dedupePageNumbers(pages);
}
