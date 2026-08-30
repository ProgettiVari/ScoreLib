import React from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { Search, Library, Share2, LogOut, Settings as SettingsIcon, ScrollText, Shield } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import TrebleClef from "@/components/TrebleClef";

export default function Header() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;

  const isAdmin = user.is_admin;
  const navItems = [
    { to: "/", label: "Cerca", icon: Search, end: true },
    { to: "/library", label: "Libreria", icon: Library },
    { to: "/shared", label: "Condivise", icon: Share2 },
    { to: "/settings", label: "Impostazioni", icon: SettingsIcon },
  ];
  if (isAdmin) {
    navItems.push(
      { to: "/admin", label: "Admin", icon: Shield },
      { to: "/logs", label: "Log", icon: ScrollText },
    );
  }

  const desktopCls = ({ isActive }) =>
    `inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-sm transition-colors ${
      isActive ? "bg-canvas3 text-ink" : "text-muted2 hover:text-ink"
    }`;
  const mobileCls = ({ isActive }) =>
    `flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2 text-[11px] font-medium transition-colors ${
      isActive ? "text-ink" : "text-muted2"
    }`;
  const topBarStyle = { paddingTop: "env(safe-area-inset-top, 0px)" };
  const bottomNavStyle = { paddingBottom: "env(safe-area-inset-bottom, 0px)" };
  const bottomSpacerStyle = { height: "calc(4rem + env(safe-area-inset-bottom, 0px))" };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <>
      <header className="sticky top-0 z-40 bg-card border-b border-rule" style={topBarStyle}>
        <div className="max-w-7xl mx-auto px-4 md:px-12 py-3 flex items-center justify-between gap-2">
          <Link to="/" className="flex items-center gap-2.5 shrink-0">
            <TrebleClef size={26} />
            <span className="font-display font-bold text-lg tracking-tight">Scorelib</span>
          </Link>

          <nav className="hidden md:flex items-center gap-0.5">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} className={desktopCls}>
                <Icon size={16} strokeWidth={1.75} /> <span>{label}</span>
              </NavLink>
            ))}
            <div className="flex items-center gap-2 ml-3 pl-3 border-l border-rule">
              <div className="flex flex-col items-end mr-2">
                <span className="text-xs font-bold leading-none">{user.name || "Utente Gruppo"}</span>
                <span className="text-[9px] text-muted3 font-mono uppercase tracking-tighter">{isAdmin ? "Admin" : "Membro"}</span>
              </div>
              <button onClick={handleLogout} className="btn-ghost" title="Logout">
                <LogOut size={16} strokeWidth={1.75} />
              </button>
            </div>
          </nav>

          <button onClick={handleLogout} className="btn-ghost md:hidden px-2" title="Logout">
            <LogOut size={18} strokeWidth={1.75} />
          </button>
        </div>
      </header>

      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-card border-t border-rule grid grid-flow-col auto-cols-fr" style={bottomNavStyle}>
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={mobileCls}>
            <Icon size={18} strokeWidth={1.75} />
            <span className="truncate max-w-full">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="md:hidden h-16" aria-hidden="true" style={bottomSpacerStyle} />
    </>
  );
}
