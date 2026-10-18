import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ACCEPTED_SOURCE_TYPES, api, type UploadResult } from "../api";
import { useWriteGuard } from "../auth/AuthProvider";
import { PageHeader } from "../components/Layout";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Mono,
  StatusBadge,
  cx,
  formatBytes,
  formatDate,
  formatDuration,
} from "../components/ui";

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });

  return (
    <>
      <PageHeader
        title={project.data?.name ?? "Project"}
        subtitle={project.data?.description || <Mono>{projectId}</Mono>}
        actions={<Link to="/" className="text-sm text-slate-600 hover:text-slate-900"> All projects</Link>}
      />
      <ErrorNote error={project.error} />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
        <Documents projectId={projectId} />
        <Runs projectId={projectId} />
      </div>
    </>
  );
}

function Documents({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const documents = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => api.documents(projectId),
  });
  const [lastUpload, setLastUpload] = useState<UploadResult[] | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["documents", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  };
  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadDocuments(projectId, files),
    onSuccess: (results) => {
      setLastUpload(results);
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: api.deleteDocument, onSuccess: refresh });

  const guard = useWriteGuard();
  const send = (files: FileList | null) => {
    if (files && files.length > 0) guard(() => upload.mutate(Array.from(files)));
  };
  const duplicates = lastUpload?.filter((r) => r.duplicate) ?? [];

  return (
    <Card title="Source documents">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          send(e.dataTransfer.files);
        }}
        className={cx(
          "mb-4 flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-sm",
          dragging ? "border-slate-500 bg-slate-50" : "border-slate-300",
        )}
      >
        <p className="text-slate-600">Drop SOPs and policies here, or</p>
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Uploading…" : "Choose files"}
        </Button>
        <p className="text-xs text-slate-500">{ACCEPTED_SOURCE_TYPES.join(" ")}</p>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={ACCEPTED_SOURCE_TYPES.join(",")}
          onChange={(e) => {
            send(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      <ErrorNote error={upload.error ?? remove.error ?? documents.error} />
      {duplicates.length > 0 && (
        <p className="mb-3 text-sm text-slate-600">
          Already in this project (identical content): {duplicates.map((d) => d.filename).join(", ")}
        </p>
      )}
      {documents.data?.length === 0 ? (
        <Empty>No documents yet.</Empty>
      ) : (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2 font-medium">File</th>
              <th className="py-2 font-medium">Parsed</th>
              <th className="py-2 font-medium">Size</th>
              <th className="py-2 font-medium">SHA-256</th>
              <th className="py-2 font-medium">Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.data?.map((d) => (
              <tr key={d.id}>
                <td className="py-2">
                  <Link to={`/documents/${d.id}`} className="text-slate-900 hover:underline">
                    {d.filename}
                  </Link>{" "}
                  <a href={api.documentFileUrl(d.id)} target="_blank" rel="noreferrer" title="Open the original file" className="text-xs text-slate-500 hover:text-slate-700">
                    Open
                  </a>
                </td>
                <td className="py-2">
                  {d.parsed ? (
                    <span className="flex items-center gap-1.5 text-xs text-slate-600">
                      {d.parsed.stats.doc_class && <Badge tone="blue">{d.parsed.stats.doc_class}</Badge>}
                      {d.parsed.stats.nodes} nodes
                      {d.parsed.stats.warnings > 0 && <Badge tone="amber">{d.parsed.stats.warnings} warnings</Badge>}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-500">not yet</span>
                  )}
                </td>
                <td className="py-2 text-slate-600">{formatBytes(d.size_bytes)}</td>
                <td className="py-2"><Mono>{d.sha256.slice(0, 12)}</Mono></td>
                <td className="py-2 text-slate-600">{formatDate(d.uploaded_at)}</td>
                <td className="py-2 text-right">
                  <Button
                    variant="danger"
                    onClick={() => guard(() => confirm(`Remove ${d.filename}?`) && remove.mutate(d.id))}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </Card>
  );
}

function Runs({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const documents = useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => api.documents(projectId),
  });
  const runs = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.runs(projectId),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 1000 : false,
  });
  const start = useMutation({
    mutationFn: () => api.startRun(projectId, !review),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs", projectId] });
      navigate(`/runs/${run.id}`);
    },
  });
  const hasDocuments = (documents.data?.length ?? 0) > 0;
  const [review, setReview] = useState(false);
  const guard = useWriteGuard();

  return (
    <Card
      title="Compile runs"
      actions={
        <>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
            <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
            Review extraction before continuing
          </label>
          <Button onClick={() => guard(() => start.mutate(), "Sign in to run your own SOPs")} disabled={!hasDocuments || start.isPending}>
            {start.isPending ? "Starting..." : "Compile"}
          </Button>
        </>
      }
    >
      <ErrorNote error={start.error ?? runs.error} />
      {runs.data?.length === 0 ? (
        <Empty>{hasDocuments ? "No runs yet. Press Compile." : "Upload a document to compile."}</Empty>
      ) : (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2 font-medium">Run</th>
              <th className="py-2 font-medium">Status</th>
              <th className="py-2 font-medium">Documents</th>
              <th className="py-2 font-medium">Started</th>
              <th className="py-2 font-medium">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.data?.map((r) => (
              <tr key={r.id}>
                <td className="py-2">
                  <Link to={`/runs/${r.id}`} className="font-mono text-xs text-slate-900 hover:underline">
                    {r.id}
                  </Link>
                </td>
                <td className="py-2"><StatusBadge status={r.status} /></td>
                <td className="py-2 text-slate-600">{r.document_ids.length}</td>
                <td className="py-2 text-slate-600">{formatDate(r.created_at)}</td>
                <td className="py-2 text-slate-600">{formatDuration(r.started_at, r.finished_at)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </Card>
  );
}
