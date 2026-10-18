import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { api, orNull } from "../../api";
import { findingCounterexample, findingNodeId, formatFacts } from "../../lib/workspace";
import { Button, useToast } from "../ui";
import { useWorkspace } from "./ctx";
import { loadPatchesForReport } from "./ExplainDialog";

function useReportData() {
  const ws = useWorkspace();
  const patches = loadPatchesForReport(ws.runId);
  const rows = ws.findings.map((f) => {
    const node = ws.flow?.nodes.find((n) => n.id === findingNodeId(f));
    const ce = findingCounterexample(f);
    return {
      f,
      step: node ? `${node.number ? node.number + " " : ""}${node.label}` : null,
      quote: f.clause_quote ?? node?.quote ?? null,
      ce: ce ? formatFacts(ce) : null,
    };
  });
  return { ws, patches, rows };
}

export function buildMarkdown(d: ReturnType<typeof useReportData>): string {
  const { ws, patches, rows } = d;
  const h = ws.health;
  const L: string[] = [];
  L.push(`# PolicyC audit report`, "");
  L.push(`- Document: ${ws.ast?.filename ?? ws.run.document_ids.join(", ")}`);
  L.push(`- Run: ${ws.runId}`, `- Generated: ${new Date().toLocaleString()}`);
  if (h) {
    L.push(`- Health score: **${h.score}/100 (grade ${h.grade})**`);
    L.push(`- Findings: ${h.errors} errors, ${h.warnings} warnings, ${h.infos} info`);
    L.push(`- Tests: ${h.tests.passed}/${h.tests.total} passed`);
  }
  L.push("", "## Findings", "");
  rows.forEach(({ f, step, quote, ce }, i) => {
    L.push(`### ${i + 1}. [${f.code}] ${f.title} (${f.severity})`);
    if (step) L.push(`- Step: ${step}`);
    if (quote) L.push(`- Clause: > ${quote}`);
    if (ce) L.push(`- Counterexample: \`${ce}\``);
    if (f.suggested_fix) L.push(`- Suggested fix: ${f.suggested_fix}`);
    L.push(`- Status: ${f.triage}`, "");
  });
  if (patches.length) {
    L.push("## Accepted patches", "");
    patches.forEach((p, i) => L.push(`${i + 1}. ${p.code ? `[${p.code}] ` : ""}~~${p.original_text}~~ -> **${p.new_text}**`));
  }
  L.push("", "_Gemini translates, the engine proves._");
  return L.join("\n");
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Hidden, print-only report that window.print() renders (the app shell is hidden by the print stylesheet). */
function PrintReport({ d }: { d: ReturnType<typeof useReportData> }) {
  const { ws, patches, rows } = d;
  const h = ws.health;
  return createPortal(
    <div className="print-only print-root" style={{ padding: 24 }}>
      <h1>PolicyC audit report</h1>
      <p>
        <strong>{ws.ast?.filename ?? ws.run.document_ids.join(", ")}</strong> - run {ws.runId} - {new Date().toLocaleString()}
      </p>
      {h && (
        <p>
          Health score <strong>{h.score}/100 (grade {h.grade})</strong>. {h.errors} errors, {h.warnings} warnings, {h.infos} info. Tests {h.tests.passed}/{h.tests.total} passed.
        </p>
      )}
      <h2>Findings ({rows.length})</h2>
      {rows.map(({ f, step, quote, ce }, i) => (
        <div className="finding" key={f.id}>
          <strong>
            {i + 1}. [{f.code}] {f.title}
          </strong>{" "}
          ({f.severity}, {f.triage})
          {step && <div>Step: {step}</div>}
          {quote && <blockquote style={{ margin: "4pt 0", paddingLeft: 8, borderLeft: "3px solid #999" }}>{quote}</blockquote>}
          {ce && <div style={{ fontFamily: "monospace" }}>Counterexample: {ce}</div>}
          {f.suggested_fix && <div>Suggested fix: {f.suggested_fix}</div>}
        </div>
      ))}
      {patches.length > 0 && (
        <>
          <h2>Accepted patches</h2>
          <ol>
            {patches.map((p, i) => (
              <li key={i}>
                <s>{p.original_text}</s> &rarr; <strong>{p.new_text}</strong>
              </li>
            ))}
          </ol>
        </>
      )}
      <p style={{ marginTop: 24, fontSize: "9pt", color: "#555" }}>Gemini translates, the engine proves.</p>
    </div>,
    document.body,
  );
}

export function ExportReportButton() {
  const d = useReportData();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      window.print();
      setOpen(false);
    }, 150);
    return () => clearTimeout(t);
  }, [open]);

  const downloadMd = async () => {
    setMenu(false);
    let text: string | null = null;
    try {
      text = await orNull(api.reportText(d.ws.runId, "md"));
    } catch {
      text = null;
    }
    download(`policyc-report-${d.ws.runId}.md`, text ?? buildMarkdown(d), "text/markdown");
    toast({ title: "Report downloaded", tone: "success" });
  };

  return (
    <div className="relative">
      <Button size="sm" variant="secondary" icon="download" onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu} disabled={!d.ws.ready}>
        <span className="hidden sm:inline">Export report</span>
        <span className="sm:hidden">Export</span>
      </Button>
      {menu && (
        <div role="menu" className="absolute right-0 top-full z-50 mt-1 w-56 animate-pop rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
          <button role="menuitem" className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100" onClick={() => { setMenu(false); setOpen(true); }}>
            <Icon2 /> Print / save as PDF
          </button>
          <button role="menuitem" className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100" onClick={() => void downloadMd()}>
            <Icon2 /> Download Markdown
          </button>
        </div>
      )}
      {open && <PrintReport d={d} />}
    </div>
  );
}

import { Icon } from "../icons";
function Icon2() {
  return <Icon name="file" size={14} />;
}
