import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMatch, useNavigate } from "react-router";

import { api, orNull } from "../api";
import { useTheme } from "../lib/theme";
import { Icon, type IconName } from "./icons";
import { Kbd, cx } from "./ui";

interface Cmd {
  id: string;
  label: string;
  hint?: string;
  icon: IconName;
  run: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { cycle } = useTheme();
  const match = useMatch("/runs/:runId/*");
  const runId = match?.params.runId;
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);

  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: open });
  const samples = useQuery({ queryKey: ["samples"], queryFn: () => orNull(api.samples()), enabled: open });

  const commands = useMemo<Cmd[]>(() => {
    const go = (to: string) => () => navigate(to);
    const list: Cmd[] = [
      { id: "home", label: "Go to Home", icon: "arrowRight", run: go("/") },
      { id: "projects", label: "Go to Projects", icon: "layers", run: go("/projects") },
      { id: "codes", label: "Go to Gap codes", icon: "code", run: go("/gap-codes") },
      { id: "about", label: "How it works", icon: "info", run: go("/about") },
      { id: "theme", label: "Toggle theme (light / dark / system)", icon: "moon", run: cycle },
    ];
    if (runId) {
      const r = `/runs/${runId}`;
      list.unshift(
        { id: "r-ws", label: "This run: workspace", hint: runId, icon: "split", run: go(r) },
        { id: "r-find", label: "This run: findings list", icon: "list", run: go(`${r}/findings`) },
        { id: "r-diag", label: "This run: diagnostics", icon: "warning", run: go(`${r}/diagnostics`) },
        { id: "r-sim", label: "This run: simulator", icon: "play", run: go(`${r}/simulator`) },
        { id: "r-tests", label: "This run: test suite", icon: "flask", run: go(`${r}/tests`) },
        { id: "r-testrun", label: "This run: test report", icon: "checkCircle", run: go(`${r}/testrun`) },
        { id: "r-real", label: "This run: reality check", icon: "database", run: go(`${r}/reality`) },
        { id: "r-graph", label: "This run: knowledge graph", icon: "git", run: go(`${r}/graph`) },
        { id: "r-ir", label: "This run: extraction review", icon: "file", run: go(`${r}/ir-review`) },
      );
    }
    projects.data?.slice(0, 8).forEach((p) =>
      list.push({ id: `p-${p.id}`, label: `Project: ${p.name}`, hint: p.id, icon: "file", run: go(`/projects/${p.id}`) }),
    );
    samples.data?.forEach((s) =>
      list.push({ id: `s-${s.id}`, label: `Try sample: ${s.title}`, hint: s.industry, icon: "sparkles", run: go(`/?sample=${s.id}`) }),
    );
    return list;
  }, [navigate, cycle, runId, projects.data, samples.data]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return commands;
    return commands.filter((c) => `${c.label} ${c.hint ?? ""}`.toLowerCase().includes(t));
  }, [q, commands]);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      setQ("");
      setActive(0);
      requestAnimationFrame(() => input.current?.focus());
    }
    if (!open && d.open) d.close();
  }, [open]);

  useEffect(() => setActive(0), [q]);

  const exec = (c?: Cmd) => {
    if (!c) return;
    onClose();
    c.run();
  };

  return (
    <dialog
      ref={dialog}
      aria-label="Quick navigation"
      onClose={onClose}
      onClick={(e) => e.target === dialog.current && onClose()}
      className="mx-auto mt-[12vh] w-[calc(100vw-1.5rem)] max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/50 backdrop:backdrop-blur-sm open:animate-pop"
    >
      <div className="flex items-center gap-2 border-b border-slate-200 px-4">
        <Icon name="search" className="text-slate-500" />
        <input
          ref={input}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              exec(filtered[active]);
            }
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="cmd-list"
          aria-activedescendant={filtered[active] ? `cmd-${filtered[active].id}` : undefined}
          placeholder="Jump to a page, project or sample..."
          className="h-12 flex-1 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-500"
        />
        <Kbd>Esc</Kbd>
      </div>
      <ul id="cmd-list" role="listbox" className="max-h-80 overflow-y-auto p-2">
        {filtered.length === 0 && <li className="px-3 py-6 text-center text-sm text-slate-500">No matches</li>}
        {filtered.map((c, i) => (
          <li
            key={c.id}
            id={`cmd-${c.id}`}
            role="option"
            aria-selected={i === active}
            onMouseMove={() => setActive(i)}
            onClick={() => exec(c)}
            className={cx(
              "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm",
              i === active ? "bg-indigo-50 text-indigo-800" : "text-slate-700",
            )}
          >
            <Icon name={c.icon} size={16} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">{c.label}</span>
            {c.hint && <span className="truncate font-mono text-xs text-slate-500">{c.hint}</span>}
          </li>
        ))}
      </ul>
    </dialog>
  );
}
