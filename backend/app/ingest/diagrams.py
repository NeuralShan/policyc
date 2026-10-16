"""Process diagrams (flowcharts, swimlanes) read from figure images with Gemini vision.

The result is a ``DiagramGraph`` on the figure node. Layer 2 compares it with the flow extracted
from the text; disagreements are gap XD004. Edges that point at unknown shapes are dropped with a
warning rather than kept as a broken graph.
"""

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.core.storage import LocalStorage
from app.schemas.docast import DiagramGraph, DiagramStatus, DocAST, IngestWarning, NodeKind


class DiagramReply(BaseModel):
    is_process_diagram: bool = Field(
        description="True for flowcharts, swimlanes and process maps; false for photos, logos, "
        "charts and other illustrations"
    )
    description: str = Field(description="One sentence describing what the figure shows")
    diagram: DiagramGraph | None = Field(
        default=None, description="The process as drawn; null if not a process diagram"
    )


def read_diagrams(
    ast: DocAST, storage: LocalStorage, llm: LLMGateway, context: CallContext
) -> tuple[DocAST, list[IngestWarning]]:
    warnings: list[IngestWarning] = []
    nodes = list(ast.nodes)
    for idx, node in enumerate(nodes):
        figure = node.figure
        if node.kind != NodeKind.FIGURE or figure is None:
            continue
        if figure.diagram_status != DiagramStatus.PENDING or not figure.image_key:
            continue
        image = storage.path(figure.image_key).read_bytes()
        try:
            reply = llm.structured(
                "diagram_reading",
                DiagramReply,
                {"caption": figure.caption or "(no caption)"},
                images=[image],
                context=context,
            )
        except (LLMUnavailable, LLMOutputError) as exc:
            warnings.append(
                IngestWarning(
                    code="diagram_pending",
                    node_id=node.id,
                    message=f"figure not analysed ({exc}); it will be retried on the next run",
                )
            )
            continue

        diagram = reply.diagram if reply.is_process_diagram else None
        if diagram is not None:
            ids = {n.id for n in diagram.nodes}
            kept = [e for e in diagram.edges if e.source in ids and e.target in ids]
            if dropped := len(diagram.edges) - len(kept):
                warnings.append(
                    IngestWarning(
                        code="diagram_edges_dropped",
                        node_id=node.id,
                        message=f"dropped {dropped} edge(s) pointing at unknown shapes",
                    )
                )
            diagram = diagram.model_copy(update={"edges": kept})
        nodes[idx] = node.model_copy(
            update={
                "figure": figure.model_copy(
                    update={
                        "diagram_status": DiagramStatus.EXTRACTED
                        if diagram
                        else DiagramStatus.NOT_A_DIAGRAM,
                        "description": reply.description,
                        "diagram": diagram,
                    }
                )
            }
        )
    return ast.model_copy(update={"nodes": nodes}), warnings
