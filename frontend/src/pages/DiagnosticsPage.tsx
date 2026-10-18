import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { api, type Diagnostic, type DiagnosticsReport } from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

const SEVERITY_TONE: Record<string, string> = {
  error: "bg-red-50 border-red-200 text-red-800",
  warning: "bg-amber-50 border-amber-200 text-amber-800",
  info: "bg-sky-50 border-sky-200 text-sky-700",
};

const SEVERITY_BADGE: Record<string, "red" | "amber" | "blue"> = {
  error: "red",
  warning: "amber",
  info: "blue",
};

const CODE_CATEGORY: Record<string, string> = {
  ST: "Structural",
  RS: "Responsibility",
  DF: "Data-flow",
  TM: "Temporal",
  LG: "Language",
  XD: "Cross-document",
};

function categoryOf(code: string) {
  return CODE_CATEGORY[code.slice(0, 2)] ?? code.slice(0, 2);
}

function DiagnosticRow({ d }: { d: Diagnostic }) {
  const tone = SEVERITY_TONE[d.severity] ?? SEVERITY_TONE.info;
  const badgeTone = SEVERITY_BADGE[d.severity] ?? "blue";
  return (
    <div className={cx("rounded border px-4 py-3", tone)}>
      <div className="flex items-start gap-3">
        <Badge tone={badgeTone}>{d.severity.toUpperCase()}</Badge>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Mono className="text-xs font-semibold">{d.code}</Mono>
            <span className="text-xs opacity-60">{categoryOf(d.code)}</span>
            {d.check_tier === "language" && (
              <span className="rounded bg-violet-100 px-1.5 py-0.5 text-xs text-violet-700">
                language tier
              </span>
            )}
          </div>
          <p className="mt-1 text-sm">{d.message}</p>
          {(d.process_id || d.step_id || d.decision_id) && (
            <div className="mt-1 flex flex-wrap gap-2 text-xs opacity-60">
              {d.process_id && <Mono>process: {d.process_id}</Mono>}
              {d.step_id && <Mono>step: {d.step_id}</Mono>}
              {d.decision_id && <Mono>decision: {d.decision_id}</Mono>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatPill({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={cx("rounded-lg border px-4 py-2 text-center", tone)}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs opacity-70">{label}</div>
    </div>
  );
}

function GroupedDiagnostics({ diagnostics }: { diagnostics: Diagnostic[] }) {
  const groups: Record<string, Diagnostic[]> = {};
  for (const d of diagnostics) {
    const cat = categoryOf(d.code);
    (groups[cat] ??= []).push(d);
  }
  if (diagnostics.length === 0) {
    return (
      <p className="text-sm text-slate-500 italic">No diagnostics — the SOP looks clean.</p>
    );
  }
  return (
    <div className="space-y-4">
      {Object.entries(groups)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([cat, items]) => (
          <div key={cat}>
            <h3 className="mb-2 text-sm font-semibold text-slate-600">
              {cat} ({items.length})
            </h3>
            <div className="space-y-2">
              {items.map((d, i) => (
                <DiagnosticRow key={`${d.code}-${d.step_id ?? d.decision_id ?? i}`} d={d} />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

export function DiagnosticsPage() {
  const { runId = "" } = useParams();

  const query = useQuery({
    queryKey: ["run-diagnostics", runId],
    queryFn: () => api.runDiagnostics(runId),
  });

  const report = query.data as DiagnosticsReport | undefined;
  const stats = report?.stats ?? {};

  return (
    <>
      <PageHeader
        title="Static Analysis"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <Link
            to={`/runs/${runId}`}
            className="text-sm text-slate-600 hover:text-slate-900"
          >
             Run
          </Link>
        }
      />
      <ErrorNote error={query.error} />

      {stats.total !== undefined && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatPill
            label="Total"
            value={stats.total ?? 0}
            tone="bg-slate-50 border-slate-200 text-slate-700"
          />
          <StatPill
            label="Errors"
            value={stats.total_errors ?? 0}
            tone="bg-red-50 border-red-200 text-red-700"
          />
          <StatPill
            label="Warnings"
            value={stats.total_warnings ?? 0}
            tone="bg-amber-50 border-amber-200 text-amber-700"
          />
          <StatPill
            label="Info"
            value={stats.total_infos ?? 0}
            tone="bg-sky-50 border-sky-200 text-sky-700"
          />
        </div>
      )}

      <Card title={`Diagnostics (${report?.diagnostics.length ?? 0})`}>
        {query.isLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : (
          <GroupedDiagnostics diagnostics={report?.diagnostics ?? []} />
        )}
      </Card>
    </>
  );
}
