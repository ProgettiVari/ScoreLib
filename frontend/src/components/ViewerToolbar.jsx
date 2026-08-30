import React from "react";
import {
  ArrowLeft,
  Star,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Cloud,
  HardDrive,
  Share2,
  Trash2,
} from "lucide-react";

/**
 * Presentational toolbar: page controls (left), search controls (right when active).
 */
export default function ViewerToolbar({
  meta,
  onBack,
  onToggleFavorite,
  page,
  search,
}) {
  return (
    <header className="viewer-toolbar" data-testid="viewer-toolbar">
      <div className="viewer-toolbar-header px-3 sm:px-4 md:px-6 py-2.5 flex items-center gap-2 sm:gap-3 flex-nowrap min-w-0">
        <button type="button" onClick={onBack} className="btn-ghost shrink-0" data-testid="viewer-back-btn">
          <ArrowLeft size={16} /> <span className="sr-only sm:not-sr-only sm:inline">Indietro</span>
        </button>
        <div className="viewer-toolbar-title flex-1 min-w-0 flex items-center justify-center gap-2 px-1 overflow-hidden">
          <span className="font-display font-semibold truncate text-center max-w-full">{meta?.title || "PDF"}</span>
          {meta && (
            <button type="button" onClick={onToggleFavorite} className="btn-ghost shrink-0" data-testid="viewer-favorite-btn" title="Preferito">
              <Star size={16} fill={meta.is_favorite ? "#0A0A0A" : "none"} strokeWidth={1.5} />
            </button>
          )}
          {meta?.storage_type && (
            <span
              className="text-mono text-[10px] px-2 py-0.5 rounded-sm border border-rule text-muted2 inline-flex items-center gap-1 shrink-0"
              data-testid="viewer-storage-badge"
              title={meta.storage_type === "google_drive" ? `Drive · ${meta.drive_file_id}` : `Locale · ${meta.file_path}`}
            >
              {meta.storage_type === "google_drive" ? <><Cloud size={10} /> DRIVE</> : <><HardDrive size={10} /> LOCALE</>}
            </span>
          )}
        </div>
      </div>

      <div className={`viewer-toolbar-controls ${search.isSearchActive ? "viewer-toolbar-controls--search" : ""}`}>
        <div className="viewer-toolbar-group viewer-toolbar-group--page" data-testid="viewer-page-nav">
          <span className="viewer-toolbar-label">Pagina</span>
          <button
            type="button"
            onClick={page.goToPrevPage}
            disabled={!page.canGoPrev}
            className="viewer-page-step"
            aria-label="Pagina precedente"
            data-testid="viewer-page-prev"
          >
            ←
          </button>
          <input
            type="number"
            min={1}
            max={page.totalPages || 1}
            value={page.pageInput}
            onChange={(e) => page.setPageInput(e.target.value)}
            onBlur={page.commitPageInput}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                page.commitPageInput();
              }
            }}
            className="viewer-page-input"
            data-testid="viewer-page-input"
            aria-label="Numero pagina"
          />
          <button
            type="button"
            onClick={page.goToNextPage}
            disabled={!page.canGoNext}
            className="viewer-page-step"
            aria-label="Pagina successiva"
            data-testid="viewer-page-next"
          >
            →
          </button>
          <span className="viewer-toolbar-meta">
            di <span data-testid="viewer-page-total">{page.totalPages || "…"}</span>
          </span>
        </div>

        <div className="viewer-toolbar-divider" aria-hidden />

        {search.isSearchActive && (
          <div className="viewer-toolbar-group viewer-toolbar-group--search" data-testid="viewer-search-bar">
              <span className="viewer-toolbar-label">Cerca</span>
              <span className="viewer-search-query" title={search.query}>"{search.query}"</span>
              <div className="viewer-toolbar-actions viewer-search-hub" data-testid="viewer-search-hub">
                <button
                  type="button"
                  onClick={search.goToPrevMatch}
                  disabled={(!search.matches || search.matches.length === 0) && (!search.matchPages || search.matchPages.length === 0) || search.matchNavigationLoading}
                  className="viewer-search-hub-btn"
                  title="Risultato precedente"
                  data-testid="match-prev"
                >
                  <ChevronLeft size={18} />
                </button>
                <button
                  type="button"
                  onClick={search.goToNextMatch}
                  disabled={(!search.matches || search.matches.length === 0) && (!search.matchPages || search.matchPages.length === 0) || search.matchNavigationLoading}
                  className="viewer-search-hub-btn"
                  title="Risultato successivo"
                  data-testid="match-next"
                >
                  <ChevronRight size={18} />
                </button>
              </div>
              <div className="viewer-toolbar-actions viewer-search-actions">
                <button
                  type="button"
                  onClick={search.toggleHighlights}
                  className="viewer-tool-btn"
                  title={search.highlightsVisible ? "Nascondi evidenziazione" : "Mostra evidenziazione"}
                  data-testid="toggle-highlights"
                >
                  {search.highlightsVisible ? <Eye size={14} /> : <EyeOff size={14} />}
                </button>
                <button
                  type="button"
                  onClick={search.dismissSearchPanel}
                  className="viewer-tool-btn viewer-tool-btn--clear"
                  title="Nascondi evidenziazione"
                  data-testid="dismiss-search"
                >
                  ×
                </button>
              </div>
            </div>
        )}
      </div>
    </header>
  );
}
