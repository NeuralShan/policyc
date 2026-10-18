import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { api, type FindingSummary, type Regression } from "../../api";
import { Icon } from "../icons";
import { Badge, Button, CodeChip, Dialog, HealthRing, SeverityIcon, StatusBadge, Tooltip, formatDate, useToast } from "../ui";
import { useWorkspace } from "./ctx";
import { ExportReportButton } from "./Report";

function Chip({ icon, tone, children, title }: { icon: "error" | "warning" | "checkCircle" | "flask"; tone: string; children: React.ReactNode; title: string }) {
  return (
    <Tooltip content={title}>
      <span tabIndex={0} className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold tabular-nums ring-1 ring-inset ${tone}`}>
        <Icon name={icon} size={13} />
        {children}
      </span>
    </Tooltip>
  );
}

function FindingList({ title, items, empty }: { title: string; items: FindingSummary[]; empty: string }) {
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title} ({items.length})
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-2 text-sm">
              <SeverityIcon severity={f.severity} size={14} />
              <CodeChip code={f.code} />
              <span className="min-w-0 flex-1 text-slate-800">{f.title}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function RegressionDialog({ reg, open, onClose }: { reg: Regression | undefined; open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open && !!reg} onClose={onClose} wide title={reg ? `Changes: ${reg.counts.fixed} fixed, ${reg.counts.new} new, ${reg.counts.remaining} remaining` : "Changes"}>
      {reg && (
        <div className="space-y-5">
          <p className="text-sm text-slate-700">
            Health score moved from <strong>{reg.health.before}</strong> to <strong>{reg.health.after}</strong>
            {reg.health.after >= reg.health.before ? " (improved)" : " (regressed)"}.
          </p>
          <FindingList title="Fixed" items={reg.fixed} empty="Nothing fixed by this revision." />
          <FindingList title="New" items={reg.new} empty="No new findings introduced. No regressions." />
          <FindingList title="Remaining" items={reg.remaining} empty="Nothing left. Clean compile." />
        </div>
      )}
    </Dialog>
  );
}

export function Toolbar() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const base = params.get("base");
  const [changesOpen, setChangesOpen] = useState(false);
  const toasted = useRef<string | null>(null);

  const runs = useQuery({ queryKey: ["runs", ws.run.project_id], queryFn: () => api.runs(ws.run.project_id) });
  const ordered = [...(runs.data ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const label = (id: string) => `v${ordered.findIndex((r) => r.id === id) + 1}`;

  const regression = useQuery({
    queryKey: ["regression", ws.runId, base],
    queryFn: () => api.regression(ws.runId, base!),
    enabled: !!base && base !== ws.runId,
    retry: false,
  });
  const reg = regression.data;

  useEffect(() => {
    if (!reg || toasted.current === `${reg.run_id}:${reg.base_run_id}`) return;
    toasted.current = `${reg.run_id}:${reg.base_run_id}`;
    toast({
      title: `${reg.counts.fixed} fixed · ${reg.counts.new} new · ${reg.counts.remaining} remaining`,
      body: `Health ${reg.health.before} → ${reg.health.after} compared with ${ordered.length ? label(reg.base_run_id) : "the previous revision"}.`,
      tone: reg.counts.new > 0 ? "info" : "success",
      action: { label: "View changes", onClick: () => setChangesOpen(true) },
      duration: 12000,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reg]);

  const h = ws.health;
  const name = ws.ast?.profile?.title?.value ?? ws.ast?.filename ?? ws.runId;

  return (
    <div className="no-print border-b border-slate-200 bg-white px-3 py-2 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link to={`/projects/${ws.run.project_id}`} aria-label="Back to project" className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100">
          <Icon name="arrowLeft" size={16} />
        </Link>
        {h ? <HealthRing score={h.score} grade={h.grade} /> : ws.loading ? <div className="skeleton h-14 w-14 rounded-full" /> : null}
        <div className="min-w-0 flex-1 basis-48">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-base font-semibold text-slate-900" title={name}>{name}</h1>
            <StatusBadge status={ws.run.status} />
          </div>
          <p className="hidden truncate font-mono text-[11px] text-slate-500 sm:block">{ws.runId} - {formatDate(ws.run.created_at)}</p>
        </div>
        {h && (
          <div className="flex flex-wrap items-center gap-1.5" aria-label="Summary counts">
            <Chip icon="error" tone="bg-red-50 text-red-700 ring-red-200" title="Errors">{h.errors} <span className="font-medium">errors</span></Chip>
            <Chip icon="warning" tone="bg-amber-50 text-amber-800 ring-amber-200" title="Warnings">{h.warnings} <span className="font-medium">warnings</span></Chip>
            <Chip
              icon={h.tests.failed ? "flask" : "checkCircle"}
              tone={h.tests.failed ? "bg-slate-100 text-slate-700 ring-slate-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}
              title="Generated tests passing"
            >
              {h.tests.passed}/{h.tests.total} <span className="font-medium">tests passed</span>
            </Chip>
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {ordered.length > 1 && (
            <div className="flex items-center gap-1.5">
              <label className="sr-only" htmlFor="rev">Revision</label>
              <Icon name="git" size={14} className="text-slate-500" />
              <select
                id="rev"
                value={ws.runId}
                onChange={(e) => navigate(`/runs/${e.target.value}${base ? `?base=${base}` : ""}`)}
                className="rounded-lg border border-slate-300 bg-white py-1 pl-2 pr-6 text-xs font-medium text-slate-800"
                title="Revision"
              >
                {ordered.map((r, i) => (
                  <option key={r.id} value={r.id}>v{i + 1} - {r.status === "succeeded" ? formatDate(r.created_at) : r.status}</option>
                ))}
              </select>
              <label className="sr-only" htmlFor="cmp">Compare with</label>
              <select
                id="cmp"
                value={base ?? ""}
                onChange={(e) => {
                  const next = new URLSearchParams(params);
                  if (e.target.value) next.set("base", e.target.value);
                  else next.delete("base");
                  toasted.current = null;
                  setParams(next, { replace: true });
                }}
                className="rounded-lg border border-slate-300 bg-white py-1 pl-2 pr-6 text-xs text-slate-800"
                title="Compare with another revision"
              >
                <option value="">Compare...</option>
                {ordered.filter((r) => r.id !== ws.runId && r.status === "succeeded").map((r) => (
                  <option key={r.id} value={r.id}>vs v{ordered.indexOf(r) + 1}</option>
                ))}
              </select>
            </div>
          )}
          {reg && (
            <button onClick={() => setChangesOpen(true)} className="inline-flex items-center gap-1">
              <Badge tone={reg.counts.new > 0 ? "amber" : "green"} icon="git">
                {reg.counts.fixed} fixed {"·"} {reg.counts.new} new {"·"} {reg.counts.remaining} left
              </Badge>
            </button>
          )}
          <span className="hidden sm:inline-flex">
            <Button size="sm" variant="secondary" icon="layers" onClick={() => ws.setTab("pipeline")}>Pipeline</Button>
          </span>
          <ExportReportButton />
        </div>
      </div>
      <RegressionDialog reg={reg} open={changesOpen} onClose={() => setChangesOpen(false)} />
    </div>
  );
}
