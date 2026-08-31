import React from "react";
import { useNavigate } from "react-router-dom";
import { FileText } from "lucide-react";
import { highlightText } from "@/lib/searchText";

/**
 * Shared search results list — used by SharedLibraryDetail and SharedView.
 * Renders null while results are loading (null), empty state when [], list when populated.
 *
 * @param {Array|null} results
 * @param {string}     q           Raw user query (used for highlight and viewer URL)
 * @param {string}     shareToken  Passed as &share= to PdfViewer when set
 * @param {string}     emptyText   Context-specific empty message
 */
export default function SearchResults({ results, q, shareToken = "", emptyText = "Nessun risultato trovato." }) {
  const navigate = useNavigate();
  if (!results) return null;

  const handleClick = (r) => {
    // Prefer explicit page label when available to avoid ambiguity
    // between numeric page labels and physical page numbers.
    const pageParam = r.page_label ? String(r.page_label) : (r.viewer_page ?? r.actual_page ?? r.page ? String(r.viewer_page ?? r.actual_page ?? r.page) : "");
    navigate(
      `/viewer/${r.pdf_id}?page=${encodeURIComponent(pageParam)}&q=${encodeURIComponent(q.trim())}` +
      (shareToken ? `&share=${encodeURIComponent(shareToken)}` : "")
    );
  };

  return (
    <ul className="border-t border-rule">
      {results.length === 0 && (
        <li className="py-8 text-center text-muted2 text-sm italic">{emptyText}</li>
      )}
      {results.map((r, idx) => (
        <li key={`${r.pdf_id}-${r.page}-${idx}`} className="py-4 border-b border-rule hover:bg-canvas2 px-2 -mx-2 transition-colors">
          <button onClick={() => handleClick(r)} className="text-left w-full flex items-start gap-4">
            <FileText size={20} className="text-muted2 mt-1 shrink-0" />
            <div className="min-w-0">
              <div className="font-display font-bold text-lg hover:underline decoration-2 underline-offset-4">
                {highlightText(r.title, q, { defaultMarkClass: 'hl', chordMarkClass: 'bg-emerald-100 text-emerald-900 px-1 rounded' })}
                <span className="text-mono text-xs font-normal text-muted3 ml-2">PAG {r.page_label || r.page}</span>
                {r.is_protected && (
                  <span className="text-mono text-xs font-normal ml-2 px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-sm">PROTETTO</span>
                )}
              </div>
              {r.snippet && (
                <p className="text-sm text-muted2 mt-1 leading-relaxed">{highlightText(r.snippet, q, { defaultMarkClass: 'hl', chordMarkClass: 'bg-emerald-100 text-emerald-900 px-1 rounded' })}</p>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}
