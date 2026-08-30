import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import AuthShell from "@/components/AuthShell";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { loginWithToken } = useAuth();
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post("/auth/reset", { token, password });
      loginWithToken(r.data.token, r.data.user);
      toast.success("Password aggiornata");
      navigate("/", { replace: true });
    } catch (e) {
      toast.error(e.response?.data?.detail || "Errore");
    } finally { setBusy(false); }
  };
  if (!token) {
    return <AuthShell title="Link non valido" testId="reset-invalid"><Link to="/forgot" className="underline">Richiedi un nuovo link</Link></AuthShell>;
  }
  return (
    <AuthShell title="Nuova password" subtitle="Imposta la nuova password per il tuo account." testId="reset-page">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="overline block mb-2">Nuova password</label>
          <input data-testid="reset-password-input" type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} className="input-base" placeholder="••••••••" />
        </div>
        <button type="submit" disabled={busy} className="btn-primary w-full disabled:opacity-50" data-testid="reset-submit-btn">
          {busy ? "Aggiornamento…" : "Aggiorna password"}
        </button>
      </form>
    </AuthShell>
  );
}
