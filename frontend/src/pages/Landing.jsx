import React from "react";
import { Link } from "react-router-dom";
import { Search, UploadCloud, Share2, BookOpen } from "lucide-react";
import TrebleClef from "@/components/TrebleClef";

const FEATURES = [
  {
    icon: Search,
    title: "Ricerca full-text",
    text: "Trova qualsiasi spartito cercando per titolo, testo o accordi, anche dentro il PDF.",
  },
  {
    icon: UploadCloud,
    title: "Libreria organizzata",
    text: "Carica i tuoi PDF, aggiungi tag e tieni tutto in ordine in un'unica libreria condivisa.",
  },
  {
    icon: Share2,
    title: "Condivisione",
    text: "Condividi intere librerie o singoli spartiti con un link, anche con chi non ha un account.",
  },
  {
    icon: BookOpen,
    title: "Lettore integrato",
    text: "Apri gli spartiti direttamente nel browser, con evidenziazione dei risultati di ricerca.",
  },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="max-w-6xl mx-auto px-6 md:px-12 py-6 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <TrebleClef size={28} />
          <span className="font-display font-bold text-xl tracking-tight">Scorelib</span>
        </div>
        <Link to="/login" className="btn-ghost">Accedi</Link>
      </header>

      <main className="max-w-4xl mx-auto px-6 md:px-12 pt-10 pb-24 text-center">
        <p className="overline mb-6">GESTIONE SPARTITI PDF</p>
        <h1 className="font-display font-black text-5xl sm:text-6xl lg:text-7xl leading-[0.95] tracking-tighter mb-6">
          Tutti i tuoi spartiti.<br />Un solo posto.
        </h1>
        <p className="text-muted2 text-lg max-w-xl mx-auto mb-10">
          Carica, organizza e trova ogni spartito in pochi secondi. Ricerca full-text, tag, condivisione e lettore integrato: tutto in Scorelib.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link to="/login" className="btn-primary">Accedi</Link>
        </div>
      </main>

      <section className="border-t border-rule">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-16 grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title}>
              <Icon size={22} className="mb-4 text-ink" strokeWidth={1.75} />
              <h3 className="font-display font-bold text-lg mb-2">{title}</h3>
              <p className="text-muted2 text-sm leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-rule">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-8 text-mono text-xs text-muted2 text-center">
          © {new Date().getFullYear()} Scorelib
        </div>
      </footer>
    </div>
  );
}
