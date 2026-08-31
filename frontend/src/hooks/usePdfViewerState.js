import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { useNavigate } from "react-router-dom";
import { buildMatchPagesFromResults, dedupePageNumbers } from "./viewerSearchUtils";

export const TOOLBAR_OFFSET = 108;
export const TOOLBAR_OFFSET_WITH_SEARCH = 148;

const SCROLL_SYNC_DEBOUNCE_MS = 80;
const URL_SYNC_DEBOUNCE_MS = 350;

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeApostrophes(value) {
  return value.replace(/[’‘]/g, "'");
}

export function detectVisiblePage(scrollY, getToolbarOffset, pageRefs, numPages, slotHeight) {
  if (numPages <= 0) return 1;
  const viewTop = scrollY + getToolbarOffset();
  const viewCenter = viewTop + window.innerHeight * 0.35;
  let bestFromDom = null;
  let anyMounted = false;

  for (let p = 1; p <= numPages; p += 1) {
    const el = pageRefs.current[p];
    if (!el) continue;
    anyMounted = true;
    const top = el.offsetTop;
    const bottom = top + el.offsetHeight;
    if (viewCenter >= top && viewCenter < bottom) return p;
    if (top <= viewCenter) bestFromDom = p;
  }

  if (anyMounted && bestFromDom != null) return bestFromDom;
  return Math.min(numPages, Math.max(1, Math.floor(viewTop / slotHeight) + 1));
}

function findFirstMatchIndexOnPage(matches, pageNum) {
  for (let i = 0; i < matches.length; i += 1) {
    const wrapper = matches[i].closest("[data-pdf-page]");
    if (wrapper && parseInt(wrapper.getAttribute("data-pdf-page"), 10) === pageNum) return i;
  }
  return -1;
}

function countMatchesOnPage(matches, pageNum) {
  let n = 0;
  for (let i = 0; i < matches.length; i += 1) {
    const wrapper = matches[i].closest("[data-pdf-page]");
    if (wrapper && parseInt(wrapper.getAttribute("data-pdf-page"), 10) === pageNum) n += 1;
  }
  return n;
}

function usePageController({
  numPages,
  slotHeight,
  getToolbarOffset,
  setRangeAround,
  pageRefs,
  mountedRef,
  pendingScrollPageRef,
  programmaticScrollRef,
  initialScrollDoneRef,
  completeInitialJumpRef,
  currentPageRef,
  onPageChange,
}) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");

  const setPageState = useCallback(
    (page, options = {}) => {
      const p = Math.max(1, Math.min(page, numPages || page || 1));
      currentPageRef.current = p;
      setCurrentPage(p);
      setPageInput(String(p));
      if (!options.skipNotify) onPageChange(p, options.source || "programmatic");
      return p;
    },
    [numPages, currentPageRef, onPageChange],
  );

  const scrollToPage = useCallback(
    (page, behavior = "auto") => {
      const p = Math.max(1, Math.min(page, numPages || page));
      programmaticScrollRef.current = true;
      pendingScrollPageRef.current = p;
      setRangeAround(p);
      setPageState(p, { source: "programmatic", skipNotify: false });

      const finish = () => {
        programmaticScrollRef.current = false;
        pendingScrollPageRef.current = null;
        if (!initialScrollDoneRef.current) {
          completeInitialJumpRef.current?.();
        }
      };

      const tryScroll = (attempts = 0) => {
        if (!mountedRef.current) return;
        const el = pageRefs.current[p];
        if (el) {
          const top = el.getBoundingClientRect().top + window.scrollY - getToolbarOffset();
          window.scrollTo({ top: Math.max(0, top), behavior });
          finish();
          return;
        }
        if (attempts < 80) {
          requestAnimationFrame(() => tryScroll(attempts + 1));
          return;
        }
        window.scrollTo({ top: Math.max(0, (p - 1) * slotHeight), behavior });
        finish();
      };

      requestAnimationFrame(() => tryScroll());
    },
    [
      numPages,
      setRangeAround,
      slotHeight,
      getToolbarOffset,
      pageRefs,
      mountedRef,
      pendingScrollPageRef,
      programmaticScrollRef,
      initialScrollDoneRef,
      completeInitialJumpRef,
      setPageState,
    ],
  );

  const goToPage = useCallback(
    (pageNumber) => {
      scrollToPage(Math.max(1, Math.min(pageNumber, numPages || 1)), "smooth");
    },
    [numPages, scrollToPage],
  );

  const commitPageInput = useCallback(() => {
    const parsed = parseInt(pageInput, 10);
    if (!Number.isFinite(parsed)) {
      setPageInput(String(currentPage));
      return;
    }
    goToPage(parsed);
  }, [pageInput, currentPage, goToPage]);

  const applyPageFromScroll = useCallback(
    (scrollY) => {
      if (numPages <= 0 || programmaticScrollRef.current) return;
      if (initialScrollDoneRef && !initialScrollDoneRef.current) return;
      const detected = detectVisiblePage(scrollY, getToolbarOffset, pageRefs, numPages, slotHeight);
      if (detected !== currentPageRef.current) {
        setPageState(detected, { source: "scroll" });
      }
    },
    [numPages, getToolbarOffset, pageRefs, slotHeight, currentPageRef, programmaticScrollRef, initialScrollDoneRef, setPageState],
  );

  return {
    currentPage,
    totalPages: numPages,
    pageInput,
    setPageInput,
    setPageState,
    goToPage,
    goToPrevPage: () => goToPage(currentPage - 1),
    goToNextPage: () => goToPage(currentPage + 1),
    commitPageInput,
    applyPageFromScroll,
    scrollToPage,
    canGoPrev: currentPage > 1,
    canGoNext: currentPage < (numPages || 1),
  };
}

function useSearchController({
  pdfId,
  initialQuery,
  shareToken,
  containerRef,
  mountedRef,
  searchDriverDoneRef,
  getCurrentPage,
  goToPage,
  numPages,
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState(initialQuery);
  const [searchPanelVisible, setSearchPanelVisible] = useState(Boolean(initialQuery));
  const [highlightsVisible, setHighlightsVisible] = useState(true);
  const [matches, setMatches] = useState([]);
  const [matchPages, setMatchPages] = useState([]); // full-file pages that contain matches
  const [matchNavigationLoading, setMatchNavigationLoading] = useState(false);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);

  const collectTimerRef = useRef(null);
  const collectRetryRef = useRef(0);
  const matchesRef = useRef([]);
  const currentMatchIndexRef = useRef(0);
  const searchNavigationRef = useRef(false);
  const searchNavigationTimerRef = useRef(null);
  const pendingSearchDirectionRef = useRef(0);

  const hasSearchQuery = query.length > 0;
  const isSearchActive = hasSearchQuery && searchPanelVisible;

  useEffect(() => {
    matchesRef.current = matches;
  }, [matches]);

  useEffect(() => {
    const hasInitialQuery = Boolean(initialQuery && initialQuery.trim());
    setQuery(initialQuery);
    setSearchPanelVisible(hasInitialQuery);
    setHighlightsVisible(hasInitialQuery);
    setMatches([]);
    matchesRef.current = [];
    setCurrentMatchIndex(0);
    currentMatchIndexRef.current = 0;
    searchNavigationRef.current = false;
    collectRetryRef.current = 0;
    if (searchNavigationTimerRef.current != null) {
      window.clearTimeout(searchNavigationTimerRef.current);
      searchNavigationTimerRef.current = null;
    }
    searchDriverDoneRef.current = false;
  }, [pdfId, initialQuery, searchDriverDoneRef]);

  // Fetch full-file match pages for the current PDF when query changes
  useEffect(() => {
    let cancelled = false;
    const q = query && query.trim();
    if (!q) {
      setMatchPages([]);
      setMatchNavigationLoading(false);
      return undefined;
    }
    setMatchNavigationLoading(true);
    const ctrl = new AbortController();
    api.get(`/search`, { params: { q, share_token: shareToken || undefined }, signal: ctrl.signal })
      .then((r) => {
        if (cancelled) return;
        const items = (r.data && r.data.results) || [];
        const pages = buildMatchPagesFromResults(items, pdfId);
        setMatchPages(pages);
      })
      .catch(() => {
        if (!cancelled) setMatchPages([]);
      })
      .finally(() => { if (!cancelled) setMatchNavigationLoading(false); });
    return () => { cancelled = true; ctrl.abort(); };
  }, [query, pdfId, shareToken]);

  const setSearchNavigationLock = useCallback((locked) => {
    if (searchNavigationTimerRef.current != null) {
      window.clearTimeout(searchNavigationTimerRef.current);
      searchNavigationTimerRef.current = null;
    }
    searchNavigationRef.current = locked;
    if (locked) {
      searchNavigationTimerRef.current = window.setTimeout(() => {
        searchNavigationRef.current = false;
        searchNavigationTimerRef.current = null;
      }, 300);
    }
  }, []);

  const syncMatchIndexToPage = useCallback(
    (pageNum, list = matchesRef.current) => {
      if (searchNavigationRef.current) return;
      if (!list.length) {
        setCurrentMatchIndex(0);
        currentMatchIndexRef.current = 0;
        return;
      }
      const idx = findFirstMatchIndexOnPage(list, pageNum);
      const selected = idx >= 0 ? idx : 0;
      setCurrentMatchIndex(selected);
      currentMatchIndexRef.current = selected;
      list.forEach((node, i) => node.classList.toggle("hl-active", i === selected));
    },
    [],
  );

  const scrollToMatch = useCallback((list, idx, behavior = "smooth") => {
    const node = list[idx];
    if (!node || !mountedRef.current) return;
    setSearchNavigationLock(true);
    list.forEach((item) => item.classList.remove("hl-active"));
    node.classList.add("hl-active");
    setCurrentMatchIndex(idx);
    currentMatchIndexRef.current = idx;
    node.scrollIntoView({ behavior, block: "center" });
  }, [mountedRef, setSearchNavigationLock]);

  const getMatchPage = useCallback((node) => {
    const wrapper = node?.closest("[data-pdf-page]");
    if (!wrapper) return null;
    return parseInt(wrapper.getAttribute("data-pdf-page"), 10);
  }, []);

  const getMatchPageGroups = useCallback((list = matchesRef.current) => {
    const pages = [];
    const seen = new Set();
    for (const node of list) {
      const page = getMatchPage(node);
      if (page != null && !seen.has(page)) {
        seen.add(page);
        pages.push(page);
      }
    }
    return pages;
  }, [getMatchPage]);

  const findLastMatchIndexOnPage = useCallback((pageNum, list = matchesRef.current) => {
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const wrapper = list[i].closest("[data-pdf-page]");
      if (wrapper && parseInt(wrapper.getAttribute("data-pdf-page"), 10) === pageNum) return i;
    }
    return -1;
  }, []);

  const resolvePendingSearch = useCallback(() => {
    const direction = pendingSearchDirectionRef.current;
    if (!direction) return false;

    const currentPage = getCurrentPage();
    const list = matchesRef.current;
    const pageMatchIndex = direction === 1
      ? findFirstMatchIndexOnPage(list, currentPage)
      : findLastMatchIndexOnPage(currentPage, list);

    if (pageMatchIndex >= 0) {
      scrollToMatch(list, pageMatchIndex, "smooth");
      pendingSearchDirectionRef.current = 0;
      return true;
    }

    const pageGroups = getMatchPageGroups(list);
    if (pageGroups.length) {
      const currentGroupIndex = pageGroups.indexOf(currentPage);
      let targetGroupIndex = currentGroupIndex >= 0
        ? currentGroupIndex + (direction === 1 ? 1 : -1)
        : direction === 1 ? 0 : pageGroups.length - 1;

      if (targetGroupIndex < 0) targetGroupIndex = pageGroups.length - 1;
      if (targetGroupIndex >= pageGroups.length) targetGroupIndex = 0;
      goToPage(pageGroups[targetGroupIndex]);
      return false;
    }

    pendingSearchDirectionRef.current = 0;
    if (!list.length) return false;
    const wrapIndex = direction === 1 ? 0 : list.length - 1;
    scrollToMatch(list, wrapIndex, "smooth");
    return true;
  }, [findLastMatchIndexOnPage, getCurrentPage, getMatchPageGroups, goToPage, scrollToMatch]);

  const collectMatches = useCallback(() => {
    if (!mountedRef.current || !containerRef.current || !hasSearchQuery) return;
    const list = Array.from(containerRef.current.querySelectorAll("mark.hl"));
    matchesRef.current = list;
    setMatches(list);

    if (list.length === 0 && collectRetryRef.current < 8) {
      collectRetryRef.current += 1;
      clearTimeout(collectTimerRef.current);
      collectTimerRef.current = window.setTimeout(collectMatches, 180);
      return;
    }

    collectRetryRef.current = 0;

    if (pendingSearchDirectionRef.current !== 0) {
      resolvePendingSearch();
      return;
    }

    // Preserve current match index if still valid (e.g., during cross-page navigation)
    const currentIdx = currentMatchIndexRef.current;
    if (currentIdx >= 0 && currentIdx < list.length) {
      list.forEach((node, i) => node.classList.toggle("hl-active", i === currentIdx));
      return;
    }

    syncMatchIndexToPage(getCurrentPage(), list);
  }, [hasSearchQuery, containerRef, mountedRef, resolvePendingSearch, syncMatchIndexToPage, getCurrentPage]);

  const scheduleCollect = useCallback(() => {
    if (!hasSearchQuery) return;
    clearTimeout(collectTimerRef.current);
    collectTimerRef.current = setTimeout(collectMatches, 120);
  }, [hasSearchQuery, collectMatches]);

  const onPageChanged = useCallback(
    (pageNum) => {
      if (!hasSearchQuery) return;
      const hasPageMatches = findFirstMatchIndexOnPage(matchesRef.current, pageNum) >= 0;
      if (hasPageMatches) {
        syncMatchIndexToPage(pageNum);
      } else {
        scheduleCollect();
      }
    },
    [hasSearchQuery, syncMatchIndexToPage, scheduleCollect],
  );

  const goToPrevMatch = useCallback(() => {
    // Prefer server-provided full-file match pages if available
    if (matchPages && matchPages.length > 0) {
      const currentPage = getCurrentPage();
      // find last page strictly less than currentPage
      let idx = -1;
      for (let i = 0; i < matchPages.length; i += 1) {
        if (matchPages[i] < currentPage) idx = i;
      }
      if (idx < 0) {
        if (matchPages.length === 0) return;
        idx = matchPages.length - 1;
      }
      const targetPage = matchPages[idx];
      if (targetPage === currentPage) return;
      pendingSearchDirectionRef.current = -1;
      currentMatchIndexRef.current = -1;
      goToPage(targetPage);
      return;
    }

    const list = matchesRef.current;
    if (list.length === 0) return;
    const pageGroups = getMatchPageGroups(list);
    if (!pageGroups.length) return;

    const currentPage = getCurrentPage();
    const currentGroupIndex = pageGroups.indexOf(currentPage);

    // If current page is part of groups, go to previous group if any
    if (currentGroupIndex >= 0) {
      const targetGroupIndex = currentGroupIndex - 1;
      if (targetGroupIndex < 0) return; // no previous group — do nothing
      pendingSearchDirectionRef.current = -1;
      currentMatchIndexRef.current = -1;
      goToPage(pageGroups[targetGroupIndex]);
      return;
    }

    // If current page not in groups, find the last group strictly less than currentPage
    let idx2 = -1;
    for (let i = 0; i < pageGroups.length; i += 1) {
      if (pageGroups[i] < currentPage) idx2 = i;
    }
    if (idx2 < 0) {
      if (pageGroups.length === 0) return;
      idx2 = pageGroups.length - 1;
    }
    pendingSearchDirectionRef.current = -1;
    currentMatchIndexRef.current = -1;
    goToPage(pageGroups[idx2]);
  }, [matchPages, getMatchPageGroups, getCurrentPage, goToPage]);

  const goToNextMatch = useCallback(() => {
    // Prefer server-provided full-file match pages if available
    if (matchPages && matchPages.length > 0) {
      const currentPage = getCurrentPage();
      // find first page strictly greater than currentPage
      let idx = -1;
      for (let i = 0; i < matchPages.length; i += 1) {
        if (matchPages[i] > currentPage) { idx = i; break; }
      }
      if (idx < 0) {
        if (matchPages.length === 0) return;
        idx = 0;
      }
      const targetPage = matchPages[idx];
      if (targetPage === currentPage) return;
      pendingSearchDirectionRef.current = 1;
      currentMatchIndexRef.current = -1;
      goToPage(targetPage);
      return;
    }

    const list = matchesRef.current;
    if (list.length === 0) return;
    const pageGroups = getMatchPageGroups(list);
    if (!pageGroups.length) return;

    const currentPage = getCurrentPage();
    const currentGroupIndex = pageGroups.indexOf(currentPage);

    // If current page is part of groups, go to next group if any
    if (currentGroupIndex >= 0) {
      const targetGroupIndex = currentGroupIndex + 1;
      if (targetGroupIndex >= pageGroups.length) return; // no next group
      pendingSearchDirectionRef.current = 1;
      currentMatchIndexRef.current = -1;
      goToPage(pageGroups[targetGroupIndex]);
      return;
    }

    // If current page not in groups, find the first group strictly greater than currentPage
    let idx2 = -1;
    for (let i = 0; i < pageGroups.length; i += 1) {
      if (pageGroups[i] > currentPage) { idx2 = i; break; }
    }
    if (idx2 < 0) {
      if (pageGroups.length === 0) return;
      idx2 = 0;
    }
    pendingSearchDirectionRef.current = 1;
    currentMatchIndexRef.current = -1;
    goToPage(pageGroups[idx2]);
  }, [matchPages, getMatchPageGroups, getCurrentPage, goToPage]);

  const toggleHighlights = useCallback(() => {
    setHighlightsVisible((v) => !v);
  }, []);

  const dismissSearchPanel = useCallback(() => {
    setSearchPanelVisible(false);
    setHighlightsVisible(false);
  }, []);

  const clearSearch = useCallback(() => {
    setQuery("");
    setSearchPanelVisible(true);
    setMatches([]);
    matchesRef.current = [];
    setCurrentMatchIndex(0);
    currentMatchIndexRef.current = 0;
    setHighlightsVisible(true);
    searchNavigationRef.current = false;
    if (searchNavigationTimerRef.current != null) {
      window.clearTimeout(searchNavigationTimerRef.current);
      searchNavigationTimerRef.current = null;
    }
    const sharePart = shareToken ? `&share=${encodeURIComponent(shareToken)}` : "";
    navigate(`/viewer/${pdfId}?page=${getCurrentPage()}${sharePart}`, { replace: true });
  }, [pdfId, getCurrentPage, navigate, shareToken]);

  const handleSearchEscape = useCallback(() => {
    if (!hasSearchQuery) return false;
    if (searchPanelVisible && highlightsVisible) {
      setHighlightsVisible(false);
      return true;
    }
    if (searchPanelVisible) {
      dismissSearchPanel();
      return true;
    }
    clearSearch();
    return true;
  }, [hasSearchQuery, searchPanelVisible, highlightsVisible, dismissSearchPanel, clearSearch]);

  const customTextRenderer = useCallback(
    ({ str }) => {
      if (!hasSearchQuery || !str) return str;
      try {
        const normalizedQuery = normalizeApostrophes(query);
        const queryPattern = escapeRegExp(normalizedQuery).replace(/'/g, "['’]");
        const re = new RegExp(`(${queryPattern})`, "ig");
        return str.replace(re, (m) => `<mark class="hl">${m}</mark>`);
      } catch (err) {
        console.error("[PdfViewer] Regex highlight failed:", { query, error: err.message });
        return str;
      }
    },
    [hasSearchQuery, query],
  );

  const pageNum = getCurrentPage();
  const pageGroups = getMatchPageGroups(matches);
  const currentActivePageIndex = pageGroups.indexOf(pageNum);
  const activeLabelIndex = currentActivePageIndex >= 0
    ? currentActivePageIndex
    : matches.length > 0
      ? pageGroups.findIndex((page) => findFirstMatchIndexOnPage(matches, page) === currentMatchIndex)
      : -1;
  const matchLabel = !pageGroups.length
    ? "Nessun risultato"
    : `${Math.max(1, activeLabelIndex + 1)} / ${pageGroups.length} · pag ${pageNum}`;

  return {
    query,
    hasSearchQuery,
    isSearchActive,
    searchPanelVisible,
    matches,
    currentMatchIndex,
    highlightsVisible,
    highlightsHidden: !highlightsVisible,
    matchLabel,
    goToPrevMatch,
    goToNextMatch,
    toggleHighlights,
    dismissSearchPanel,
    clearSearch,
    handleSearchEscape,
    customTextRenderer,
    scheduleCollect,
    collectMatches,
    onPageChanged,
    collectTimerRef,
    matchPages,
    matchNavigationLoading,
  };
}

export function usePdfViewerState({
  pdfId,
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
}) {
  const navigate = useNavigate();
  const programmaticScrollRef = useRef(false);
  const searchDriverDoneRef = useRef(false);
  const initialJumpPendingRef = useRef(initialPage > 1);
  const currentPageRef = useRef(initialPage);
  const completeInitialJumpRef = useRef(null);
  const urlSyncTimerRef = useRef(null);
  const scrollSyncTimerRef = useRef(null);
  const activeQueryRef = useRef(initialQuery);

  const getCurrentPage = useCallback(() => currentPageRef.current, []);

  const syncUrl = useCallback(
    (page, q) => {
      clearTimeout(urlSyncTimerRef.current);
      urlSyncTimerRef.current = setTimeout(() => {
        const queryPart = q ? `&q=${encodeURIComponent(q)}` : "";
        const sharePart = shareToken ? `&share=${encodeURIComponent(shareToken)}` : "";
        navigate(`/viewer/${pdfId}?page=${page}${queryPart}${sharePart}`, { replace: true });
      }, URL_SYNC_DEBOUNCE_MS);
    },
    [pdfId, navigate, shareToken],
  );

  const onPageChange = useCallback(
    (realPage, source = "scroll") => {
      const p = Math.max(1, Math.min(realPage, numPages || realPage || 1));
      onPageChangedRef.current?.(p);

      if (source !== "url" && (source === "programmatic" || initialScrollDoneRef.current)) {
        syncUrl(p, activeQueryRef.current);
      }
    },
    [numPages, syncUrl, initialScrollDoneRef],
  );

  const onPageChangedRef = useRef(null);

  const page = usePageController({
    numPages,
    slotHeight,
    getToolbarOffset,
    setRangeAround,
    pageRefs,
    mountedRef,
    pendingScrollPageRef,
    programmaticScrollRef,
    initialScrollDoneRef,
    completeInitialJumpRef,
    currentPageRef,
    onPageChange,
  });

  const search = useSearchController({
    pdfId,
    initialQuery,
    shareToken,
    containerRef,
    mountedRef,
    searchDriverDoneRef,
    getCurrentPage,
    // Use immediate scroll (auto) for search navigation to avoid smooth/jerky animations
    goToPage: page.scrollToPage,
    numPages,
  });

  activeQueryRef.current = search.searchPanelVisible ? search.query : "";
  onPageChangedRef.current = search.onPageChanged;

  useEffect(() => {
    const p = Math.max(1, Math.min(initialPage, numPages || initialPage || 1));
    const externalPageChange = p !== currentPageRef.current;
    currentPageRef.current = p;
    initialJumpPendingRef.current = initialPage > 1;
    if (numPages > 0 && externalPageChange) {
      initialScrollDoneRef.current = false;
      searchDriverDoneRef.current = false;
    }
    page.setPageState(p, { source: "document", skipNotify: true });
    return () => {
      clearTimeout(scrollSyncTimerRef.current);
      clearTimeout(urlSyncTimerRef.current);
    };
  }, [pdfId, initialPage, numPages]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      clearTimeout(scrollSyncTimerRef.current);
      clearTimeout(urlSyncTimerRef.current);
    };
  }, []);

  const scrollToPageRef = useRef(null);
  scrollToPageRef.current = page.scrollToPage;

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        if (search.handleSearchEscape()) e.preventDefault();
        return;
      }
      if (document.activeElement?.tagName === "INPUT") return;
      if (!search.isSearchActive) return;
      if (e.key === "n") {
        e.preventDefault();
        search.goToNextMatch();
      } else if (e.key === "N") {
        e.preventDefault();
        search.goToPrevMatch();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [search]);

  const onPageRender = useCallback(
    (pageNumber, generation, renderGenerationRef) => {
      if (!mountedRef.current || generation !== renderGenerationRef.current) return;
      if (pendingScrollPageRef.current === pageNumber) {
        scrollToPageRef.current?.(pageNumber, "auto");
      }
      if (
        initialJumpPendingRef.current
        && !initialScrollDoneRef.current
        && pageNumber === currentPageRef.current
      ) {
        initialJumpPendingRef.current = false;
        initialScrollDoneRef.current = true;
        searchDriverDoneRef.current = true;
        if (search.hasSearchQuery) {
          window.setTimeout(() => search.collectMatches(), 0);
          window.setTimeout(() => search.collectMatches(), 250);
        }
      }
      search.scheduleCollect();
    },
    [mountedRef, pendingScrollPageRef, initialScrollDoneRef, searchDriverDoneRef, search],
  );

  const handleScroll = useCallback(
    (scrollY) => {
      clearTimeout(scrollSyncTimerRef.current);
      scrollSyncTimerRef.current = setTimeout(() => {
        page.applyPageFromScroll(scrollY);
      }, SCROLL_SYNC_DEBOUNCE_MS);
    },
    [page],
  );

  const completeInitialJump = useCallback(() => {
    initialScrollDoneRef.current = true;
    searchDriverDoneRef.current = true;
    if (search.hasSearchQuery) {
      window.setTimeout(() => search.collectMatches(), 0);
      window.setTimeout(() => search.collectMatches(), 250);
    }
  }, [initialScrollDoneRef, searchDriverDoneRef, search]);

  completeInitialJumpRef.current = completeInitialJump;

  return {
    page,
    search,
    scrollToPageRef,
    onPageRender,
    handleScroll,
    completeInitialJump,
    currentPageRef,
  };
}

export default usePdfViewerState;
