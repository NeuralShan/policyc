import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, type TestCase, type TestOrigin } from "../api";
import { PageHeader } from "../components/Layout";
import { Badge, Card, ErrorNote, Mono, cx } from "../components/ui";

const ORIGIN_TONE: Record<TestOrigin, "blue" | "green" | "amber" | "red"> = {
  boundary: "blue",
  path: "green",
  branch: "amber",
  fault: "red",
};

const ORIGIN_LABEL: Record<TestOrigin, string> = {
  boundary: "Boundary",
  path: "Path",
  branch: "Branch (Z3)",
  fault: "Fault injection",
};

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className={cx("rounded-lg border px-4 py-3 text-center", tone)}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs opacity-70">{label}</div>
    </div>
  );
}

function TestCaseRow({ tc }: { tc: TestCase }) {
  const [open, setOpen] = useState(false);
  const factsEntries = Object.entries(tc.scenario.facts);
  const actorEntries = Object.entries(tc.scenario.actor_overrides);
  const systemEntries = Object.entries(tc.scenario.system_overrides);

  return (
    <div className="border-b border-slate-100 last:border-0">
      <button
        className="flex w-full items-start gap-3 py-3 text-left hover:bg-slate-50"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="mt-0.5 shrink-0">
          <Badge tone={ORIGIN_TONE[tc.origin]}>{ORIGIN_LABEL[tc.origin]}</Badge>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{tc.description}</p>
          <div className="mt-0.5 flex flex-wrap gap-2">
            <Mono className="text-xs text-slate-400">{tc.id}</Mono>
            {tc.tags.slice(0, 3).map((t) => (
              <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                {t}
              </span>
            ))}
          </div>
        </div>
        <span className="shrink-0 text-xs text-slate-400">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mb-3 ml-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
          {factsEntries.length > 0 && (
            <div className="mb-2">
              <span className="font-medium text-slate-600">Facts: </span>
              {factsEntries.map(([k, v]) => (
                <span key={k} className="mr-3">
                  <Mono>{k}</Mono> = <strong>{String(v)}</strong>
                </span>
              ))}
            </div>
          )}
          {actorEntries.length > 0 && (
            <div className="mb-2">
              <span className="font-medium text-slate-600">Actor overrides: </span>
              {actorEntries.map(([k, v]) => (
                <span key={k} className="mr-3">
                  <Mono>{k}</Mono>:{" "}
                  <span className={v === null ? "text-red-600" : ""}>
                    {v === null ? "unavailable" : v}
                  </span>
                </span>
              ))}
            </div>
          )}
          {systemEntries.length > 0 && (
            <div className="mb-2">
              <span className="font-medium text-slate-600">System overrides: </span>
              {systemEntries.map(([k, v]) => (
                <span key={k} className="mr-3">
                  <Mono>{k}</Mono>:{" "}
                  <span className={!v ? "text-red-600" : "text-emerald-600"}>
                    {v ? "up" : "DOWN"}
                  </span>
                </span>
              ))}
            </div>
          )}
          {tc.expected_outcome && (
            <div>
              <span className="font-medium text-slate-600">Expected: </span>
              <Mono>{tc.expected_outcome}</Mono>
              {tc.expected_branch && (
                <span>
                  {" "}→ branch <Mono>{tc.expected_branch}</Mono>
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const ORIGINS: TestOrigin[] = ["boundary", "path", "branch", "fault"];

export function TestSuitePage() {
  const { runId = "" } = useParams();
  const [filter, setFilter] = useState<TestOrigin | "all">("all");

  const query = useQuery({
    queryKey: ["run-testcases", runId],
    queryFn: () => api.runTestcases(runId),
  });

  const suite = query.data;
  const filtered = filter === "all"
    ? suite?.test_cases ?? []
    : suite?.test_cases.filter((tc) => tc.origin === filter) ?? [];

  return (
    <>
      <PageHeader
        title="Test Suite"
        subtitle={<Mono className="text-sm">{runId}</Mono>}
        actions={
          <Link to={`/runs/${runId}`} className="text-sm text-slate-600 hover:text-slate-900">
            ← Run
          </Link>
        }
      />
      <ErrorNote error={query.error} />

      {suite && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard
            label="Total"
            value={suite.stats.total ?? 0}
            tone="bg-slate-50 border-slate-200 text-slate-700"
          />
          <StatCard
            label="Boundary"
            value={suite.stats.boundary ?? 0}
            tone="bg-sky-50 border-sky-200 text-sky-700"
          />
          <StatCard
            label="Branch (Z3)"
            value={suite.stats.branch ?? 0}
            tone="bg-amber-50 border-amber-200 text-amber-700"
          />
          <StatCard
            label="Fault"
            value={suite.stats.fault ?? 0}
            tone="bg-red-50 border-red-200 text-red-700"
          />
          <StatCard
            label="Path"
            value={suite.stats.path ?? 0}
            tone="bg-emerald-50 border-emerald-200 text-emerald-700"
          />
        </div>
      )}

      <Card
        title={
          <div className="flex items-center gap-3">
            <span>Test cases ({filtered.length})</span>
            <div className="flex gap-1">
              <button
                onClick={() => setFilter("all")}
                className={cx(
                  "rounded px-2 py-0.5 text-xs",
                  filter === "all"
                    ? "bg-slate-700 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                )}
              >
                All
              </button>
              {ORIGINS.map((o) => (
                <button
                  key={o}
                  onClick={() => setFilter(o)}
                  className={cx(
                    "rounded px-2 py-0.5 text-xs capitalize",
                    filter === o
                      ? "bg-slate-700 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                  )}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>
        }
      >
        {query.isLoading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-slate-400 italic">No test cases.</p>
        ) : (
          <div>
            {filtered.map((tc) => (
              <TestCaseRow key={tc.id} tc={tc} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
