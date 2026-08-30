import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Cloud, Users, FileText, AlertTriangle, RefreshCw, ScrollText, Unlink, HardDriveUpload, Check, X, CheckCircle } from "lucide-react";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { startGoogleOAuth } from "@/lib/google";

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

export default function Admin() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [requests, setRequests] = useState([]);
  const [users, setUsers] = useState([]);
  const [showAllRequests, setShowAllRequests] = useState(false);
  const [showAllUsers, setShowAllUsers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [master, setMaster] = useState(null);

  const isAdmin = user?.is_admin;
  const visibleRequests = showAllRequests ? requests : requests.slice(0, 3);
  const visibleUsers = showAllUsers ? users : users.slice(0, 3);

  const load = async () => {
    setBusy(true);
    try {
      const [s, m, r, u] = await Promise.all([
        api.get("/admin/stats"),
        api.get("/admin/master-drive/status"),
        api.get("/admin/access-requests"),
        api.get("/admin/users").catch(() => ({ data: { users: [] } }))
      ]);
      setStats(s.data); 
      setMaster(m.data);
      setRequests(r.data || []);
      setUsers(u.data.users || []);
    } catch (e) {
      toast.error(getErrorMessage(e));
    } finally { setBusy(false); }
  };

  const handleRequest = async (email, action) => {
    try {
      await api.post(`/admin/access-requests/${action}`, { email });
      toast.success(`Richiesta ${action === "approve" ? "approvata" : "rifiutata"}`);
      load();
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  };

  const connectMaster = async () => { try { await startGoogleOAuth("master"); } catch { toast.error("Errore OAuth"); } };
  const resetTodayData = async () => {
    const password = window.prompt("Inserisci la password per resetare richieste, utenti approvati e log odierni:", "");
    if (!password) return;
    try {
      const r = await api.post("/admin/reset-today", { password });
      toast.success(`Reset completato: ${r.data.deleted.access_requests} richieste, ${r.data.deleted.users} utenti, ${r.data.deleted.logs} log rimossi.`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore reset dati odierni");
    }
  };
  const disconnectMaster = async () => {
    if (!window.confirm("Scollegare il Master Drive? Tutti i backup automatici si fermeranno.")) return;
    try { await api.post("/admin/master-drive/disconnect"); toast.success("Disconnesso"); load(); }
    catch (e) { toast.error(getErrorMessage(e)); }
  };

  useEffect(() => { if (isAdmin) load(); }, [isAdmin]);

  const resetBtnRef = useRef(null);
  useEffect(() => {
    const el = resetBtnRef.current;
    if (!el || typeof document === "undefined") return undefined;

    const applyColor = () => {
      const dark = document.documentElement.classList.contains("dark");
      const color = dark ? "hsl(var(--foreground))" : "#000000";
      try {
        // Set text color on the button (for label)
        el.style.setProperty("color", color, "important");

        // For SVG elements: set stroke to color and ensure fill is none
        const all = el.querySelectorAll("*");
        all.forEach((child) => {
          // Use namespace check to detect SVG elements
          if (child instanceof SVGElement) {
            child.style.setProperty("stroke", color, "important");
            child.style.setProperty("fill", "none", "important");
          } else {
            child.style.setProperty("color", color, "important");
          }
        });
      } catch (err) {
        // ignore in older browsers
      }
    };

    applyColor();
    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === "attributes" && m.attributeName === "class") {
          applyColor();
          break;
        }
      }
    });
    obs.observe(document.documentElement, { attributes: true });
    return () => obs.disconnect();
  }, []);

  if (!isAdmin) {
    return (
      <div className="max-w-2xl mx-auto p-12 text-center">
        <Shield size={32} className="mx-auto mb-3 text-muted2" strokeWidth={1.5} />
        <h2 className="font-display text-2xl font-bold mb-2">Accesso riservato</h2>
        <p className="text-muted2">Questa sezione è disponibile solo per l'amministratore.</p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 md:px-12 py-12">
      <div className="flex items-end justify-between flex-wrap gap-4 mb-10">
        <div className="min-w-0">
          <p className="overline mb-2 flex items-center gap-2"><Shield size={12} /> AMMINISTRATORE</p>
          <h1 className="font-display font-black text-4xl md:text-5xl tracking-tighter">Pannello Amministratore</h1>
        </div>
        <div className="flex flex-wrap gap-2 w-full sm:w-auto">
          <button onClick={() => navigate("/logs")} className="btn-ghost border border-rule rounded-sm px-3 py-2 text-sm whitespace-nowrap">
            <ScrollText size={14} /> Log di sistema
          </button>
          <button ref={resetBtnRef} onClick={resetTodayData} className="btn-ghost border border-rule rounded-sm px-3 py-2 text-sm !text-black dark:!text-amber-300 admin-reset-btn whitespace-nowrap">
            <AlertTriangle size={14} /> Reset dati odierni
          </button>
          <button onClick={load} disabled={busy} className="btn-primary whitespace-nowrap">
            <RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Aggiorna
          </button>
        </div>
      </div>

      <div className="space-y-12">
        {/* Stats Quick Look */}
        {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat icon={<Users size={16} />} label="Utenti registrati" value={stats.users_total} />
            <Stat icon={<FileText size={16} />} label="Spartiti Totali" value={stats.pdfs_total} />
            <Stat icon={<Cloud size={16} />} label="Backup Drive" value={master?.connected ? "ATTIVO" : "OFF"} accent={!master?.connected} />
            <Stat icon={<AlertTriangle size={16} />} label="Richieste Pendenti" value={requests.filter(r => r.status === 'pending').length} accent={requests.filter(r => r.status === 'pending').length > 0} />
          </div>
        )}

        {/* Membri e Online status */}
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Users size={20} /> Utenti approvati
          </h2>
          <div className="border border-rule rounded-md bg-card divide-y divide-rule">
            {users.length > 0 ? (
              visibleUsers.map((u, idx) => (
                <div key={idx} className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-full bg-canvas3 flex items-center justify-center text-xs font-bold">
                      {u.name.split(' ').map(n => n[0]).join('').toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{u.name}</div>
                      <div className="text-[10px] text-muted3 text-mono uppercase tracking-widest break-all sm:break-normal">{u.email}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-muted2 uppercase tracking-wider font-mono self-start sm:self-auto">
                    <div className="text-xs text-muted3">{u.created_at ? new Date(u.created_at).toLocaleString() : "-"}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-4 text-center text-muted3 italic text-sm">Nessun utente approvato</div>
            )}
            {users.length > 3 && (
              <div className="p-3 text-right bg-canvas2 border-t border-rule">
                <button type="button" onClick={() => setShowAllUsers((v) => !v)} className="btn-ghost text-sm">{showAllUsers ? "Mostra meno" : `Mostra tutti gli ${users.length} utenti`}</button>
              </div>
            )}
          </div>
        </section>

        {/* Access Requests */}
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <AlertTriangle size={20} /> Richieste di Accesso
          </h2>
          <div className="border border-rule rounded-md overflow-hidden bg-card">
            <div className="md:hidden divide-y divide-rule">
              {visibleRequests.map((r, idx) => (
                <div key={idx} className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-bold break-words">{r.name}</div>
                      <div className="text-xs text-muted3 text-mono break-all">{r.email}</div>
                    </div>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 ${
                      r.status === 'approved' ? 'bg-emerald-500 text-emerald-950 dark:bg-emerald-400 dark:text-emerald-950' :
                      r.status === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>
                      {r.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-3 text-xs text-mono text-muted2">
                    <span>IP</span>
                    <span className="break-all text-right">{r.ip || "—"}</span>
                  </div>
                  {r.status === 'pending' && (
                    <div className="flex justify-end gap-2 pt-1">
                      <button onClick={() => handleRequest(r.email, "approve")} className="p-2 bg-emerald-100 text-emerald-700 rounded-sm hover:bg-emerald-200" aria-label="Approva richiesta"><Check size={16} /></button>
                      <button onClick={() => handleRequest(r.email, "reject")} className="p-2 bg-red-100 text-red-700 rounded-sm hover:bg-red-200" aria-label="Rifiuta richiesta"><X size={16} /></button>
                    </div>
                  )}
                </div>
              ))}
              {requests.length === 0 && (
                <div className="py-8 text-center text-muted3 italic">Nessuna richiesta trovata</div>
              )}
            </div>

            <table className="hidden md:table w-full text-sm">
              <thead className="bg-canvas2 border-b border-rule text-left">
                <tr>
                  <th className="py-3 px-4 overline">Richiedente</th>
                  <th className="py-3 px-4 overline">IP</th>
                  <th className="py-3 px-4 overline">Stato</th>
                  <th className="py-3 px-4 overline text-right">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {visibleRequests.map((r, idx) => (
                  <tr key={idx} className="border-b border-rule hover:bg-canvas2">
                    <td className="py-3 px-4">
                      <div className="font-bold">{r.name}</div>
                      <div className="text-xs text-muted3 text-mono">{r.email}</div>
                    </td>
                    <td className="py-3 px-4 text-xs text-mono">{r.ip || "—"}</td>
                    <td className="py-3 px-4">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        r.status === 'approved' ? 'bg-emerald-500 text-emerald-950 dark:bg-emerald-400 dark:text-emerald-950' : 
                        r.status === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                      }`}>
                        {r.status.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right">
                      {r.status === 'pending' && (
                        <div className="flex justify-end gap-2">
                          <button onClick={() => handleRequest(r.email, "approve")} className="p-1.5 bg-emerald-100 text-emerald-700 rounded-sm hover:bg-emerald-200"><Check size={16} /></button>
                          <button onClick={() => handleRequest(r.email, "reject")} className="p-1.5 bg-red-100 text-red-700 rounded-sm hover:bg-red-200"><X size={16} /></button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {requests.length === 0 && (
                  <tr><td colSpan="4" className="py-8 text-center text-muted3 italic">Nessuna richiesta trovata</td></tr>
                )}
              </tbody>
            </table>
          {requests.length > 3 && (
            <div className="border-t border-rule bg-canvas2 px-4 py-3 text-right">
              <button
                type="button"
                onClick={() => setShowAllRequests((value) => !value)}
                className="btn-ghost text-sm"
              >
                {showAllRequests ? "Mostra meno" : `Mostra tutte le ${requests.length} richieste`}
              </button>
            </div>
          )}
          </div>
        </section>

        {/* Master Drive panel */}
        <section>
          <h2 className="font-display font-bold text-xl mb-4 flex items-center gap-2">
            <Cloud size={20} /> Google Drive Master
          </h2>
          <div className="border border-rule rounded-md p-5 bg-card">
            <div className="flex items-start justify-between flex-wrap gap-4 mb-3">
              <div>
                <p className="text-sm text-muted2 max-w-2xl">
                  Tutti gli spartiti caricati dal gruppo vengono salvati automaticamente su questo account Drive.
                </p>
              </div>
              <div className="flex gap-2">
                {!master?.connected ? (
                  <button onClick={connectMaster} className="btn-primary !py-2 !px-3 text-sm">
                    <HardDriveUpload size={14} /> Collega Account Google
                  </button>
                ) : (
                  <button
                    onClick={disconnectMaster}
                    className="btn-ghost btn-ghost-danger border border-red-300 rounded-sm px-3 py-1.5 text-sm"
                  >
                    <Unlink size={14} /> Scollega Drive
                  </button>
                )}
              </div>
            </div>
            {master?.connected && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t border-rule pt-4">
                <div><div className="overline mb-1">Email collegata</div><div className="text-mono text-sm">{master.email}</div></div>
                <div><div className="overline mb-1">Stato Backup</div><div className="text-emerald-700 text-sm font-medium flex items-center gap-1"><CheckCircle size={14} /> Sincronizzazione Attiva</div></div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Stat({ icon, label, value, accent }) {
  return (
    <div className={`border border-rule rounded-md p-4 ${accent ? "bg-amber-50 border-amber-300" : "bg-card"}`}>
      <div className="flex items-center gap-2 text-muted2 text-xs uppercase tracking-wider font-mono mb-2">
        {icon} {label}
      </div>
      <div className="font-display text-3xl font-bold tracking-tighter">{value}</div>
    </div>
  );
}
