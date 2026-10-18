import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { api, type CaseResult, type RealityReport, type RlFinding } from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FitnessBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone =
    pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-400" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200">
        <div className={cx("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums">{pct}%</span>
    </div>
  );
}

function RlBadge({ code }: { code: string }) {
  const tone: Record<string, "red" | "amber" | "blue"> = {
    RL001: "amber",
    RL002: "blue",
    RL003: "amber",
    RL004: "red",
  };
  return <Badge tone={tone[code] ?? "amber"}>{code}</Badge>;
}

function FindingsCard({ findings }: { findings: RlFinding[] }) {
  if (!findings.length) {
    return (
      <Card title="RL Findings">
        <p className="text-sm italic text-slate-500">No findings — all conformance thresholds met.</p>
      </Card>
    );
  }
  return (
    <Card title={`RL Findings (${findings.length})`}>
      <ul className="space-y-3">
        {findings.map((f, i) => (
          <li key={i} className="flex gap-3">
            <div className="mt-0.5 shrink-0">
              <RlBadge code={f.code} />
            </div>
            <div className="min-w-0">
              <p className="text-sm text-slate-800">{f.message}</p>
              <div className="mt-0.5 flex gap-3 text-xs text-slate-500">
                {f.step_id && <Mono>{f.step_id}</Mono>}
                {f.activity && <span>"{f.activity}"</span>}
                <span>{(f.rate * 100).toFixed(0)}% of cases</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function CaseRow({ result }: { result: CaseResult }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-slate-100 last:border-0">
      <button
        className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-slate-50"
        onClick={() => setOpen((o) => !o)}
      >
        <Mono className="w-32 shrink-0 text-xs text-slate-600">{result.case_id}</Mono>
        <FitnessBar value={result.fitness} />
        {result.has_no_path && <Badge tone="red">no path</Badge>}
        {result.skipped.length > 0 && (
          <span className="text-xs text-amber-700">
            {result.skipped.length} skipped
          </span>
        )}
        {result.sla_breaches.length > 0 && (
          <span className="text-xs text-red-700">
            {result.sla_breaches.length} SLA breach
          </span>
        )}
        <span className="ml-auto shrink-0 text-xs text-slate-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mb-3 ml-3 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
          {result.synced.length > 0 && (
            <div>
              <span className="font-medium text-emerald-700">Synced: </span>
              {result.synced.map((s) => <Mono key={s} className="mr-1.5">{s}</Mono>)}
            </div>
          )}
          {result.skipped.length > 0 && (
            <div>
              <span className="font-medium text-amber-700">Skipped: </span>
              {result.skipped.map((s) => <Mono key={s} className="mr-1.5 text-amber-700">{s}</Mono>)}
            </div>
          )}
          {result.extra.length > 0 && (
            <div>
              <span className="font-medium text-blue-700">Extra activities: </span>
              {result.extra.map((a, i) => (
                <span key={i} className="mr-2 italic text-slate-600">"{a}"</span>
              ))}
            </div>
          )}
          {result.sla_breaches.length > 0 && (
            <div>
              <span className="font-medium text-red-700">SLA breaches: </span>
              {result.sla_breaches.map((s) => <Mono key={s} className="mr-1.5 text-red-700">{s}</Mono>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function UploadForm({
  runId,
  onUploaded,
}: {
  runId: string;
  onUploaded: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [caseIdCol, setCaseIdCol] = useState("case_id");
  const [activityCol, setActivityCol] = useState("activity");
  const [timestampCol, setTimestampCol] = useState("timestamp");
  const [resourceCol, setResourceCol] = useState("");
  const qc = useQueryClient();

  const uploadMut = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("Select a CSV file");
      return api.uploadCaseHistory(runId, file, {
        case_id_col: caseIdCol,
        activity_col: activityCol,
        timestamp_col: timestampCol,
        resource_col: resourceCol || undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["case-history", runId] });
      onUploaded();
    },
  });

  return (
    <Card title="Upload Case History (CSV)">
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-600">
            CSV file
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="block w-full text-sm text-slate-600"
          />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Case ID column", caseIdCol, setCaseIdCol],
            ["Activity column", activityCol, setActivityCol],
            ["Timestamp column", timestampCol, setTimestampCol],
            ["Resource column (optional)", resourceCol, setResourceCol],
          ].map(([label, value, setter]) => (
            <div key={label as string}>
              <label className="mb-1 block text-xs font-medium text-slate-600">{label as string}</label>
              <input
                type="text"
                value={value as string}
                onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
          ))}
        </div>
        <button
          onClick={() => uploadMut.mutate()}
          disabled={uploadMut.isPending}
          className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {uploadMut.isPending ? "Uploading…" : "Upload"}
        </button>
        {uploadMut.isError && (
          <ErrorNote error={(uploadMut.error as Error).message} />
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Filter = "all" | "conformant" | "non_conformant";

export function RealityPage() {
  const { runId = "" } = useParams();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [uploaded, setUploaded] = useState(false);

  // Avoid probing GET /reality (a 404 logs console noise) until a report can exist: the run artifact is
  // a stub until a check ran, and we remember locally that this browser already ran one.
  const runQuery = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  const ranKey = `policyc.reality.${runId}`;
  const artifact = runQuery.data?.artifacts?.reality as { stub?: boolean } | undefined;
  const mayExist = !!artifact && !artifact.stub ? true : localStorage.getItem(ranKey) === "1";
  const reportQuery = useQuery({
    queryKey: ["reality-report", runId],
    queryFn: () => api.realityReport(runId),
    enabled: mayExist,
    retry: false,
  });

  const report: RealityReport | undefined = reportQuery.data ?? undefined;

  const runMut = useMutation({
    mutationFn: () => api.runRealityCheck(runId),
    onSuccess: (r) => {
      localStorage.setItem(ranKey, "1");
      qc.setQueryData(["reality-report", runId], r);
    },
  });

  const filtered =
    filter === "conformant"
      ? report?.case_results.filter((r) => r.fitness >= 0.8) ?? []
      : filter === "non_conformant"
        ? report?.case_results.filter((r) => r.fitness < 0.8) ?? []
        : report?.case_results ?? [];

  const avgPct = report ? Math.round(report.avg_fitness * 100) : null;

  return (
    <>
      <PageHeader
        title="Reality Check"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
             Run
          </Link>
        }
      />

      {/* Upload form (always shown if no report yet, or after click) */}
      {(!report || uploaded) && (
        <div className="mb-6">
          <UploadForm runId={runId} onUploaded={() => setUploaded(false)} />
        </div>
      )}

      {/* Run button */}
      {!report && (
        <div className="mb-6 flex items-center gap-4">
          <button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {runMut.isPending ? "Running…" : "Run Conformance Check"}
          </button>
          {runMut.isError && (
            <ErrorNote error={(runMut.error as Error).message} />
          )}
        </div>
      )}

      {/* Summary stats */}
      {report && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-center">
              <div className="text-2xl font-bold">{report.total_cases}</div>
              <div className="text-xs opacity-70">Total cases</div>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-center">
              <div className="text-2xl font-bold text-emerald-700">
                {report.conformant_cases}
              </div>
              <div className="text-xs opacity-70">Conformant (≥80%)</div>
            </div>
            <div className={cx(
              "rounded-lg border px-4 py-3 text-center",
              (avgPct ?? 0) >= 80
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : (avgPct ?? 0) >= 50
                  ? "border-amber-200 bg-amber-50 text-amber-700"
                  : "border-red-200 bg-red-50 text-red-700",
            )}>
              <div className="text-2xl font-bold">{avgPct}%</div>
              <div className="text-xs opacity-70">Avg fitness</div>
            </div>
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-center">
              <div className="text-2xl font-bold text-rose-700">
                {report.rl_findings.length}
              </div>
              <div className="text-xs opacity-70">RL findings</div>
            </div>
          </div>

          {/* RL findings */}
          <div className="mb-6">
            <FindingsCard findings={report.rl_findings} />
          </div>

          {/* Per-case results */}
          <Card
            title={
              <div className="flex items-center gap-3">
                <span>Cases ({filtered.length})</span>
                <div className="flex gap-1">
                  {(["all", "conformant", "non_conformant"] as Filter[]).map((f) => (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      className={cx(
                        "rounded px-2 py-0.5 text-xs",
                        filter === f
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                      )}
                    >
                      {f === "all" ? "All" : f === "conformant" ? "Conformant" : "Non-conformant"}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => { setUploaded(true); runMut.reset(); }}
                  className="ml-auto text-xs text-slate-500 hover:text-slate-700"
                >
                  Re-upload
                </button>
              </div>
            }
          >
            {filtered.length === 0 ? (
              <p className="text-sm italic text-slate-500">No cases.</p>
            ) : (
              <div>
                {filtered.map((r) => (
                  <CaseRow key={r.case_id} result={r} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      <ErrorNote error={reportQuery.isError && reportQuery.error instanceof Error
        ? (reportQuery.error.message.includes("404") ? null : reportQuery.error)
        : null}
      />
    </>
  );
}
