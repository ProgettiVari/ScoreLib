import React, { useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, X } from "lucide-react";

const AMAZON_GIFT_CARD_URL = "https://www.amazon.it/b?node=3557017031";

export default function CoffeeSupportModal({ open, onClose, email, loading }) {
  const closeButtonRef = useRef(null);
  const emailInputRef = useRef(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    closeButtonRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) setCopied(false);
  }, [open]);

  if (!open) return null;

  const copyEmail = async () => {
    if (!email) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(email);
    } catch (error) {
      emailInputRef.current?.focus();
      emailInputRef.current?.select();
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay/80 p-4 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      data-testid="coffee-support-modal"
    >
      <div
        className="w-full max-w-md rounded-md border-2 border-ink bg-canvas p-6 shadow-[0_10px_0_0_rgba(0,0,0,0.18)] animate-result-in"
        role="dialog"
        aria-modal="true"
        aria-labelledby="coffee-support-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="overline mb-2">UN PICCOLO GESTO</p>
            <h2 id="coffee-support-title" className="font-display text-2xl font-bold tracking-tight">
              Offrimi un caffè
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="btn-ghost shrink-0"
            aria-label="Chiudi"
          >
            <X size={18} />
          </button>
        </div>

        <p className="mb-5 leading-relaxed text-muted2">
          Se Scorelib ti è utile, puoi mandarmi un buono regalo Amazon digitale. Grazie davvero.
        </p>

        <div className="mb-5 border-y border-rule py-4">
          <p className="mb-2 text-sm text-muted2">Invialo a questo indirizzo:</p>
          {loading ? (
            <p className="text-sm text-muted3" aria-live="polite">Caricamento email...</p>
          ) : email ? (
            <div className="flex items-center gap-2">
              <input
                ref={emailInputRef}
                className="min-w-0 flex-1 border-b border-rule bg-transparent py-1 font-mono text-sm text-ink outline-none focus:border-ink"
                value={email}
                readOnly
                aria-label="Email di supporto"
              />
              <button
                type="button"
                onClick={copyEmail}
                className="btn-ghost shrink-0 gap-2"
                aria-label={copied ? "Email copiata" : "Copia email"}
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
                <span className="text-xs">{copied ? "Copiato!" : "Copia"}</span>
              </button>
            </div>
          ) : (
            <p className="text-sm text-muted2" aria-live="polite">Email di supporto non configurata.</p>
          )}
        </div>

        <ol className="mb-6 space-y-2 text-sm leading-relaxed text-muted2">
          <li><span className="font-mono text-ink">01</span> Copia l&apos;email qui sopra.</li>
          <li><span className="font-mono text-ink">02</span> Apri Amazon e scegli un buono regalo digitale.</li>
          <li><span className="font-mono text-ink">03</span> Invialo a quell&apos;indirizzo.</li>
        </ol>

        <a
          href={AMAZON_GIFT_CARD_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="btn-primary w-full justify-center gap-2"
        >
          Vai ai buoni regalo Amazon <ExternalLink size={15} />
        </a>
      </div>
    </div>
  );
}
