import { useState } from "react";
import { Link } from "react-router";

import { Icon } from "../icons";
import { Badge, Button, EmptyState, SkeletonList, cx } from "../ui";
import { useWorkspace } from "./ctx";
import { OUTCOME_UI } from "./TracePanel";

export default function TestsPanel() {
  const ws = useWorkspace();
  const [only, setOnly] = useState<"all" | "fail" | "pass">("all");
  const rep = ws.testrun;
  if (rep === undefined) return <div className="p-4"><SkeletonList rows={4} /></div>;
  if (rep === null) return <EmptyState title="No test run yet" art="flask">The test stage has not produced results for this run.</EmptyState>;
  const rows = rep.results.filter((r) => only === "all" || (only === "fail" ? r.verdict === "fail" : r.verdict === "pass"));
  const cov = rep.coverage;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-3 py-2 text-sm">
        <span className="font-semibold text-slate-900">{rep.passed}/{rep.total} passed</span>
        <span className="text-xs text-slate-600">
          coverage: steps {Math.round(cov.step_coverage_pct)}% | decisions {Math.round(cov.decision_coverage_pct)}% | branches {Math.round(cov.branch_coverage_pct)}%
        </span>
        <div className="ml-auto flex items-center gap-2">
          {(["all", "fail", "pass"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setOnly(f)}
              aria-pressed={only === f}
              className={cx("rounded-full px-2.5 py-0.5 text-xs font-medium", only === f ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200")}
            >
              {f === "all" ? "All" : f === "fail" ? "Failing" : "Passing"}
            </button>
          ))}
          <Link to={`/runs/${ws.runId}/testrun`} className="text-xs font-medium text-indigo-700 hover:underline">Full report</Link>
        </div>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {rows.map((r) => {
          const scen = (r.trace as unknown as { scenario?: { description?: string; facts?: Record<string, unknown> } } | null)?.scenario;
          return (
            <li key={r.test_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-100 px-3 py-2 last:border-0">
              <Badge tone={r.verdict === "pass" ? "green" : r.verdict === "fail" ? "red" : "slate"} icon={r.verdict === "pass" ? "checkCircle" : r.verdict === "fail" ? "error" : "chevronRight"}>
                {r.verdict}
              </Badge>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-xs font-medium text-slate-900">{r.test_id}</span>
                <span className="block truncate text-xs text-slate-600">
                  {scen?.description}
                  {r.trace && <> - {OUTCOME_UI[r.trace.outcome]?.text.split(":")[0] ?? r.trace.outcome}</>}
                  {r.fail_reasons.length > 0 && <> - {r.fail_reasons.join(", ").replace(/_/g, " ")}</>}
                </span>
              </span>
              {r.trace && (
                <Button size="sm" variant="secondary" onClick={() => ws.showTrace(r.trace!, `Test ${r.test_id}`)}>
                  <Icon name="play" size={12} /> Trace
                </Button>
              )}
            </li>
          );
        })}
        {rows.length === 0 && <li className="p-6 text-center text-sm text-slate-500">No tests in this filter.</li>}
      </ul>
    </div>
  );
}
