import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import {
  api,
  type ExecutionTrace,
  type SimulateRequest,
  type TraceStep,
} from "../api";
import { FactsForm } from "../components/FactsForm";
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
      <span className="mt-0.5 w-6 shrink-0 text-right text-xs text-slate-500">{ts.seq + 1}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={badge}>{ts.node_kind}</Badge>
          <span className="text-sm font-medium">{ts.action ?? ts.node_id}</span>
          {ts.branch_taken && (
            <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-700">
              {ts.branch_taken}
            </span>
          )}
          {ts.decision_outcome && (
            <Mono className="text-xs opacity-60">{ts.decision_outcome}</Mono>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-3 text-xs text-slate-500">
          {ts.actor && <span>actor: {ts.actor}</span>}
          {ts.sla_ok === false && (
            <span className="text-amber-700 font-medium">SLA breached</span>
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
          <p className="text-sm text-slate-500 italic">No steps executed.</p>
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

export function SimulatorPage() {
  const { runId = "" } = useParams();
  const [scenarioId, setScenarioId] = useState("sc_adhoc");

  const tracesQuery = useQuery({
    queryKey: ["run-traces", runId],
    queryFn: () => api.runTraces(runId),
  });
  const irQuery = useQuery({ queryKey: ["ir", runId], queryFn: () => api.runIr(runId) });

  const simulate = useMutation({
    mutationFn: (req: SimulateRequest) => api.simulate(runId, req),
    onSuccess: () => tracesQuery.refetch(),
  });

  return (
    <>
      <PageHeader
        title="Simulator"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <Link to={`/runs/${runId}`} className="text-sm font-medium text-indigo-700 hover:underline">
            Back to run
          </Link>
        }
      />
      <ErrorNote error={tracesQuery.error ?? simulate.error} />

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card title="Scenario">
          <div className="space-y-3">
            <div>
              <label htmlFor="scenario-id" className="mb-1 block text-xs font-medium text-slate-700">
                Scenario ID
              </label>
              <input
                id="scenario-id"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                value={scenarioId}
                onChange={(e) => setScenarioId(e.target.value)}
              />
            </div>
            <FactsForm
              ir={irQuery.data?.ir}
              pending={simulate.isPending}
              // Invalid JSON must never leave the previous trace on screen as if it were the answer.
              onInvalid={() => simulate.reset()}
              onRun={(facts) => simulate.mutate({ scenario_id: scenarioId, description: "Ad-hoc run", facts })}
            />
          </div>
        </Card>

        <Card title={`Previous traces (${tracesQuery.data?.length ?? 0})`}>
          {tracesQuery.isLoading ? (
            <p className="text-sm text-slate-500">Loading...</p>
          ) : !tracesQuery.data?.length ? (
            <p className="text-sm italic text-slate-500">No traces yet. Run a simulation.</p>
          ) : (
            <ul className="space-y-1">
              {tracesQuery.data.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-2 text-sm">
                  <Mono className="text-xs">{t.scenario_id}</Mono>
                  <Badge
                    tone={t.outcome === "completed" ? "green" : t.outcome === "ambiguous" || t.outcome === "undetermined" ? "amber" : "red"}
                    icon={t.outcome === "completed" ? "checkCircle" : t.outcome === "ambiguous" || t.outcome === "undetermined" ? "warning" : "error"}
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
