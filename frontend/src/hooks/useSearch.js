import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { normalizeForMatching } from "@/lib/searchText";

/**
 * Unified search hook used by Home, SharedLibraryDetail and SharedView.
 *
 * @param {string} q            Raw user query
 * @param {object} opts
 * @param {string} opts.pdfIdsStr  Comma-joined PDF IDs to restrict scope (empty = all)
 * @param {string} opts.shareToken Share token for public/shared access
 * @param {string} opts.tag        Tag filter (Home only)
 * @returns {Array|null} results — null while idle/loading, [] on empty, array on success
 */
export function useSearch(q, { pdfIdsStr = "", shareToken = "", tag = "" } = {}) {
  const [results, setResults] = useState(null);
  const tref = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    clearTimeout(tref.current);
    if (!q.trim()) { setResults(null); return; }

    const ctrl = new AbortController();
    let alive = true;

    tref.current = setTimeout(async () => {
      try {
        const params = { q: normalizeForMatching(q) };
        if (pdfIdsStr) params.pdf_ids = pdfIdsStr;
        if (shareToken) params.share_token = shareToken;
        if (tag) params.tag = tag;
        const r = await api.get("/search", { params, signal: ctrl.signal });
        if (alive && mountedRef.current) setResults(r.data.results || []);
      } catch (e) {
        if (alive && mountedRef.current &&
            e.name !== "CanceledError" && e.name !== "AbortError" && e.code !== "ERR_CANCELED") {
          setResults([]);
        }
      }
    }, 350);

    return () => { alive = false; clearTimeout(tref.current); ctrl.abort(); };
  }, [q, pdfIdsStr, shareToken, tag]);

  return results;
}
