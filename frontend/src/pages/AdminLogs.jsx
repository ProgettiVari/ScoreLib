import React, { useState, useEffect, useCallback, useRef } from "react";
import { Lock, RefreshCw, Search, Pause, Play } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const ADMIN_EMAIL = "admin@scorelib.app";

function levelColor(level) {
  if (level === "error") return "text-red-600 border-red-300 bg-red-50";
  if (level === "warn") return "text-amber-700 border-amber-300 bg-amber-50";
  return "text-muted2 border-rule bg-card";
}

export default function AdminLogs() {
  const { user } = useAuth();
  const isAdmin = user?.email?.toLowerCase() === ADMIN_EMAIL || user?.is_admin;
  const [items, setItems] = useState([]);
  const [types, setTypes] = useState([]);
  const [filterType, setFilterType] = useState("all");
  const [filterLevel, setFilterLevel] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("date_desc");
  const [busy, setBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const tref = useRef(null);

  const fetchLogs = useCallback(async () => {
    if (!isAdmin) return;
    setBusy(true);
    try {
      const r = await api.get("/admin/logs", { params: { event_type: filterType, q, sort, limit: 500 } });
      let list = r.data.items;
      if (filterLevel !== "all") list = list.filter((x) => (x.level || "info") === filterLevel);
      setItems(list);
      setTypes(r.data.types);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally {
      setBusy(false);
    }
  }, [isAdmin, filterType, filterLevel, q, sort]);

  useEffect(() => {
    if (!isAdmin) return undefined;
    fetchLogs();
    return undefined;
  }, [isAdmin, fetchLogs]);

  useEffect(() => {
    if (!isAdmin || !autoRefresh) return undefined;
    tref.current = setInterval(() => fetchLogs(), 5000);
    return () => clearInterval(tref.current);
  }, [isAdmin, autoRefresh, fetchLogs]);

  if (!isAdmin) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center p-6">
        <div className="w-full max-w-sm border border-rule rounded-md p-8 bg-card" data-testid="admin-denied">
          <Lock size={28} strokeWidth={1.5} className="mb-3" />
          <h1 className="font-display font-black text-3xl tracking-tighter mb-2">Accesso riservato</h1>
          <p className="text-muted2 text-sm">I log di sistema sono disponibili solo per gli amministratori.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 md:px-12 py-12" data-testid="admin-logs-page">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-8">
        <div>
          <p className="overline mb-2">SISTEMA</p>
          <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Logs</h1>
          <p className="text-mono text-sm text-muted2 mt-1">
            <span data-testid="logs-count">{items.length}</span> eventi {autoRefresh ? "- auto-refresh ogni 5s" : "- refresh manuale"}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setAutoRefresh((v) => !v)} className="btn-ghost border border-rule rounded-sm px-3 py-2 text-sm" data-testid="toggle-autorefresh">
            {autoRefresh ? <><Pause size={14} /> Pausa</> : <><Play size={14} /> Auto</>}
          </button>
          <button onClick={fetchLogs} disabled={busy} className="btn-primary disabled:opacity-50" data-testid="admin-refresh-btn">
            <RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Aggiorna
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4 border border-rule rounded-sm p-3 bg-canvas2">
        <div className="flex items-center gap-2 flex-1 min-w-[200px]">
          <Search size={14} className="text-muted2" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca nei log..." className="bg-transparent outline-none text-sm w-full" data-testid="admin-search-input" />
        </div>
        <select value={filterLevel} onChange={(e) => setFilterLevel(e.target.value)} className="border border-rule rounded-sm px-2 py-1.5 text-sm bg-card" data-testid="admin-filter-level">
          <option value="all">Tutti i livelli</option>
          <option value="info">Info</option>
          <option value="warn">Warning</option>
          <option value="error">Error</option>
        </select>
        <select value={filterType} onChange={(e) => setFilterType(e.target.value)} className="border border-rule rounded-sm px-2 py-1.5 text-sm bg-card" data-testid="admin-filter-type">
          <option value="all">Tutti gli eventi</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} className="border border-rule rounded-sm px-2 py-1.5 text-sm bg-card" data-testid="admin-sort">
          <option value="date_desc">Piu recenti</option>
          <option value="date_asc">Meno recenti</option>
        </select>
      </div>

      <div className="border border-rule rounded-md bg-card max-h-[70vh] overflow-y-auto font-mono text-xs" data-testid="admin-logs-list">
        {items.length === 0 && <div className="py-12 text-center text-muted2 text-sm">Nessun log</div>}
        {items.map((l) => (
          <div key={l.id} className="border-b border-rule px-4 py-2 flex flex-wrap gap-3 items-baseline hover:bg-canvas2" data-testid={`log-row-${l.id}`}>
            <span className="text-muted3 shrink-0">{l.created_at?.slice(0, 19).replace("T", " ")}</span>
            <span className={`px-2 py-0.5 rounded-sm border ${levelColor(l.level)} shrink-0 text-[10px] uppercase tracking-wider`}>
              {l.level || "info"}
            </span>
            <span className="text-ink shrink-0">{l.event_type}</span>
            {l.user_id && <span className="text-muted3 shrink-0">[{l.user_id.slice(0, 16)}]</span>}
            <span className="text-muted2 flex-1 break-words font-sans">{l.description}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
