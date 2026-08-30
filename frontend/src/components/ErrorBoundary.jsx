import React from "react";
import api from "@/lib/api";

function reportClientError(error, info = {}) {
  try {
    api.post("/logs/client-error", {
      message: String(error?.message || error),
      stack: String(error?.stack || ""),
      component_stack: String(info?.componentStack || ""),
      url: window.location.href,
    }).catch(() => {});
  } catch (_) {
    // best effort only
  }
}

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidMount() {
    window.addEventListener("error", this.onWindowError);
    window.addEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  componentWillUnmount() {
    window.removeEventListener("error", this.onWindowError);
    window.removeEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  onWindowError = (event) => {
    const error = event.error || new Error(event.message || "Errore frontend");
    reportClientError(error);
  };

  onUnhandledRejection = (event) => {
    const error = event.reason instanceof Error ? event.reason : new Error(String(event.reason || "Promise rifiutata"));
    reportClientError(error);
  };

  componentDidCatch(error, info) {
    reportClientError(error, info);
    console.error("UI Error:", error, info);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-canvas" data-testid="error-boundary">
                <div className="max-w-md w-full border border-rule rounded-md p-6 bg-card">
            <p className="overline mb-2">ERRORE INTERFACCIA</p>
            <h1 className="font-display font-black text-3xl tracking-tighter mb-2">Qualcosa e andato storto.</h1>
                    <p className="text-muted2 text-sm mb-4">L'errore e stato registrato nei log. Puoi riprovare oppure ricaricare la pagina.</p>
            <pre className="text-mono text-xs text-red-600 bg-red-50 border border-red-200 rounded-sm p-2 max-h-32 overflow-auto whitespace-pre-wrap mb-4">{String(this.state.error?.message || this.state.error)}</pre>
            <div className="flex gap-2">
              <button onClick={this.reset} className="btn-primary !py-2 text-sm" data-testid="error-retry-btn">Riprova</button>
              <button onClick={() => window.location.reload()} className="btn-ghost border border-rule rounded-sm px-4 py-2 text-sm" data-testid="error-reload-btn">Ricarica</button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
