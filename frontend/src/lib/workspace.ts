import type {
  AggregatedFinding,
  DocAST,
  DocNode,
  Diagnostic,
  FlowEdge,
  FlowGraph,
  FlowNode,
  Health,
  SopIR,
  TestRunReport,
} from "../api";

export interface CharRange {
  start: number;
  end: number;
}

const SEV_RANK = { error: 3, warning: 2, info: 1 } as const;
export const severityRank = (s: string | null | undefined) => SEV_RANK[s as keyof typeof SEV_RANK] ?? 0;

/** Counterexample facts for a finding, read defensively from every place the backend may put them. */
export function findingCounterexample(f: AggregatedFinding): Record<string, unknown> | null {
  const w = f.witness;
  if (w && typeof w === "object" && Object.keys(w).length) {
    const facts = (w as Record<string, unknown>).facts;
    return facts && typeof facts === "object" ? (facts as Record<string, unknown>) : (w as Record<string, unknown>);
  }
  for (const e of f.evidence) {
    const c = e.counterexample ?? e.witness;
    if (c && typeof c === "object" && Object.keys(c).length) return c;
  }
  return null;
}

export function formatFacts(facts: Record<string, unknown>) {
  return Object.entries(facts)
    .map(([k, v]) => `${k} = ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
}

/** Test ids referenced by a finding's evidence (used to find a failing trace for "Show trace"). */
export function findingTestIds(f: AggregatedFinding): string[] {
  return [...new Set(f.evidence.map((e) => e.test_id).filter((x): x is string => !!x))];
}

export function findingNodeId(f: AggregatedFinding) {
  return f.step_id ?? f.decision_id ?? null;
}

/* ------------------------------------------------------------ flow fallback */
function condLabel(c: Record<string, unknown> | undefined, fallback: string): string {
  if (!c || c.kind === "always" || c.kind === "unknown") return fallback;
  if (c.kind === "compare") {
    const ops: Record<string, string> = { gt: ">", gte: ">=", lt: "<", lte: "<=", eq: "=", ne: "!=", in: "in", not_in: "not in" };
    const right = c.right ?? c.value;
    return `${c.left} ${ops[c.op as string] ?? c.op} ${typeof right === "string" ? right : JSON.stringify(right)}`;
  }
  if (c.kind === "vague") return String(c.text ?? fallback);
  return fallback;
}

/** Build a flow graph from the extracted IR when GET /flow is not available. */
export function buildFlowFromIr(runId: string, ir: SopIR): FlowGraph | null {
  const proc = ir.processes[0];
  if (!proc) return null;
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const preceding = new Set(proc.decisions.map((d) => d.preceding_step_id));
  const span = (spans: { document_id: string; char_start: number | null; char_end: number | null; quote: string }[]) => spans[0];
  const actor = (s: (typeof proc.steps)[number]) => ir.symbols.roles.find((r) => r.id === s.actor_role_id)?.name ?? s.actor_raw;

  proc.steps.forEach((s, i) => {
    const sp = span(s.source_spans);
    nodes.push({
      id: s.id,
      kind: s.kind === "terminal" ? "terminal" : "step",
      label: s.action,
      number: s.number,
      actor: actor(s) ?? null,
      modal: s.modal,
      quote: sp?.quote ?? null,
      char_start: sp?.char_start ?? null,
      char_end: sp?.char_end ?? null,
      document_id: sp?.document_id ?? proc.document_id,
      severity: null,
      finding_ids: [],
      codes: [],
      inferred: false,
    });
    const next = proc.steps[i + 1];
    if (next && !preceding.has(s.id)) {
      edges.push({ id: `${s.id}->${next.id}`, source: s.id, target: next.id, label: null, kind: "flow", inferred: true });
    }
  });
  let needEnd = !preceding.has(proc.steps.at(-1)?.id ?? "");
  proc.decisions.forEach((d) => {
    const sp = span(d.source_spans);
    nodes.push({
      id: d.id,
      kind: "decision",
      label: d.question,
      number: null,
      actor: null,
      modal: null,
      quote: sp?.quote ?? null,
      char_start: sp?.char_start ?? null,
      char_end: sp?.char_end ?? null,
      document_id: sp?.document_id ?? proc.document_id,
      severity: null,
      finding_ids: [],
      codes: [],
      inferred: false,
    });
    edges.push({ id: `${d.preceding_step_id}->${d.id}`, source: d.preceding_step_id, target: d.id, label: null, kind: "flow", inferred: false });
    d.branches.forEach((b, bi) => {
      const target = b.next_step_id === "END" || !b.next_step_id ? "END" : b.next_step_id;
      if (target === "END") needEnd = true;
      edges.push({
        id: `${d.id}#${bi}`,
        source: d.id,
        target,
        label: condLabel(b.condition, b.label || "otherwise"),
        kind: "branch",
        inferred: false,
      });
    });
  });
  if (needEnd || proc.steps.length) {
    nodes.push({
      id: "END", kind: "terminal", label: "End", number: null, actor: null, modal: null, quote: null,
      char_start: null, char_end: null, document_id: null, severity: null, finding_ids: [], codes: [], inferred: true,
    });
    const last = proc.steps.at(-1);
    if (last && !preceding.has(last.id)) edges.push({ id: `${last.id}->END`, source: last.id, target: "END", label: null, kind: "flow", inferred: true });
  }
  const ids = new Set(nodes.map((n) => n.id));
  return {
    run_id: runId,
    process_id: proc.id,
    entry: proc.steps[0]?.id ?? null,
    nodes,
    edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
  };
}

/** Overlay findings on a flow (severity/codes/finding ids) and mark unreachable nodes. */
export function decorateFlow(flow: FlowGraph, findings: AggregatedFinding[]): FlowGraph {
  const byNode = new Map<string, AggregatedFinding[]>();
  for (const f of findings) {
    const id = findingNodeId(f);
    if (id) byNode.set(id, [...(byNode.get(id) ?? []), f]);
  }
  const reach = new Set<string>();
  if (flow.entry) {
    const adj = new Map<string, string[]>();
    flow.edges.forEach((e) => adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]));
    const stack = [flow.entry];
    while (stack.length) {
      const n = stack.pop()!;
      if (reach.has(n)) continue;
      reach.add(n);
      stack.push(...(adj.get(n) ?? []));
    }
  }
  const nodes = flow.nodes.map((n) => {
    const fs = byNode.get(n.id) ?? [];
    const sev = fs.reduce<FlowNode["severity"]>((acc, f) => (severityRank(f.severity) > severityRank(acc) ? f.severity : acc), n.severity);
    const ids = [...new Set([...n.finding_ids, ...fs.map((f) => f.id)])];
    const codes = [...new Set([...n.codes, ...fs.map((f) => f.code)])];
    return { ...n, severity: sev, finding_ids: ids, codes, unreachable: n.unreachable ?? (flow.entry ? !reach.has(n.id) : false) };
  });
  return { ...flow, nodes };
}

/* ------------------------------------------------------------------ health */
export function deriveHealth(findings: AggregatedFinding[], testrun: TestRunReport | null | undefined): Health {
  const errors = findings.filter((f) => f.severity === "error").length;
  const warnings = findings.filter((f) => f.severity === "warning").length;
  const infos = findings.filter((f) => f.severity === "info").length;
  const score = Math.max(0, Math.min(100, Math.round(100 - errors * 7 - warnings * 3 - infos * 0.5)));
  const grade = score >= 90 ? "A" : score >= 80 ? "B" : score >= 70 ? "C" : score >= 60 ? "D" : "F";
  return {
    score,
    grade,
    errors,
    warnings,
    infos,
    tests: { total: testrun?.total ?? 0, passed: testrun?.passed ?? 0, failed: testrun?.failed ?? 0 },
    coverage: {
      steps: (testrun?.coverage.step_coverage_pct ?? 0) / 100,
      decisions: (testrun?.coverage.decision_coverage_pct ?? 0) / 100,
      branches: (testrun?.coverage.branch_coverage_pct ?? 0) / 100,
    },
  };
}

/* ------------------------------------------------------------- doc / clause */
export function rangesOverlap(a: CharRange, b: CharRange) {
  return a.start < b.end && b.start < a.end;
}

export function nodeRanges(n: DocNode): CharRange[] {
  return n.spans
    .filter((s) => s.char_start != null && s.char_end != null)
    .map((s) => ({ start: s.char_start as number, end: s.char_end as number }));
}

export function nodeOverlaps(n: DocNode, ranges: CharRange[]) {
  const nr = nodeRanges(n);
  return nr.some((a) => ranges.some((b) => rangesOverlap(a, b)));
}

/** Char ranges of a finding: diagnostics with matching code+location first, then the flow node's range. */
export function findingRanges(f: AggregatedFinding, diagnostics: Diagnostic[], flow: FlowGraph | undefined): CharRange[] {
  const out: CharRange[] = [];
  const codes = new Set(f.evidence.map((e) => e.code).concat(f.code));
  for (const d of diagnostics) {
    if (!codes.has(d.code)) continue;
    if ((f.step_id && d.step_id !== f.step_id) || (!f.step_id && f.decision_id && d.decision_id !== f.decision_id)) continue;
    for (const s of d.source_spans) if (s.char_start != null && s.char_end != null) out.push({ start: s.char_start, end: s.char_end });
  }
  if (!out.length) {
    const n = flow?.nodes.find((x) => x.id === findingNodeId(f));
    if (n?.char_start != null && n.char_end != null) out.push({ start: n.char_start, end: n.char_end });
  }
  return out;
}

export function nodeRange(n: FlowNode | undefined): CharRange[] {
  return n && n.char_start != null && n.char_end != null ? [{ start: n.char_start, end: n.char_end }] : [];
}

export function clauseLabel(f: AggregatedFinding, flow: FlowGraph | undefined, ast: DocAST | undefined, ranges: CharRange[]): string[] {
  const labels = new Set<string>();
  const n = flow?.nodes.find((x) => x.id === findingNodeId(f));
  if (n?.number) labels.add(`§${n.number}`);
  if (ast && ranges.length) {
    for (const dn of ast.nodes) if (dn.number && nodeOverlaps(dn, ranges)) labels.add(`§${dn.number}`);
  }
  return [...labels].slice(0, 3);
}

export function titleCase(s: string) {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Variables that appear in decision conditions of the IR (used to build the simulator facts form). */
export function irVariables(ir: SopIR | undefined): { name: string; ops: Set<string>; samples: unknown[] }[] {
  const vars = new Map<string, { ops: Set<string>; samples: unknown[] }>();
  const walk = (c: unknown) => {
    if (!c || typeof c !== "object") return;
    const o = c as Record<string, unknown>;
    if (o.kind === "compare" && typeof o.left === "string") {
      const v = vars.get(o.left) ?? { ops: new Set<string>(), samples: [] };
      v.ops.add(String(o.op));
      const right = o.right ?? o.value;
      if (right !== undefined) {
        if (Array.isArray(right)) v.samples.push(...right);
        else v.samples.push(right);
      }
      vars.set(o.left, v);
    }
    for (const val of Object.values(o)) {
      if (Array.isArray(val)) val.forEach(walk);
      else if (val && typeof val === "object") walk(val);
    }
  };
  ir?.processes.forEach((p) => p.decisions.forEach((d) => d.branches.forEach((b) => walk(b.condition))));
  return [...vars.entries()].map(([name, v]) => ({ name, ...v }));
}
