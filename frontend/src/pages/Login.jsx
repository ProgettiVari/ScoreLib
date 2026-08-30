import React, { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import AuthShell from "@/components/AuthShell";

const ADMIN_EMAIL = process.env.REACT_APP_ADMIN_EMAIL?.toLowerCase() || "admin@scorelib.app";

export default function Login() {
  const [mode, setMode] = useState("login"); // default to login
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordRequired, setPasswordRequired] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [otpRequired, setOtpRequired] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithToken } = useAuth();

  const normalizedEmail = email.toLowerCase().trim();
  const isAdminEmail = normalizedEmail === ADMIN_EMAIL;
  const shouldShowPassword = isAdminEmail || passwordRequired;

  useEffect(() => {
    if (!isAdminEmail) {
      setPassword("");
      setPasswordRequired(false);
    }
  }, [isAdminEmail]);

  const completeLogin = (data) => {
    loginWithToken(data.token, data.user);
    let from = location.state?.from || "/";
    if (from === "/login") from = "/";
    // Prevent redirecting normal users to admin
    if (from === "/admin" && !data.user?.is_admin) from = "/";
    navigate(from, { replace: true });
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = { email: normalizedEmail };
      if (shouldShowPassword) {
        payload.password = password;
      }
      const r = await api.post("/auth/login", payload);
      if (r.data?.otp_required) {
        setOtpRequired(true);
        toast.success("Ti abbiamo inviato un codice di accesso via email.");
      } else {
        completeLogin(r.data);
      }
    } catch (err) {
      if (err?.response?.status === 400 && err?.response?.data?.detail === "Password richiesta") {
        setPasswordRequired(true);
        toast.error("Password richiesta per accesso admin. Inseriscila e riprova.");
      } else {
        toast.error(err?.response?.data?.detail || "Credenziali non valide");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post("/auth/login/verify-otp", { email: normalizedEmail, code: otpCode });
      completeLogin(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Codice non valido o scaduto");
    } finally {
      setBusy(false);
    }
  };

  const handleRequest = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/request-access", { name, email });
      setSuccess(true);
      toast.success("Richiesta inviata con successo!");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Errore nell'invio della richiesta");
    } finally {
      setBusy(false);
    }
  };

  if (otpRequired) {
    return (
      <AuthShell title="Controlla la tua email" subtitle={`Abbiamo inviato un codice a ${email}`}>
        <form onSubmit={handleVerifyOtp} className="space-y-4">
          <div>
            <label className="overline block mb-2">Codice di accesso</label>
            <input
              type="text" inputMode="numeric" autoFocus required value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              className="input-base" placeholder="123456" maxLength={6}
            />
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Verifica in corso..." : "Verifica e accedi"}
          </button>
          <div className="pt-4 text-center">
            <button
              type="button" onClick={() => { setOtpRequired(false); setOtpCode(""); }}
              className="text-sm text-ink hover:underline font-medium"
            >
              Torna indietro
            </button>
          </div>
        </form>
      </AuthShell>
    );
  }

  if (success) {
    return (
      <AuthShell title="Richiesta Inviata" subtitle="Grazie per l'interesse.">
        <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-6 text-center space-y-4 py-6">
          <p className="text-ink text-base font-semibold">
            La tua richiesta di accesso per <strong>{email}</strong> è stata inoltrata.
          </p>
          <p className="text-muted3 text-sm">
            Riceverai un'email quando la richiesta sarà approvata o rifiutata. Controlla anche la cartella spam se non vedi subito il messaggio.
          </p>
          <button onClick={() => { setSuccess(false); setMode("login"); }} className="btn-secondary w-full">
            Torna al login
          </button>
        </div>
      </AuthShell>
    );
  }
  return (
    <AuthShell 
      title={mode === "login" ? "Accedi" : "Richiedi Accesso"}
      subtitle={mode === "login" ? "Accedi al tuo account" : "Richiedi l'accesso per visualizzare la libreria"}
    >
      {mode === "login" ? (
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="overline block mb-2">Email</label>
            <input 
              type="email" required value={email} 
              onChange={(e) => setEmail(e.target.value)} 
              className="input-base" placeholder="tu@esempio.com" 
            />
          </div>
          {shouldShowPassword && (
            <div>
              <label className="overline block mb-2">Password</label>
              <input 
                type="password" required value={password} 
                onChange={(e) => setPassword(e.target.value)} 
                className="input-base" placeholder="********" 
              />
            </div>
          )}

          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Accesso in corso..." : "Accedi"}
          </button>
          
          <div className="pt-4 text-center space-y-2">
            <button 
              type="button" onClick={() => setMode("request")}
              className="text-sm text-ink hover:underline font-medium"
            >
              Non hai l'accesso? Richiedilo qui
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={handleRequest} className="space-y-4">
          <div>
            <label className="overline block mb-2">Nome Completo</label>
            <input 
              type="text" required value={name} 
              onChange={(e) => setName(e.target.value)} 
              className="input-base" placeholder="Mario Rossi" 
            />
          </div>
          <div>
            <label className="overline block mb-2">Email</label>
            <input 
              type="email" required value={email} 
              onChange={(e) => setEmail(e.target.value)} 
              className="input-base" placeholder="tu@esempio.com" 
            />
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Invio richiesta..." : "Invia Richiesta"}
          </button>
          <div className="pt-4 text-center">
            <button 
              type="button" onClick={() => setMode("login")}
              className="text-sm text-ink hover:underline font-medium"
            >
              Torna al login
            </button>
          </div>
        </form>
      )}
    </AuthShell>
  );
}
