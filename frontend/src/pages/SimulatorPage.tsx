import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  api,
  type ExecutionTrace,
  type SimulateRequest,
  type TraceStep,
} from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

const OUTCOME_TONE: Record<string, string> = {
  completed: "bg-emerald-50 border-emerald-200 text-emerald-800",
  dead_end: "bg-red-50 border-red-200 text-red-800",
  undetermined: "bg-amber-50 border-amber-200 text-amber-800",
  conflict: "bg-red-50 border-red-200 text-red-800",
  ambiguous: "bg-amber-50 border-amber-200 text-amber-800",
  loop_detected: "bg-red-50 border-red-200 text-red-800",
  max_steps: "bg-slate-50 border-slate-200 text-slate-700",
};

const STATUS_BADGE: Record<string, "green" | "red" | "amber" | "blue"> = {
  ok: "green",
  sla_breached: "amber",
  actor_unavailable: "amber",
  system_down: "red",
  input_missing: "red",
};

function TraceStepRow({ ts }: { ts: TraceStep }) {
  const badge =
    ts.node_kind === "decision"
      ? "blue"
      : ts.node_kind === "terminal"
        ? "green"
        : (STATUS_BADGE[ts.step_status ?? "ok"] ?? "blue");

  return (
    <div className="flex items-start gap-3 border-b border-slate-100 py-2 last:border-0">
      <span className="mt-0.5 w-6 shrink-0 text-right text-xs text-slate-400">{ts.seq + 1}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={badge}>{ts.node_kind}</Badge>
          <span className="text-sm font-medium">{ts.action ?? ts.node_id}</span>
          {ts.branch_taken && (
            <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-700">
              → {ts.branch_taken}
            </span>
          )}
          {ts.decision_outcome && (
            <Mono className="text-xs opacity-60">{ts.decision_outcome}</Mono>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-3 text-xs text-slate-500">
          {ts.actor && <span>actor: {ts.actor}</span>}
          {ts.sla_ok === false && (
            <span className="text-amber-600 font-medium">SLA breached</span>
          )}
          {ts.note && <span className="italic">{ts.note}</span>}
          <span>{ts.elapsed_s.toFixed(0)} s elapsed</span>
        </div>
      </div>
    </div>
  );
}

function TraceView({ trace }: { trace: ExecutionTrace }) {
  const tone = OUTCOME_TONE[trace.outcome] ?? OUTCOME_TONE.max_steps;
  return (
    <div className="space-y-4">
      <div className={cx("rounded-lg border px-5 py-4", tone)}>
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide opacity-60">Outcome</div>
            <div className="text-lg font-bold capitalize">{trace.outcome.replace(/_/g, " ")}</div>
          </div>
          <div>
            <div className="text-xs font-medium uppercase tracking-wide opacity-60">Steps</div>
            <div className="text-lg font-bold">{trace.steps.length}</div>
          </div>
          <div>
            <div className="text-xs font-medium uppercase tracking-wide opacity-60">Elapsed</div>
            <div className="text-lg font-bold">{trace.elapsed_s.toFixed(0)} s</div>
          </div>
          {trace.sla_breaches > 0 && (
            <div>
              <div className="text-xs font-medium uppercase tracking-wide opacity-60">SLA breaches</div>
              <div className="text-lg font-bold text-amber-700">{trace.sla_breaches}</div>
            </div>
          )}
          {trace.actor_unavailable_count > 0 && (
            <div>
              <div className="text-xs font-medium uppercase tracking-wide opacity-60">Unavailable actors</div>
              <div className="text-lg font-bold">{trace.actor_unavailable_count}</div>
            </div>
          )}
        </div>
      </div>

      <Card title={`Execution trace (${trace.steps.length} events)`}>
        {trace.steps.length === 0 ? (
          <p className="text-sm text-slate-400 italic">No steps executed.</p>
        ) : (
          <div>
            {trace.steps.map((ts) => (
              <TraceStepRow key={ts.seq} ts={ts} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

const DEFAULT_FACTS = `{
  "amount": 1000
}`;

export function SimulatorPage() {
  const { runId = "" } = useParams();
  const [scenarioId, setScenarioId] = useState("sc_adhoc");
  const [factsText, setFactsText] = useState(DEFAULT_FACTS);
  const [factsError, setFactsError] = useState<string | null>(null);

  const tracesQuery = useQuery({
    queryKey: ["run-traces", runId],
    queryFn: () => api.runTraces(runId),
  });

  const simulate = useMutation({
    mutationFn: (req: SimulateRequest) => api.simulate(runId, req),
    onSuccess: () => tracesQuery.refetch(),
  });

  function handleRun() {
    setFactsError(null);
    let facts: Record<string, unknown> = {};
    try {
      facts = JSON.parse(factsText);
    } catch {
      setFactsError("Invalid JSON in facts field");
      return;
    }
    simulate.mutate({ scenario_id: scenarioId, description: "Ad-hoc run", facts });
  }

  return (
    <>
      <PageHeader
        title="Simulator"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
            ← Run
          </Link>
        }
      />
      <ErrorNote error={tracesQuery.error ?? simulate.error} />

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card title="Scenario">
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Scenario ID
              </label>
              <input
                className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none"
                value={scenarioId}
                onChange={(e) => setScenarioId(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Facts (JSON)
              </label>
              <textarea
                rows={6}
                className={cx(
                  "w-full rounded border px-3 py-2 font-mono text-sm focus:outline-none",
                  factsError
                    ? "border-red-400 focus:border-red-400"
                    : "border-slate-300 focus:border-indigo-400",
                )}
                value={factsText}
                onChange={(e) => setFactsText(e.target.value)}
              />
              {factsError && (
                <p className="mt-1 text-xs text-red-600">{factsError}</p>
              )}
            </div>
            <button
              onClick={handleRun}
              disabled={simulate.isPending}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {simulate.isPending ? "Running…" : "Run simulation →"}
            </button>
          </div>
        </Card>

        <Card title={`Previous traces (${tracesQuery.data?.length ?? 0})`}>
          {tracesQuery.isLoading ? (
            <p className="text-sm text-slate-400">Loading…</p>
          ) : !tracesQuery.data?.length ? (
            <p className="text-sm text-slate-400 italic">No traces yet — run a simulation.</p>
          ) : (
            <ul className="space-y-1">
              {tracesQuery.data.map((t) => (
                <li key={t.id} className="flex items-center justify-between text-sm">
                  <Mono className="text-xs">{t.scenario_id}</Mono>
                  <Badge
                    tone={
                      t.outcome === "completed"
                        ? "green"
                        : t.outcome === "ambiguous" || t.outcome === "undetermined"
                          ? "amber"
                          : "red"
                    }
                  >
                    {t.outcome}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {simulate.data && <TraceView trace={simulate.data} />}
    </>
  );
}
