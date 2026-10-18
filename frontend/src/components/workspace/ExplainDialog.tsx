import { useMutation, useQuery } from "@tanstack/react-query";
import { diffWords } from "diff";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError, api, type ExplainPatch } from "../../api";
import { findingCounterexample, formatFacts } from "../../lib/workspace";
import { Icon } from "../icons";
import { Button, CodeChip, Dialog, ErrorNote, Skeleton, Spinner, cx, useTaxonomy } from "../ui";
import { useWorkspace } from "./ctx";

type PatchStatus = "pending" | "accepted" | "rejected";

export function savePatchesForReport(runId: string, patches: { original_text: string; new_text: string; code?: string }[]) {
  try {
    sessionStorage.setItem(`policyc.patches.${runId}`, JSON.stringify(patches));
  } catch {
    /* storage full / disabled */
  }
}
export function loadPatchesForReport(runId: string): { original_text: string; new_text: string; code?: string }[] {
  try {
    return JSON.parse(sessionStorage.getItem(`policyc.patches.${runId}`) ?? "[]");
  } catch {
    return [];
  }
}

function WordDiff({ a, b }: { a: string; b: string }) {
  const parts = useMemo(() => diffWords(a, b), [a, b]);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Current wording</p>
        <p className="rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-800 ring-1 ring-slate-200">
          {parts.filter((p) => !p.added).map((p, i) => (
            <span key={i} className={cx(p.removed && "rounded bg-red-100 px-0.5 text-red-800 line-through decoration-red-500")}>{p.value}</span>
          ))}
        </p>
      </div>
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Proposed wording</p>
        <p className="rounded-lg bg-slate-50 p-3 text-sm leading-relaxed text-slate-800 ring-1 ring-slate-200">
          {parts.filter((p) => !p.removed).map((p, i) => (
            <span key={i} className={cx(p.added && "rounded bg-emerald-100 px-0.5 font-medium text-emerald-800 underline decoration-emerald-500 underline-offset-2")}>{p.value}</span>
          ))}
        </p>
      </div>
    </div>
  );
}

function PatchCard({ patch, status, text, onStatus, onText }: {
  patch: ExplainPatch;
  status: PatchStatus;
  text: string;
  onStatus: (s: PatchStatus) => void;
  onText: (t: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className={cx("rounded-xl border p-3 transition-colors", status === "accepted" ? "border-emerald-300 bg-emerald-50/40" : status === "rejected" ? "border-slate-200 opacity-60" : "border-slate-200")}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {patch.clause_ref && <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{patch.clause_ref}</span>}
        <span className="min-w-0 flex-1 text-xs text-slate-600">{patch.rationale}</span>
        {status !== "pending" && (
          <span className={cx("inline-flex items-center gap-1 text-xs font-semibold", status === "accepted" ? "text-emerald-700" : "text-slate-600")}>
            <Icon name={status === "accepted" ? "checkCircle" : "x"} size={13} /> {status}
          </span>
        )}
      </div>
      {editing ? (
        <div>
          <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-500" htmlFor={`edit-${patch.id}`}>Edit proposed wording</label>
          <textarea id={`edit-${patch.id}`} value={text} onChange={(e) => onText(e.target.value)} rows={4} className="w-full rounded-lg border border-slate-300 bg-white p-2 text-sm" />
        </div>
      ) : (
        <WordDiff a={patch.original_text} b={text} />
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant={status === "accepted" ? "success" : "secondary"} icon="check" onClick={() => { onStatus("accepted"); setEditing(false); }}>Accept</Button>
        <Button size="sm" variant="secondary" icon="wand" onClick={() => setEditing((e) => !e)}>{editing ? "Preview diff" : "Edit"}</Button>
        <Button size="sm" variant="ghost" icon="x" onClick={() => { onStatus("rejected"); setEditing(false); }}>Reject</Button>
      </div>
    </div>
  );
}

export default function ExplainDialog() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const finding = ws.findings.find((f) => f.id === ws.explainFor);
  const open = !!finding;

  const explain = useQuery({
    queryKey: ["explain", ws.runId, ws.explainFor],
    queryFn: () => api.explainFinding(ws.runId, ws.explainFor!),
    enabled: open,
    staleTime: Infinity,
    retry: false,
  });

  const [status, setStatus] = useState<Record<string, PatchStatus>>({});
  const [texts, setTexts] = useState<Record<string, string>>({});
  useEffect(() => {
    setStatus({});
    setTexts({});
  }, [ws.explainFor]);

  const [compiling, setCompiling] = useState<{ runId: string; message: string } | null>(null);
  const apply = useMutation({
    mutationFn: async () => {
      const chosen = (explain.data?.patches ?? []).filter((p) => status[p.id] === "accepted");
      const payload = chosen.map((p) => ({ original_text: p.original_text, new_text: texts[p.id] ?? p.new_text }));
      const res = await api.applyPatches(ws.runId, payload);
      savePatchesForReport(res.run_id, payload.map((p) => ({ ...p, code: finding?.code })));
      setCompiling({ runId: res.run_id, message: "Recompiling the patched document..." });
      // Poll until the new run settles.
      for (let i = 0; i < 240; i++) {
        const r = await api.run(res.run_id);
        const last = r.events.at(-1);
        if (last) setCompiling({ runId: res.run_id, message: `${last.stage}: ${last.message}` });
        if (r.status === "succeeded") return res;
        if (r.status === "failed") throw new Error(r.error ?? "Recompilation failed");
        if (r.status === "paused") return res; // lands on the new run's own review prompt
        await new Promise((ok) => setTimeout(ok, 1500));
      }
      throw new Error("Timed out waiting for the recompile");
    },
    onSuccess: (res) => {
      ws.openExplain(null);
      setCompiling(null);
      navigate(`/runs/${res.run_id}?base=${res.base_run_id}`);
    },
    onError: () => setCompiling(null),
  });

  const patches = explain.data?.patches ?? [];
  const accepted = patches.filter((p) => status[p.id] === "accepted").length;
  const unavailable = explain.error instanceof ApiError && (explain.error.status === 404 || explain.error.status === 405 || explain.error.status === 501);
  const ce = finding ? findingCounterexample(finding) : null;
  const taxonomy = useTaxonomy();
  const title = finding ? (finding.title && finding.title !== finding.code ? finding.title : (taxonomy.get(finding.code)?.title ?? finding.title)) : "";
  const detail = finding?.evidence.find((e) => e.kind !== "test_failure")?.message;

  return (
    <Dialog
      open={open}
      onClose={() => !compiling && ws.openExplain(null)}
      wide
      title={
        <span className="flex flex-wrap items-center gap-2">
          <Icon name="wand" className="text-indigo-600" /> Explain &amp; fix {finding && <CodeChip code={finding.code} />}
        </span>
      }
      footer={
        compiling ? null : (
          <>
            <span className="mr-auto text-xs text-slate-500">{patches.length ? `${accepted} of ${patches.length} patch(es) accepted` : ""}</span>
            <Button variant="ghost" onClick={() => ws.openExplain(null)}>Close</Button>
            {patches.length > 1 && (
              <Button variant="secondary" onClick={() => setStatus(Object.fromEntries(patches.map((p) => [p.id, "accepted" as const])))}>Accept all</Button>
            )}
            <Button disabled={accepted === 0 || apply.isPending} onClick={() => apply.mutate()} icon="refresh">
              Apply {accepted || ""} &amp; recompile
            </Button>
          </>
        )
      }
    >
      {finding && (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-semibold text-slate-900">{title}</p>
            {detail && detail !== title && <p className="mt-0.5 text-sm text-slate-600">{detail}</p>}
          </div>
          {compiling ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center" role="status">
              <Spinner size={36} className="text-indigo-600" />
              <p className="text-sm font-semibold text-slate-900">Compiling the revised procedure</p>
              <p className="max-w-md break-words font-mono text-xs text-slate-600">{compiling.message}</p>
              <p className="text-xs text-slate-500">Parse, extract, analyse, generate tests, run tests. Usually under a minute.</p>
            </div>
          ) : explain.isLoading ? (
            <div className="space-y-3" role="status" aria-label="Generating explanation">
              <Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" />
              <Skeleton className="mt-4 h-24 w-full" />
              <p className="flex items-center gap-2 text-xs text-slate-500"><Spinner size={12} /> Gemini is drafting an explanation and fix...</p>
            </div>
          ) : unavailable ? (
            <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 ring-1 ring-amber-200">
              Explain &amp; fix is not available on this backend yet. {finding.suggested_fix && <>Suggested fix: {finding.suggested_fix}</>}
            </p>
          ) : explain.error ? (
            <ErrorNote error={explain.error} onRetry={() => void explain.refetch()} />
          ) : explain.data ? (
            <>
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">What is wrong</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-800">{explain.data.plain_explanation}</p>
                {ce && <p className="mt-2 inline-block rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800">counterexample: {formatFacts(ce)}</p>}
              </section>
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Impact</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-800">{explain.data.impact}</p>
              </section>
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Proposed patches</h3>
                {patches.length === 0 && <p className="text-sm text-slate-600">No automatic patch is proposed for this finding.</p>}
                <div className="space-y-3">
                  {patches.map((p) => (
                    <PatchCard
                      key={p.id}
                      patch={p}
                      status={status[p.id] ?? "pending"}
                      text={texts[p.id] ?? p.new_text}
                      onStatus={(s) => setStatus((x) => ({ ...x, [p.id]: s }))}
                      onText={(t) => setTexts((x) => ({ ...x, [p.id]: t }))}
                    />
                  ))}
                </div>
              </section>
            </>
          ) : null}
          <ErrorNote error={apply.error} />
        </div>
      )}
    </Dialog>
  );
}
