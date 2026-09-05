import React, { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import AuthShell from "@/components/AuthShell";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [otpRequired, setOtpRequired] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { loginWithToken } = useAuth();

  const normalizedEmail = email.toLowerCase().trim();

  useEffect(() => {
    if (!cooldownUntil) return;

    const tick = () => {
      const remaining = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
      setCooldownSeconds(remaining);
      if (remaining <= 0) {
        setCooldownUntil(0);
      }
    };

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [cooldownUntil]);

  const completeLogin = (data) => {
    loginWithToken(data.token, data.user);
    let from = location.state?.from || "/";
    if (from === "/login") from = "/";
    if (from === "/admin" && !data.user?.is_admin) from = "/";
    navigate(from, { replace: true });
  };

  const handleRequestOtp = async (e) => {
    e.preventDefault();

    if (!normalizedEmail) {
      toast.error("Inserisci una email valida.");
      return;
    }

    setBusy(true);
    try {
      const payload = { email: normalizedEmail };
      if (password.trim()) payload.password = password;

      const res = await api.post("/auth/login", payload);
      const data = res?.data ?? {};

      if (data?.token) {
        completeLogin(data);
        return;
      }

      if (res?.status === 200 && (data?.otp_required === true || data?.email)) {
        setOtpRequired(true);
        setOtpCode("");
        setCooldownUntil(Date.now() + 60000);
        toast.success("Ti abbiamo inviato un codice di accesso via email.");
        return;
      }

      toast.error(data?.detail || "Impossibile richiedere il codice");
    } catch (err) {
      if (err?.response?.status === 400 && err?.response?.data?.detail === "Password richiesta") {
        setShowPassword(true);
        toast.error("Password richiesta per accesso admin. Inseriscila e riprova.");
        return;
      }

      toast.error(err?.response?.data?.detail || "Impossibile richiedere il codice");
    } finally {
      setBusy(false);
    }
  };

  const resendOtp = async () => {
    if (cooldownSeconds > 0) return;
    setBusy(true);
    try {
      const res = await api.post("/auth/login", { email: normalizedEmail });
      const data = res?.data ?? {};
      if (res?.status === 200 && (data?.otp_required === true || data?.email)) {
        setOtpCode("");
        setCooldownUntil(Date.now() + 60000);
        toast.success("Abbiamo inviato un nuovo codice via email.");
        return;
      }
      toast.error(data?.detail || "Impossibile richiedere un nuovo codice");
    } catch (err) {
      const detail = err?.response?.data?.detail || "Impossibile richiedere un nuovo codice";
      toast.error(detail);
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
      const detail = err?.response?.data?.detail || "Codice non valido o scaduto";
      if (detail === "Riprova più tardi.") {
        toast.error("Troppi tentativi. Riprova più tardi.");
      } else {
        toast.error(detail);
      }
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
      <AuthShell title="Controlla la tua email" subtitle={`Abbiamo inviato un codice a ${normalizedEmail}`}>
        <form onSubmit={handleVerifyOtp} className="space-y-4">
          <div>
            <label className="overline block mb-2">Inserisci il codice di accesso</label>
            <input
              type="text" inputMode="numeric" autoFocus required value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              className="input-base" placeholder="123456" maxLength={6}
            />
          </div>
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? "Verifica in corso..." : "Verifica e accedi"}
          </button>
          <div className="pt-4 text-center space-y-2">
            <button
              type="button"
              disabled={busy || cooldownSeconds > 0}
              onClick={resendOtp}
              className="text-sm text-ink hover:underline font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {cooldownSeconds > 0 ? `Rinvia codice tra ${cooldownSeconds}s` : "Non hai ricevuto il codice? Rinviamelo"}
            </button>
            <div>
              <button
                type="button" onClick={() => { setOtpRequired(false); setOtpCode(""); }}
                className="text-sm text-ink hover:underline font-medium"
              >
                Torna indietro
              </button>
            </div>
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
        <form onSubmit={handleRequestOtp} className="space-y-4">
          <div>
            <label className="overline block mb-2">Email</label>
            <input
              type="email" required value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setPassword("");
                setShowPassword(false);
              }}
              className="input-base" placeholder="tu@esempio.com"
            />
          </div>

          {showPassword && (
            <div>
              <label className="overline block mb-2">Password</label>
              <input
                type="password" required value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-base" placeholder="********"
              />
            </div>
          )}

          {!showPassword && (
            <button
              type="button"
              onClick={() => setShowPassword(true)}
              className="text-sm text-ink hover:underline font-medium"
            >
              Accedi con password
            </button>
          )}

          <button
            type="submit"
            disabled={busy || cooldownSeconds > 0}
            className="btn-primary w-full disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {busy ? "Invio in corso..." : cooldownSeconds > 0 ? `Attendi ${cooldownSeconds}s...` : "Richiedi codice"}
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
