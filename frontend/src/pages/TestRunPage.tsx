import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  api,
  type CoverageReport,
  type FailReason,
  type TestResult,
  type TestRunReport,
  type TestVerdict,
} from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

// ---------------------------------------------------------------------------
// Tone maps
// ---------------------------------------------------------------------------

const VERDICT_TONE: Record<TestVerdict, "green" | "red" | "amber"> = {
  pass: "green",
  fail: "red",
  skip: "amber",
};

const VERDICT_LABEL: Record<TestVerdict, string> = {
  pass: "PASS",
  fail: "FAIL",
  skip: "SKIP",
};

const REASON_LABEL: Record<FailReason, string> = {
  structural_gap: "Structural gap",
  sla_breach: "SLA breach",
  actor_unavailable: "Actor unavailable",
  expected_outcome_mismatch: "Outcome mismatch",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <div className={cx("rounded-lg border px-4 py-3 text-center", tone)}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs opacity-70">{label}</div>
    </div>
  );
}

function CoverageBar({ label, pct, covered, total }: { label: string; pct: number; covered: number; total: number }) {
  const w = Math.round(pct);
  const tone = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-400" : "bg-red-500";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span>
          {covered}/{total} — {pct.toFixed(1)}%
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div className={cx("h-full rounded-full transition-all", tone)} style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

function CoverageCard({ cov }: { cov: CoverageReport }) {
  return (
    <Card title="Coverage">
      <div className="space-y-4">
        <CoverageBar
          label="Steps"
          pct={cov.step_coverage_pct}
          covered={cov.steps_covered}
          total={cov.steps_total}
        />
        <CoverageBar
          label="Decisions"
          pct={cov.decision_coverage_pct}
          covered={cov.decisions_covered}
          total={cov.decisions_total}
        />
        <CoverageBar
          label="Branches"
          pct={cov.branch_coverage_pct}
          covered={cov.branches_covered}
          total={cov.branches_total}
        />
        {cov.uncovered_step_ids.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-slate-600">Uncovered steps</p>
            <div className="flex flex-wrap gap-1.5">
              {cov.uncovered_step_ids.map((id) => (
                <Mono key={id} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                  {id}
                </Mono>
              ))}
            </div>
          </div>
        )}
        {cov.uncovered_branch_keys.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-slate-600">Uncovered branches</p>
            <div className="flex flex-wrap gap-1.5">
              {cov.uncovered_branch_keys.map((key) => (
                <Mono key={key} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                  {key}
                </Mono>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function TestResultRow({ result }: { result: TestResult }) {
  const [open, setOpen] = useState(false);
  const verdict = result.verdict as TestVerdict;

  return (
    <div className="border-b border-slate-100 last:border-0">
      <button
        className="flex w-full items-start gap-3 py-3 text-left hover:bg-slate-50"
        onClick={() => setOpen((o) => !o)}
      >
        <Badge tone={VERDICT_TONE[verdict]}>{VERDICT_LABEL[verdict]}</Badge>
        <div className="min-w-0 flex-1">
          <Mono className="text-xs text-slate-600">{result.test_id}</Mono>
          {result.fail_reasons.length > 0 && (
            <div className="mt-0.5 flex flex-wrap gap-1.5">
              {result.fail_reasons.map((r) => (
                <span
                  key={r}
                  className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700"
                >
                  {REASON_LABEL[r as FailReason] ?? r}
                </span>
              ))}
            </div>
          )}
          {result.skip_reason && (
            <p className="text-xs text-amber-700">{result.skip_reason}</p>
          )}
        </div>
        {result.trace && (
          <Badge
            tone={
              result.trace.outcome === "completed"
                ? "green"
                : result.trace.outcome === "undetermined" || result.trace.outcome === "conflict"
                  ? "red"
                  : "amber"
            }
          >
            {result.trace.outcome}
          </Badge>
        )}
        <span className="shrink-0 text-xs text-slate-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && result.trace && (
        <div className="mb-3 ml-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
          <p className="mb-2 font-medium text-slate-600">
            Trace — {result.trace.steps.length} steps, outcome:{" "}
            <Mono>{result.trace.outcome}</Mono>
          </p>
          <ol className="space-y-1">
            {result.trace.steps.map((ts) => (
              <li key={ts.seq} className="flex items-center gap-2">
                <span className="shrink-0 text-slate-500">{ts.seq + 1}.</span>
                <Mono className="text-slate-500">{ts.node_id}</Mono>
                <span className="text-slate-500">{ts.node_kind}</span>
                {ts.action && <span className="truncate text-slate-700">{ts.action}</span>}
                {ts.branch_taken && (
                  <span className="text-amber-700">{ts.branch_taken}</span>
                )}
                {ts.step_status && ts.step_status !== "ok" && (
                  <span className="text-red-700">[{ts.step_status}]</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type VerdictFilter = TestVerdict | "all";

export function TestRunPage() {
  const { runId = "" } = useParams();
  const [filter, setFilter] = useState<VerdictFilter>("all");

  const query = useQuery({
    queryKey: ["run-testrun", runId],
    queryFn: () => api.runTestrun(runId),
  });

  const report: TestRunReport | undefined = query.data;

  const filtered =
    filter === "all"
      ? report?.results ?? []
      : report?.results.filter((r) => r.verdict === filter) ?? [];

  const passRate =
    report && report.total > 0
      ? ((report.passed / report.total) * 100).toFixed(1)
      : "—";

  return (
    <>
      <PageHeader
        title="Test Run Report"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <div className="flex gap-3">
            <Link to={`/runs/${runId}/tests`} className="text-sm text-slate-600 hover:text-slate-900">
               Test Suite
            </Link>
            <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
               Run
            </Link>
          </div>
        }
      />
      <ErrorNote error={query.error} />

      {report && (
        <>
          {/* Summary stat cards */}
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <StatCard
              label="Total"
              value={report.total}
              tone="bg-slate-50 border-slate-200 text-slate-700"
            />
            <StatCard
              label="Passed"
              value={report.passed}
              tone="bg-emerald-50 border-emerald-200 text-emerald-700"
            />
            <StatCard
              label="Failed"
              value={report.failed}
              tone="bg-red-50 border-red-200 text-red-700"
            />
            <StatCard
              label="Skipped"
              value={report.skipped}
              tone="bg-amber-50 border-amber-200 text-amber-700"
            />
            <StatCard
              label="Pass rate"
              value={`${passRate}%`}
              tone={
                parseFloat(passRate) >= 80
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : parseFloat(passRate) >= 50
                    ? "bg-amber-50 border-amber-200 text-amber-700"
                    : "bg-red-50 border-red-200 text-red-700"
              }
            />
          </div>

          {/* Coverage */}
          <div className="mb-6">
            <CoverageCard cov={report.coverage} />
          </div>

          {/* Results table */}
          <Card
            title={
              <div className="flex items-center gap-3">
                <span>Results ({filtered.length})</span>
                <div className="flex gap-1">
                  {(["all", "pass", "fail", "skip"] as VerdictFilter[]).map((v) => (
                    <button
                      key={v}
                      onClick={() => setFilter(v)}
                      className={cx(
                        "rounded px-2 py-0.5 text-xs capitalize",
                        filter === v
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                      )}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>
            }
          >
            {query.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="text-sm italic text-slate-500">No results.</p>
            ) : (
              <div>
                {filtered.map((r) => (
                  <TestResultRow key={r.test_id} result={r} />
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {query.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
    </>
  );
}
