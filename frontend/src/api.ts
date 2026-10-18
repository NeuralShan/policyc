// Typed client for the FastAPI backend. Types mirror backend/app/schemas/api.py.

export type RunStatus = "queued" | "running" | "paused" | "succeeded" | "failed";
export type StageEventStatus = "started" | "progress" | "completed" | "failed";

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  document_count: number;
  run_count: number;
}

export interface DocumentInfo {
  id: string;
  project_id: string;
  filename: string;
  media_type: string;
  sha256: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface UploadResult extends DocumentInfo {
  duplicate: boolean;
}

export interface ParseStats {
  pages: number;
  nodes: number;
  headings: number;
  tables: number;
  figures: number;
  diagrams: number;
  ocr_pages: number;
  vision_corrected: number;
  warnings: number;
  doc_class: DocClass | null;
}

export interface DocumentWithParse extends DocumentInfo {
  parsed: { ast_id: string; run_id: string | null; created_at: string; complete: boolean; stats: ParseStats } | null;
}

// DocAST (backend/app/schemas/docast.py)
export type NodeKind = "title" | "heading" | "paragraph" | "list_item" | "table" | "figure" | "note";
export type TextSource = "native" | "ocr" | "ocr_verified" | "vision";
export type DocClass = "procedural" | "normative" | "descriptive" | "mixed" | "other";

export interface BBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface SourceSpan {
  document_id: string;
  page: number | null;
  bbox: BBox | null;
  char_start: number | null;
  char_end: number | null;
  quote: string;
}

export interface TableCell {
  row: number;
  col: number;
  row_span: number;
  col_span: number;
  text: string;
  column_header: boolean;
  row_header: boolean;
}

export interface DiagramGraph {
  title: string | null;
  lanes: string[];
  nodes: { id: string; label: string; kind: string; lane: string | null }[];
  edges: { source: string; target: string; label: string | null }[];
}

export interface FigureData {
  image_key: string | null;
  caption: string | null;
  diagram_status: "skipped" | "pending" | "not_a_diagram" | "extracted";
  description: string | null;
  diagram: DiagramGraph | null;
}

export interface DocNode {
  id: string;
  kind: NodeKind;
  parent_id: string | null;
  level: number | null;
  number: string | null;
  text: string;
  spans: SourceSpan[];
  text_source: TextSource;
  alt_text: string | null;
  table: { num_rows: number; num_cols: number; cells: TableCell[] } | null;
  figure: FigureData | null;
}

export interface GroundedValue {
  value: string;
  quote: string;
}

export interface DocumentProfile {
  doc_class: DocClass;
  rationale: string;
  title: GroundedValue | null;
  document_code: GroundedValue | null;
  version: GroundedValue | null;
  effective_date: GroundedValue | null;
  owner: GroundedValue | null;
  model: string;
}

export interface IngestWarning {
  code: string;
  message: string;
  node_id: string | null;
  page: number | null;
}

export interface DocAST {
  document_id: string;
  filename: string;
  media_type: string;
  parser: string;
  pages: { page_no: number; width: number; height: number; text_source: TextSource }[];
  text: string;
  nodes: DocNode[];
  furniture: string[];
  profile: DocumentProfile | null;
  warnings: IngestWarning[];
}

export interface Run {
  id: string;
  project_id: string;
  status: RunStatus;
  document_ids: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEvent {
  id: number;
  stage: string;
  status: StageEventStatus;
  message: string;
  created_at: string;
}

export interface RunDetail extends Run {
  artifacts: Record<string, unknown>;
  events: RunEvent[];
}

export interface Stage {
  key: string;
  label: string;
  layer: number;
  compiler_analogy: string;
  description: string;
  implemented: boolean;
}

export interface GapCode {
  code: string;
  category: string;
  title: string;
  default_severity: "error" | "warning" | "info";
  layer: number;
  tier: "deterministic" | "historical" | "judgment";
}

// SOP IR types (backend/app/schemas/ir_sop.py)
export interface IrStep {
  id: string;
  kind: string;
  number: string | null;
  actor_role_id: string | null;
  actor_raw: string | null;
  modal: string;
  action: string;
  inputs: string[];
  outputs: string[];
  systems: string[];
  sla: { max_duration: number; unit: string; vague: boolean; vague_text: string | null } | null;
  source_spans: SourceSpan[];
  extraction_confidence: number;
  note: string | null;
}

export interface IrDecision {
  id: string;
  question: string;
  preceding_step_id: string;
  branches: { label: string; next_step_id: string; condition: Record<string, unknown> }[];
  source_spans: SourceSpan[];
  extraction_confidence: number;
}

export interface IrProcess {
  id: string;
  name: string;
  document_id: string;
  steps: IrStep[];
  decisions: IrDecision[];
  references: { ref_text: string; doc_code: string | null; resolved: boolean }[];
}

export interface IrWarning {
  code: string;
  message: string;
  step_id: string | null;
  decision_id: string | null;
}

export interface IrRole { id: string; name: string; }
export interface IrArtifact { id: string; name: string; abbreviation: string | null; }
export interface IrSystem { id: string; name: string; }

export interface SopIR {
  schema_version: number;
  run_id: string;
  document_ids: string[];
  symbols: { roles: IrRole[]; artifacts: IrArtifact[]; systems: IrSystem[]; terms: unknown[] };
  processes: IrProcess[];
  warnings: IrWarning[];
  review_status: "pending" | "approved" | "rejected";
  extraction_stats: Record<string, number>;
}

export interface IRReviewOut {
  ir_id: string;
  review_status: string;
  stats: Record<string, number>;
  warnings: IrWarning[];
  ir: SopIR;
}

export interface GraphNode {
  id: string;
  type: "process" | "step" | "decision" | "role" | "artifact" | "system";
  data: { label: string; modal?: string | null };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface GraphStats {
  nodes: number;
  edges: number;
  processes: number;
  steps: number;
  decisions: number;
  roles: number;
  artifacts: number;
  systems: number;
  merges: number;
  cross_refs: number;
  unresolved_refs: number;
  warnings: number;
}

export interface GraphWarning {
  code: string;
  severity: string;
  message: string;
}

export interface GraphOut {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: GraphStats;
  warnings: GraphWarning[];
  cypher_sha256: string | null;
}

// Diagnostics / Layer 4
export type DiagnosticSeverity = "error" | "warning" | "info";
export type CheckTier = "deterministic" | "language";

export interface Diagnostic {
  code: string;
  severity: DiagnosticSeverity;
  message: string;
  process_id: string | null;
  step_id: string | null;
  decision_id: string | null;
  source_spans: SourceSpan[];
  evidence: Record<string, unknown>;
  check_tier: CheckTier;
}

export interface DiagnosticsReport {
  run_id: string;
  diagnostics: Diagnostic[];
  stats: Record<string, number>;
}

// Layer 6 — test generation
export type TestOrigin = "boundary" | "path" | "branch" | "fault";

export interface TestCase {
  id: string;
  description: string;
  origin: TestOrigin;
  process_id: string;
  scenario: {
    id: string;
    description: string;
    process_id: string | null;
    facts: Record<string, unknown>;
    actor_overrides: Record<string, string | null>;
    system_overrides: Record<string, boolean>;
  };
  expected_outcome: TraceOutcome | null;
  expected_branch: string | null;
  expected_decision_id: string | null;
  tags: string[];
}

export interface TestSuite {
  version: number;
  run_id: string;
  test_cases: TestCase[];
  stats: Record<string, number>;
}

// Layer 5 — process simulator
export type TraceOutcome =
  | "completed"
  | "dead_end"
  | "undetermined"
  | "conflict"
  | "ambiguous"
  | "loop_detected"
  | "max_steps";
export type DecisionOutcome = "determined" | "undetermined" | "conflict" | "ambiguous";
export type StepStatus = "ok" | "sla_breached" | "actor_unavailable" | "system_down" | "input_missing";

export interface TraceStep {
  seq: number;
  node_id: string;
  node_kind: "step" | "decision" | "terminal";
  process_id: string;
  action: string | null;
  actor: string | null;
  step_status: StepStatus | null;
  decision_outcome: DecisionOutcome | null;
  branch_taken: string | null;
  sla_max_s: number | null;
  elapsed_s: number;
  sla_ok: boolean | null;
  note: string | null;
}

export interface ExecutionTrace {
  version: number;
  run_id: string;
  process_id: string;
  scenario_id: string;
  steps: TraceStep[];
  outcome: TraceOutcome;
  elapsed_s: number;
  sla_breaches: number;
  actor_unavailable_count: number;
  system_down_count: number;
}

export interface SimulateRequest {
  scenario_id?: string;
  description?: string;
  process_id?: string | null;
  facts?: Record<string, unknown>;
  actor_overrides?: Record<string, string | null>;
  system_overrides?: Record<string, boolean>;
}

export interface TraceSummary {
  id: string;
  scenario_id: string;
  process_id: string;
  outcome: TraceOutcome;
  created_at: string;
}

// Layer 7 — test execution & oracle
export type TestVerdict = "pass" | "fail" | "skip";
export type FailReason =
  | "expected_outcome_mismatch"
  | "structural_gap"
  | "sla_breach"
  | "actor_unavailable";

export interface TestResult {
  test_id: string;
  verdict: TestVerdict;
  fail_reasons: FailReason[];
  trace: ExecutionTrace | null;
  skip_reason: string | null;
}

export interface CoverageReport {
  steps_total: number;
  steps_covered: number;
  step_coverage_pct: number;
  decisions_total: number;
  decisions_covered: number;
  decision_coverage_pct: number;
  branches_total: number;
  branches_covered: number;
  branch_coverage_pct: number;
  uncovered_step_ids: string[];
  uncovered_branch_keys: string[];
}

export interface TestRunReport {
  version: number;
  run_id: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  results: TestResult[];
  coverage: CoverageReport;
  stats: Record<string, number>;
}

// Layer 8 — reality / conformance checking
export interface ColumnMap {
  case_id: string;
  activity: string;
  timestamp: string;
  resource: string | null;
}

export interface CaseHistorySummary {
  source_filename: string;
  stats: { total_cases: number; total_events: number; unique_activities: number };
  column_map: ColumnMap;
}

export interface CaseResult {
  case_id: string;
  fitness: number;
  synced: string[];
  skipped: string[];
  extra: string[];
  sla_breaches: string[];
  has_no_path: boolean;
}

export interface RlFinding {
  code: string;
  message: string;
  step_id: string | null;
  activity: string | null;
  case_count: number;
  rate: number;
}

export interface RealityReport {
  version: number;
  run_id: string;
  source_filename: string;
  total_cases: number;
  conformant_cases: number;
  avg_fitness: number;
  case_results: CaseResult[];
  rl_findings: RlFinding[];
  extra_activity_counts: Record<string, number>;
  stats: Record<string, number | string>;
}

// Layer 9 — findings, scoring & remediation
export type ConfidenceTier = "deterministic" | "historical" | "judgment";
export type FindingTriage = "open" | "accepted" | "false_positive" | "wont_fix" | "fixed";

export interface EvidenceItem {
  kind: "diagnostic" | "test_failure" | "rl_finding";
  code: string;
  message: string;
  process_id?: string | null;
  step_id?: string | null;
  decision_id?: string | null;
  test_id?: string | null;
  fail_reason?: string | null;
  case_count?: number | null;
  rate?: number | null;
  counterexample?: Record<string, unknown> | null;
  witness?: Record<string, unknown> | null;
}

export interface RiskScore {
  likelihood: number;
  impact: number;
  confidence_weight: number;
  total: number;
}

export interface AggregatedFinding {
  id: string;
  code: string;
  title: string;
  severity: "error" | "warning" | "info";
  confidence_tier: ConfidenceTier;
  triage: FindingTriage;
  process_id: string | null;
  step_id: string | null;
  decision_id: string | null;
  evidence: EvidenceItem[];
  risk: RiskScore;
  rank: number;
  // Optional fields the backend may add; always read defensively.
  witness?: Record<string, unknown> | string | null;
  clause_quote?: string | null;
  suggested_fix?: string | null;
  fingerprint?: string | null;
}

export interface FindingsReport {
  version: number;
  run_id: string;
  findings: AggregatedFinding[];
  stats: Record<string, unknown>;
}


// --- Demo workspace contract (samples, flow, health, explain/fix, regression) -------------------
export interface Sample {
  id: string;
  title: string;
  description: string;
  industry: string;
  planted_bugs: number;
  precomputed: boolean;
  language?: string;
}

export interface MeInfo {
  auth_enabled: boolean;
  uid: string | null;
  email: string | null;
  name: string | null;
  picture: string | null;
}

export interface FlowNode {
  id: string;
  kind: "step" | "decision" | "terminal";
  label: string;
  number: string | null;
  actor: string | null;
  modal: string | null;
  quote: string | null;
  char_start: number | null;
  char_end: number | null;
  document_id: string | null;
  severity: "error" | "warning" | "info" | null;
  finding_ids: string[];
  codes: string[];
  inferred: boolean;
  unreachable?: boolean;
}
export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  label: string | null;
  kind: "flow" | "branch";
  inferred: boolean;
}
export interface FlowGraph {
  run_id: string;
  process_id: string;
  entry: string | null;
  nodes: FlowNode[];
  edges: FlowEdge[];
}

export interface Health {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  errors: number;
  warnings: number;
  infos: number;
  tests: { total: number; passed: number; failed: number };
  coverage: { steps: number; decisions: number; branches: number };
}

export interface ExplainPatch {
  id: string;
  clause_ref: string | null;
  original_text: string;
  new_text: string;
  rationale: string;
}
export interface Explanation {
  finding_id: string;
  plain_explanation: string;
  impact: string;
  patches: ExplainPatch[];
}
export interface ApplyPatchesResult {
  run_id: string;
  base_run_id: string;
  document_id: string;
}
export interface FindingSummary {
  id: string;
  code: string;
  title: string;
  severity: "error" | "warning" | "info";
  step_id: string | null;
}
export interface Regression {
  base_run_id: string;
  run_id: string;
  counts: { fixed: number; new: number; remaining: number };
  fixed: FindingSummary[];
  new: FindingSummary[];
  remaining: FindingSummary[];
  health: { before: number; after: number };
}

export const ACCEPTED_SOURCE_TYPES = [".pdf", ".docx", ".html", ".htm", ".md", ".txt"];

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/** Error thrown for every non-2xx response; `status` lets callers special-case 404/401. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// --- auth plumbing (set by auth/AuthProvider) -------------------------------------------------
let tokenProvider: (() => Promise<string | null>) | null = null;
export function setTokenProvider(fn: (() => Promise<string | null>) | null) {
  tokenProvider = fn;
}
const unauthorizedListeners = new Set<(message: string) => void>();
export function onUnauthorized(fn: (message: string) => void) {
  unauthorizedListeners.add(fn);
  return () => {
    unauthorizedListeners.delete(fn);
  };
}
export async function currentToken(): Promise<string | null> {
  try {
    return tokenProvider ? await tokenProvider() : null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await currentToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(API_BASE + path, { ...init, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep the status line
    }
    if (response.status === 401) unauthorizedListeners.forEach((fn) => fn(detail));
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

async function requestText(path: string): Promise<string> {
  const token = await currentToken();
  const response = await fetch(API_BASE + path, token ? { headers: { Authorization: `Bearer ${token}` } } : undefined);
  if (!response.ok) throw new ApiError(`${response.status} ${response.statusText}`, response.status);
  return response.text();
}

/** Run an optional endpoint; a 404 (feature not deployed / nothing yet) resolves to null. */
export async function orNull<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return null;
    throw e;
  }
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  stages: () => request<Stage[]>("/api/pipeline/stages"),
  taxonomy: () => request<GapCode[]>("/api/taxonomy"),

  projects: () => request<Project[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, description: string) =>
    request<Project>("/api/projects", json({ name, description })),

  documents: (projectId: string) =>
    request<DocumentWithParse[]>(`/api/projects/${projectId}/documents`),
  document: (id: string) => request<DocumentWithParse>(`/api/documents/${id}`),
  documentAst: (id: string) => request<DocAST>(`/api/documents/${id}/ast`),
  figureUrl: (documentId: string, nodeId: string) => `${API_BASE}/api/documents/${documentId}/figures/${nodeId}`,
  uploadDocuments: (projectId: string, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<UploadResult[]>(`/api/projects/${projectId}/documents`, {
      method: "POST",
      body: form,
    });
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  documentFileUrl: (id: string) => `${API_BASE}/api/documents/${id}/file`,

  runs: (projectId: string) => request<Run[]>(`/api/projects/${projectId}/runs`),
  run: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  startRun: (projectId: string, autoApprove = true) =>
    request<Run>(`/api/projects/${projectId}/runs`, json({ auto_approve: autoApprove })),
  /** SSE cannot send headers, so the id token travels as a query parameter. */
  runEventsUrl: async (id: string) => {
    const token = await currentToken();
    return `${API_BASE}/api/runs/${id}/events${token ? `?access_token=${encodeURIComponent(token)}` : ""}`;
  },

  runIr: (runId: string) => request<IRReviewOut>(`/api/runs/${runId}/ir`),
  reviewIr: (runId: string, approved: boolean, overrides: Record<string, unknown> = {}) =>
    request<Run>(`/api/runs/${runId}/ir/review`, json({ approved, overrides })),

  runGraph: (runId: string) => request<GraphOut>(`/api/runs/${runId}/graph`),
  runCypherUrl: (runId: string) => `${API_BASE}/api/runs/${runId}/cypher`,

  runDiagnostics: (runId: string) => request<DiagnosticsReport>(`/api/runs/${runId}/diagnostics`),

  runTestcases: (runId: string) => request<TestSuite>(`/api/runs/${runId}/testcases`),

  simulate: (runId: string, body: SimulateRequest) =>
    request<ExecutionTrace>(`/api/runs/${runId}/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  runTraces: (runId: string) => request<TraceSummary[]>(`/api/runs/${runId}/traces`),

  runTestrun: (runId: string) => request<TestRunReport>(`/api/runs/${runId}/testrun`),

  // Layer 8 — reality / conformance checking
  uploadCaseHistory: (
    runId: string,
    file: File,
    opts: { case_id_col?: string; activity_col?: string; timestamp_col?: string; resource_col?: string } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    const params = new URLSearchParams();
    if (opts.case_id_col) params.set("case_id_col", opts.case_id_col);
    if (opts.activity_col) params.set("activity_col", opts.activity_col);
    if (opts.timestamp_col) params.set("timestamp_col", opts.timestamp_col);
    if (opts.resource_col) params.set("resource_col", opts.resource_col);
    const qs = params.toString();
    return request<CaseHistorySummary>(
      `/api/runs/${runId}/case-history${qs ? "?" + qs : ""}`,
      { method: "POST", body: form },
    );
  },
  caseHistory: (runId: string) => request<CaseHistorySummary>(`/api/runs/${runId}/case-history`),
  runRealityCheck: (runId: string) => request<RealityReport>(
    `/api/runs/${runId}/reality`, { method: "POST" }
  ),
  realityReport: (runId: string) => orNull(request<RealityReport>(`/api/runs/${runId}/reality`)),

  // Layer 9 — findings
  runFindings: (runId: string) => request<FindingsReport>(`/api/runs/${runId}/findings`),
  updateFindingTriage: (runId: string, findingId: string, triage: FindingTriage) =>
    request<FindingsReport>(
      `/api/runs/${runId}/findings/${findingId}/triage`,
      { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ triage }) },
    ),

  // --- workspace contract ---
  me: () => request<MeInfo>("/api/me"),
  samples: () => request<Sample[]>("/api/samples"),
  runSample: (id: string, live = false) =>
    request<{ project_id: string; run_id: string; cached: boolean }>(
      `/api/samples/${id}/run?live=${live}`,
      { method: "POST" },
    ),
  runFlow: (runId: string) => request<FlowGraph>(`/api/runs/${runId}/flow`),
  runHealth: (runId: string) => request<Health>(`/api/runs/${runId}/health`),
  explainFinding: (runId: string, findingId: string) =>
    request<Explanation>(`/api/runs/${runId}/findings/${findingId}/explain`, { method: "POST" }),
  applyPatches: (runId: string, patches: { original_text: string; new_text: string }[]) =>
    request<ApplyPatchesResult>(`/api/runs/${runId}/apply-patches`, json({ patches })),
  regression: (runId: string, baseRunId: string) =>
    request<Regression>(`/api/runs/${runId}/regression?base=${encodeURIComponent(baseRunId)}`),
  reportText: (runId: string, format: "md" | "html") =>
    requestText(`/api/runs/${runId}/report?format=${format}`),
};
