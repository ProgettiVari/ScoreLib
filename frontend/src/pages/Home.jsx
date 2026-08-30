import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Search as SearchIcon, Upload as UploadIcon } from "lucide-react";
import api from "@/lib/api";
import { useSearch } from "@/hooks/useSearch";
import UploadModal from "@/components/UploadModal";
import TrebleClef from "@/components/TrebleClef";
import { highlightText } from "@/lib/searchText";

const RECENT_SEARCHES_KEY = "scorelib.recentSearches";
const MAX_RECENT_SEARCHES = 8;


function normalizeRecentTerm(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function loadRecentSearches() {
  try {
    const stored = window.localStorage.getItem(RECENT_SEARCHES_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => String(item || "").trim().replace(/\s+/g, " "))
      .filter(Boolean)
      .slice(0, MAX_RECENT_SEARCHES);
  } catch {
    return [];
  }
}

function saveRecentSearches(list) {
  try {
    const normalized = list
      .map((item) => String(item || "").trim().replace(/\s+/g, " "))
      .filter(Boolean)
      .slice(0, MAX_RECENT_SEARCHES);
    window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(normalized));
  } catch {
    // ignore storage errors
  }
}



export default function Home() {
  const [q, setQ] = useState("");
  const [selectedTag, setSelectedTag] = useState(null);
  const [availableTags, setAvailableTags] = useState([]);
  const [count, setCount] = useState(0);
  const [countLoading, setCountLoading] = useState(true);
  const [openUpload, setOpenUpload] = useState(false);
  const [recentSearches, setRecentSearches] = useState([]);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const inputRef = useRef(null);

  // Read tag from URL parameter on mount
  useEffect(() => {
    const tagFromUrl = searchParams.get("tag");
    if (tagFromUrl) {
      setSelectedTag(tagFromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setRecentSearches(loadRecentSearches());
    // Carica i tag disponibili da /pdfs
    api.get("/pdfs")
      .then((r) => {
        const tagsSet = new Set();
        (r.data.items || []).forEach(item => {
          if (item.tags && Array.isArray(item.tags)) {
            item.tags.forEach(t => tagsSet.add(t));
          }
        });
        setAvailableTags(Array.from(tagsSet).sort());
      })
      .catch(() => {}); // ignora errori nel caricamento tag
  }, []);

  const addRecentSearch = (term) => {
    const normalized = String(term || "").trim().replace(/\s+/g, " ");
    if (!normalized) return;
    setRecentSearches((current) => {
      const next = [normalized, ...current.filter((item) => normalizeRecentTerm(item) !== normalizeRecentTerm(normalized))]
        .slice(0, MAX_RECENT_SEARCHES);
      saveRecentSearches(next);
      return next;
    });
  };

  useEffect(() => {
    let alive = true;
    api.get("/pdfs")
      .then((r) => { if (alive) setCount(r.data.items.length); })
      .catch(() => {})
      .finally(() => { if (alive) setCountLoading(false); });
    const onKey = (e) => {
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || e.key === "/") {
        if (document.activeElement?.tagName === "INPUT") return;
        e.preventDefault(); inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => { alive = false; window.removeEventListener("keydown", onKey); };
  }, []);

  const submitSearch = (event) => {
    event.preventDefault();
    const nextTerm = q.trim().replace(/\s+/g, " ");
    if (!nextTerm) return;
    setQ(nextTerm);
    addRecentSearch(nextTerm);
  };

  const results = useSearch(q, { tag: selectedTag });

  return (
    <div className="max-w-4xl mx-auto px-6 md:px-12 py-12 md:py-20">
      <div className="text-center mb-10">
        <div className="inline-block mb-6"><TrebleClef size={44} /></div>
        <h1 className="font-display font-black text-4xl sm:text-5xl lg:text-6xl tracking-tighter mb-3">
          Trova ogni spartito.<br />In un battito.
        </h1>
        <p className="text-muted2">Premi <kbd className="text-mono text-xs border border-rule rounded px-1.5 py-0.5">/</kbd> per cercare ovunque.</p>
      </div>

      <form onSubmit={submitSearch} className="bg-card border-2 border-ink rounded-md mb-3" style={{ boxShadow: "0 6px 0 0 rgba(0,0,0,0.18)" }}>
        <div className="flex items-center gap-3 px-5">
          <SearchIcon size={20} className="text-muted2" strokeWidth={1.75} />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitSearch(e);
            }}
            placeholder="Cerca per titolo, contenuto, accordi..."
            className="w-full text-xl md:text-2xl py-5 outline-none placeholder:text-muted3 bg-transparent"
          />
          {q && <button type="button" onClick={() => setQ("")} className="text-mono text-xs text-muted2 hover:text-ink">CANCELLA</button>}
        </div>
      </form>
      {availableTags.length > 0 && (
        <div className="bg-card border-2 border-rule rounded-md mb-4 px-5 py-3 flex items-center gap-3">
          <label htmlFor="tagSelect" className="text-sm font-semibold text-muted2 whitespace-nowrap">Filtra per tag:</label>
          <select
            id="tagSelect"
            value={selectedTag || ""}
            onChange={(e) => {
              const newTag = e.target.value || null;
              setSelectedTag(newTag);
              // Update URL parameter
              if (newTag) {
                setSearchParams({ tag: newTag });
              } else {
                setSearchParams({});
              }
            }}
            className="flex-1 px-3 py-2 bg-canvas border border-rule rounded text-sm outline-none"
          >
            <option value="">-- Tutti i tag --</option>
            {availableTags.map(tag => (
              <option key={tag} value={tag}>{tag}</option>
            ))}
          </select>
        </div>
      )}
      {recentSearches.length > 0 && (
        <div className="bg-card border-2 border-rule rounded-md mb-6 px-5 py-4 text-sm text-muted2" style={{ boxShadow: "0 6px 0 0 rgba(0,0,0,0.08)" }}>
          <div className="mb-2 uppercase tracking-[0.18em] text-[10px] font-semibold">Ricerche recenti</div>
          <div className="flex flex-wrap gap-2">
            {recentSearches.map((term) => (
              <button
                key={term}
                onClick={() => setQ(term)}
                className="rounded-full border border-rule px-3 py-1 text-sm text-muted3 hover:bg-canvas3"
                title={term}
              >
                {term}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between text-sm text-muted2 mb-8">
        <span>{countLoading ? "Caricamento libreria..." : `${count} PDF nella libreria globale`}</span>
        <button onClick={() => setOpenUpload(true)} className="btn-primary !py-2 !px-4 text-sm">
          <UploadIcon size={16} /> Carica PDF
        </button>
      </div>

      {results && (
        <ul className="border-t border-rule">
          {results.length === 0 && (
            <li className="py-10 text-center text-muted2">Nessun risultato per "<span className="text-ink">{q}</span>"</li>
          )}
          {results.map((r, idx) => (
            <li key={idx} className="py-5 border-b border-rule animate-fade-in">
              <button
                onClick={async () => {
                  addRecentSearch(q);
                  const pageParam = r.page_label ? String(r.page_label) : (r.viewer_page ?? r.actual_page ?? r.page ? String(r.viewer_page ?? r.actual_page ?? r.page) : "");
                  navigate(`/viewer/${r.pdf_id}?page=${encodeURIComponent(pageParam)}&q=${encodeURIComponent(q)}`);
                }}
                className="text-left w-full group"
              >
                <div className="flex items-baseline gap-3 flex-wrap mb-1">
                  <span className="font-display text-xl font-semibold group-hover:underline decoration-2 underline-offset-4">{highlightText(r.title, q, { defaultMarkClass: 'hl', chordMarkClass: 'bg-emerald-100 text-emerald-900 px-1 rounded' })}</span>
                  <span className="text-mono text-[10px] px-2 py-0.5 bg-canvas3 rounded-sm text-muted2">
                    PAG {r.page_label || r.page}
                  </span>
                  {r.is_protected && (
                    <span className="text-mono text-[10px] px-2 py-0.5 bg-amber-100 text-amber-700 rounded-sm font-bold">
                      PROTETTO
                    </span>
                  )}
                </div>
                {r.snippet && <p className="text-muted2 leading-relaxed">{highlightText(r.snippet, q, { defaultMarkClass: 'hl' })}</p>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <UploadModal open={openUpload} onClose={() => setOpenUpload(false)} onComplete={() => api.get("/pdfs").then((r) => setCount(r.data.items.length))} />
    </div>
  );
}
