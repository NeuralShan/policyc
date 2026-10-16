import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api } from "../api";
import { PageHeader } from "../components/Layout";
import { Button, Card, Empty, ErrorNote, Mono, formatDate } from "../components/ui";

export function ProjectsPage() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="A project groups the documents compiled together, such as all SOPs of one process area."
      />
      <div className="grid gap-6 md:grid-cols-3">
        <div className="md:col-span-2">
          <Card title="All projects">
            <ErrorNote error={projects.error} />
            {projects.data?.length === 0 && <Empty>No projects yet. Create one to get started.</Empty>}
            <ul className="divide-y divide-slate-100">
              {projects.data?.map((p) => (
                <li key={p.id}>
                  <Link to={`/projects/${p.id}`} className="block rounded-md px-2 py-3 hover:bg-slate-50">
                    <div className="flex items-baseline justify-between gap-4">
                      <span className="font-medium text-slate-900">{p.name}</span>
                      <Mono>{p.id}</Mono>
                    </div>
                    {p.description && <p className="mt-0.5 text-sm text-slate-600">{p.description}</p>}
                    <p className="mt-1 text-xs text-slate-500">
                      {p.document_count} document{p.document_count === 1 ? "" : "s"} · {p.run_count} run
                      {p.run_count === 1 ? "" : "s"} · created {formatDate(p.created_at)}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <CreateProject />
      </div>
    </>
  );
}

function CreateProject() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => api.createProject(name, description),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    },
  });

  return (
    <Card title="New project">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <label className="block text-sm">
          <span className="text-slate-700">Name</span>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Customer Operations SOPs"
            required
            maxLength={200}
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-700">Description</span>
          <textarea
            className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </label>
        <ErrorNote error={create.error} />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          Create project
        </Button>
      </form>
    </Card>
  );
}
