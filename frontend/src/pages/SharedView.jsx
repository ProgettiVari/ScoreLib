import React, { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { FileText, Lock } from "lucide-react";
import api from "@/lib/api";
import { useSearch } from "@/hooks/useSearch";
import SearchResults from "@/components/SearchResults";

export default function SharedView() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [lib, setLib] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;

    api.get(`/shared/${token}`, { signal: ctrl.signal }).then((r) => {
      if (alive) setLib(r.data);
    }).catch((e) => {
      if (!alive || e.name === "CanceledError" || e.name === "AbortError" || e.code === "ERR_CANCELED") return;
      setError(e.response?.data?.detail || "Errore");
    });

    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [token]);

  const pdfIdsStr = (lib?.pdfs || []).map((p) => String(p.id)).join(",");
  const searchResults = useSearch(lib ? q : "", { pdfIdsStr, shareToken: token });

  if (error) return (
    <div className="max-w-2xl mx-auto p-12 text-center">
      <h2 className="font-display text-2xl font-bold mb-2">Link non disponibile</h2>
      <p className="text-muted2">{error}</p>
      <Link to="/" className="btn-primary mt-6 inline-block">Torna alla Home</Link>
    </div>
  );

  if (!lib) return <div className="p-12 text-mono text-sm text-muted2">Caricamento…</div>;

  return (
    <div className="max-w-6xl mx-auto px-6 md:px-12 py-12">
      <p className="overline mb-2">LIBRERIA CONDIVISA</p>
      <h1 className="font-display font-black text-4xl tracking-tighter mb-1">{lib.name}</h1>
      {lib.description && <p className="text-muted2 mb-6 max-w-2xl">{lib.description}</p>}

      <div className="public-view-banner border rounded-md p-4 mb-8 text-sm">
        <div className="flex gap-2">
          <Lock size={16} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-bold">Vista Pubblica</p>
            <p>Gli spartiti protetti sono visibili solo ai membri del gruppo Chiesa Pomigliano.</p>
            <Link to="/login" className="font-bold underline mt-2 inline-block hover:opacity-80">Accedi come Gruppo</Link>
          </div>
        </div>
      </div>

      <div className="mb-6">
        <label className="overline block mb-2">Cerca nel contenuto della condivisione</label>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Cerca parole presenti nei PDF..."
          className="w-full border border-rule rounded-md bg-card px-4 py-3 text-sm focus:outline-none focus:border-ink"
        />
      </div>

      {q.trim() ? (
        <SearchResults
          results={searchResults}
          q={q}
          shareToken={token}
          emptyText="Nessun PDF disponibile pubblicamente per la ricerca richiesta."
        />
      ) : (
        <ul className="border-t border-rule">
          {(lib.pdfs || []).length === 0 && (
            <li className="py-12 text-center text-muted2 text-sm">Nessun PDF disponibile pubblicamente.</li>
          )}
          {(lib.pdfs || []).map((p, idx) => (
            <li key={p.id || idx} className="py-4 border-b border-rule hover:bg-canvas2 px-2 -mx-2 transition-colors">
              <button onClick={() => navigate(`/viewer/${p.id}`)} className="text-left w-full flex items-start gap-4">
                <FileText size={18} className="text-muted2 mt-1 shrink-0" />
                <div className="min-w-0">
                  <div className="font-display font-bold text-lg hover:underline decoration-2 underline-offset-4">{p.title}</div>
                  <div className="text-mono text-xs text-muted3 mt-1">{p.pages || ""} pagine</div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
