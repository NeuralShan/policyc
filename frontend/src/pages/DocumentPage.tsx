import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { api, type DocAST, type DocNode, type TextSource } from "../api";
import { PageHeader } from "../components/Layout";
import { PdfViewer } from "../components/PdfViewer";
import { Badge, Card, Empty, ErrorNote, Mono, cx, type Tone } from "../components/ui";

const sourceBadge: Partial<Record<TextSource, { label: string; tone: Tone; title: string }>> = {
  ocr: { label: "OCR", tone: "amber", title: "Read by local OCR only; not cross-checked" },
  ocr_verified: { label: "OCR ✓", tone: "green", title: "Local OCR confirmed by an independent vision reading" },
  vision: { label: "vision", tone: "violet", title: "OCR and vision disagreed; the vision reading is used" },
};

const kindLabel: Record<DocNode["kind"], string> = {
  title: "Title",
  heading: "H",
  paragraph: "¶",
  list_item: "•",
  table: "Table",
  figure: "Figure",
  note: "Note",
};

export function DocumentPage() {
  const { documentId = "" } = useParams();
  const document = useQuery({ queryKey: ["document", documentId], queryFn: () => api.document(documentId) });
  const ast = useQuery({
    queryKey: ["ast", documentId],
    queryFn: () => api.documentAst(documentId),
    retry: false,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = ast.data?.nodes.find((n) => n.id === selectedId) ?? null;

  return (
    <>
      <PageHeader
        title={document.data?.filename ?? "Document"}
        subtitle={ast.data && <AstSummary ast={ast.data} />}
        actions={
          document.data && (
            <>
              <a href={api.documentFileUrl(documentId)} target="_blank" rel="noreferrer" className="text-sm text-slate-600 hover:text-slate-900">
                Original ↗
              </a>
              <Link to={`/projects/${document.data.project_id}`} className="text-sm text-slate-600 hover:text-slate-900">
                ← Project
              </Link>
            </>
          )
        }
      />
      <ErrorNote error={document.error} />
      {ast.isError && (
        <Card>
          <Empty>Not parsed yet. Run a compile from the project page to ingest this document.</Empty>
        </Card>
      )}
      {ast.data && (
        <div className="space-y-6">
          <Profile ast={ast.data} />
          <Warnings ast={ast.data} onSelect={setSelectedId} />
          <div className="grid gap-6 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <Card title={`Outline · ${ast.data.nodes.length} nodes`}>
                <Outline ast={ast.data} selectedId={selectedId} onSelect={setSelectedId} />
              </Card>
            </div>
            <div className="space-y-6 lg:col-span-3">
              {selected && <NodeDetail ast={ast.data} node={selected} />}
              <Card title="Source">
                {ast.data.media_type === "application/pdf" ? (
                  <PdfViewer url={api.documentFileUrl(documentId)} ast={ast.data} selectedId={selectedId} onSelect={setSelectedId} />
                ) : (
                  <TextView ast={ast.data} selectedId={selectedId} onSelect={setSelectedId} />
                )}
              </Card>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function AstSummary({ ast }: { ast: DocAST }) {
  const tables = ast.nodes.filter((n) => n.kind === "table").length;
  const figures = ast.nodes.filter((n) => n.kind === "figure").length;
  return (
    <span className="flex flex-wrap items-center gap-3">
      {ast.profile && <Badge tone="blue">{ast.profile.doc_class}</Badge>}
      {ast.pages.length > 0 && <span>{ast.pages.length} pages</span>}
      <span>{tables} tables</span>
      <span>{figures} figures</span>
      <Mono>{ast.parser}</Mono>
    </span>
  );
}

function Profile({ ast }: { ast: DocAST }) {
  const p = ast.profile;
  if (!p) return null;
  const fields = [
    ["Title", p.title],
    ["Document code", p.document_code],
    ["Version", p.version],
    ["Effective date", p.effective_date],
    ["Owner", p.owner],
  ] as const;
  return (
    <Card title="Profile">
      <p className="mb-3 text-sm text-slate-700">
        <Badge tone="blue">{p.doc_class}</Badge> <span className="ml-1">{p.rationale}</span>
      </p>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="text-slate-900">
              {value ? (
                <span title={`Evidence: “${value.quote}”`}>{value.value}</span>
              ) : (
                <span className="text-slate-400">not stated</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-slate-400">Hover a value to see its evidence quote · {p.model}</p>
    </Card>
  );
}

function Warnings({ ast, onSelect }: { ast: DocAST; onSelect: (id: string) => void }) {
  if (ast.warnings.length === 0) return null;
  return (
    <Card title={`Warnings · ${ast.warnings.length}`}>
      <ul className="space-y-1 text-sm">
        {ast.warnings.map((w, i) => (
          <li key={i} className="flex gap-2">
            <Mono>{w.code}</Mono>
            <span className="text-slate-700">{w.message}</span>
            {w.node_id && (
              <button type="button" className="text-xs text-sky-700 hover:underline" onClick={() => onSelect(w.node_id!)}>
                {w.node_id}
              </button>
            )}
            {w.page && <span className="text-xs text-slate-400">p{w.page}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function depths(ast: DocAST): Map<string, number> {
  const depth = new Map<string, number>();
  for (const n of ast.nodes) depth.set(n.id, n.parent_id ? (depth.get(n.parent_id) ?? 0) + 1 : 0);
  return depth;
}

function Outline({ ast, selectedId, onSelect }: {
  ast: DocAST;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const depth = depths(ast);
  const selectedRow = useRef<HTMLButtonElement>(null);
  useEffect(() => selectedRow.current?.scrollIntoView({ block: "nearest" }), [selectedId]);
  return (
    <div className="max-h-[75vh] overflow-y-auto pr-1">
      {ast.nodes.map((n) => {
        const badge = sourceBadge[n.text_source];
        const isHeading = n.kind === "title" || n.kind === "heading";
        return (
          <button
            key={n.id}
            ref={n.id === selectedId ? selectedRow : undefined}
            type="button"
            onClick={() => onSelect(n.id)}
            className={cx(
              "flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left text-sm",
              n.id === selectedId ? "bg-amber-100" : "hover:bg-slate-50",
            )}
            style={{ paddingLeft: 6 + (depth.get(n.id) ?? 0) * 14 }}
          >
            <span className="w-9 shrink-0 font-mono text-[10px] text-slate-400">{kindLabel[n.kind]}</span>
            <span className={cx("min-w-0 flex-1 truncate", isHeading ? "font-medium text-slate-900" : "text-slate-700")}>
              {n.text || <span className="text-slate-400">(no caption)</span>}
            </span>
            {badge && <Badge tone={badge.tone}>{badge.label}</Badge>}
          </button>
        );
      })}
    </div>
  );
}

function TextView({ ast, selectedId, onSelect }: {
  ast: DocAST;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const selectedBlock = useRef<HTMLDivElement>(null);
  useEffect(() => selectedBlock.current?.scrollIntoView({ block: "center", behavior: "smooth" }), [selectedId]);
  return (
    <div className="max-h-[75vh] space-y-2 overflow-y-auto">
      {ast.nodes.map((n) => (
        <div
          key={n.id}
          ref={n.id === selectedId ? selectedBlock : undefined}
          onClick={() => onSelect(n.id)}
          className={cx(
            "cursor-pointer rounded px-2 py-1",
            n.id === selectedId ? "bg-amber-100 ring-1 ring-amber-400" : "hover:bg-slate-50",
            n.kind === "title" && "text-lg font-semibold",
            n.kind === "heading" && "mt-3 font-semibold",
            n.kind === "list_item" && "pl-6 text-sm",
            n.kind === "paragraph" && "text-sm",
          )}
        >
          {n.kind === "table" && n.table ? (
            <TableGrid node={n} />
          ) : n.kind === "figure" ? (
            <Figure documentId={ast.document_id} node={n} />
          ) : (
            n.text
          )}
        </div>
      ))}
    </div>
  );
}

function TableGrid({ node }: { node: DocNode }) {
  const table = node.table!;
  const rows = Array.from({ length: table.num_rows }, (_, r) => table.cells.filter((c) => c.row === r));
  return (
    <table className="w-full border-collapse text-xs">
      <tbody>
        {rows.map((cells, r) => (
          <tr key={r}>
            {cells.map((c) => {
              const Cell = c.column_header || c.row_header ? "th" : "td";
              return (
                <Cell key={c.col} colSpan={c.col_span} rowSpan={c.row_span} className="border border-slate-200 px-2 py-1 text-left align-top">
                  {c.text}
                </Cell>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Figure({ documentId, node }: { documentId: string; node: DocNode }) {
  const figure = node.figure;
  return (
    <figure>
      {figure?.image_key && <img src={api.figureUrl(documentId, node.id)} alt={figure.caption ?? "figure"} className="max-h-96 border border-slate-200" />}
      <figcaption className="mt-1 text-xs text-slate-500">
        {node.text || "(no caption)"} · diagram: {figure?.diagram_status ?? "n/a"}
      </figcaption>
    </figure>
  );
}

function NodeDetail({ ast, node }: { ast: DocAST; node: DocNode }) {
  const badge = sourceBadge[node.text_source];
  const span = node.spans[0];
  const diagram = node.figure?.diagram;
  return (
    <Card title={<span className="flex items-center gap-2">Node <Mono>{node.id}</Mono></span>}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{node.kind}</Badge>
          {node.number && <Badge tone="slate">#{node.number}</Badge>}
          {node.level !== null && <Badge tone="slate">level {node.level}</Badge>}
          {badge && <span title={badge.title}><Badge tone={badge.tone}>{badge.label}</Badge></span>}
          {span?.page && <span className="text-xs text-slate-500">page {span.page}</span>}
          {span?.char_start !== null && span && (
            <Mono>chars {span.char_start}–{span.char_end}</Mono>
          )}
        </div>
        {node.kind === "table" ? <TableGrid node={node} /> : node.kind === "figure" ? (
          <Figure documentId={ast.document_id} node={node} />
        ) : (
          <p className="whitespace-pre-wrap text-slate-900">{node.text}</p>
        )}
        {node.alt_text && (
          <div className="rounded-md bg-violet-50 p-2 text-xs text-violet-900 ring-1 ring-violet-200">
            <div className="font-medium">Local OCR read this differently:</div>
            <div className="mt-1 font-mono">{node.alt_text}</div>
          </div>
        )}
        {node.figure?.description && <p className="text-xs text-slate-600">{node.figure.description}</p>}
        {diagram && (
          <div className="grid gap-3 text-xs sm:grid-cols-2">
            <div>
              <div className="mb-1 font-medium text-slate-700">Shapes ({diagram.nodes.length})</div>
              <ul className="space-y-0.5">
                {diagram.nodes.map((d) => (
                  <li key={d.id}>
                    <Mono>{d.id}</Mono> <Badge>{d.kind}</Badge> {d.label}
                    {d.lane && <span className="text-slate-400"> · {d.lane}</span>}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 font-medium text-slate-700">Arrows ({diagram.edges.length})</div>
              <ul className="space-y-0.5">
                {diagram.edges.map((e, i) => (
                  <li key={i}>
                    <Mono>{e.source} → {e.target}</Mono> {e.label && <span className="text-slate-600">“{e.label}”</span>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
