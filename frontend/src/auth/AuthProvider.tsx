import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, onUnauthorized, setTokenProvider } from "../api";

/** Firebase config comes from Vite env; when absent, auth is disabled and the app is fully open. */
const env = import.meta.env as Record<string, string | undefined>;
const firebaseConfig = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  appId: env.VITE_FIREBASE_APP_ID,
  messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID,
};
export const FIREBASE_CONFIGURED = Boolean(firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.appId);

export interface AuthUser {
  uid: string;
  name: string | null;
  email: string | null;
  photoURL: string | null;
}

interface AuthState {
  /** True when sign-in is required/offered at all (Firebase configured). */
  enabled: boolean;
  /** Still resolving the initial auth state. */
  loading: boolean;
  user: AuthUser | null;
  /** Guest = auth enabled, not signed in, chose "Explore the demo". */
  guest: boolean;
  /** Can the current visitor start runs / upload / patch? */
  canWrite: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  continueAsGuest: () => void;
  /** Show the friendly sign-in prompt (e.g. after a write action as guest or a 401). */
  promptSignIn: (reason?: string) => void;
  dismissPrompt: () => void;
  promptOpen: boolean;
  promptReason: string | null;
  authError: string | null;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

type FbAuth = typeof import("firebase/auth");

export function AuthProvider({ children }: { children: ReactNode }) {
  const [serverEnabled, setServerEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(FIREBASE_CONFIGURED);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [guest, setGuest] = useState(() => sessionStorage.getItem("policyc.guest") === "1");
  const [promptOpen, setPromptOpen] = useState(false);
  const [promptReason, setPromptReason] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [fb, setFb] = useState<{ mod: FbAuth; auth: import("firebase/auth").Auth } | null>(null);

  // Ask the backend whether it enforces auth (works for both local dev and the HF Space).
  useEffect(() => {
    if (!FIREBASE_CONFIGURED) return; // auth is off locally: skip the probe entirely
    api.me().then((m) => setServerEnabled(m.auth_enabled)).catch(() => setServerEnabled(false));
  }, []);

  useEffect(() => {
    if (!FIREBASE_CONFIGURED) return;
    let unsub: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const [{ initializeApp }, mod] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
      if (cancelled) return;
      const app = initializeApp(firebaseConfig);
      const auth = mod.getAuth(app);
      setFb({ mod, auth });
      setTokenProvider(async () => (auth.currentUser ? auth.currentUser.getIdToken() : null));
      unsub = mod.onAuthStateChanged(auth, (u) => {
        setUser(u ? { uid: u.uid, name: u.displayName, email: u.email, photoURL: u.photoURL } : null);
        setLoading(false);
      });
    })().catch((e) => {
      setAuthError(String(e));
      setLoading(false);
    });
    return () => {
      cancelled = true;
      unsub?.();
      setTokenProvider(null);
    };
  }, []);

  const promptSignIn = useCallback((reason?: string) => {
    setPromptReason(reason ?? null);
    setPromptOpen(true);
  }, []);

  useEffect(() => onUnauthorized((msg) => promptSignIn(msg || "Sign in required")), [promptSignIn]);

  const signIn = useCallback(async () => {
    setAuthError(null);
    if (!fb) return;
    try {
      await fb.mod.signInWithPopup(fb.auth, new fb.mod.GoogleAuthProvider());
      sessionStorage.removeItem("policyc.guest");
      setGuest(false);
      setPromptOpen(false);
    } catch (e) {
      const code = (e as { code?: string }).code;
      if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
        setAuthError(e instanceof Error ? e.message : "Sign-in failed");
      }
    }
  }, [fb]);

  const signOut = useCallback(async () => {
    if (fb) await fb.mod.signOut(fb.auth);
    sessionStorage.removeItem("policyc.guest");
    setGuest(false);
  }, [fb]);

  const continueAsGuest = useCallback(() => {
    sessionStorage.setItem("policyc.guest", "1");
    setGuest(true);
  }, []);

  const enabled = FIREBASE_CONFIGURED && serverEnabled !== false;

  const value = useMemo<AuthState>(
    () => ({
      enabled,
      loading: enabled && loading,
      user,
      guest: enabled && !user && guest,
      canWrite: !enabled || !!user,
      signIn,
      signOut,
      continueAsGuest,
      promptSignIn,
      dismissPrompt: () => setPromptOpen(false),
      promptOpen,
      promptReason,
      authError,
    }),
    [enabled, loading, user, guest, signIn, signOut, continueAsGuest, promptSignIn, promptOpen, promptReason, authError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Wrap a write action: guests (auth enabled, not signed in) get the friendly prompt instead of a 401. */
export function useWriteGuard() {
  const { canWrite, promptSignIn } = useAuth();
  return useCallback(
    (action: () => void, reason = "Sign in to run your own SOPs") => {
      if (canWrite) action();
      else promptSignIn(reason);
    },
    [canWrite, promptSignIn],
  );
}
