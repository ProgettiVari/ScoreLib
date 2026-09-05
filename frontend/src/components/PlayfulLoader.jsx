import React, { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

const DEFAULT_MESSAGES = [
  "Sto cercando il tempo giusto...",
  "Le note stanno prendendo posto.",
  "Un piccolo assolo di pazienza.",
  "Controllo che nessuna battuta sia rimasta indietro.",
  "La scansione sta leggendo tra le righe.",
  "Accordo dopo accordo, ci siamo quasi.",
  "Il pentagramma è quasi pronto.",
  "Faccio un ultimo giro sulle pagine.",
  "Le pause sono importanti, anche per i PDF.",
  "Sto lucidando l'indice della libreria.",
  "Cerco il ritornello giusto.",
  "Quasi al finale, senza accelerare troppo.",
];

export default function PlayfulLoader({ messages = DEFAULT_MESSAGES, className = "" }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % messages.length);
    }, 3500);
    return () => window.clearInterval(timer);
  }, [messages.length]);

  return (
    <div className={`flex items-center justify-center gap-3 ${className}`} aria-live="polite">
      <LoaderCircle size={16} className="shrink-0 animate-spin text-ink" aria-hidden="true" />
      <span key={index} className="animate-fade-in text-muted2">{messages[index]}</span>
    </div>
  );
}
