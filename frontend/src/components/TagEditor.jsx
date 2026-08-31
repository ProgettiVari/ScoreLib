import React, { useState, useRef, useEffect } from "react";
import { X, Plus, Tag as TagIcon } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";

const SUGGESTIONS = ["jazz", "worship", "gospel", "lead sheet", "coro", "piano solo", "classica", "pop", "blues", "rock"];

export default function TagEditor({ pdf, onUpdate, onClose }) {
  const [tags, setTags] = useState(pdf.tags || []);
  const [input, setInput] = useState("");
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const addTag = (t) => {
    const v = (t || input).trim().toLowerCase();
    if (!v) return;
    if (tags.includes(v)) { setInput(""); return; }
    setTags((p) => [...p, v]);
    setInput("");
  };
  const remove = (t) => setTags((p) => p.filter((x) => x !== t));

  const save = async () => {
    try {
      const r = await api.patch(`/pdfs/${pdf.id}`, { tags });
      onUpdate(r.data);
      onClose();
    } catch (e) {
      const message = e.response?.data?.detail || "Errore salvataggio tag";
      console.error("Tag save failed", message);
      toast.error(message);
    }
  };

  const remaining = SUGGESTIONS.filter((s) => !tags.includes(s));

  return (
    <div className="fixed inset-0 z-50 bg-overlay flex items-center justify-center p-4" onClick={onClose} data-testid="tag-editor-modal">
      <div className="bg-card border border-rule rounded-md w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-xl font-bold tracking-tight flex items-center gap-2"><TagIcon size={18} /> Tag</h2>
          <button onClick={onClose} className="btn-ghost"><X size={16} /></button>
        </div>
        <p className="text-sm text-muted2 mb-3 truncate">{pdf.title}</p>
        <div className="flex flex-wrap gap-2 mb-3 min-h-[40px]" data-testid="tag-list">
          {tags.length === 0 && <span className="text-sm text-muted3">Nessun tag</span>}
          {tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 px-2 py-1 bg-ink text-white text-xs rounded-sm font-mono dark:bg-canvas3 dark:text-ink" data-testid={`tag-chip-${t}`}>
              {t}
              <button onClick={() => remove(t)} className="hover:opacity-70"><X size={12} /></button>
            </span>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); addTag(); }} className="flex gap-2 mb-4">
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} placeholder="Aggiungi tag…" className="input-base flex-1" data-testid="tag-input" />
          <button type="submit" className="btn-primary !py-2 !px-3" data-testid="tag-add-btn"><Plus size={14} /></button>
        </form>
        {remaining.length > 0 && (
          <div className="mb-4">
            <p className="overline mb-2">Suggerimenti</p>
            <div className="flex flex-wrap gap-1.5">
              {remaining.map((s) => (
                <button key={s} onClick={() => addTag(s)} className="text-xs font-mono px-2 py-1 border border-rule hover:border-ink rounded-sm transition-colors" data-testid={`tag-suggest-${s.replace(/\s/g, "-")}`}>+ {s}</button>
              ))}
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-2 border-t border-rule">
          <button onClick={onClose} className="btn-ghost border border-rule rounded-sm px-4 py-2">Annulla</button>
          <button onClick={save} className="btn-primary" data-testid="tag-save-btn">Salva</button>
        </div>
      </div>
    </div>
  );
}
