import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Users, Trash2, Share2, ExternalLink, DoorOpen } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function Shared() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/libraries");
      setItems(r.data.items || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const create = async (e) => {
    e.preventDefault();
    try {
      await api.post("/libraries", { name, description: desc });
      setShowCreate(false);
      setName("");
      setDesc("");
      toast.success("Libreria creata");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    }
  };

  const del = async (id) => {
    if (!window.confirm("Eliminare la libreria condivisa?")) return;
    try {
      await api.delete(`/libraries/${id}`);
      toast.success("Libreria eliminata");
      load();
    } catch (e) {
      toast.error("Errore eliminazione");
    }
  };

  const canDeleteLibrary = (library) => Boolean(user && (user.is_admin || user.role === "admin" || user.user_id === library.owner_id));
  const canLeaveLibrary = (library) => Boolean(user && user.user_id && user.user_id !== library.owner_id && !user.is_admin && user.role !== "admin");

  const leaveLibrary = async (id, libName) => {
    if (!window.confirm(`Abbandonare la libreria "${libName}"? Potrai rientrare tramite il link di condivisione.`)) return;
    try {
      await api.post(`/libraries/${id}/leave`);
      toast.success("Hai abbandonato la libreria");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore abbandono libreria");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-6 md:px-12 py-12">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-10">
        <div>
          <p className="overline mb-2 flex items-center gap-2"><Share2 size={12} /> CONDIVISE</p>
          <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Librerie Pubbliche</h1>
          <p className="text-muted2 mt-2">Raccolte di spartiti accessibili esternamente tramite link.</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus size={16} /> Nuova Libreria
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <div key={i} className="h-40 bg-canvas2 animate-pulse rounded-md"></div>)}
        </div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center border border-dashed border-rule rounded-md">
          <Users size={32} className="mx-auto mb-4 text-muted3" strokeWidth={1} />
          <p className="text-muted2 italic">Nessuna libreria condivisa disponibile.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((l) => (
            <div key={l.id} className="border border-rule rounded-md p-5 bg-card hover:border-ink transition-colors group relative">
              <div className="flex items-start justify-between mb-3">
                <div className="p-2 bg-canvas2 rounded-sm text-ink">
                  <Users size={20} />
                </div>
                {canDeleteLibrary(l) ? (
                  <button onClick={() => del(l.id)} className="text-black dark:text-white transition-colors" title="Elimina libreria" aria-label="Elimina libreria">
                    <Trash2 size={16} className="transition-colors text-black dark:text-white" style={{ color: 'hsl(var(--foreground))' }} />
                  </button>
                ) : canLeaveLibrary(l) ? (
                  <button onClick={() => leaveLibrary(l.id, l.name)} className="text-muted3 hover:text-red-600 transition-colors" title="Abbandona libreria" aria-label="Abbandona libreria">
                    <DoorOpen size={16} />
                  </button>
                ) : null}
              </div>
              <h3 className="font-bold text-xl leading-tight mb-1 truncate">{l.name}</h3>
              <p className="text-sm text-muted2 line-clamp-2 mb-4 h-10">{l.description || "Nessuna descrizione"}</p>
              
              <div className="flex items-center justify-between text-mono text-[10px] uppercase tracking-widest text-muted3 mb-4">
                <span>{(l.pdf_ids || []).length} Documenti</span>
                <span>{l.created_at?.slice(0, 10)}</span>
              </div>

              <div className="flex items-center gap-2 pt-4 border-t border-rule">
                <Link
                  to={`/libraries/${l.id}`}
                  className="flex-1 flex items-center justify-center gap-2 py-2 bg-canvas2 hover:bg-ink hover:text-white rounded-sm text-xs font-bold transition-all library-manage-btn"
                  data-discover="true"
                >
                  <ExternalLink size={14} /> Gestisci Libreria
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 bg-overlay flex items-center justify-center p-4" onClick={() => setShowCreate(false)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={create} className="bg-card border border-rule rounded-md w-full max-w-md p-6 space-y-4">
            <h2 className="font-display text-2xl font-bold tracking-tight">Nuova libreria</h2>
            <div>
              <label className="overline block mb-2">Nome</label>
              <input required value={name} onChange={(e) => setName(e.target.value)} className="w-full border border-rule rounded-sm px-3 py-2 focus:outline-none focus:border-ink" />
            </div>
            <div>
              <label className="overline block mb-2">Descrizione</label>
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} className="w-full border border-rule rounded-sm px-3 py-2 focus:outline-none focus:border-ink min-h-[80px]" />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm font-bold">Annulla</button>
              <button type="submit" className="btn-primary">Crea</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
