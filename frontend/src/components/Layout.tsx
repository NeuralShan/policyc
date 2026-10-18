import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { useAuth } from "../auth/AuthProvider";
import { SignInPrompt, SignInScreen, UserMenu } from "../auth/AuthUI";
import { useTheme } from "../lib/theme";
import { CommandPalette } from "./CommandPalette";
import { Icon, Logo } from "./icons";
import { Kbd, ToastProvider, cx } from "./ui";

const navItems = [
  { to: "/", label: "Home", end: true },
  { to: "/projects", label: "Projects", end: false },
  { to: "/gap-codes", label: "Gap codes", end: false },
  { to: "/about", label: "How it works", end: false },
];

/** Pages rendered inside a workspace tab hide their own page header and chrome. */
export const EmbeddedContext = createContext(false);
export const useEmbedded = () => useContext(EmbeddedContext);

export function ThemeToggle() {
  const { mode, cycle } = useTheme();
  const label = mode === "light" ? "Light" : mode === "dark" ? "Dark" : "System";
  return (
    <button
      onClick={cycle}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      aria-label={`Theme: ${label}. Click to change.`}
      title={`Theme: ${label}`}
    >
      <Icon name={mode === "light" ? "sun" : mode === "dark" ? "moon" : "monitor"} size={18} />
    </button>
  );
}

export function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const auth = useAuth();
  const mainRef = useRef<HTMLElement>(null);
  const isWorkspace = /^\/runs\/[^/]+\/?$/.test(location.pathname);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);

  const gated = auth.enabled && !auth.user && !auth.guest;

  return (
    <ToastProvider>
      <div className="flex min-h-screen flex-col">
        <a
          href="#main"
          className="sr-only z-[200] rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-40 border-b border-slate-200 glass">
          <div className="mx-auto flex h-14 max-w-[1800px] items-center gap-3 px-3 sm:px-5">
            <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label="PolicyC home">
              <Logo />
              <span className="text-[15px] font-bold tracking-tight text-slate-900">
                Policy<span className="text-indigo-600 dark:text-indigo-400">C</span>
              </span>
            </Link>
            <nav aria-label="Primary" className="ml-4 hidden gap-0.5 md:flex">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cx(
                      "rounded-lg px-3 py-1.5 text-sm transition-colors",
                      isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-1.5">
              <button
                onClick={() => setPaletteOpen(true)}
                className="hidden h-9 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 text-sm text-slate-500 hover:border-slate-300 hover:text-slate-700 sm:inline-flex"
                aria-label="Open quick navigation"
              >
                <Icon name="search" size={14} />
                <span>Quick nav</span>
                <span className="flex gap-0.5">
                  <Kbd>Ctrl</Kbd>
                  <Kbd>K</Kbd>
                </span>
              </button>
              <button
                onClick={() => setPaletteOpen(true)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 sm:hidden"
                aria-label="Open quick navigation"
              >
                <Icon name="search" size={18} />
              </button>
              <ThemeToggle />
              <UserMenu />
              <button
                onClick={() => setMenuOpen((o) => !o)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 md:hidden"
                aria-label="Menu"
                aria-expanded={menuOpen}
              >
                <Icon name={menuOpen ? "x" : "menu"} size={18} />
              </button>
            </div>
          </div>
          {menuOpen && (
            <nav aria-label="Mobile" className="border-t border-slate-200 bg-white px-3 py-2 md:hidden">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cx("block rounded-lg px-3 py-2 text-sm", isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-700")
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          )}
        </header>
        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className={cx(
            "min-w-0 flex-1 outline-none",
            isWorkspace ? "flex flex-col" : "mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8",
          )}
        >
          {auth.loading ? <div className="p-10 text-center text-sm text-slate-500">Loading...</div> : gated ? <SignInScreen /> : <Outlet />}
        </main>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <SignInPrompt />
      </div>
    </ToastProvider>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  const embedded = useEmbedded();
  if (embedded) {
    return actions ? <div className="mb-3 flex flex-wrap items-center justify-end gap-2">{actions}</div> : null;
  }
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="break-words text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
