import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

import type { BBox, DocAST } from "../api";
import { cx } from "./ui";

GlobalWorkerOptions.workerSrc = workerUrl;

interface Box {
  nodeId: string;
  bbox: BBox;
}

/** Renders every page of a PDF with the DocAST nodes' bounding boxes overlaid (click to select). */
export function PdfViewer({ url, ast, selectedId, onSelect }: {
  url: string;
  ast: DocAST;
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const task = getDocument({ url });
    task.promise.then(setPdf, (e: unknown) => setError(String(e)));
    return () => {
      void task.destroy();
    };
  }, [url]);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const boxesByPage = new Map<number, Box[]>();
  for (const node of ast.nodes) {
    for (const span of node.spans) {
      if (span.page && span.bbox) {
        const list = boxesByPage.get(span.page) ?? [];
        list.push({ nodeId: node.id, bbox: span.bbox });
        boxesByPage.set(span.page, list);
      }
    }
  }

  return (
    <div ref={container} className="space-y-4">
      {error && <p className="text-sm text-red-700">Could not load the PDF: {error}</p>}
      {pdf && width > 0 &&
        ast.pages.map((page) => (
          <PdfPage
            key={page.page_no}
            pdf={pdf}
            pageNo={page.page_no}
            scale={width / page.width}
            height={page.height}
            boxes={boxesByPage.get(page.page_no) ?? []}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

function PdfPage({ pdf, pageNo, scale, height, boxes, selectedId, onSelect }: {
  pdf: PDFDocumentProxy;
  pageNo: number;
  scale: number;
  height: number;
  boxes: Box[];
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const selectedBox = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let task: RenderTask | null = null;
    let cancelled = false;
    void pdf.getPage(pageNo).then((page) => {
      if (cancelled || !canvas.current) return;
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      canvas.current.width = viewport.width;
      canvas.current.height = viewport.height;
      task = page.render({ canvas: canvas.current, viewport });
      task.promise.catch(() => undefined); // cancelled on re-render
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, pageNo, scale]);

  useEffect(() => {
    selectedBox.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedId]);

  return (
    <div className="relative shadow ring-1 ring-slate-200" style={{ height: height * scale }}>
      <canvas ref={canvas} className="absolute inset-0 h-full w-full" />
      {boxes.map((box, i) => {
        const selected = box.nodeId === selectedId;
        return (
          <button
            key={`${box.nodeId}-${i}`}
            ref={selected ? selectedBox : undefined}
            type="button"
            title={box.nodeId}
            onClick={() => onSelect(box.nodeId)}
            className={cx(
              "absolute rounded-sm transition-colors",
              selected
                ? "bg-amber-300/30 ring-2 ring-amber-500"
                : "hover:bg-sky-300/20 hover:ring-1 hover:ring-sky-500",
            )}
            style={{
              left: box.bbox.x0 * scale - 2,
              top: box.bbox.y0 * scale - 2,
              width: (box.bbox.x1 - box.bbox.x0) * scale + 4,
              height: (box.bbox.y1 - box.bbox.y0) * scale + 4,
            }}
          />
        );
      })}
      <span className="absolute right-2 bottom-1 text-xs text-slate-500">page {pageNo}</span>
    </div>
  );
}
