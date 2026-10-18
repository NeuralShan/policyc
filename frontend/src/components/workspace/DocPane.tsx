import { Fragment, useEffect, useMemo, useRef } from "react";
import { Link } from "react-router";

import type { DocNode, FlowNode } from "../../api";
import { nodeOverlaps, nodeRanges, rangesOverlap, severityRank } from "../../lib/workspace";
import { Icon } from "../icons";
import { EmptyState, SkeletonList, cx } from "../ui";
import { useWorkspace } from "./ctx";

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function Text({ text, vague }: { text: string; vague: RegExp | null }) {
  if (!vague) return <>{text}</>;
  const parts = text.split(vague);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className="vague-underline" title="Vague phrase: not testable as written">
            {p}
          </span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

function TableView({ node, vague }: { node: DocNode; vague: RegExp | null }) {
  const t = node.table;
  if (!t) return <Text text={node.text} vague={vague} />;
  const rows: Record<number, typeof t.cells> = {};
  t.cells.forEach((c) => (rows[c.row] = [...(rows[c.row] ?? []), c]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <tbody>
          {Object.entries(rows).map(([r, cells]) => (
            <tr key={r}>
              {cells
                .sort((a, b) => a.col - b.col)
                .map((c) => {
                  const Tag = c.column_header || c.row_header ? "th" : "td";
                  return (
                    <Tag
                      key={`${c.row}-${c.col}`}
                      colSpan={c.col_span}
                      rowSpan={c.row_span}
                      className={cx("border border-slate-200 px-2 py-1 text-left align-top", Tag === "th" && "bg-slate-50 font-semibold")}
                    >
                      <Text text={c.text} vague={vague} />
                    </Tag>
                  );
                })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DocPane() {
  const ws = useWorkspace();
  const container = useRef<HTMLDivElement>(null);

  const vague = useMemo(() => {
    const phrases = new Set<string>();
    ws.diagnostics.forEach((d) => {
      const v = d.evidence?.vague_text;
      if (typeof v === "string" && v.length > 2) phrases.add(v);
    });
    ws.ir?.processes.forEach((p) => p.steps.forEach((s) => s.sla?.vague_text && phrases.add(s.sla.vague_text)));
    if (!phrases.size) return null;
    return new RegExp(`(${[...phrases].sort((a, b) => b.length - a.length).map(escapeRe).join("|")})`, "gi");
  }, [ws.diagnostics, ws.ir]);

  const nodes = ws.ast?.nodes ?? [];

  // Which flow nodes (and findings) belong to which clause.
  const flowByClause = useMemo(() => {
    const m = new Map<string, FlowNode[]>();
    if (!ws.flow) return m;
    for (const dn of nodes) {
      const rs = nodeRanges(dn);
      if (!rs.length) continue;
      const hits = ws.flow.nodes.filter(
        (fn) => fn.char_start != null && fn.char_end != null && rs.some((r) => rangesOverlap(r, { start: fn.char_start!, end: fn.char_end! })),
      );
      if (hits.length) m.set(dn.id, hits);
    }
    return m;
  }, [nodes, ws.flow]);

  const firstHl = nodes.find((n) => ws.highlight.length && nodeOverlaps(n, ws.highlight));
  useEffect(() => {
    if (!firstHl) return;
    document.getElementById(`clause-${firstHl.id}`)?.scrollIntoView({ block: "center", behavior: ws.reducedMotion ? "auto" : "smooth" });
  }, [firstHl, ws.reducedMotion]);

  if (!ws.documentId) return <EmptyState title="No document" art="doc" />;
  if (!ws.ast)
    return (
      <div className="p-4">
        <SkeletonList rows={8} />
      </div>
    );

  return (
    <div ref={container} className="h-full overflow-y-auto" role="region" aria-label="Source document, numbered clauses" tabIndex={0}>
      <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 glass">
        <p className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-slate-700">
          <Icon name="file" size={14} className="shrink-0 text-slate-500" />
          <span className="truncate">{ws.ast.filename}</span>
        </p>
        <Link to={`/documents/${ws.documentId}`} className="shrink-0 text-xs font-medium text-indigo-700 hover:underline">
          Open PDF
        </Link>
      </div>
      <ol className="space-y-0.5 p-2">
        {nodes.map((n, idx) => {
          const hl = ws.highlight.length > 0 && nodeOverlaps(n, ws.highlight);
          const linked = flowByClause.get(n.id) ?? [];
          const sev = linked.reduce<string | null>((a, f) => (severityRank(f.severity) > severityRank(a) ? f.severity : a), null);
          const selectedHere = linked.some((f) => f.id === ws.selectedNodeId);
          const heading = n.kind === "title" || n.kind === "heading";
          const clickable = linked.length > 0;
          return (
            <li key={n.id}>
              <div
                id={`clause-${n.id}`}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                aria-pressed={clickable ? hl || selectedHere : undefined}
                onClick={clickable ? () => ws.selectNode(linked[0].id, nodeRanges(n)) : undefined}
                onKeyDown={clickable ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), ws.selectNode(linked[0].id, nodeRanges(n))) : undefined}
                className={cx(
                  "group relative flex gap-2 rounded-md px-2 py-1.5 transition-colors duration-150",
                  clickable && "cursor-pointer hover:bg-slate-100",
                  (hl || selectedHere) && "clause-hl",
                  heading ? "mt-2" : "",
                )}
              >
                <span className="w-9 shrink-0 select-none pt-0.5 text-right font-mono text-[10px] leading-5 text-slate-500">
                  {n.number ?? (heading ? "" : idx + 1)}
                </span>
                <div
                  className={cx(
                    "min-w-0 flex-1 break-words",
                    n.kind === "title" && "text-base font-bold text-slate-900",
                    n.kind === "heading" && "text-sm font-semibold text-slate-900",
                    !heading && "text-[13px] leading-relaxed text-slate-800",
                    n.kind === "list_item" && "pl-1",
                  )}
                >
                  {n.kind === "table" ? <TableView node={n} vague={vague} /> : n.kind === "figure" ? (
                    <span className="italic text-slate-500">[Figure] {n.figure?.caption ?? n.text}</span>
                  ) : (
                    <Text text={n.text} vague={vague} />
                  )}
                </div>
                {sev && (
                  <span
                    className={cx("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", sev === "error" ? "bg-red-500" : sev === "warning" ? "bg-amber-500" : "bg-blue-500")}
                    title={`${sev} on this clause`}
                  >
                    <span className="sr-only">{sev} on this clause</span>
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
