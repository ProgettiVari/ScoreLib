import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Trash2, FileText, Upload as UploadIcon, Star, Tag as TagIcon, Lock, Unlock } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import UploadModal from "@/components/UploadModal";
import TagEditor from "@/components/TagEditor";

export default function Library() {
  const [items, setItems] = useState([]);
  const [tags, setTags] = useState([]);
  const [sort, setSort] = useState("date_desc");
  const [favOnly, setFavOnly] = useState(false);
  const [tagFilter, setTagFilter] = useState("");
  const [openUpload, setOpenUpload] = useState(false);
  const [editTagsFor, setEditTagsFor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const loadSeq = useRef(0);
  const mountedRef = useRef(false);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const isAdmin = user?.is_admin;

  // Load tag from URL parameter on mount
  useEffect(() => {
    const tagFromUrl = searchParams.get("tag");
    if (tagFromUrl) {
      setTagFilter(tagFromUrl);
    } else {
      // Also try localStorage as fallback
      const storedTag = localStorage.getItem("lib_tagFilter");
      if (storedTag) {
        setTagFilter(storedTag);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load library with retry and cache fallback for resilience during indexing
  const load = useCallback(async () => {
    const seq = loadSeq.current + 1;
    loadSeq.current = seq;
    setLoading(true);
    let successfullyLoaded = false;
    
    try {
      const params = { sort };
      if (favOnly) params.favorite = true;
      if (tagFilter) params.tag = tagFilter;
      
      // Create a shorter timeout for the first request to avoid blocking UI during indexing
      const ctrl = new AbortController();
      const timeoutId = setTimeout(() => ctrl.abort(), 8000); // 8s timeout instead of 30s default
      
      try {
        const r = await api.get("/pdfs", { params, signal: ctrl.signal });
        clearTimeout(timeoutId);
        
        if (mountedRef.current && seq === loadSeq.current) {
          setItems(r.data.items || []);
          // Cache to localStorage for offline resilience
          try {
            localStorage.setItem("lib_cache", JSON.stringify({
              items: r.data.items || [],
              timestamp: Date.now(),
            }));
          } catch (e) {}
          
          const allTags = new Set();
          (r.data.items || []).forEach(p => (p.tags || []).forEach(t => allTags.add(t)));
          setTags(Array.from(allTags).sort());
          setLoadError("");
          successfullyLoaded = true;
        }
      } catch (fetchErr) {
        clearTimeout(timeoutId);
        if (fetchErr?.code !== "ECONNABORTED") throw fetchErr;
        
        // If timeout, try fallback from cache
        const cached = localStorage.getItem("lib_cache");
        if (cached) {
          try {
            const data = JSON.parse(cached);
            if (mountedRef.current && seq === loadSeq.current) {
              setItems(data.items || []);
              const allTags = new Set();
              (data.items || []).forEach(p => (p.tags || []).forEach(t => allTags.add(t)));
              setTags(Array.from(allTags).sort());
              setLoadError("Libreria in aggiornamento. Mostrando ultima versione...");
              successfullyLoaded = true;
            }
          } catch (e) {}
        }
      }
    } catch (e) {
      if (mountedRef.current && seq === loadSeq.current) {
        const msg = e.response?.data?.detail || "Libreria non caricata";
        setLoadError(msg);
        
        // Try show cached version on error
        const cached = localStorage.getItem("lib_cache");
        if (cached) {
          try {
            const data = JSON.parse(cached);
            setItems(data.items || []);
            const allTags = new Set();
            (data.items || []).forEach(p => (p.tags || []).forEach(t => allTags.add(t)));
            setTags(Array.from(allTags).sort());
            setLoadError(`Errore: ${msg}. Mostrando versione cached.`);
            successfullyLoaded = true;
          } catch (e) {
            toast.error(msg);
          }
        } else {
          toast.error(msg);
        }
      }
    } finally {
      if (mountedRef.current && seq === loadSeq.current) {
        setLoading(false);
      }
    }
  }, [sort, favOnly, tagFilter]);

  useEffect(() => {
    mountedRef.current = true;
    // Load tag filter from localStorage on mount
    const savedTagFilter = localStorage.getItem("lib_tagFilter");
    if (savedTagFilter) {
      setTagFilter(savedTagFilter);
    }
    return () => {
      mountedRef.current = false;
      loadSeq.current += 1;
    };
  }, []);

  // Separate effect to reload when tagFilter changes (or on mount)
  useEffect(() => {
    load();
  }, [load, tagFilter]);

  const remove = async (id, title) => {
    if (!window.confirm(`Eliminare definitivamente "${title}"?`)) return;
    try {
      await api.delete(`/pdfs/${id}`);
      toast.success("Eliminato");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore eliminazione");
    }
  };

  const toggleFav = async (p) => {
    try {
      const r = await api.patch(`/pdfs/${p.id}`, { is_favorite: !p.is_favorite });
      setItems((arr) => arr.map((x) => (x.id === p.id ? r.data : x)));
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore preferito");
    }
  };

  const toggleProtection = async (p) => {
    if (!isAdmin) return;
    try {
    const r = await api.patch(`/pdfs/${p.id}`, { is_protected: !p.is_protected });
    setItems((arr) => arr.map((x) => (x.id === p.id ? r.data : x)));
    toast.success(p.is_protected ? "Spartito reso pubblico" : "Spartito protetto (accesso limitato)");
    } catch (e) {
      toast.error("Errore modifica protezione");
    }
  };

  const updateItem = (updated) => setItems((arr) => arr.map((x) => (x.id === updated.id ? updated : x)));

  const countText = loading
    ? "Caricamento PDF..."
    : `${items.length} PDF${favOnly ? " preferiti" : tagFilter ? ` con tag "${tagFilter}"` : " indicizzati"}`;

  return (
    <div className="max-w-6xl mx-auto px-6 md:px-12 py-12">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-10">
        <div>
          <p className="overline mb-2">ARCHIVIO</p>
          <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Libreria</h1>
          <p className="text-mono text-sm text-muted2 mt-2"><span>{countText}</span></p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setOpenUpload(true)} className="btn-primary"><UploadIcon size={16} /> Carica PDF</button>
        </div>
      </div>

          <div className="flex flex-col gap-3 mb-4 pb-4 border-b border-rule">
            {/* First row: Preferiti + Ordina on the right */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setFavOnly((v) => !v)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-sm border transition-colors ${favOnly ? "bg-amber-500 text-white border-amber-500 dark:bg-amber-600 dark:border-amber-600" : "border-rule hover:border-ink dark:border-rule dark:hover:border-amber-400"}`}
              >
                <Star size={14} fill={favOnly ? "#FFFFFF" : "none"} /> Preferiti
              </button>
              <div className="flex-1"></div>
              <div className="flex items-center gap-2">
                <span className="overline whitespace-nowrap">ORDINA</span>
                <select value={sort} onChange={(e) => setSort(e.target.value)} className="border border-rule rounded-sm px-3 py-1.5 text-sm bg-card">
                  <option value="date_desc">Più recenti</option>
                  <option value="date_asc">Meno recenti</option>
                  <option value="name_asc">Nome A-Z</option>
                  <option value="name_desc">Nome Z-A</option>
                </select>
              </div>
            </div>
            
            {/* Second row: Tags filter */}
            {tags.length > 0 && (
              <div className="w-full">
                <select value={tagFilter} onChange={(e) => {
                  const newTag = e.target.value;
                  setTagFilter(newTag);
                  localStorage.setItem("lib_tagFilter", newTag);
                  // Update URL parameter
                  if (newTag) {
                    setSearchParams({ tag: newTag });
                  } else {
                    setSearchParams({});
                  }
                }} className="w-full border border-rule rounded-sm px-3 py-1.5 text-sm bg-card">
                  <option value="">Tutti i tag</option>
                  {tags.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            )}
          </div>

      {loading ? (
        <div className="border border-dashed border-rule rounded-md p-16 text-center text-muted2 text-mono text-sm">Caricamento libreria...</div>
      ) : loadError ? (
        <div className="border border-dashed border-rule rounded-md p-16 text-center">
          <FileText size={32} className="mx-auto mb-3 text-muted3" strokeWidth={1.5} />
          <h3 className="font-display text-xl font-bold mb-1">Libreria non disponibile</h3>
          <p className="text-muted2 mb-6">{loadError}</p>
          <button onClick={load} className="btn-primary">Riprova</button>
        </div>
      ) : items.length === 0 ? (
        <div className="border border-dashed border-rule rounded-md p-16 text-center">
          <FileText size={32} className="mx-auto mb-3 text-muted3" strokeWidth={1.5} />
          <h3 className="font-display text-xl font-bold mb-1">Nessun PDF</h3>
          <p className="text-muted2 mb-6">{favOnly || tagFilter ? "Modifica i filtri o carica nuovi PDF." : "Carica qualche PDF per iniziare."}</p>
          <button onClick={() => setOpenUpload(true)} className="btn-primary"><UploadIcon size={16} /> Carica PDF</button>
        </div>
      ) : (
        <ul className="border-t border-rule">
          {items.map((p) => (
            <li key={p.id} className="group flex items-center justify-between gap-4 py-4 border-b border-rule hover:bg-canvas2 px-2 -mx-2 transition-colors">
              <button onClick={() => toggleFav(p)} className="shrink-0" title={p.is_favorite ? "Rimuovi preferito" : "Aggiungi ai preferiti"}>
                <Star 
                  size={18} 
                  strokeWidth={1.5} 
                  fill={p.is_favorite ? "currentColor" : "none"} 
                  className={p.is_favorite ? "text-ink dark:text-amber-400" : "text-muted3 hover:text-ink dark:hover:text-amber-400"} 
                />
              </button>
              <button onClick={() => navigate(`/viewer/${p.id}`)} className="flex-1 text-left flex items-center gap-3 min-w-0">
                <FileText size={18} strokeWidth={1.5} className="shrink-0 text-muted2" />
                <div className="min-w-0">
                  <div className="font-display text-lg font-medium group-hover:underline decoration-2 underline-offset-4 truncate">{p.title}</div>
                  <div className="flex items-center gap-2 flex-wrap mt-0.5">
                    <span className="text-mono text-[10px] text-muted2">
                      {p.created_at?.slice(0, 10)} - {p.status === "ready" ? `${p.pages}pp` : p.status === "error" ? "errore" : "elaborazione"} - {(p.size / 1024).toFixed(0)} KB
                    </span>
                    {p.is_protected && (
                      <span className="text-mono text-[10px] px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-sm font-bold">PROTETTO</span>
                    )}
                    {(p.tags || []).map((t) => (
                      <span key={t} className="text-mono text-[10px] px-1.5 py-0.5 bg-canvas3 rounded-sm dark:bg-canvas2 dark:text-ink">{t}</span>
                    ))}
                  </div>
                </div>
              </button>
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 shrink-0">
                {isAdmin && (
                  <button 
                    onClick={() => toggleProtection(p)} 
                    className={`btn-ghost ${p.is_protected ? "text-amber-600" : "text-emerald-600"}`} 
                    title={p.is_protected ? "Protetto (accesso limitato) - Clicca per rendere pubblico" : "Pubblico - Clicca per proteggere"}
                  >
                    {p.is_protected ? <Lock size={15} /> : <Unlock size={15} />}
                  </button>
                )}
                <button onClick={() => setEditTagsFor(p)} className="btn-ghost" title="Tag"><TagIcon size={15} /></button>
                <button onClick={() => remove(p.id, p.title)} className="btn-ghost text-black dark:text-white" title="Elimina"><Trash2 size={15} className="transition-colors text-black dark:text-white" style={{ color: 'hsl(var(--foreground))' }} /></button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <UploadModal open={openUpload} onClose={() => setOpenUpload(false)} onComplete={load} />
      {editTagsFor && <TagEditor pdf={editTagsFor} onClose={() => setEditTagsFor(null)} onUpdate={updateItem} />}
    </div>
  );
}
