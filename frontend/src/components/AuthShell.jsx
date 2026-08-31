import React from "react";
import { Link } from "react-router-dom";
import TrebleClef from "@/components/TrebleClef";

export default function AuthShell({ title, subtitle, children, footer, testId }) {
  return (
    <div className="min-h-screen grid md:grid-cols-2 bg-canvas">
      <aside className="hidden md:flex relative bg-canvas2 text-ink overflow-hidden border-r border-rule">
        <div className="relative z-10 flex flex-col justify-between p-12 w-full">
          <Link to="/" className="flex items-center gap-2.5" data-testid="auth-brand">
            <TrebleClef size={28} />
            <span className="font-display font-bold text-xl tracking-tight">Scorelib</span>
          </Link>
          <div>
            <h2 className="font-display font-black text-5xl leading-[0.95] tracking-tighter mb-4">
              La tua libreria<br />di spartiti.<br />Sempre con te.
            </h2>
            <p className="overline">UPLOAD - INDICIZZA - SUONA</p>
          </div>
          <div className="text-mono text-xs text-muted2">(c) {new Date().getFullYear()} Scorelib</div>
        </div>
      </aside>
      <main className="flex items-center justify-center p-6 md:p-16">
        <div className="w-full max-w-md" data-testid={testId}>
          <div className="md:hidden mb-6"><TrebleClef size={36} /></div>
          <h1 className="font-display font-black text-4xl tracking-tighter mb-2">{title}</h1>
          {subtitle && <p className="text-muted2 mb-8">{subtitle}</p>}
          {children}
          {footer && <div className="mt-8 text-sm text-muted2">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
