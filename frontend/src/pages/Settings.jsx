import React, { useCallback, useEffect, useState } from "react";
import { Moon, Sun, Monitor, Cloud, RefreshCw, Users, CheckCircle } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export default function Settings() {
  const { user } = useAuth();
  const [backup, setBackup] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [theme, setTheme] = useState(() => {
    const stored = localStorage.getItem("theme");
    if (stored && ["light", "dark", "system"].includes(stored)) return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  const isAdmin = user?.is_admin;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const b = await api.get("/backup/status");
      setBackup(b.data);
      if (isAdmin) {
        const u = await api.get("/admin/users").catch(() => ({ data: { users: [] } }));
        setUsers(u.data.users || []);
      } else {
        setUsers([]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  const changeTheme = (t) => {
    setTheme(t);
    localStorage.setItem("theme", t);
    const root = document.documentElement;
    if (t === "dark") {
      root.classList.add("dark");
      root.style.colorScheme = "dark";
    } else if (t === "light") {
      root.classList.remove("dark");
      root.style.colorScheme = "light";
    } else {
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.classList.toggle("dark", isDark);
      root.style.colorScheme = isDark ? "dark" : "light";
    }
    // Dispatch event to notify other components if needed
    window.dispatchEvent(new Event("theme-change"));
  };

  return (
    <div className="max-w-4xl mx-auto px-6 md:px-12 py-12">
      <div className="mb-10">
        <p className="overline mb-2">IMPOSTAZIONI</p>
        <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Preferenze</h1>
        
        {!isAdmin ? (
          <p className="text-sm rounded-md p-3 mt-4" style={{ background: 'hsl(var(--card))', color: 'hsl(var(--foreground))', border: '1px solid hsl(var(--rule))' }}>
            Stai usando un account approvato. Le impostazioni di sicurezza sono gestite dall'amministratore.
          </p>
        ) : (
          <p className="text-sm rounded-md p-3 mt-4" style={{ background: 'hsl(var(--card))', color: 'hsl(var(--foreground))', border: '1px solid hsl(var(--rule))' }}>
            Account Amministratore · Gestione completa del sistema attiva.
          </p>
        )}
      </div>

      <div className="space-y-12">
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Users size={20} /> {isAdmin ? "Strumenti Creatore" : "Scopri il tuo spazio"}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {!isAdmin ? (
              <>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Organizza</p>
                  <h3 className="font-semibold text-lg mb-2">Usa tag e preferiti</h3>
                  <p className="text-sm text-muted2">Applica tag agli spartiti e salva i preferiti per trovare subito il materiale giusto.</p>
                </div>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Condividi</p>
                  <h3 className="font-semibold text-lg mb-2">Crea librerie pubbliche</h3>
                  <p className="text-sm text-muted2">Crea una libreria, aggiungi PDF e condividi il link a musicisti e fratelli.</p>
                </div>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Esplora</p>
                  <h3 className="font-semibold text-lg mb-2">Trova nuovi spartiti</h3>
                  <p className="text-sm text-muted2">Usa la ricerca avanzata e scopri spartiti nella libreria pubblica. Il tuo account ti permette di partecipare attivamente.</p>
                </div>
              </>
            ) : (
              <>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Pannello Creatore</p>
                  <h3 className="font-semibold text-lg mb-2">Gestisci accessi e backup</h3>
                  <p className="text-sm text-muted2">Controlla richieste di accesso, gestisci il backup Google Drive e tieni sotto controllo lo stato del sistema.</p>
                </div>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Contenuti condivisi</p>
                  <h3 className="font-semibold text-lg mb-2">Crea librerie pubbliche</h3>
                  <p className="text-sm text-muted2">Crea e modifica librerie pubbliche per il tuo gruppo, aggiungendo i PDF più utili agli utenti approvati.</p>
                </div>
                <div className="border border-rule rounded-md p-5 bg-card">
                  <p className="overline mb-2">Consigli</p>
                  <h3 className="font-semibold text-lg mb-2">Mantieni il sistema pulito</h3>
                  <p className="text-sm text-muted2">Usa nomi chiari, tag coerenti e rimuovi librerie obsolete per migliorare l’esperienza degli utenti.</p>
                </div>
              </>
            )}
          </div>
        </section>

        {/* Tema */}
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Monitor size={20} /> Tema
          </h2>
          <div className="grid grid-cols-3 gap-3">
            <ThemeBtn active={theme === "light"} onClick={() => changeTheme("light")} icon={<Sun size={16} />} label="Chiaro" />
            <ThemeBtn active={theme === "dark"} onClick={() => changeTheme("dark")} icon={<Moon size={16} />} label="Scuro" />
            <ThemeBtn active={theme === "system"} onClick={() => changeTheme("system")} icon={<Monitor size={16} />} label="Sistema" />
          </div>
        </section>

        {/* Google Drive Master */}
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Cloud size={20} /> Google Drive Master
          </h2>
          <div className="border border-rule rounded-md p-5 bg-card">
            {backup?.drive_connected ? (
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-emerald-700 font-bold text-sm mb-1">
                    <CheckCircle size={16} /> BACKUP AUTOMATICO ATTIVO
                  </div>
                  <p className="text-sm text-muted2">
                    Tutti gli spartiti sono sincronizzati sul Drive del sistema.
                  </p>
                  <div className="mt-4 grid grid-cols-2 gap-4">
                    <div><div className="overline text-[10px]">Spartiti</div><div className="text-xl font-bold">{backup.total_pdfs}</div></div>
                    <div><div className="overline text-[10px]">Sincronizzati</div><div className="text-xl font-bold">{backup.backed_up_pdfs}</div></div>
                  </div>
                </div>
                {isAdmin && (
                  <button onClick={load} disabled={loading} className="btn-ghost border border-rule rounded-sm p-2">
                    <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
                  </button>
                )}
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-sm text-muted2 mb-4">Il backup su Google Drive non è configurato.</p>
                {isAdmin && (
                  <button onClick={() => window.location.href='/admin'} className="btn-primary text-sm">Configura in Admin</button>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ThemeBtn({ active, onClick, icon, label }) {
  const activeStyle = active ? { background: 'hsl(var(--ink))', color: 'hsl(var(--background))', borderColor: 'hsl(var(--ink))' } : {};
  return (
    <button
      onClick={onClick}
      style={activeStyle}
      className={`flex flex-col items-center gap-2 p-4 rounded-md border transition-all ${active ? "" : "bg-card border-rule hover:border-ink"}`}>
      {icon}
      <span className="text-xs font-mono uppercase">{label}</span>
    </button>
  );
}
