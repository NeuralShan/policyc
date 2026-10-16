import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router";

import { cx } from "./ui";

const navItems = [
  { to: "/", label: "Projects", end: true },
  { to: "/gap-codes", label: "Gap codes", end: false },
];

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-3">
          <NavLink to="/" className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-bold text-slate-900">policyc</span>
            <span className="text-sm text-slate-500">Policy Compiler</span>
          </NavLink>
          <nav className="flex gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cx(
                    "rounded-md px-3 py-1.5 text-sm",
                    isActive ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
