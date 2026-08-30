import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import api from "@/lib/api";
import AuthShell from "@/components/AuthShell";

export default function ResendVerification() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post("/auth/resend-verification", { email });
      toast.success(r.data.message);
    } catch (e) {
      const msg = e.response?.data?.detail || "Errore";
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Verifica email" subtitle="Ricevi un link per verificare il tuo account">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="overline block mb-2">Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input-base"
            placeholder="tu@esempio.com"
          />
        </div>
        <button type="submit" disabled={busy} className="btn-primary w-full disabled:opacity-50">
          {busy ? "Invio…" : "Invia email"}
        </button>
      </form>
      <div className="mt-6 text-sm text-muted2">
        Hai già verificato? <Link to="/login" className="underline hover:text-ink">Accedi</Link>
      </div>
    </AuthShell>
  );
}