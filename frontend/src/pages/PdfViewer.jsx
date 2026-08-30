import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { toast } from "sonner";
import api, { API, getAuthToken } from "@/lib/api";
import ViewerToolbar from "@/components/ViewerToolbar";
import { stripChords } from "@/lib/searchText";
import usePdfViewerState, {
  TOOLBAR_OFFSET,
  TOOLBAR_OFFSET_WITH_SEARCH,
} from "@/hooks/usePdfViewerState";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

// Suppress pdfjs non-critical warnings (TT fonts, annotation styles)
if (typeof window !== "undefined") {
  const originalWarn = console.warn.bind(console);
  const originalError = console.error.bind(console);
  const shouldFilter = (v) => {
    const s = String(v || "");
    return /TT:|AnnotationBorderStyle|undefined function/i.test(s);
  };

  console.warn = (msg, ...args) => {
    if (shouldFilter(msg) || args.some(shouldFilter)) return;
    originalWarn(msg, ...args);
  };

  console.error = (msg, ...args) => {
    if (shouldFilter(msg) || args.some(shouldFilter)) return;
    originalError(msg, ...args);
  };
}

const PAGE_GAP = 24;
const PAGE_FOOTER_H = 28;
const PAGE_ASPECT = 297 / 210;
const PAGE_BUFFER = 4;

const PDF_FULL_BLEED = {
  width: "100vw",
  maxWidth: "100vw",
  marginLeft: "calc(50% - 50vw)",
  boxSizing: "border-box",
};

const estimatePageHeight = (width, scale) =>
  Math.round(width * scale * PAGE_ASPECT + PAGE_FOOTER_H + PAGE_GAP);

async function measureSlotHeight(pdf, pageNumber, width, scale) {
  const page = await pdf.getPage(pageNumber);
  const vp = page.getViewport({ scale: 1 });
  return Math.round((vp.height / vp.width) * width * scale + PAGE_FOOTER_H + PAGE_GAP);
}

function isCanceled(error) {
  return error?.name === "CanceledError" || error?.name === "AbortError" || error?.code === "ERR_CANCELED";
}

function pageRangeAround(page, numPages, buffer = PAGE_BUFFER) {
  const p = Math.max(1, Math.min(page, numPages));
  return {
    start: Math.max(1, p - buffer),
    end: Math.min(numPages, p + buffer),
  };
}

function rangeFromScroll(scrollY, viewportHeight, slotHeight, numPages, toolbarOffset) {
  const top = scrollY + toolbarOffset;
  const bottom = top + viewportHeight;
  return {
    start: Math.max(1, Math.floor(top / slotHeight) - PAGE_BUFFER),
    end: Math.min(numPages, Math.ceil(bottom / slotHeight) + PAGE_BUFFER),
  };
}

export default function PdfViewer() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const shareToken = params.get("share") || params.get("share_token") || "";
  const rawPageParam = params.get("page");
  const pageParam = (rawPageParam && rawPageParam !== "undefined" && rawPageParam !== "null") ? rawPageParam : "";
  const _parsedPage = parseInt(pageParam, 10);
  const initialPage = Number.isFinite(_parsedPage) ? _parsedPage : 1;
  const initialQuery = params.get("q") || "";
  const navigate = useNavigate();

  const [meta, setMeta] = useState(null);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1);
  const [containerWidth, setContainerWidth] = useState(800);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);
  const [pageHeight, setPageHeight] = useState(null);
  const [visibleRange, setVisibleRange] = useState({ start: 1, end: 12 });

  const containerRef = useRef(null);
  const pageRefs = useRef({});
  const pdfDocRef = useRef(null);
  const pendingScrollPageRef = useRef(null);
  const mountedRef = useRef(false);
  const visibleRangeRef = useRef({ start: 1, end: 12 });
  const initialScrollDoneRef = useRef(false);
  const renderGenerationRef = useRef(0);
  const [renderGeneration, setRenderGeneration] = useState(0);
  const initialSearchScrollRef = useRef(false);
  const token = getAuthToken();
  const fileUrl = `${API}/pdfs/${id}/file${shareToken ? `?share_token=${encodeURIComponent(shareToken)}` : ""}`;
  const fileObj = useMemo(() => ({
    url: fileUrl,
    httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
  }), [fileUrl, token]);

  const slotHeight = pageHeight || estimatePageHeight(containerWidth, scale);
  const totalHeight = numPages > 0 ? numPages * slotHeight : 0;
  const mountedPageCount = numPages > 0 ? visibleRange.end - visibleRange.start + 1 : 0;

  const applyVisibleRange = useCallback((start, end) => {
    if (visibleRangeRef.current.start === start && visibleRangeRef.current.end === end) return;
    visibleRangeRef.current = { start, end };
    setVisibleRange({ start, end });
  }, []);

  const setRangeAround = useCallback(
    (page, buffer = PAGE_BUFFER + 2) => {
      if (numPages <= 0) return;
      const { start, end } = pageRangeAround(page, numPages, buffer);
      applyVisibleRange(start, end);
    },
    [numPages, applyVisibleRange],
  );

  const toolbarOffsetRef = useRef(
    initialQuery ? TOOLBAR_OFFSET_WITH_SEARCH : TOOLBAR_OFFSET,
  );
  const getToolbarOffset = useCallback(
    () => toolbarOffsetRef.current,
    [],
  );

  const getPageLabel = useCallback(
    (pageNumber) => {
      if (!meta?.page_labels || pageNumber < 1) return String(pageNumber);
      return meta.page_labels[pageNumber - 1] || String(pageNumber);
    },
    [meta?.page_labels],
  );

  const {
    page,
    search,
    scrollToPageRef,
    onPageRender,
    handleScroll,
    completeInitialJump,
    currentPageRef,
  } = usePdfViewerState({
    pdfId: id,
    initialPage,
    initialQuery,
    shareToken,
    numPages,
    slotHeight,
    getToolbarOffset,
    setRangeAround,
    containerRef,
    pageRefs,
    mountedRef,
    pendingScrollPageRef,
    initialScrollDoneRef,
  });

  toolbarOffsetRef.current = search.isSearchActive ? TOOLBAR_OFFSET_WITH_SEARCH : TOOLBAR_OFFSET;

  scrollToPageRef.current = page.scrollToPage;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimeout(search.collectTimerRef.current);
      pageRefs.current = {};
    };
  }, [search.collectTimerRef]);

  useEffect(() => {
    clearTimeout(search.collectTimerRef.current);
    initialScrollDoneRef.current = false;
    setMeta(null);
    setNumPages(0);
    setBusy(true);
    setError(null);
    setPageHeight(null);
    pageRefs.current = {};
    visibleRangeRef.current = { start: 1, end: 12 };
    setVisibleRange({ start: 1, end: 12 });
  }, [id, search.collectTimerRef]);

  useEffect(() => {
    const ctrl = new AbortController();
    api.get(`/pdfs/${id}`, { params: shareToken ? { share_token: shareToken } : undefined, signal: ctrl.signal })
      .then((r) => {
        if (mountedRef.current) setMeta(r.data);
      })
      .catch((e) => {
        if (!isCanceled(e) && mountedRef.current) setError(e.response?.data?.detail || "PDF non trovato");
      });
    return () => ctrl.abort();
  }, [id, shareToken]);

  /* eslint-disable react-hooks/exhaustive-deps */
  // This effect intentionally avoids page/currentPageRef in its dependency list to prevent
  // stale URL-driven jumps from interrupting an in-flight programmatic scroll.
  useEffect(() => {
    if (!meta?.page_labels?.length || numPages <= 0 || !pageParam) return;

    const normalizedLabel = pageParam.trim();
    const idx = meta.page_labels.findIndex((label) => {
      if (label == null) return false;
      const a = String(label).trim();
      if (a === normalizedLabel) return true;
      if (a.toLowerCase() === normalizedLabel.toLowerCase()) return true;
      const an = parseInt(a, 10);
      const bn = parseInt(normalizedLabel, 10);
      if (Number.isFinite(an) && Number.isFinite(bn) && an === bn) return true;
      return false;
    });

    const targetPage = idx >= 0 ? idx + 1 : null;
    if (!targetPage) return;
    if (targetPage === currentPageRef.current) return;
    if (pendingScrollPageRef.current != null) return;

    page.goToPage(targetPage);
  }, [meta?.page_labels, numPages, pageParam]);

  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    const update = () => {
      if (!containerRef.current) return;
      const nextWidth = Math.max(280, Math.min(containerRef.current.clientWidth - 32, 1000));
      setContainerWidth((prev) => (Math.abs(prev - nextWidth) > 4 ? nextWidth : prev));
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    renderGenerationRef.current += 1;
    setRenderGeneration(renderGenerationRef.current);
    if (numPages > 0) setRangeAround(currentPageRef.current);

    const pdf = pdfDocRef.current;
    if (!pdf || numPages <= 0) {
      setPageHeight(null);
      return undefined;
    }

    let cancelled = false;
    (async () => {
      const h = await measureSlotHeight(pdf, 1, containerWidth, scale);
      if (cancelled || !mountedRef.current || h <= 0) return;
      setPageHeight(h);
      const target = pendingScrollPageRef.current || currentPageRef.current;
      if (target > 1) scrollToPageRef.current?.(target, "auto");
    })();

    return () => { cancelled = true; };
  }, [id, scale, containerWidth, numPages, setRangeAround, currentPageRef, scrollToPageRef]);

  const onDocumentLoad = useCallback(
    async (pdf) => {
      if (!mountedRef.current) return;
      pdfDocRef.current = pdf;
      const loadedPages = pdf.numPages;
      const target = Math.max(1, Math.min(initialPage, loadedPages));
      const measureAt = target > 1 ? target : 1;

      try {
        const h = await measureSlotHeight(pdf, measureAt, containerWidth, scale);
        if (mountedRef.current && h > 0) setPageHeight(h);
      } catch (err) {
        console.error("[PdfViewer] Failed to measure page height:", err);
      }

      const { start, end } = pageRangeAround(target, loadedPages, PAGE_BUFFER + 3);
      visibleRangeRef.current = { start, end };
      setVisibleRange({ start, end });
      page.setPageState(target, { source: "document", skipNotify: true });
      setNumPages(loadedPages);
      setBusy(false);
    },
    [initialPage, containerWidth, scale, page],
  );

  const handlePageRenderSuccess = useCallback(
    (pageNumber) => {
      if (!mountedRef.current) return;
      const el = pageRefs.current[pageNumber];
      if (el?.offsetHeight > 0) {
        const measured = el.offsetHeight;
        setPageHeight((prev) => (prev && Math.abs(prev - measured) < 4 ? prev : measured));
      }
      // Post-process the PDF text layer to strip chord tokens which disrupt reading
      try {
        const root = pageRefs.current[pageNumber];
        const textLayer = root?.querySelector(".react-pdf__Page__textContent") || root?.querySelector(".textLayer");
        if (textLayer) {
          const walker = document.createTreeWalker(textLayer, NodeFilter.SHOW_TEXT, null, false);
          const textNodes = [];
          let n;
          // collect nodes first to avoid modifying walker iteration
          while ((n = walker.nextNode())) textNodes.push(n);
          for (const node of textNodes) {
            const original = node.nodeValue;
            if (!original || !original.trim()) continue;
            const cleaned = stripChords(original);
            if (cleaned !== original) node.nodeValue = cleaned;
          }
        }
      } catch (err) {
        console.error("[PdfViewer] stripChords post-process failed:", err);
      }
      onPageRender(pageNumber, renderGeneration, renderGenerationRef);
    },
    [onPageRender, renderGeneration],
  );

  useEffect(() => {
    if (numPages > 0 && pageHeight && initialPage > 1 && !initialScrollDoneRef.current) {
      page.scrollToPage(initialPage, "auto");
      return;
    }
    if (numPages > 0 && pageHeight && !initialScrollDoneRef.current && initialPage <= 1) {
      completeInitialJump();
    }
    return undefined;
  }, [numPages, pageHeight, initialPage, page, completeInitialJump]);

  useEffect(() => {
    if (!search.hasSearchQuery || numPages === 0) return undefined;
    const t = setTimeout(search.collectMatches, 250);
    return () => clearTimeout(t);
  }, [search.hasSearchQuery, numPages, visibleRange, search.collectMatches]);

  useEffect(() => {
    if (!search.hasSearchQuery || numPages === 0 || !pageHeight || initialSearchScrollRef.current) return undefined;
    if (!mountedRef.current) return undefined;

    let cancelled = false;
    const maxAttempts = 120; // ~2 seconds at 60fps
    const explicitPageRequested = Boolean(pageParam && pageParam.trim());
    const explicitPage = explicitPageRequested ? currentPageRef.current : null;

    // If server provided full-file match pages, jump to first match page immediately only when
    // the user did not land on a specific page from a search result.
    if (search.matchPages && search.matchPages.length > 0 && !explicitPageRequested) {
      const target = search.matchPages[0];
      let attempts = 0;
      if (target !== currentPageRef.current) {
        page.scrollToPage(target, "auto");
      }
      const tryScrollOnTarget = () => {
        if (cancelled) return;
        attempts += 1;
        const el = pageRefs.current[target];
        if (el) {
          const match = el.querySelector("mark.hl");
          if (match) {
            initialSearchScrollRef.current = true;
            return;
          }
        }
        if (attempts < maxAttempts) requestAnimationFrame(tryScrollOnTarget);
      };
      tryScrollOnTarget();
      return () => { cancelled = true; };
    }

    // Fallback: if a page was explicitly requested, only scroll within that page.
    let attempts = 0;
    const tryFind = () => {
      if (cancelled) return;
      attempts += 1;
      for (let p = 1; p <= numPages; p += 1) {
        if (explicitPage != null && p !== explicitPage) continue;
        const el = pageRefs.current[p];
        if (!el) continue;
        const match = el.querySelector("mark.hl");
        if (match) {
          if (p !== currentPageRef.current) page.scrollToPage(p, "auto");
          initialSearchScrollRef.current = true;
          return;
        }
      }
      if (attempts < maxAttempts) requestAnimationFrame(tryFind);
    };

    tryFind();
    return () => { cancelled = true; };
  }, [search.matches, search.matchPages, search.hasSearchQuery, pageParam, numPages, pageHeight, currentPageRef, page]);

  useEffect(() => {
    if (numPages <= 0) return undefined;
    const toolbarOffset = search.isSearchActive ? TOOLBAR_OFFSET_WITH_SEARCH : TOOLBAR_OFFSET;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const scrollY = window.scrollY;
        const { start, end } = rangeFromScroll(scrollY, window.innerHeight, slotHeight, numPages, toolbarOffset);
        applyVisibleRange(start, end);
        handleScroll(scrollY);
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
    };
  }, [numPages, slotHeight, search.isSearchActive, applyVisibleRange, handleScroll]);

  const toggleFavorite = async () => {
    if (!meta) return;
    try {
      const r = await api.patch(`/pdfs/${id}`, { is_favorite: !meta.is_favorite });
      if (!mountedRef.current) return;
      setMeta(r.data);
      toast.success(r.data.is_favorite ? "Aggiunto ai preferiti" : "Rimosso dai preferiti");
    } catch (err) {
      if (isCanceled(err)) return;
      console.error("[PdfViewer] Failed to toggle favorite:", { pdf_id: id, error: err.message });
      toast.error("Errore nel salvataggio del preferito");
    }
  };


  const visiblePageNumbers = useMemo(() => {
    if (numPages <= 0) return [];
    return Array.from(
      { length: visibleRange.end - visibleRange.start + 1 },
      (_, index) => visibleRange.start + index,
    );
  }, [numPages, visibleRange.start, visibleRange.end]);

  const reloadFile = async () => {
    setBusy(true);
    try {
      await api.post(`/pdfs/${id}/reload`);
      toast.success("File ricaricato da Drive. Riprovo ad aprire...");
      window.location.reload();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Errore nel ricaricamento");
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-12 text-center" data-testid="pdf-viewer-error">
        <p className="text-lg font-display mb-3">{error}</p>
        <div className="flex gap-3">
          <button type="button" onClick={() => navigate(-1)} className="btn-ghost border border-rule rounded-sm px-4 py-2">Indietro</button>
          <button type="button" onClick={reloadFile} disabled={busy} className="btn-primary">
            {busy ? "Ricaricamento..." : "Ricarica File da Drive"}
          </button>
        </div>
        <p className="mt-4 text-sm text-muted2 max-w-md mx-auto">
          Se il file è stato perso localmente, puoi forzare il recupero dal backup Google Drive del sistema.
        </p>
      </div>
    );
  }

  // Block viewer when PDF is still being processed
  const pdfStatus = meta?.status || meta?.processing_status;
  const isProcessing = pdfStatus && pdfStatus !== "ready" && pdfStatus !== "failed" && pdfStatus !== "error";
  if (isProcessing) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-12 text-center" data-testid="pdf-viewer-processing">
        <div className="mb-4">
          <div className="inline-block w-12 h-12 border-4 border-canvas3 border-t-ink rounded-full animate-spin" />
        </div>
        <h3 className="font-display text-xl font-bold mb-2">PDF in elaborazione</h3>
        <p className="text-muted2 mb-6">
          Il file è stato ricevuto e verrà indicizzato a breve.<br />
          Puoi navigare, cercare e caricare altri PDF mentre l'elaborazione continua in background.
        </p>
        <div className="flex gap-3">
          <button type="button" onClick={() => navigate("/library")} className="btn-primary">Vai alla libreria</button>
          <button type="button" onClick={() => window.location.reload()} className="btn-ghost border border-rule rounded-sm px-4 py-2">Riprova</button>
        </div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen flex flex-col bg-canvas3 ${search.highlightsHidden ? "hl-off" : ""}`} data-testid="pdf-viewer-page">
      <ViewerToolbar
        meta={meta}
        onBack={() => navigate(-1)}
        onToggleFavorite={toggleFavorite}
        page={page}
        search={search}
      />

      <div ref={containerRef} className="flex-1 flex flex-col items-center py-8 overflow-x-visible">
        {busy && <div className="text-mono text-sm text-muted2 py-12" data-testid="pdf-loading">Caricamento PDF…</div>}
        <Document
          key={id}
          file={fileObj}
          onLoadSuccess={onDocumentLoad}
          onLoadError={(e) => {
            if (!mountedRef.current) return;
            setError("Impossibile caricare il PDF");
            setBusy(false);
            console.error(e);
          }}
          loading=""
          error=""
          className="w-full flex flex-col items-center"
        >
          {numPages > 0 && (
            <div
              className="relative w-full max-w-full overflow-visible"
              style={{ height: totalHeight }}
              data-testid="pdf-virtual-scroll"
              data-mounted-pages={mountedPageCount}
              data-total-pages={numPages}
            >
              {visiblePageNumbers.map((pageNumber) => (
                <div
                  key={`${id}-${pageNumber}-${renderGeneration}`}
                  ref={(el) => {
                    if (el) pageRefs.current[pageNumber] = el;
                    else delete pageRefs.current[pageNumber];
                  }}
                  className="absolute left-0 right-0 mx-auto bg-card shadow-md border border-rule overflow-visible"
                  style={{
                    top: (pageNumber - 1) * slotHeight,
                    width: containerWidth,
                    maxWidth: "100%",
                  }}
                  data-testid={`pdf-page-${pageNumber}`}
                  data-pdf-page={pageNumber}
                >
                  <Page
                    pageNumber={pageNumber}
                    width={containerWidth}
                    renderTextLayer
                    renderAnnotationLayer={false}
                    customTextRenderer={search.customTextRenderer}
                    onRenderSuccess={() => handlePageRenderSuccess(pageNumber)}
                    onRenderError={(e) => console.error("[PdfViewer] Page render failed:", { pdf_id: id, pageNumber, error: e.message })}
                    loading=""
                  />
                  <div
                    style={{
                      ...PDF_FULL_BLEED,
                      background: "var(--canvas3)",
                      borderTop: "1px solid var(--rule)",
                      minHeight: PAGE_FOOTER_H,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: "0.375rem 0",
                    }}
                    aria-hidden="true"
                  >
                    <span className="text-mono text-xs text-muted3">PAG {getPageLabel(pageNumber)}</span>
                  </div>
                  {pageNumber < numPages && (
                    <div
                      style={{
                        ...PDF_FULL_BLEED,
                        height: PAGE_GAP,
                        background: "var(--canvas2)",
                      }}
                      aria-hidden="true"
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </Document>
      </div>
    </div>
  );
}
