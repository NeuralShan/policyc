import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, type TraceOutcome } from "../../api";
import { titleCase } from "../../lib/workspace";
import { FactsForm } from "../FactsForm";
import { Icon } from "../icons";
import { Badge, Button, ErrorNote, EmptyState, Kbd, cx, type Tone } from "../ui";
import { useWorkspace } from "./ctx";

export const OUTCOME_UI: Record<TraceOutcome, { tone: Tone; icon: "checkCircle" | "error" | "warning"; text: string }> = {
  completed: { tone: "green", icon: "checkCircle", text: "Completed" },
  dead_end: { tone: "red", icon: "error", text: "Dead end: no way forward" },
  undetermined: { tone: "amber", icon: "warning", text: "Undetermined: a decision cannot be evaluated" },
  conflict: { tone: "red", icon: "error", text: "Conflict: more than one branch applies" },
  ambiguous: { tone: "amber", icon: "warning", text: "Ambiguous: rule is vague" },
  loop_detected: { tone: "red", icon: "error", text: "Loop: never terminates" },
  max_steps: { tone: "red", icon: "error", text: "Step limit reached" },
};

export default function TracePanel() {
  const ws = useWorkspace();
  const t = ws.traceState;
  const [scenario, setScenario] = useState(!t);
  const sim = useMutation({
    mutationFn: (facts: Record<string, unknown>) => api.simulate(ws.runId, { scenario_id: "sc_adhoc", description: "Ad-hoc run", facts }),
    onSuccess: (trace) => ws.showTrace(trace, "Ad-hoc scenario"),
  });

  useEffect(() => {
    if (t) setScenario(false);
  }, [t]);

  // Space toggles play/pause while the trace tab is focused.
  const onKey = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).closest("input, select, textarea, button")) return;
    if (e.key === " ") {
      e.preventDefault();
      ws.playing ? ws.pause() : ws.play();
    } else if (e.key === "ArrowRight") ws.stepTo(ws.traceIdx + 1);
    else if (e.key === "ArrowLeft") ws.stepTo(ws.traceIdx - 1);
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto" onKeyDown={onKey}>
      {!t ? (
        <EmptyState title="No trace selected" art="flow">
          Pick a failing test or a finding and choose <strong>Show trace</strong> to watch the case travel through the flowchart, or simulate your own facts below.
        </EmptyState>
      ) : (
        <TraceView />
      )}
      <div className="border-t border-slate-200 px-3 py-2">
        <button onClick={() => setScenario((s) => !s)} aria-expanded={scenario} className="flex items-center gap-1.5 text-sm font-medium text-slate-700 hover:text-slate-900">
          <Icon name={scenario ? "chevronDown" : "chevronRight"} size={14} /> Simulate your own scenario
        </button>
        {scenario && (
          <div className="mt-3 max-w-2xl pb-3">
            <FactsForm ir={ws.ir} pending={sim.isPending} onRun={(f) => sim.mutate(f)} onInvalid={() => ws.clearTrace()} />
            <div className="mt-2"><ErrorNote error={sim.error} /></div>
          </div>
        )}
      </div>
    </div>
  );
}

function TraceView() {
  const ws = useWorkspace();
  const t = ws.traceState!;
  const steps = t.trace.steps;
  const cur = steps[ws.traceIdx];
  const out = OUTCOME_UI[t.trace.outcome];
  const atEnd = ws.traceIdx >= steps.length - 1;
  const labelOf = (id: string) => ws.flow?.nodes.find((n) => n.id === id);

  return (
    <div className="px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={out.tone} icon={out.icon}>{titleCase(t.trace.outcome)}</Badge>
        <span className="min-w-0 truncate text-sm font-medium text-slate-800">{t.label}</span>
        <Button size="sm" variant="ghost" onClick={ws.clearTrace} className="ml-auto">Clear</Button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="Trace playback controls">
        <Button size="sm" variant="secondary" onClick={() => ws.stepTo(0)} aria-label="Restart" icon="refresh" />
        <Button size="sm" variant="secondary" onClick={() => ws.stepTo(ws.traceIdx - 1)} disabled={ws.traceIdx <= 0} aria-label="Step back" icon="arrowLeft" />
        {ws.playing ? (
          <Button size="sm" onClick={ws.pause} icon="pause2" aria-label="Pause">Pause</Button>
        ) : (
          <Button size="sm" onClick={ws.play} icon="play" aria-label="Play">{atEnd ? "Replay" : "Play"}</Button>
        )}
        <Button size="sm" variant="secondary" onClick={() => ws.stepTo(ws.traceIdx + 1)} disabled={atEnd} aria-label="Step forward" icon="arrowRight" />
        <label className="ml-1 flex items-center gap-1.5 text-xs text-slate-600">
          Speed
          <select value={ws.speed} onChange={(e) => ws.setSpeed(Number(e.target.value))} className="rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs">
            <option value={0.5}>0.5x</option>
            <option value={1}>1x</option>
            <option value={2}>2x</option>
            <option value={4}>4x</option>
          </select>
        </label>
        <span className="lg:hidden">
          <Button size="sm" variant="secondary" icon="git" onClick={() => ws.setTab("flow")}>Watch on flowchart</Button>
        </span>
        <span className="text-xs tabular-nums text-slate-500">step {ws.traceIdx + 1} / {steps.length}</span>
        <span className="hidden items-center gap-1 text-[11px] text-slate-500 md:flex"><Kbd>Space</Kbd> play <Kbd>←</Kbd><Kbd>→</Kbd> step</span>
      </div>
      {ws.reducedMotion && <p className="mt-1 text-xs text-slate-500">Reduced motion is on: the whole path is highlighted statically.</p>}
      {atEnd && (
        <p
          role="status"
          className={cx(
            "mt-2 flex items-start gap-2 rounded-lg px-3 py-2 text-sm ring-1",
            t.trace.outcome === "completed" ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-red-50 text-red-800 ring-red-200",
          )}
        >
          <Icon name={out.icon} className="mt-0.5 shrink-0" />
          <span>
            {out.text}
            {cur && t.trace.outcome !== "completed" && (
              <> at <strong className="font-semibold">{labelOf(cur.node_id)?.label ?? cur.action ?? cur.node_id}</strong></>
            )}
            .
          </span>
        </p>
      )}
      <ol className="mt-3 space-y-1" aria-label="Trace steps">
        {steps.map((s, i) => {
          const n = labelOf(s.node_id);
          const active = i === ws.traceIdx;
          const done = i < ws.traceIdx;
          return (
            <li key={s.seq}>
              <button
                onClick={() => ws.stepTo(i)}
                aria-current={active ? "step" : undefined}
                className={cx(
                  "flex w-full items-start gap-3 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                  active ? "bg-indigo-50 ring-1 ring-indigo-300" : "hover:bg-slate-50",
                  !done && !active && "opacity-60",
                )}
              >
                <span className={cx("mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold", active ? "bg-indigo-600 text-white" : "bg-slate-200 text-slate-700")}>
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-slate-900">
                    <span className="mr-1.5 font-mono text-[11px] text-slate-500">{s.node_id}</span>
                    {n?.label ?? s.action ?? s.node_kind}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-600">
                    <span>{s.node_kind}</span>
                    {(s.actor ?? n?.actor) && <span className="flex items-center gap-1"><Icon name="user" size={11} />{s.actor ?? n?.actor}</span>}
                    {s.decision_outcome && (
                      <span className={cx("font-medium", s.decision_outcome === "determined" ? "text-emerald-700" : "text-red-700")}>
                        decision: {s.decision_outcome}
                      </span>
                    )}
                    {s.branch_taken && <span>branch: <span className="font-mono">{s.branch_taken}</span></span>}
                    {s.step_status && s.step_status !== "ok" && <span className="font-medium text-red-700">{s.step_status}</span>}
                    {s.note && <span className="italic">{s.note}</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
