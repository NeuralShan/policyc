import { useEffect, useRef, useState } from "react";

import { Icon, Logo } from "../components/icons";
import { Button, Dialog } from "../components/ui";
import { useAuth } from "./AuthProvider";

function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z" />
      <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

export function GoogleButton({ label = "Continue with Google" }: { label?: string }) {
  const { signIn } = useAuth();
  return (
    <button
      onClick={() => void signIn()}
      className="inline-flex items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-800 shadow-sm transition-all hover:bg-slate-50 hover:shadow active:scale-[0.98]"
    >
      <GoogleG />
      {label}
    </button>
  );
}

/** Full-page gate shown when auth is enabled and the visitor is neither signed in nor a guest. */
export function SignInScreen() {
  const { continueAsGuest, authError } = useAuth();
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center px-6 py-20 text-center animate-fade-in">
      <Logo size={56} />
      <h1 className="mt-6 text-3xl font-bold tracking-tight text-slate-900">PolicyC</h1>
      <p className="mt-3 text-lg text-slate-700">
        Software gets compiled and tested before it ships. The procedures that are running behind banks, factories and hospitals never do.{" "}
        <span className="font-semibold text-indigo-700">PolicyC compiles them.</span>
      </p>
      <div className="mt-8 flex flex-col items-center gap-3">
        <GoogleButton />
        <Button variant="ghost" onClick={continueAsGuest}>
          Explore the demo as guest
        </Button>
        {authError && (
          <p role="alert" className="max-w-sm text-sm text-red-700">
            {authError}
          </p>
        )}
      </div>
      <p className="mt-8 max-w-sm text-xs text-slate-500">
        Guests can open the sample projects read-only. Sign in to upload and compile your own SOPs.
      </p>
    </div>
  );
}

/** Friendly dialog for write actions as a guest and for 401 responses. */
export function SignInPrompt() {
  const { promptOpen, dismissPrompt, promptReason, enabled } = useAuth();
  const { authError } = useAuth();
  if (!enabled) return null;
  return (
    <Dialog open={promptOpen} onClose={dismissPrompt} title="Sign in to continue">
      <div className="space-y-4 text-sm text-slate-700">
        <p>
          {promptReason && promptReason !== "Sign in required" ? promptReason : "This action needs a signed-in account."}{" "}
          Guests can explore the demo projects, but compiling your own procedures needs a Google account.
        </p>
        <div className="flex justify-center py-1">
          <GoogleButton />
        </div>
        {authError && <p className="text-red-700">{authError}</p>}
      </div>
    </Dialog>
  );
}

export function UserMenu() {
  const { enabled, user, guest, signOut, signIn } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  if (!enabled) return null;
  if (!user) {
    return guest ? (
      <Button size="sm" variant="secondary" onClick={() => void signIn()}>
        Sign in
      </Button>
    ) : null;
  }
  const initials = (user.name ?? user.email ?? "?").slice(0, 1).toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.name ?? user.email ?? "user"}`}
        className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700 ring-2 ring-white hover:ring-indigo-200"
      >
        {user.photoURL ? <img src={user.photoURL} alt="" referrerPolicy="no-referrer" className="h-full w-full object-cover" /> : initials}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-11 z-50 w-64 animate-pop rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
          <div className="border-b border-slate-100 px-3 pb-2 pt-1">
            <p className="truncate text-sm font-semibold text-slate-900">{user.name ?? "Signed in"}</p>
            <p className="truncate text-xs text-slate-500">{user.email}</p>
          </div>
          <button
            role="menuitem"
            onClick={() => void signOut()}
            className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
          >
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
