import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ACCEPTED_SOURCE_TYPES, api, orNull, type Sample } from "../api";
import { useAuth, useWriteGuard } from "../auth/AuthProvider";
import { Icon, type IconName } from "../components/icons";
import { Badge, Button, ErrorNote, Skeleton, Spinner, cx, formatDate, useToast } from "../components/ui";

const STEPS: { icon: IconName; title: string; body: string; tag: string }[] = [
  {
    icon: "code",
    title: "Compile",
    tag: "Gemini translates",
    body: "Upload a PDF, DOCX or Markdown SOP. Gemini reads it and extracts a process model: steps, actors, decisions, thresholds, each tied to the exact clause it came from.",
  },
  {
    icon: "flask",
    title: "Test",
    tag: "The engine proves",
    body: "A deterministic engine runs static analysis, solver-generated boundary tests and simulations over the model. Every finding comes with a counterexample, not an opinion.",
  },
  {
    icon: "wand",
    title: "Fix",
    tag: "You stay in control",
    body: "Click a finding, watch the failing case walk through the flowchart, review a word-level patch, accept it and recompile. You see exactly what got fixed and what regressed.",
  },
];

function SampleCard({ sample, busy, onTry }: { sample: Sample; busy: boolean; onTry: () => void }) {
  const icon: IconName = /bank|financ/i.test(sample.industry) ? "database" : /manufact|safety|industr/i.test(sample.industry) ? "shield" : "file";
  return (
    <article className="group flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
          <Icon name={icon} size={20} />
        </span>
        <Badge tone="slate">{sample.industry}</Badge>
      </div>
      <h3 className="mt-4 text-base font-semibold text-slate-900">{sample.title}</h3>
      <p className="mt-1 flex-1 text-sm leading-relaxed text-slate-600">{sample.description}</p>
      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-red-700 dark:text-red-400">
          <Icon name="flag" size={14} /> Planted bugs: <span className="tabular-nums">{sample.planted_bugs}</span>
        </span>
        <Button onClick={onTry} disabled={busy} aria-label={`Try the ${sample.title} sample`}>
          {busy ? <Spinner size={14} /> : null}
          {busy ? "Opening..." : "Try it"}
          {!busy && <Icon name="arrowRight" size={14} />}
        </Button>
      </div>
    </article>
  );
}

function DropZone() {
  const navigate = useNavigate();
  const guard = useWriteGuard();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [review, setReview] = useState(false);
  const [stage, setStage] = useState<string | null>(null);

  const go = useMutation({
    mutationFn: async (file: File) => {
      setStage("Creating project");
      const project = await api.createProject(file.name.replace(/\.[^.]+$/, ""), "Uploaded from the home page");
      setStage("Uploading document");
      await api.uploadDocuments(project.id, [file]);
      setStage("Starting compile");
      return api.startRun(project.id, !review);
    },
    onSuccess: (run) => navigate(`/runs/${run.id}`),
    onError: (e) => toast({ title: "Could not start the run", body: e instanceof Error ? e.message : String(e), tone: "error" }),
    onSettled: () => setStage(null),
  });

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (f) guard(() => go.mutate(f));
  };

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files); }}
        className={cx(
          "flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          drag ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white hover:border-indigo-300",
        )}
      >
        {go.isPending ? (
          <>
            <Spinner size={28} className="text-indigo-600" />
            <p className="mt-3 text-sm font-medium text-slate-800">{stage}...</p>
          </>
        ) : (
          <>
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-700"><Icon name="upload" size={22} /></span>
            <p className="mt-3 text-base font-semibold text-slate-900">Drop your own SOP here</p>
            <p className="mt-1 text-sm text-slate-600">PDF, DOCX, HTML, Markdown or text. We compile it and show you what is broken.</p>
            <input ref={input} type="file" accept={ACCEPTED_SOURCE_TYPES.join(",")} className="sr-only" onChange={(e) => { pick(e.target.files); e.target.value = ""; }} aria-label="Choose an SOP file to upload" />
            <Button className="mt-4" variant="secondary" icon="file" onClick={() => input.current?.click()}>Choose a file</Button>
            <label className="mt-4 flex cursor-pointer items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
              Review extraction before continuing
            </label>
          </>
        )}
      </div>
    </div>
  );
}

export function HomePage() {
  const navigate = useNavigate();
  const auth = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const samples = useQuery({ queryKey: ["samples"], queryFn: () => orNull(api.samples()), retry: false });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [busyId, setBusyId] = useState<string | null>(null);

  const runSample = useMutation({
    mutationFn: (id: string) => api.runSample(id, false),
    onMutate: (id) => setBusyId(id),
    onSuccess: (r) => navigate(`/runs/${r.run_id}`),
    onError: (e) => toast({ title: "Could not open the sample", body: e instanceof Error ? e.message : String(e), tone: "error" }),
    onSettled: () => setBusyId(null),
  });

  // Command palette deep link: /?sample=<id>
  const wanted = params.get("sample");
  useEffect(() => {
    if (!wanted) return;
    setParams({}, { replace: true });
    runSample.mutate(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted]);

  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const recent = [...(projects.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);

  return (
    <div className="space-y-14 sm:space-y-20">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white px-5 py-12 shadow-sm sm:px-12 sm:py-16">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-indigo-500/10 blur-3xl" />
        <div aria-hidden="true" className="pointer-events-none absolute -bottom-32 -left-16 h-72 w-72 rounded-full bg-indigo-400/10 blur-3xl" />
        <div className="relative mx-auto max-w-3xl text-center">
          <Badge tone="indigo" icon="sparkles">Google Cloud AI Builder Cup 2026</Badge>
          <h1 className="mt-5 text-balance text-3xl font-bold leading-tight tracking-tight text-slate-900 sm:text-5xl">
            Software gets compiled and tested before it ships.
            <span className="block text-slate-500">Your procedures never did.</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-pretty text-base leading-relaxed text-slate-700 sm:text-lg">
            The procedures that run banks, factories and hospitals never do. <strong className="font-semibold text-indigo-700">PolicyC compiles them</strong>:
            it finds the dead ends, contradictions and untestable clauses in your SOPs before an auditor, or an incident, does.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button size="lg" onClick={() => scrollTo("samples")} icon="sparkles">Try a sample</Button>
            <Button size="lg" variant="secondary" onClick={() => scrollTo("upload")} icon="upload">Upload your SOP</Button>
          </div>
          {auth.enabled && !auth.user && (
            <p className="mt-4 text-xs text-slate-500">You are browsing as a guest: samples are read-only, sign in to compile your own.</p>
          )}
        </div>
      </section>

      {/* How it works */}
      <section aria-labelledby="how" className="space-y-6">
        <div className="text-center">
          <h2 id="how" className="text-2xl font-bold tracking-tight text-slate-900">How it works</h2>
          <p className="mt-2 text-slate-600">
            <em className="not-italic font-semibold text-indigo-700">Gemini translates, the engine proves.</em> The model never decides whether your procedure is correct.
          </p>
        </div>
        <ol className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white"><Icon name={s.icon} size={20} /></span>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Step {i + 1}</p>
                  <h3 className="text-lg font-semibold text-slate-900">{s.title}</h3>
                </div>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-slate-700">{s.body}</p>
              <p className="mt-3 inline-flex rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">{s.tag}</p>
              {i < 2 && <Icon name="arrowRight" size={18} className="absolute -right-3.5 top-1/2 z-10 hidden -translate-y-1/2 rounded-full bg-white text-slate-400 md:block" />}
            </li>
          ))}
        </ol>
        <p className="text-center text-sm"><Link to="/about" className="font-medium text-indigo-700 hover:underline">Read the full story: what is checked and why you can trust it</Link></p>
      </section>

      {/* Samples */}
      <section id="samples" aria-labelledby="samples-h" className="scroll-mt-20 space-y-6">
        <div>
          <h2 id="samples-h" className="text-2xl font-bold tracking-tight text-slate-900">Try it on a real SOP with planted bugs</h2>
          <p className="mt-1 text-slate-600">One click opens the compiled result: flowchart, problems, counterexamples and fixes.</p>
        </div>
        {samples.isLoading ? (
          <div className="grid gap-4 md:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="space-y-3 rounded-2xl border border-slate-200 bg-white p-5"><Skeleton className="h-10 w-10" /><Skeleton className="h-5 w-2/3" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-4/5" /></div>)}</div>
        ) : samples.data ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {samples.data.map((s) => (
              <SampleCard key={s.id} sample={s} busy={busyId === s.id} onTry={() => {
                // Samples are public demos: guests may open them (cached results are read-only).
                runSample.mutate(s.id);
              }} />
            ))}
          </div>
        ) : (
          <div role="status" className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
            The sample library is not available on this server yet. Upload your own SOP below, or open an existing project.
          </div>
        )}
        <ErrorNote error={samples.error} onRetry={() => void samples.refetch()} />
      </section>

      {/* Upload + recent */}
      <section className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-5">
        <div id="upload" className="scroll-mt-20 lg:col-span-3">
          <h2 className="mb-3 text-lg font-semibold text-slate-900">Compile your own</h2>
          <DropZone />
        </div>
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Recent projects</h2>
            <Link to="/projects" className="text-sm font-medium text-indigo-700 hover:underline">All projects</Link>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
            {projects.isLoading ? (
              <div className="space-y-3 p-4"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>
            ) : recent.length === 0 ? (
              <p className="p-6 text-center text-sm text-slate-500">Nothing here yet. Open a sample or upload an SOP.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {recent.map((p) => (
                  <li key={p.id}>
                    <Link to={`/projects/${p.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-slate-50 first:rounded-t-2xl last:rounded-b-2xl">
                      <Icon name="file" size={16} className="shrink-0 text-slate-500" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-900">{p.name}</span>
                        <span className="block text-xs text-slate-500">{p.run_count} run{p.run_count === 1 ? "" : "s"} - {formatDate(p.created_at)}</span>
                      </span>
                      <Icon name="chevronRight" size={14} className="text-slate-400" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
