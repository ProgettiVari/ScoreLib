import React from "react";
import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";

export default function SupportThanks() {
  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center px-6 py-12">
      <div className="bg-card border border-rule rounded-md max-w-lg w-full p-8 text-center shadow-[0_10px_0_0_rgba(0,0,0,0.08)]">
        <div className="mb-4 flex justify-center">
          <div className="rounded-full bg-emerald-100 text-emerald-700 p-3 dark:bg-emerald-500/20 dark:text-emerald-300">
            <CheckCircle2 size={28} />
          </div>
        </div>
        <p className="overline mb-3">SUPPORTO</p>
        <h1 className="font-display text-3xl font-black tracking-tight mb-3">Grazie per il caffè ☕</h1>
        <p className="text-muted2 leading-relaxed mb-6">
          Il pagamento è stato ricevuto. Il tuo sostegno aiuta a tenere attivo Scorelib e a migliorare i servizi per la comunità.
        </p>
        <Link to="/" className="btn-primary">Torna alla home</Link>
      </div>
    </div>
  );
}
