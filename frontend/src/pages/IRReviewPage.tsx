import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";

import { api, type IRReviewOut, type IrDecision, type IrProcess, type IrStep, type IrWarning } from "../api";
import { PageHeader } from "../components/Layout";
import {
  Badge,
  Card,
  ErrorNote,
  Mono,
  cx,
} from "../components/ui";

const WARNING_CODES: Record<string, "amber" | "red"> = {
  xd004_candidate: "amber",
  roundtrip_missing: "amber",
  roundtrip_wrong: "red",
  roundtrip_hallucinated: "red",
  validation_error: "red",
  ungrounded_step: "red",
  ungrounded_decision: "red",
  symbol_ungrounded: "amber",
  structure_pass_failed: "red",
  symbol_pass_failed: "amber",
};

function ModalBadge({ modal }: { modal: string }) {
  const color =
    modal === "shall" || modal === "must"
      ? "red"
      : modal === "should"
        ? "amber"
        : modal === "may"
          ? "blue"
          : "slate";
  return <Badge tone={color as "red" | "amber" | "blue" | "slate"}>{modal}</Badge>;
}

function StepCard({ step, symbols }: { step: IrStep; symbols: IRReviewOut["ir"]["symbols"] }) {
  const actor =
    step.actor_role_id
      ? (symbols.roles.find((r) => r.id === step.actor_role_id)?.name ?? step.actor_role_id)
      : step.actor_raw ?? "(no actor)";

  const lowConf = step.extraction_confidence < 0.7;

  return (
    <div
      className={cx(
        "rounded-md border p-3",
        lowConf ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Mono className="text-xs text-slate-500">{step.id}</Mono>
        {step.number && <Mono className="text-xs">{step.number}</Mono>}
        <Badge tone="blue">{step.kind}</Badge>
        <ModalBadge modal={step.modal} />
        <span className="font-medium text-slate-900">{actor}</span>
        <span className="text-slate-700">→</span>
        <span className="text-slate-900">{step.action}</span>
        {lowConf && (
          <Badge tone="amber" title={`confidence ${step.extraction_confidence.toFixed(2)}`}>
            low confidence
          </Badge>
        )}
      </div>
      {step.sla && (
        <p className="mt-1 text-xs text-slate-600">
          SLA:{" "}
          {step.sla.vague
            ? <span className="text-amber-700">{step.sla.vague_text ?? "vague"}</span>
            : `${step.sla.max_duration} ${step.sla.unit}`}
        </p>
      )}
      {step.note && <p className="mt-1 text-xs text-amber-700">{step.note}</p>}
      {step.source_spans.length > 0 && (
        <p className="mt-1 text-xs text-slate-500 italic">
          &quot;{step.source_spans[0].quote}&quot;
        </p>
      )}
    </div>
  );
}

function DecisionCard({ decision }: { decision: IrDecision }) {
  return (
    <div className="rounded-md border border-violet-200 bg-violet-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Mono className="text-xs text-slate-500">{decision.id}</Mono>
        <Badge tone="violet">decision</Badge>
        <span className="font-medium text-slate-900">{decision.question}</span>
      </div>
      <ul className="mt-2 space-y-1">
        {decision.branches.map((b, i) => (
          <li key={i} className="flex items-center gap-2 text-sm text-slate-700">
            <span className="font-medium">{b.label}</span>
            <span className="text-slate-500">→</span>
            <Mono className="text-xs">{b.next_step_id}</Mono>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ProcessPanel({
  process,
  symbols,
}: {
  process: IrProcess;
  symbols: IRReviewOut["ir"]["symbols"];
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {process.steps.map((s) => (
          <StepCard key={s.id} step={s} symbols={symbols} />
        ))}
        {process.decisions.map((d) => (
          <DecisionCard key={d.id} decision={d} />
        ))}
      </div>
      {process.references.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            External references
          </p>
          <ul className="space-y-1 text-sm">
            {process.references.map((r, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="text-slate-700">{r.ref_text}</span>
                {!r.resolved && <Badge tone="amber">unresolved</Badge>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SymbolsPanel({ symbols }: { symbols: IRReviewOut["ir"]["symbols"] }) {
  return (
    <div className="space-y-4">
      {symbols.roles.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Roles</p>
          <div className="flex flex-wrap gap-1.5">
            {symbols.roles.map((r) => <Badge key={r.id} tone="blue">{r.name}</Badge>)}
          </div>
        </div>
      )}
      {symbols.artifacts.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Artifacts</p>
          <div className="flex flex-wrap gap-1.5">
            {symbols.artifacts.map((a) => (
              <Badge key={a.id} tone="emerald">
                {a.name}{a.abbreviation ? ` (${a.abbreviation})` : ""}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {symbols.systems.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Systems</p>
          <div className="flex flex-wrap gap-1.5">
            {symbols.systems.map((s) => <Badge key={s.id} tone="violet">{s.name}</Badge>)}
          </div>
        </div>
      )}
    </div>
  );
}

function WarningsList({ warnings }: { warnings: IrWarning[] }) {
  if (!warnings.length) return <p className="text-sm text-slate-500">No warnings.</p>;
  return (
    <ul className="space-y-1.5">
      {warnings.map((w, i) => (
        <li key={i} className="flex items-start gap-2 text-sm">
          <Badge tone={WARNING_CODES[w.code] ?? "slate"}>{w.code}</Badge>
          <span className="text-slate-700">{w.message}</span>
        </li>
      ))}
    </ul>
  );
}

export function IRReviewPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const ir = useQuery({
    queryKey: ["run-ir", runId],
    queryFn: () => api.runIr(runId),
  });

  const review = useMutation({
    mutationFn: (approved: boolean) =>
      api.reviewIr(runId, approved, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      navigate(`/runs/${runId}`);
    },
  });

  if (ir.isLoading) return <p className="p-8 text-slate-500">Loading IR…</p>;
  if (ir.error) return <ErrorNote error={ir.error} />;
  if (!ir.data) return null;

  const data = ir.data;
  const sopIR = data.ir;

  return (
    <>
      <PageHeader
        title="IR Review"
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Badge tone={data.review_status === "approved" ? "emerald" : data.review_status === "rejected" ? "red" : "amber"}>
              {data.review_status}
            </Badge>
            <span className="text-sm text-slate-600">
              {data.stats.steps ?? 0} steps · {data.stats.decisions ?? 0} decisions ·{" "}
              {data.stats.warnings ?? 0} warning(s)
            </span>
          </span>
        }
        actions={
          <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
             Run
          </Link>
        }
      />

      <ErrorNote error={review.error} />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: Symbol table */}
        <div className="lg:col-span-1">
          <Card title="Glossary">
            <SymbolsPanel symbols={sopIR.symbols} />
          </Card>
        </div>

        {/* Right: Processes + warnings */}
        <div className="space-y-6 lg:col-span-2">
          {sopIR.processes.length === 0 ? (
            <Card title="Processes">
              <p className="text-sm text-slate-500">No processes extracted.</p>
            </Card>
          ) : (
            sopIR.processes.map((p) => (
              <Card key={p.id} title={<span>{p.name} <Mono className="text-xs text-slate-500">{p.id}</Mono></span>}>
                <ProcessPanel process={p} symbols={sopIR.symbols} />
              </Card>
            ))
          )}

          <Card title={`Extraction warnings (${data.warnings.length})`}>
            <WarningsList warnings={data.warnings} />
          </Card>

          {/* Review actions */}
          {data.review_status === "pending" && (
            <Card title="Your decision">
              <p className="mb-4 text-sm text-slate-700">
                Review the extracted IR above. If the steps and decisions look correct, approve to
                continue. If the extraction is wrong, reject and fix the source document or
                re-extract.
              </p>
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => review.mutate(true)}
                  disabled={review.isPending}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {review.isPending ? "Approving…" : "Approve & continue"}
                </button>
                <button
                  onClick={() => review.mutate(false)}
                  disabled={review.isPending}
                  className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  {review.isPending ? "Rejecting…" : "Reject"}
                </button>
              </div>
            </Card>
          )}

          {data.review_status !== "pending" && (
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
              This IR was <strong>{data.review_status}</strong>.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
