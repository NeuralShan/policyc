import { useId, useMemo, useState } from "react";

import type { SopIR } from "../api";
import { irVariables } from "../lib/workspace";
import { Button, cx } from "./ui";

type Facts = Record<string, unknown>;

/**
 * Facts editor for the simulator: a typed form built from the variables seen in the IR's decision
 * conditions, with an "advanced JSON" toggle. Invalid JSON never reaches `onRun`; `onInvalid` lets the
 * parent drop any stale result so it cannot be mistaken for the current input.
 */
export function FactsForm({
  ir,
  onRun,
  onInvalid,
  pending,
  initialFacts,
  submitLabel = "Run simulation",
}: {
  ir: SopIR | undefined;
  onRun: (facts: Facts) => void;
  onInvalid?: () => void;
  pending?: boolean;
  initialFacts?: Facts;
  submitLabel?: string;
}) {
  const vars = useMemo(() => irVariables(ir), [ir]);
  const [advanced, setAdvanced] = useState(false);
  const [facts, setFacts] = useState<Facts>(initialFacts ?? {});
  const [text, setText] = useState(() => JSON.stringify(initialFacts ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  const uid = useId();
  const showJson = advanced || vars.length === 0;

  const setVar = (name: string, value: unknown) => {
    const next = { ...facts };
    if (value === "" || value === undefined) delete next[name];
    else next[name] = value;
    setFacts(next);
    setText(JSON.stringify(next, null, 2));
  };

  const submit = () => {
    if (showJson) {
      try {
        const parsed = JSON.parse(text);
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
        setError(null);
        setFacts(parsed);
        onRun(parsed);
      } catch {
        setError("Invalid JSON: facts must be an object such as { \"amount\": 1000 }");
        onInvalid?.();
      }
    } else {
      setError(null);
      onRun(facts);
    }
  };

  return (
    <div className="space-y-3">
      {!showJson && (
        <div className="grid gap-3 sm:grid-cols-2">
          {vars.map((v) => {
            const numeric = v.samples.length > 0 ? v.samples.every((s) => typeof s === "number") : [...v.ops].some((o) => ["gt", "gte", "lt", "lte"].includes(o));
            const bool = v.samples.length > 0 && v.samples.every((s) => typeof s === "boolean");
            const strs = [...new Set(v.samples.filter((s) => typeof s === "string"))] as string[];
            const id = `${uid}-${v.name}`;
            const cur = facts[v.name];
            return (
              <div key={v.name}>
                <label htmlFor={id} className="mb-1 block font-mono text-xs font-medium text-slate-700">
                  {v.name}
                </label>
                {bool ? (
                  <select
                    id={id}
                    value={cur === undefined ? "" : String(cur)}
                    onChange={(e) => setVar(v.name, e.target.value === "" ? undefined : e.target.value === "true")}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                  >
                    <option value="">(unset)</option>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <>
                    <input
                      id={id}
                      type={numeric ? "number" : "text"}
                      list={strs.length ? `${id}-list` : undefined}
                      value={cur === undefined ? "" : String(cur)}
                      onChange={(e) => setVar(v.name, numeric ? (e.target.value === "" ? undefined : Number(e.target.value)) : e.target.value)}
                      placeholder={v.samples.length ? `e.g. ${String(v.samples[0])}` : undefined}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
                    />
                    {strs.length > 0 && <datalist id={`${id}-list`}>{strs.map((s) => <option key={s} value={s} />)}</datalist>}
                  </>
                )}
                <p className="mt-0.5 text-[11px] text-slate-500">used in: {[...v.ops].join(", ")}</p>
              </div>
            );
          })}
        </div>
      )}
      {showJson && (
        <div>
          <label htmlFor={`${uid}-json`} className="mb-1 block text-xs font-medium text-slate-700">
            Facts (JSON object)
          </label>
          <textarea
            id={`${uid}-json`}
            rows={6}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setError(null);
            }}
            aria-invalid={!!error}
            aria-describedby={error ? `${uid}-err` : undefined}
            className={cx(
              "w-full rounded-lg border bg-white px-3 py-2 font-mono text-sm",
              error ? "border-red-400" : "border-slate-300",
            )}
          />
        </div>
      )}
      {error && (
        <p id={`${uid}-err`} role="alert" className="text-xs font-medium text-red-700">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={submit} disabled={pending} icon="play">
          {pending ? "Running..." : submitLabel}
        </Button>
        {vars.length > 0 && (
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={advanced}
              onChange={(e) => {
                setAdvanced(e.target.checked);
                setError(null);
                if (e.target.checked) setText(JSON.stringify(facts, null, 2));
              }}
            />
            Advanced JSON
          </label>
        )}
        {vars.length === 0 && <span className="text-xs text-slate-500">No decision variables found in the model, so enter facts as JSON.</span>}
      </div>
    </div>
  );
}
