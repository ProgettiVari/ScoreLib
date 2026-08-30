import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Users, Trash2, Lock, DoorOpen, EyeOff, Eye } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const getErrorMessage = (error) => {
  if (!error) return "Errore sconosciuto";
  const detail = error.response?.data?.detail;
  if (!detail) return "Errore sconosciuto";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map(d => typeof d === "string" ? d : (d.msg || JSON.stringify(d)));
    return msgs.join("; ");
  }
  return JSON.stringify(detail);
};

export default function SharedLibraries() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [hiddenItems, setHiddenItems] = useState([]);
  const [show, setShow] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  const load = async () => { 
    try { 
      const r = await api.get("/libraries"); 
      setItems(r.data.items); 
    } catch {} 
  };
  const loadHidden = async () => { 
    try { 
      const r = await api.get("/libraries/hidden"); 
      setHiddenItems(r.data.items); 
    } catch {} 
  };
  useEffect(() => { load(); loadHidden(); }, []);

  const create = async (e) => {
    e.preventDefault();
    try { await api.post("/libraries", { name, description: desc }); setShow(false); setName(""); setDesc(""); toast.success("Libreria creata"); load(); }
    catch (e) { toast.error(getErrorMessage(e)); }
  };
  const del = async (id) => { if (!window.confirm("Eliminare la libreria condivisa?")) return; await api.delete(`/libraries/${id}`); load(); };
  const canDeleteLibrary = (library) => Boolean(user && (user.is_admin || user.role === "admin" || user.user_id === library.owner_id));
  const leaveLibrary = async (id, libName) => {
    if (!window.confirm(`Abbandonare la libreria "${libName}"? Potrai rientrare tramite il link di condivisione.`)) return;
    try {
      await api.post(`/libraries/${id}/leave`);
      toast.success("Hai abbandonato la libreria");
      load();
      loadHidden();
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  };
  const unhide = async (id) => { await api.delete(`/libraries/${id}/leave`); toast.success("Libreria ripristinata"); load(); loadHidden(); };

  return (
    <div className="max-w-6xl mx-auto px-6 md:px-12 py-12">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-10" data-testid="shared-libraries-page">
        <div>
          <p className="overline mb-2">COLLABORAZIONE</p>
          <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Librerie condivise</h1>
          <p className="text-muted2 mt-2 max-w-xl">Raccogli spartiti e condividi un link con altri musicisti.</p>
        </div>
        <button onClick={() => setShow(true)} className="btn-primary" data-testid="new-library-btn"><Plus size={16} /> Nuova libreria</button>
      </div>

      {items.length === 0 ? (
        <div className="border border-dashed border-rule rounded-md p-16 text-center" data-testid="shared-empty">
          <Users size={32} className="mx-auto mb-3 text-muted3" strokeWidth={1.5} />
          <h3 className="font-display text-xl font-bold mb-1">Nessuna libreria</h3>
          <p className="text-muted2">Crea una libreria per raccogliere e condividere spartiti.</p>
        </div>
      ) : (
        <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="shared-libraries-list">
          {items.map((l) => (
            <li key={l.id} className="border border-rule rounded-md p-5 hover:border-ink transition-colors" data-testid={`shared-lib-${l.id}`}>
              <div className="flex items-start justify-between gap-2 mb-3">
                <Link to={`/libraries/${l.id}`} className="flex items-start gap-2 min-w-0 flex-1">
                  {l.owner_id !== user?.user_id && (
                    <Lock
                      size={16}
                      className="shrink-0 text-muted2 mt-1"
                      title="Libreria condivisa in sola lettura"
                      aria-label="Libreria condivisa in sola lettura"
                      data-testid={`shared-lib-lock-${l.id}`}
                    />
                  )}
                  <div className="min-w-0">
                    <h3 className="font-display text-xl font-bold tracking-tight hover:underline">{l.name}</h3>
                    {l.description && <p className="text-sm text-muted2 mt-1 line-clamp-2">{l.description}</p>}
                  </div>
                </Link>
                {canDeleteLibrary(l) ? (
                  <button onClick={() => del(l.id)} className="text-black dark:text-white transition-colors" data-testid={`shared-lib-delete-${l.id}`} title="Elimina libreria" aria-label="Elimina libreria"><Trash2 size={14} className="transition-colors text-black dark:text-white" style={{ color: 'hsl(var(--foreground))' }} /></button>
                ) : (
                  <button
                    type="button"
                    onClick={() => leaveLibrary(l.id, l.name)}
                    className="btn-ghost shrink-0"
                    title="Abbandona libreria"
                    aria-label="Abbandona libreria"
                    data-testid={`shared-lib-leave-${l.id}`}
                  >
                    <DoorOpen size={14} />
                  </button>
                )}
              </div>
              <div className="flex items-center justify-between text-mono text-xs text-muted2 mt-3 pt-3 border-t border-rule">
                <span>{(l.pdf_ids || []).length} PDF</span>
                <span>{(l.members || []).length + 1} membri</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {hiddenItems.length > 0 && (
        <div className="mt-12">
          <button onClick={() => setShowHidden(!showHidden)} className="btn-ghost border border-rule rounded-sm px-4 py-2 mb-4">
            {showHidden ? <><Eye size={16} /> Nascondi sezione nascoste</> : <><EyeOff size={16} /> Mostra nascoste ({hiddenItems.length})</>}
          </button>
          {showHidden && (
            <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 opacity-60">
              {hiddenItems.map((l) => (
                <li key={l.id} className="border border-rule rounded-md p-5 hover:border-ink transition-colors">
                  <div className="flex items-start justify-between mb-3">
                    <div className="block">
                      <h3 className="font-display text-xl font-bold tracking-tight">{l.name}</h3>
                      {l.description && <p className="text-sm text-muted2 mt-1 line-clamp-2">{l.description}</p>}
                    </div>
                    <button onClick={() => unhide(l.id)} className="btn-ghost" data-testid={`shared-lib-unhide-${l.id}`}><Eye size={14} /></button>
                  </div>
                  <div className="flex items-center justify-between text-mono text-xs text-muted2 mt-3 pt-3 border-t border-rule">
                    <span>{(l.pdf_ids || []).length} PDF</span>
                    <span>{(l.members || []).length + 1} membri</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {show && (
        <div className="fixed inset-0 z-50 bg-overlay flex items-center justify-center p-4" onClick={() => setShow(false)} data-testid="new-library-modal">
          <form onClick={(e) => e.stopPropagation()} onSubmit={create} className="bg-card border border-rule rounded-md w-full max-w-md p-6 space-y-4">
            <h2 className="font-display text-2xl font-bold tracking-tight">Nuova libreria</h2>
            <div>
              <label className="overline block mb-2">Nome</label>
              <input required value={name} onChange={(e) => setName(e.target.value)} className="input-base" data-testid="new-library-name" />
            </div>
            <div>
              <label className="overline block mb-2">Descrizione</label>
              <textarea value={desc} onChange={(e) => setDesc(e.target.value)} className="input-base min-h-[80px]" data-testid="new-library-desc" />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShow(false)} className="btn-ghost border border-rule rounded-sm px-4 py-2">Annulla</button>
              <button type="submit" className="btn-primary" data-testid="new-library-submit">Crea</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
