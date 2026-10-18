import { Link } from "react-router";

import { Icon, type IconName } from "../components/icons";
import { Badge, Card, CodeChip } from "../components/ui";

const LAYERS: { icon: IconName; title: string; who: "Gemini" | "Engine"; body: string }[] = [
  { icon: "file", title: "Ingest", who: "Gemini", body: "Parses PDF, DOCX and Markdown into numbered clauses with exact character spans, using OCR and vision only where the text layer is missing." },
  { icon: "code", title: "Extract", who: "Gemini", body: "Translates prose into a process model: steps, actors, decisions, thresholds and SLAs. Every element keeps a pointer back to its source clause." },
  { icon: "warning", title: "Static analysis", who: "Engine", body: "Graph and Z3 checks find dead ends, unreachable steps, overlapping or missing branches, vague terms and undefined roles. Deterministic, with a witness." },
  { icon: "flask", title: "Test generation", who: "Engine", body: "An SMT solver generates boundary and branch tests, so a rule like \"under 10,000\" is tested at 9,999, 10,000 and 10,001." },
  { icon: "play", title: "Simulation", who: "Engine", body: "Every generated case is executed over the model. Cases that get stuck, loop or hit a conflict become findings with a replayable trace." },
  { icon: "database", title: "Reality check", who: "Engine", body: "Upload real case logs and measure conformance: where do people skip steps, add steps, or breach SLAs?" },
];

export function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-10">
      <header className="space-y-3">
        <Badge tone="indigo" icon="info">About / How it works</Badge>
        <h1 className="text-balance text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Gemini translates. The engine proves.</h1>
        <p className="text-lg leading-relaxed text-slate-700">
          Software gets compiled and tested before it ships. The procedures that run banks, factories and hospitals never do. PolicyC compiles them.
        </p>
      </header>

      <Card>
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900"><Icon name="sparkles" className="text-indigo-600" /> What Gemini does</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-700">
              Language models are excellent translators and unreliable judges. Gemini is used only to turn messy prose into a structured process model, and to draft
              plain-English explanations and candidate rewrites. It never decides whether a procedure is correct.
            </p>
          </div>
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900"><Icon name="shield" className="text-emerald-600" /> What the engine does</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-700">
              Every verdict comes from deterministic code: graph analysis, an SMT solver and a simulator. Each finding carries a code, the source clause, a concrete
              counterexample and a suggested fix, so you can check the claim yourself instead of trusting a model.
            </p>
          </div>
        </div>
      </Card>

      <section>
        <h2 className="mb-4 text-xl font-semibold text-slate-900">The pipeline, like a compiler</h2>
        <ol className="space-y-3">
          {LAYERS.map((l, i) => (
            <li key={l.title} className="flex gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-700"><Icon name={l.icon} size={18} /></span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-500">L{i + 1}</span>
                  <h3 className="font-semibold text-slate-900">{l.title}</h3>
                  <Badge tone={l.who === "Gemini" ? "violet" : "green"} icon={l.who === "Gemini" ? "sparkles" : "shield"}>{l.who === "Gemini" ? "Gemini translates" : "Engine proves"}</Badge>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-slate-700">{l.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-slate-900">Reading a finding</h2>
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Icon name="error" className="text-red-600" /> <CodeChip code="ST005" tone="red" /> <span className="font-medium text-slate-900">Overlapping branches</span>
          </div>
          <p className="mt-2 inline-block rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-800">counterexample: amount = 10000, requester_role = staff</p>
          <p className="mt-2 text-sm text-slate-700">
            Codes are grouped by layer. Hover any code in the app to see its meaning, or browse them all in the{" "}
            <Link to="/gap-codes" className="font-medium text-indigo-700 hover:underline">gap code catalogue</Link>.
            Severity is always shown as an icon plus a word, never colour alone.
          </p>
        </div>
      </section>

      <p className="pb-6 text-center"><Link to="/" className="font-medium text-indigo-700 hover:underline">Back home and try a sample</Link></p>
    </div>
  );
}
