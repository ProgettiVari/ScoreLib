import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, UploadCloud, Share2, BookOpen, ArrowRight, Coffee, Moon, Sun } from "lucide-react";
import TrebleClef from "@/components/TrebleClef";
import { applyThemeSetting, resolveInitialTheme } from "@/lib/theme";
import api from "@/lib/api";
import CoffeeSupportModal from "@/components/CoffeeSupportModal";

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

const STEPS = [
  { n: "01", label: "UPLOAD", text: "Carica i PDF dei tuoi spartiti, anche in blocco." },
  { n: "02", label: "INDICIZZA", text: "Scorelib legge testo e accordi di ogni pagina." },
  { n: "03", label: "SUONA", text: "Trova il pezzo giusto in un istante e aprilo nel lettore." },
];

export default function Landing() {
  const [theme, setTheme] = useState(() => resolveInitialTheme());
  const [coffeeOpen, setCoffeeOpen] = useState(false);
  const [supportEmail, setSupportEmail] = useState(null);
  const [supportEmailLoading, setSupportEmailLoading] = useState(false);

  useEffect(() => {
    applyThemeSetting(theme);
    localStorage.setItem("theme", theme);
    window.dispatchEvent(new Event("theme-change"));
  }, [theme]);

  const handleCoffee = async () => {
    setCoffeeOpen(true);
    if (supportEmail !== null) return;
    setSupportEmailLoading(true);
    try {
      const { data } = await api.get("/support/info");
      setSupportEmail(data?.email || "");
    } catch (error) {
      setSupportEmail("");
    } finally {
      setSupportEmailLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-20 bg-canvas/90 backdrop-blur border-b border-rule">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-5 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <TrebleClef size={26} />
            <span className="font-display font-bold text-xl tracking-tight">Scorelib</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Cambia tema landing"
              onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
              className="relative inline-flex h-8 w-14 items-center rounded-full border border-rule bg-canvas2 p-1 transition-colors"
            >
              <Sun size={11} className="absolute left-2 text-muted2" aria-hidden="true" />
              <Moon size={11} className="absolute right-2 text-muted2" aria-hidden="true" />
              <span
                className={`inline-block h-6 w-6 rounded-full bg-ink text-white flex items-center justify-center transition-transform ${theme === "dark" ? "translate-x-6" : "translate-x-0"}`}
              >
                {theme === "dark" ? <Moon size={12} aria-hidden="true" /> : <Sun size={12} aria-hidden="true" />}
              </span>
            </button>
            <button type="button" onClick={handleCoffee} className="btn-ghost gap-2"><Coffee size={15} /> Offrimi un caffè</button>
            <Link to="/login" className="btn-ghost">Accedi</Link>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 md:px-12 pt-16 md:pt-24 pb-20 grid lg:grid-cols-2 gap-14 items-center">
        <div>
          <p className="overline mb-6">GESTIONE SPARTITI PDF</p>
          <h1 className="font-display font-black text-5xl sm:text-6xl leading-[0.95] tracking-tighter mb-6">
            Tutti i tuoi<br />spartiti.<br />Un solo posto.
          </h1>
          <p className="text-muted2 text-lg max-w-md mb-10 leading-relaxed">
            Carica, organizza e trova ogni spartito in pochi secondi. Ricerca full-text, tag, condivisione e lettore integrato.
          </p>
          <div className="flex items-center gap-4">
            <Link to="/login" className="btn-primary">
              Accedi <ArrowRight size={16} />
            </Link>
            <span className="text-sm text-muted2">Non hai un account? <Link to="/login" className="text-ink underline underline-offset-4">Richiedilo</Link></span>
          </div>
        </div>

        <div className="relative">
          <div className="hidden md:block absolute -z-10 right-[-1.5rem] bottom-[-1.5rem] w-full h-full rounded-md piano-bars opacity-[0.06]" />
          <div
            className="bg-card border-2 border-ink rounded-md overflow-hidden"
            style={{ boxShadow: "0 10px 0 0 rgba(0,0,0,0.18)" }}
          >
            <div className="flex items-center gap-3 px-5 py-4 border-b border-rule">
              <Search size={18} className="text-muted2 shrink-0" strokeWidth={1.75} />
              <span className="text-lg text-muted3 truncate">Nel cuore della notte...</span>
            </div>
            <ul>
              <li className="px-5 py-4 border-b border-rule">
                <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                  <span className="font-display font-semibold">
                    Nel cuore della <mark className="bg-highlight text-highlightFg px-1 rounded-sm">notte</mark>
                  </span>
                  <span className="text-mono text-[10px] px-2 py-0.5 bg-canvas3 rounded-sm text-muted2">PAG 2</span>
                </div>
                <p className="text-muted2 text-sm">
                  ...si accende una luce, resto sveglio nel cuore della{" "}
                  <mark className="bg-highlight text-highlightFg px-1 rounded-sm">notte</mark>...
                </p>
              </li>
              <li className="px-5 py-4">
                <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                  <span className="font-display font-semibold">
                    Canzone della <mark className="bg-highlight text-highlightFg px-1 rounded-sm">notte</mark>
                  </span>
                  <span className="text-mono text-[10px] px-2 py-0.5 bg-canvas3 rounded-sm text-muted2">PAG 1</span>
                </div>
                <p className="text-muted2 text-sm">Am · F · C · G, un giro semplice per la notte...</p>
              </li>
            </ul>
          </div>
        </div>
      </main>

      <div className="border-y border-rule bg-canvas2">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-4 text-center">
          <p className="overline">UPLOAD &nbsp;·&nbsp; INDICIZZA &nbsp;·&nbsp; SUONA</p>
        </div>
      </div>

      <section className="max-w-6xl mx-auto px-6 md:px-12 py-20">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div
              key={title}
              className="bg-card border-2 border-rule rounded-md p-6 transition-all duration-150 hover:border-ink hover:-translate-y-1 shadow-[0_3px_0_0_rgba(0,0,0,0.06)] hover:shadow-[0_6px_0_0_rgba(0,0,0,0.14)]"
            >
              <div className="w-10 h-10 flex items-center justify-center rounded-md bg-canvas3 mb-5">
                <Icon size={19} className="text-ink" strokeWidth={1.75} />
              </div>
              <h3 className="font-display font-bold text-lg mb-2">{title}</h3>
              <p className="text-muted2 text-sm leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-t border-rule">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-20">
          <h2 className="font-display font-black text-3xl sm:text-4xl tracking-tighter mb-12 text-center">
            Come funziona
          </h2>
          <div className="grid sm:grid-cols-3 gap-10">
            {STEPS.map(({ n, label, text }) => (
              <div key={n}>
                <span className="text-mono text-sm text-muted3">{n}</span>
                <h3 className="overline mt-2 mb-3 text-ink" style={{ letterSpacing: "0.04em" }}>{label}</h3>
                <p className="text-muted2 leading-relaxed">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-rule bg-canvas2">
        <div className="max-w-3xl mx-auto px-6 md:px-12 py-20 text-center">
          <h2 className="font-display font-black text-4xl sm:text-5xl tracking-tighter mb-4">
            Pronto a ritrovare<br />ogni spartito?
          </h2>
          <p className="text-muted2 mb-8">Accedi e inizia a cercare nella libreria in pochi secondi.</p>
          <Link to="/login" className="btn-primary">
            Accedi <ArrowRight size={16} />
          </Link>
        </div>
      </section>

      <footer className="border-t border-rule">
        <div className="max-w-6xl mx-auto px-6 md:px-12 py-8 flex items-center justify-between text-mono text-xs text-muted2">
          <span className="flex items-center gap-2">
            <TrebleClef size={16} /> Scorelib
          </span>
          <span>© {new Date().getFullYear()} Scorelib</span>
        </div>
      </footer>
      <CoffeeSupportModal
        open={coffeeOpen}
        onClose={() => setCoffeeOpen(false)}
        email={supportEmail}
        loading={supportEmailLoading}
      />
    </div>
  );
}
