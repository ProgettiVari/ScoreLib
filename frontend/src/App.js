import React, { useEffect, useRef, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { Toaster } from "sonner";

import api from "@/lib/api";
import { getGoogleRedirectUri } from "@/lib/google";

import { AuthProvider, useAuth } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Header from "@/components/Header";

import Login from "@/pages/Login";
import Home from "@/pages/Home";
import Library from "@/pages/Library";
import SharedView from "@/pages/SharedView";
import PdfViewer from "@/pages/PdfViewer";
import Settings from "@/pages/Settings";
import Shared from "@/pages/Shared";
import SharedLibraryDetail from "@/pages/SharedLibraryDetail";
import AdminLogs from "@/pages/AdminLogs";
import Admin from "@/pages/Admin";
import { shouldHideAppChrome } from "@/viewer/viewerChrome";

function GoogleOAuthReturn() {
  const navigate = useNavigate();
  const location = useLocation();
  const processed = useRef(false);
  const [status, setStatus] = useState("Connessione a Google in corso...");

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const error = params.get("error");
    const mode = sessionStorage.getItem("google_oauth_mode");
    sessionStorage.removeItem("google_oauth_mode");

    if (error) {
      setStatus(`Errore Google: ${error}`);
      setTimeout(() => navigate("/login", { replace: true }), 2000);
      return;
    }

    if (!code) {
      setStatus("Codice di autorizzazione mancante. Reindirizzo al login...");
      setTimeout(() => navigate("/login", { replace: true }), 2000);
      return;
    }

    if (!mode) {
      setStatus("Modalità OAuth non riconosciuta. Reindirizzo al login...");
      setTimeout(() => navigate("/login", { replace: true }), 2000);
      return;
    }

    (async () => {
      try {
        const redirect_uri = getGoogleRedirectUri();

        // Solo la modalità "master" è supportata per la connessione Drive dell'admin
        if (mode === "master") {
          await api.post("/admin/master-drive/connect", {
            code,
            redirect_uri,
          });
          navigate("/admin", { replace: true });
          return;
        }

        // Login Google rimosso per gli utenti normali
        navigate("/login", { replace: true });
      } catch (e) {
        setStatus("Errore Google");
        setTimeout(() => navigate("/login", { replace: true }), 2000);
      }
    })();
  }, [location.search, navigate]);

  return <div>{status}</div>;
}

function ChromeWrapper({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  const noChrome = shouldHideAppChrome(location.pathname);

  return (
    <>
      {user && !noChrome && <Header />}
      {children}
    </>
  );
}

function AppShell() {
  const location = useLocation();

  const params = new URLSearchParams(location.search);
  if (params.get("code") || params.get("error")) {
    return <GoogleOAuthReturn />;
  }

  return (
    <ChromeWrapper>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<ProtectedRoute><Home /></ProtectedRoute>} />
        <Route path="/library" element={<ProtectedRoute><Library /></ProtectedRoute>} />
        <Route path="/shared" element={<ProtectedRoute><Shared /></ProtectedRoute>} />
        <Route path="/libraries/:id" element={<ProtectedRoute><SharedLibraryDetail /></ProtectedRoute>} />
        <Route path="/shared/:token" element={<SharedView />} />
        <Route path="/viewer/:id" element={<PdfViewer />} />
        <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
        <Route path="/logs" element={<ProtectedRoute><AdminLogs /></ProtectedRoute>} />
        <Route path="/admin" element={<ProtectedRoute><Admin /></ProtectedRoute>} />
      </Routes>
    </ChromeWrapper>
  );
}

function applyThemeSetting(theme) {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
    root.style.colorScheme = "dark";
  } else if (theme === "light") {
    root.classList.remove("dark");
    root.style.colorScheme = "light";
  } else {
    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.classList.toggle("dark", isDark);
    root.style.colorScheme = isDark ? "dark" : "light";
  }
}

function resolveInitialTheme() {
  const stored = localStorage.getItem("theme");
  if (stored && ["light", "dark", "system"].includes(stored)) {
    return stored;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  useEffect(() => {
    const initialTheme = resolveInitialTheme();
    applyThemeSetting(initialTheme);

    const onThemeChange = () => {
      const stored = localStorage.getItem("theme");
      const nextTheme = stored && ["light", "dark", "system"].includes(stored)
        ? stored
        : resolveInitialTheme();
      applyThemeSetting(nextTheme);
    };

    window.addEventListener("theme-change", onThemeChange);
    return () => window.removeEventListener("theme-change", onThemeChange);
  }, []);

  return (
    <AuthProvider>
      <BrowserRouter>
        <AppShell />
        <Toaster />
      </BrowserRouter>
    </AuthProvider>
  );
}
