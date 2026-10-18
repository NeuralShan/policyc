import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { api } from "../api";
import { Icon, type IconName } from "./icons";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

/* ---------------------------------------------------------------- Buttons */
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";

const buttonStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-indigo-600 text-white shadow-sm hover:bg-indigo-700 disabled:bg-slate-300 disabled:text-slate-500 dark:hover:bg-indigo-500",
  secondary: "border border-slate-300 bg-white text-slate-800 shadow-sm hover:bg-slate-100 disabled:text-slate-400",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  danger: "text-red-700 hover:bg-red-50 disabled:text-slate-400",
  success: "bg-emerald-600 text-white shadow-sm hover:bg-emerald-700 disabled:bg-slate-300 disabled:text-slate-500",
};

export function Button({
  variant = "primary",
  size = "md",
  icon,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" | "lg"; icon?: IconName }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100",
        size === "sm" ? "px-2.5 py-1 text-xs" : size === "lg" ? "px-5 py-2.5 text-base" : "px-3.5 py-1.5 text-sm",
        buttonStyles[variant],
        className,
      )}
      {...props}
    >
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Cards */
export function Card({
  title,
  actions,
  children,
  className,
  flush,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

/* ----------------------------------------------------------------- Badges */
const tones = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  blue: "bg-blue-50 text-blue-700 ring-blue-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
} as const;

export type Tone = keyof typeof tones;

export function Badge({
  tone = "slate",
  children,
  title,
  icon,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
  icon?: IconName;
}) {
  return (
    <span
      className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset", tones[tone])}
      title={title}
    >
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

const statusTones: Record<string, { tone: Tone; icon: IconName }> = {
  queued: { tone: "slate", icon: "clock" },
  pending: { tone: "slate", icon: "clock" },
  running: { tone: "indigo", icon: "refresh" },
  paused: { tone: "amber", icon: "pause2" },
  succeeded: { tone: "green", icon: "checkCircle" },
  completed: { tone: "green", icon: "checkCircle" },
  failed: { tone: "red", icon: "error" },
  skipped: { tone: "slate", icon: "chevronRight" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = statusTones[status] ?? { tone: "slate" as Tone, icon: "info" as IconName };
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {status}
    </Badge>
  );
}

export type Severity = "error" | "warning" | "info";
export const SEVERITY: Record<Severity, { label: string; tone: Tone; icon: IconName; text: string }> = {
  error: { label: "Error", tone: "red", icon: "error", text: "text-red-600 dark:text-red-400" },
  warning: { label: "Warning", tone: "amber", icon: "warning", text: "text-amber-600 dark:text-amber-400" },
  info: { label: "Info", tone: "blue", icon: "info", text: "text-blue-600 dark:text-blue-400" },
};

export function SeverityIcon({ severity, size = 16 }: { severity: Severity; size?: number }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <span className={s.text} title={s.label} role="img" aria-label={s.label}>
      <Icon name={s.icon} size={size} />
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? SEVERITY.info;
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

export function Mono({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={cx("break-all font-mono text-xs text-slate-600", className)} title={title}>
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex min-w-5 items-center justify-center rounded border border-slate-300 bg-slate-100 px-1 py-px font-mono text-[10px] font-medium text-slate-600">
      {children}
    </kbd>
  );
}

/* ------------------------------------------------- Taxonomy code + tooltip */
export function useTaxonomy() {
  const q = useQuery({ queryKey: ["taxonomy"], queryFn: api.taxonomy, staleTime: Infinity });
  return useMemo(() => new Map((q.data ?? []).map((g) => [g.code, g])), [q.data]);
}

export function CodeChip({ code, tone = "slate" }: { code: string; tone?: "slate" | "red" | "amber" | "indigo" }) {
  const taxonomy = useTaxonomy();
  const entry = taxonomy.get(code);
  const toneCls =
    tone === "red"
      ? "bg-red-50 text-red-700 ring-red-200"
      : tone === "amber"
        ? "bg-amber-50 text-amber-800 ring-amber-200"
        : tone === "indigo"
          ? "bg-indigo-50 text-indigo-700 ring-indigo-200"
          : "bg-slate-100 text-slate-700 ring-slate-200";
  const chip = (
    <span
      aria-label={entry ? `${code}: ${entry.title}` : undefined}
      className={cx(
        "inline-flex items-center rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-tight ring-1 ring-inset",
        toneCls,
      )}
    >
      {code}
    </span>
  );
  if (!entry) return chip;
  return (
    <Tooltip
      content={
        <span className="block max-w-64 whitespace-normal text-left">
          <span className="block font-semibold">{entry.title}</span>
          <span className="block opacity-80">
            {entry.category} - layer {entry.layer} - {entry.tier} check
          </span>
        </span>
      }
    >
      {chip}
    </Tooltip>
  );
}

/* ---------------------------------------------------------------- Tooltip */
export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
}) {
  const id = useId();
  return (
    <span className="group/tt relative inline-flex" aria-describedby={id}>
      {children}
      <span
        role="tooltip"
        id={id}
        className={cx(
          "pointer-events-none absolute left-1/2 z-50 w-max max-w-[80vw] -translate-x-1/2 rounded-md bg-slate-900 px-2 py-1 text-xs font-normal text-white opacity-0 shadow-lg transition-opacity duration-150 group-focus-within/tt:opacity-100 group-hover/tt:opacity-100 dark:bg-slate-200 dark:text-slate-900",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {content}
      </span>
    </span>
  );
}

/* ----------------------------------------------------------------- States */
export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
      <Icon name="error" className="mt-0.5 shrink-0" />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="shrink-0 font-medium underline underline-offset-2">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

type Illustration = "doc" | "check" | "search" | "flow" | "flask" | "chart";
export function EmptyState({
  title,
  children,
  action,
  art = "doc",
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  art?: Illustration;
}) {
  return (
    <div className="flex animate-fade-in flex-col items-center px-4 py-10 text-center">
      <EmptyArt art={art} />
      <h3 className="mt-4 text-sm font-semibold text-slate-800">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-slate-500">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

function EmptyArt({ art }: { art: Illustration }) {
  const common = { fill: "none", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg width="120" height="84" viewBox="0 0 120 84" aria-hidden="true">
      <ellipse cx="60" cy="76" rx="42" ry="5" className="fill-slate-200" />
      {art === "doc" && (
        <g {...common}>
          <rect x="38" y="8" width="44" height="58" rx="6" className="fill-white stroke-slate-300" strokeWidth="2" />
          <path d="M47 24h26M47 33h26M47 42h16" className="stroke-slate-300" strokeWidth="3" />
          <circle cx="78" cy="58" r="10" className="fill-indigo-100 stroke-indigo-500" strokeWidth="2" />
          <path d="M74 58l3 3 5-6" className="stroke-indigo-500" strokeWidth="2" />
        </g>
      )}
      {art === "check" && (
        <g {...common}>
          <circle cx="60" cy="38" r="26" className="fill-emerald-50 stroke-emerald-500" strokeWidth="2.5" />
          <path d="M48 39l9 9 16-18" className="stroke-emerald-500" strokeWidth="3.5" />
        </g>
      )}
      {art === "search" && (
        <g {...common}>
          <circle cx="54" cy="34" r="20" className="fill-white stroke-slate-300" strokeWidth="2.5" />
          <path d="M69 49l16 16" className="stroke-indigo-500" strokeWidth="4" />
          <path d="M46 34h16" className="stroke-slate-300" strokeWidth="3" />
        </g>
      )}
      {art === "flow" && (
        <g {...common} strokeWidth="2">
          <rect x="46" y="6" width="28" height="14" rx="7" className="fill-white stroke-indigo-500" />
          <path d="M60 20v10" className="stroke-slate-300" />
          <path d="M60 30l16 10-16 10-16-10z" className="fill-white stroke-slate-400" />
          <path d="M44 40H26v14M76 40h18v14" className="stroke-slate-300" />
          <rect x="12" y="54" width="28" height="14" rx="3" className="fill-white stroke-slate-300" />
          <rect x="80" y="54" width="28" height="14" rx="3" className="fill-white stroke-slate-300" />
        </g>
      )}
      {art === "flask" && (
        <g {...common} strokeWidth="2.5">
          <path d="M50 8h20M53 8v22L36 62a5 5 0 0 0 4.5 7h39a5 5 0 0 0 4.5-7L67 30V8" className="fill-white stroke-slate-300" />
          <path d="M42 54h36" className="stroke-indigo-500" />
          <circle cx="56" cy="46" r="2.5" className="fill-indigo-400 stroke-none" />
          <circle cx="66" cy="42" r="2" className="fill-indigo-300 stroke-none" />
        </g>
      )}
      {art === "chart" && (
        <g {...common} strokeWidth="2">
          <path d="M26 68V12M26 68h72" className="stroke-slate-300" />
          <path d="M34 54l16-14 14 8 24-30" className="stroke-indigo-500" strokeWidth="3" />
          <circle cx="88" cy="18" r="4" className="fill-indigo-500 stroke-none" />
        </g>
      )}
    </svg>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-4 w-full", className)} aria-hidden="true" />;
}

export function SkeletonList({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx("space-y-3", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ))}
    </div>
  );
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={cx("animate-spin", className)} role="status" aria-label="Loading">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* -------------------------------------------------------------- Health ring */
const gradeColor = (score: number) =>
  score >= 80 ? "var(--color-emerald-500)" : score >= 60 ? "var(--color-amber-500)" : "var(--color-red-500)";

export function HealthRing({ score, grade, size = 56 }: { score: number; grade?: string; size?: number }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Health score ${score} out of 100${grade ? `, grade ${grade}` : ""}`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth="5" className="stroke-slate-200" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          stroke={gradeColor(score)}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.max(0, Math.min(100, score)) / 100)}
          style={{ transition: "stroke-dashoffset 600ms ease-out" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="text-sm font-bold tabular-nums text-slate-900">{score}</span>
        {grade && <span className="mt-0.5 text-[10px] font-semibold text-slate-500">{grade}</span>}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- Tabs */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: ReactNode; count?: number; icon?: IconName }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === value);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      onChange(next.id);
      requestAnimationFrame(() => document.getElementById(`tab-${next.id}`)?.focus());
    }
  };
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className="flex gap-0.5 overflow-x-auto" style={{ scrollbarWidth: "none" }}>
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            aria-selected={active}
            aria-controls={`panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={cx(
              "relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-2 text-sm font-medium transition-colors",
              active ? "text-indigo-700" : "text-slate-500 hover:text-slate-800",
            )}
          >
            {t.icon && <Icon name={t.icon} size={14} />}
            {t.label}
            {t.count !== undefined && (
              <span
                className={cx(
                  "rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
                  active ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-600",
                )}
              >
                {t.count}
              </span>
            )}
            {active && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-indigo-600" />}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ Dialog */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cx(
        "m-auto w-[calc(100vw-1.5rem)] rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/50 backdrop:backdrop-blur-sm open:animate-pop",
        wide ? "max-w-4xl" : "max-w-lg",
      )}
    >
      {open && (
        <div className="flex max-h-[88vh] flex-col">
          <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <Icon name="x" />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3">{footer}</footer>
          )}
        </div>
      )}
    </dialog>
  );
}

/* ------------------------------------------------------------------ Toasts */
interface ToastInput {
  title: string;
  body?: ReactNode;
  tone?: "success" | "error" | "info";
  action?: { label: string; onClick: () => void };
  duration?: number;
}
interface ToastItem extends ToastInput {
  id: number;
}
const ToastContext = createContext<(t: ToastInput) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (t: ToastInput) => {
      const id = ++counter.current;
      setItems((xs) => [...xs.slice(-3), { ...t, id }]);
      const d = t.duration ?? (t.tone === "error" ? 9000 : 8000);
      if (d > 0) setTimeout(() => dismiss(id), d);
    },
    [dismiss],
  );
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="no-print pointer-events-none fixed inset-x-0 bottom-0 z-[100] flex flex-col items-center gap-2 p-4 sm:items-end">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className="pointer-events-auto flex w-full max-w-sm animate-slide-up items-start gap-3 rounded-xl border border-slate-200 bg-white p-3.5 shadow-xl"
          >
            <span className={t.tone === "error" ? "text-red-600" : t.tone === "success" ? "text-emerald-600" : "text-indigo-600"}>
              <Icon name={t.tone === "error" ? "error" : t.tone === "success" ? "checkCircle" : "info"} size={18} />
            </span>
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-semibold text-slate-900">{t.title}</p>
              {t.body && <div className="mt-0.5 text-slate-600">{t.body}</div>}
              {t.action && (
                <button
                  onClick={() => {
                    t.action!.onClick();
                    dismiss(t.id);
                  }}
                  className="mt-1.5 font-medium text-indigo-700 underline-offset-2 hover:underline"
                >
                  {t.action.label}
                </button>
              )}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="rounded p-0.5 text-slate-500 hover:text-slate-800">
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/* ------------------------------------------------------------------- hooks */
export function useMediaQuery(query: string) {
  const [m, setM] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    on();
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return m;
}
export const usePrefersReducedMotion = () => useMediaQuery("(prefers-reduced-motion: reduce)");

/* ------------------------------------------------------------- formatting */
export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDuration(startIso: string | null, endIso: string | null) {
  if (!startIso) return "-";
  const ms = (endIso ? new Date(endIso) : new Date()).getTime() - new Date(startIso).getTime();
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}
