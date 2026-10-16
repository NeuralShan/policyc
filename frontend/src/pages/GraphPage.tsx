import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { api, type GraphNode, type GraphOut } from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

const NODE_TONES: Record<string, string> = {
  process: "bg-indigo-50 border-indigo-200 text-indigo-800",
  step: "bg-slate-50 border-slate-200 text-slate-800",
  decision: "bg-amber-50 border-amber-200 text-amber-800",
  role: "bg-emerald-50 border-emerald-200 text-emerald-700",
  artifact: "bg-sky-50 border-sky-200 text-sky-700",
  system: "bg-purple-50 border-purple-200 text-purple-700",
};

const WARNING_TONES: Record<string, "amber" | "red"> = {
  xd001_unresolved_ref: "amber",
  entity_merge_overlap: "amber",
  graph_validation_error: "red",
};

function NodeCard({ node }: { node: GraphNode }) {
  const cls = NODE_TONES[node.type] ?? NODE_TONES.step;
  return (
    <div className={cx("rounded border px-3 py-2 text-sm", cls)}>
      <span className="mr-2 font-medium">{node.data.label}</span>
      {node.data.modal && (
        <span className="text-xs opacity-60">[{node.data.modal}]</span>
      )}
      <Mono className="ml-1 text-xs opacity-50">{node.id}</Mono>
    </div>
  );
}

function ProcessSection({
  proc,
  nodes,
  edges,
}: {
  proc: GraphNode;
  nodes: GraphNode[];
  edges: GraphOut["edges"];
}) {
  const childIds = new Set(
    edges.filter((e) => e.source === proc.id).map((e) => e.target)
  );
  const children = nodes.filter((n) => childIds.has(n.id));

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Badge tone="blue">{proc.type}</Badge>
          {proc.data.label}
          <Mono className="text-xs text-slate-400">{proc.id}</Mono>
        </span>
      }
    >
      {children.length === 0 ? (
        <p className="text-sm text-slate-400 italic">No steps or decisions.</p>
      ) : (
        <div className="space-y-2">
          {children.map((child) => (
            <NodeCard key={child.id} node={child} />
          ))}
        </div>
      )}
    </Card>
  );
}

export function GraphPage() {
  const { runId = "" } = useParams();

  const query = useQuery({
    queryKey: ["run-graph", runId],
    queryFn: () => api.runGraph(runId),
  });

  if (query.isLoading) return <p className="p-8 text-slate-500">Loading graph…</p>;
  if (query.error) return <ErrorNote error={query.error} />;
  if (!query.data) return null;

  const { nodes, edges, stats, warnings, cypher_sha256 } = query.data;

  const processNodes = nodes.filter((n) => n.type === "process");
  const symbolNodes = nodes.filter((n) =>
    ["role", "artifact", "system"].includes(n.type)
  );
  const errorWarnings = warnings.filter((w) => w.severity === "error");

  return (
    <>
      <PageHeader
        title="Knowledge Graph"
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-600">
              {stats.nodes} nodes · {stats.edges} edges · {stats.merges} merge(s)
            </span>
            {stats.unresolved_refs > 0 && (
              <Badge tone="amber">{stats.unresolved_refs} unresolved ref(s)</Badge>
            )}
            {errorWarnings.length > 0 && (
              <Badge tone="red">{errorWarnings.length} graph error(s)</Badge>
            )}
          </span>
        }
        actions={
          <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
            ← Run
          </Link>
        }
      />

      <div className="grid gap-6 lg:grid-cols-4">
        {/* Stats sidebar */}
        <aside className="space-y-4 lg:col-span-1">
          <Card title="Stats">
            <dl className="space-y-1 text-sm">
              {(
                [
                  ["Processes", stats.processes],
                  ["Steps", stats.steps],
                  ["Decisions", stats.decisions],
                  ["Roles", stats.roles],
                  ["Artifacts", stats.artifacts],
                  ["Systems", stats.systems],
                  ["Entity merges", stats.merges],
                  ["Cross-refs", stats.cross_refs],
                  ["Unresolved refs", stats.unresolved_refs],
                ] as [string, number][]
              ).map(([label, count]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="font-medium text-slate-800">{count}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {cypher_sha256 && (
            <Card title=".cypher artifact">
              <p className="mb-3 text-xs text-slate-500 break-all">
                sha256: <Mono>{cypher_sha256.slice(0, 16)}…</Mono>
              </p>
              <a
                href={api.runCypherUrl(runId)}
                download={`run-${runId}.cypher`}
                className="inline-flex items-center rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Download .cypher
              </a>
            </Card>
          )}

          {symbolNodes.length > 0 && (
            <Card title="Symbols">
              <div className="space-y-1">
                {symbolNodes.map((n) => (
                  <NodeCard key={n.id} node={n} />
                ))}
              </div>
            </Card>
          )}
        </aside>

        {/* Main: processes + warnings */}
        <div className="space-y-6 lg:col-span-3">
          {processNodes.length === 0 ? (
            <Card title="Processes">
              <p className="text-sm text-slate-500">No processes in graph.</p>
            </Card>
          ) : (
            processNodes.map((proc) => (
              <ProcessSection key={proc.id} proc={proc} nodes={nodes} edges={edges} />
            ))
          )}

          {warnings.length > 0 && (
            <Card title={`Warnings (${warnings.length})`}>
              <ul className="space-y-2">
                {warnings.map((w, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Badge tone={WARNING_TONES[w.code] ?? "amber"}>{w.code}</Badge>
                    <span className="text-slate-700">{w.message}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
