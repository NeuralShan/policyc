import { useState } from "react";
import { useParams } from "react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type AggregatedFinding, type FindingTriage } from "../api";

const SEV_COLOUR: Record<string, string> = {
  error: "bg-red-100 text-red-800",
  warning: "bg-yellow-100 text-yellow-800",
  info: "bg-blue-100 text-blue-800",
};

const TIER_COLOUR: Record<string, string> = {
  deterministic: "bg-purple-100 text-purple-700",
  historical: "bg-teal-100 text-teal-700",
  judgment: "bg-slate-100 text-slate-700",
};

const TRIAGE_OPTIONS: FindingTriage[] = ["open", "accepted", "false_positive", "wont_fix", "fixed"];

function RiskBar({ total }: { total: number }) {
  const pct = Math.min(100, (total / 4) * 100);
  const colour = total >= 3 ? "bg-red-500" : total >= 1.5 ? "bg-yellow-400" : "bg-green-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded bg-slate-200">
        <div className={`h-2 rounded ${colour}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-600">{total.toFixed(2)}</span>
    </div>
  );
}

function FindingRow({ finding, runId }: { finding: AggregatedFinding; runId: string }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();

  const triageMut = useMutation({
    mutationFn: (t: FindingTriage) => api.updateFindingTriage(runId, finding.id, t),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["findings", runId] }),
  });

  return (
    <div className="border rounded-lg bg-white shadow-sm overflow-hidden">
      <button
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-slate-50 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="w-6 text-slate-500 font-mono text-sm shrink-0 mt-0.5">
          #{finding.rank}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="font-mono text-sm font-semibold">{finding.code}</span>
            <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${SEV_COLOUR[finding.severity] ?? ""}`}>
              {finding.severity}
            </span>
            <span className={`px-1.5 py-0.5 rounded text-xs ${TIER_COLOUR[finding.confidence_tier] ?? ""}`}>
              {finding.confidence_tier}
            </span>
          </div>
          <p className="text-sm text-slate-700 truncate">{finding.title}</p>
          {(finding.step_id || finding.decision_id) && (
            <p className="text-xs text-slate-500 mt-0.5">
              {finding.step_id && `step: ${finding.step_id}`}
              {finding.decision_id && ` decision: ${finding.decision_id}`}
            </p>
          )}
        </div>
        <div className="shrink-0 mt-1">
          <RiskBar total={finding.risk.total} />
        </div>
        <span className="text-slate-500 ml-2 mt-0.5">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t px-4 py-3 space-y-3 bg-slate-50">
          {/* Risk breakdown */}
          <div className="text-xs text-slate-600 flex gap-4">
            <span>Likelihood <strong>{finding.risk.likelihood.toFixed(2)}</strong></span>
            <span>Impact <strong>{finding.risk.impact.toFixed(2)}</strong></span>
            <span>Confidence <strong>{finding.risk.confidence_weight.toFixed(2)}</strong></span>
            <span>Score <strong>{finding.risk.total.toFixed(2)}</strong></span>
          </div>

          {/* Evidence */}
          <div>
            <p className="text-xs font-semibold text-slate-600 mb-1">Evidence ({finding.evidence.length})</p>
            <ul className="space-y-1">
              {finding.evidence.map((ev, i) => (
                <li key={i} className="text-xs text-slate-700 bg-white border rounded px-2 py-1">
                  <span className="font-mono text-slate-500 mr-1">[{ev.kind}]</span>
                  {ev.message}
                  {ev.rate != null && (
                    <span className="ml-2 text-slate-500">
                      {ev.case_count} cases ({(ev.rate * 100).toFixed(0)}%)
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Triage */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-600 font-semibold">Triage:</span>
            {TRIAGE_OPTIONS.map((t) => (
              <button
                key={t}
                disabled={triageMut.isPending}
                onClick={() => triageMut.mutate(t)}
                className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                  finding.triage === t
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-slate-700 border-slate-300 hover:border-indigo-400"
                }`}
              >
                {t.replace("_", " ")}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function FindingsPage() {
  const { runId } = useParams<{ runId: string }>();
  const [sevFilter, setSevFilter] = useState<string>("all");
  const [triageFilter, setTriageFilter] = useState<string>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["findings", runId],
    queryFn: () => api.runFindings(runId!),
    enabled: !!runId,
  });

  if (isLoading) return <p className="p-8 text-slate-600">Loading findings…</p>;
  if (error) return <p className="p-8 text-red-500">{String(error)}</p>;
  if (!data) return null;

  const stats = data.stats as Record<string, unknown>;
  const findings = data.findings.filter((f) => {
    if (sevFilter !== "all" && f.severity !== sevFilter) return false;
    if (triageFilter !== "all" && f.triage !== triageFilter) return false;
    return true;
  });

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Findings</h1>
        <p className="text-sm text-slate-600 mt-1">Run {runId}</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total", value: stats.total as number },
          { label: "Open", value: stats.open as number, colour: "text-red-700" },
          { label: "Error", value: (stats.by_severity as Record<string, number>)?.error ?? 0, colour: "text-red-500" },
          { label: "Warning", value: (stats.by_severity as Record<string, number>)?.warning ?? 0, colour: "text-yellow-700" },
        ].map(({ label, value, colour }) => (
          <div key={label} className="bg-white rounded-lg border p-4 text-center shadow-sm">
            <p className={`text-3xl font-bold ${colour ?? "text-slate-800"}`}>{value ?? 0}</p>
            <p className="text-xs text-slate-600 mt-1">{label}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-center">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 font-semibold">Severity:</span>
          {["all", "error", "warning", "info"].map((s) => (
            <button
              key={s}
              onClick={() => setSevFilter(s)}
              className={`px-2 py-1 rounded text-xs border transition-colors ${
                sevFilter === s ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-700 border-slate-300 hover:border-indigo-400"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-600 font-semibold">Triage:</span>
          {["all", "open", "accepted", "fixed"].map((t) => (
            <button
              key={t}
              onClick={() => setTriageFilter(t)}
              className={`px-2 py-1 rounded text-xs border transition-colors ${
                triageFilter === t ? "bg-indigo-600 text-white border-indigo-600" : "bg-white text-slate-700 border-slate-300 hover:border-indigo-400"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-500 ml-auto">{findings.length} / {data.findings.length} shown</span>
      </div>

      {/* Findings list */}
      {findings.length === 0 ? (
        <p className="text-slate-600 text-sm py-8 text-center">No findings match the current filters.</p>
      ) : (
        <div className="space-y-2">
          {findings.map((f) => (
            <FindingRow key={f.id} finding={f} runId={runId!} />
          ))}
        </div>
      )}
    </div>
  );
}
