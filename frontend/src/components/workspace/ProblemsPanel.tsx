import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { api, type AggregatedFinding, type FindingTriage } from "../../api";
import { useWriteGuard } from "../../auth/AuthProvider";
import {
  clauseLabel,
  findingCounterexample,
  findingNodeId,
  findingRanges,
  findingTestIds,
  formatFacts,
} from "../../lib/workspace";
import { Icon } from "../icons";
import { Button, CodeChip, EmptyState, Kbd, SeverityIcon, SkeletonList, cx, useTaxonomy, useToast, type Severity } from "../ui";
import { useWorkspace } from "./ctx";

const TRIAGE_UI: { value: FindingTriage; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "accepted", label: "Accepted" },
  { value: "false_positive", label: "Dismissed" },
];

/** Resolve and show an animated witness trace for a finding. */
export function useShowFindingTrace() {
  const ws = useWorkspace();
  const toast = useToast();
  const simulate = useMutation({
    mutationFn: (facts: Record<string, unknown>) => api.simulate(ws.runId, { scenario_id: "sc_witness", description: "Finding witness", facts }),
  });
  return {
    pending: simulate.isPending,
    show: async (f: AggregatedFinding) => {
      const ids = findingTestIds(f);
      const res = ws.testrun?.results.find((r) => ids.includes(r.test_id) && r.trace);
      if (res?.trace) {
        ws.showTrace(res.trace, `${f.code} - test ${res.test_id}`);
        return;
      }
      const facts = findingCounterexample(f);
      if (facts) {
        try {
          ws.showTrace(await simulate.mutateAsync(facts), `${f.code} - witness ${formatFacts(facts)}`);
        } catch (e) {
          toast({ title: "Could not simulate witness", body: e instanceof Error ? e.message : String(e), tone: "error" });
        }
        return;
      }
      // Fall back to any failing trace that touches the finding's node.
      const node = findingNodeId(f);
      const any = ws.testrun?.results.find((r) => r.trace && r.trace.steps.some((s) => s.node_id === node)) ?? ws.testrun?.results.find((r) => r.trace && r.verdict === "fail");
      if (any?.trace) ws.showTrace(any.trace, `${f.code} - nearest failing test ${any.test_id}`);
      else toast({ title: "No witness trace for this finding", body: "It is a static finding, so there is no execution to replay.", tone: "info" });
    },
  };
}

const FILTERS: { id: Severity | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "error", label: "Errors" },
  { id: "warning", label: "Warnings" },
  { id: "info", label: "Info" },
];

export default function ProblemsPanel() {
  const ws = useWorkspace();
  const qc = useQueryClient();
  const guard = useWriteGuard();
  const toast = useToast();
  const trace = useShowFindingTrace();
  const taxonomy = useTaxonomy();
  const [filter, setFilter] = useState<Severity | "all">("all");
  const list = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => ws.findings.filter((f) => filter === "all" || f.severity === filter), [ws.findings, filter]);

  const triage = useMutation({
    mutationFn: ({ id, t }: { id: string; t: FindingTriage }) => api.updateFindingTriage(ws.runId, id, t),
    onMutate: async ({ id, t }) => {
      await qc.cancelQueries({ queryKey: ["findings", ws.runId] });
      const prev = qc.getQueryData(["findings", ws.runId]);
      qc.setQueryData(["findings", ws.runId], (old: { findings: AggregatedFinding[] } | undefined) =>
        old ? { ...old, findings: old.findings.map((f) => (f.id === id ? { ...f, triage: t } : f)) } : old,
      );
      return { prev };
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(["findings", ws.runId], ctx?.prev);
      toast({ title: "Could not update triage", body: e instanceof Error ? e.message : String(e), tone: "error" });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["findings", ws.runId] }),
  });

  const idx = rows.findIndex((f) => f.id === ws.selectedFindingId);

  useEffect(() => {
    if (ws.selectedFindingId) document.getElementById(`finding-${ws.selectedFindingId}`)?.scrollIntoView({ block: "nearest" });
  }, [ws.selectedFindingId]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("select, button, a, input, textarea")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const n = rows[Math.min(idx + 1, rows.length - 1)];
      if (n) ws.selectFinding(n.id);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const n = rows[Math.max(idx - 1, 0)];
      if (n) ws.selectFinding(n.id);
    } else if (e.key === "Enter" && rows[idx]) {
      e.preventDefault();
      ws.selectFinding(rows[idx].id);
    } else if ((e.key === "f" || e.key === "F") && rows[idx] && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      ws.openExplain(rows[idx].id);
    } else if ((e.key === "t" || e.key === "T") && rows[idx]) {
      e.preventDefault();
      void trace.show(rows[idx]);
    }
  };

  if (ws.loading) return <div className="p-4"><SkeletonList rows={5} /></div>;
  if (ws.findingsError)
    return (
      <EmptyState
        title="Analysis results are not available for this run"
        art="search"
        action={<Button variant="secondary" icon="refresh" onClick={ws.refetchAll}>Retry</Button>}
      >
        {ws.findingsError instanceof Error ? ws.findingsError.message : "The findings could not be loaded."}
      </EmptyState>
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-1.5">
        <div className="flex gap-1" role="group" aria-label="Filter by severity">
          {FILTERS.map((f) => {
            const count = f.id === "all" ? ws.findings.length : ws.findings.filter((x) => x.severity === f.id).length;
            return (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                aria-pressed={filter === f.id}
                className={cx(
                  "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                  filter === f.id ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200",
                )}
              >
                {f.label} <span className="tabular-nums opacity-80">{count}</span>
              </button>
            );
          })}
        </div>
        <p className="ml-auto hidden items-center gap-1.5 text-[11px] text-slate-500 md:flex">
          <Kbd>↑</Kbd><Kbd>↓</Kbd> move <Kbd>Enter</Kbd> select <Kbd>T</Kbd> trace <Kbd>F</Kbd> explain &amp; fix
        </p>
      </div>
      {rows.length === 0 ? (
        <EmptyState title={ws.findings.length ? "Nothing in this filter" : "No problems found"} art="check">
          {ws.findings.length ? "Try another severity filter." : "The compiler found no findings in this procedure. Ship it."}
        </EmptyState>
      ) : (
        <div
          ref={list}
          role="listbox"
          tabIndex={0}
          aria-label="Problems"
          aria-activedescendant={ws.selectedFindingId ? `finding-${ws.selectedFindingId}` : undefined}
          onKeyDown={onKey}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {rows.map((f) => {
            const selected = f.id === ws.selectedFindingId;
            const node = ws.flow?.nodes.find((n) => n.id === findingNodeId(f));
            const ranges = findingRanges(f, ws.diagnostics, ws.flow);
            const clauses = clauseLabel(f, ws.flow, ws.ast, ranges);
            const ce = findingCounterexample(f);
            const closed = f.triage !== "open";
            const title = f.title && f.title !== f.code ? f.title : (taxonomy.get(f.code)?.title ?? f.title);
            const detail = f.evidence.find((e) => e.kind !== "test_failure")?.message ?? f.evidence[0]?.message;
            return (
              <div
                key={f.id}
                id={`finding-${f.id}`}
                role="option"
                aria-selected={selected}
                onClick={() => ws.selectFinding(f.id)}
                className={cx(
                  "cursor-pointer border-b border-slate-100 px-3 py-2.5 transition-colors duration-150 last:border-0",
                  selected ? "bg-indigo-50 shadow-[inset_3px_0_0_var(--color-indigo-500)]" : "hover:bg-slate-50",
                  closed && "opacity-70",
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5"><SeverityIcon severity={f.severity} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <CodeChip code={f.code} tone={f.severity === "error" ? "red" : f.severity === "warning" ? "amber" : "slate"} />
                      <span className={cx("text-sm font-medium text-slate-900", closed && "line-through")}>{title}</span>
                      {f.confidence_tier !== "deterministic" && (
                        <span className="rounded bg-slate-100 px-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-600">{f.confidence_tier}</span>
                      )}
                    </div>
                    {detail && detail !== title && <p className="mt-0.5 text-xs text-slate-700">{detail}</p>}
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-600">
                      {node && (
                        <span className="min-w-0 max-w-full truncate">
                          at <span className="font-mono">{node.number ?? node.id}</span> {node.label}
                        </span>
                      )}
                      {clauses.map((c) => (
                        <span key={c} className="rounded bg-slate-100 px-1.5 font-mono text-[11px] text-slate-700">{c}</span>
                      ))}
                    </p>
                    {f.clause_quote && <blockquote className="mt-1 border-l-2 border-slate-300 pl-2 text-xs italic text-slate-600">{f.clause_quote}</blockquote>}
                    {ce && (
                      <p className="mt-1.5 inline-flex max-w-full items-start gap-1.5 rounded-md bg-slate-100 px-2 py-1 font-mono text-[11.5px] text-slate-800">
                        <span className="font-sans text-[10px] font-semibold uppercase tracking-wide text-slate-500">counterexample</span>
                        <span className="break-all">{formatFacts(ce)}</span>
                      </p>
                    )}
                    {f.suggested_fix && <p className="mt-1 text-xs text-emerald-700"><span className="font-semibold">Suggested fix:</span> {f.suggested_fix}</p>}
                    {selected && (
                      <div className="mt-2 flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <Button size="sm" variant="secondary" icon="play" onClick={() => void trace.show(f)} disabled={trace.pending}>
                          Show trace
                        </Button>
                        <Button size="sm" icon="wand" onClick={() => guard(() => ws.openExplain(f.id), "Sign in to generate and apply fixes")}>
                          Explain &amp; fix
                        </Button>
                        <span className="flex gap-2 lg:hidden">
                          <Button size="sm" variant="secondary" icon="git" onClick={() => ws.setTab("flow")}>Flowchart</Button>
                          <Button size="sm" variant="secondary" icon="file" onClick={() => ws.setTab("doc")}>Clause</Button>
                        </span>
                        <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-600">
                          Triage
                          <select
                            value={f.triage}
                            onChange={(e) => guard(() => triage.mutate({ id: f.id, t: e.target.value as FindingTriage }), "Sign in to triage findings")}
                            className="rounded-md border border-slate-300 bg-white px-1.5 py-1 text-xs text-slate-800"
                          >
                            {TRIAGE_UI.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                            {!TRIAGE_UI.some((o) => o.value === f.triage) && <option value={f.triage}>{f.triage}</option>}
                          </select>
                        </label>
                      </div>
                    )}
                  </div>
                  {!selected && (
                    <Icon name="chevronRight" size={14} className="mt-1 shrink-0 text-slate-400" />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
