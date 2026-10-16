"""DocAST: the output of Layer 1 (the "lexer").

A document becomes a flat, ordered list of nodes (headings, paragraphs, list items, tables,
figures) arranged in a section tree by ``parent_id``. ``DocAST.text`` is the canonical text of the
whole document; every node's ``SourceSpan`` indexes into it, so for every span
``ast.text[span.char_start:span.char_end] == span.quote`` holds. Later layers quote clauses by
offset and the check is a plain string comparison. Page and bounding box (top-left origin, PDF
points) locate the same span on the rendered page.
"""

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.provenance import BBox, SourceSpan

DOCAST_SCHEMA_VERSION = 1


class NodeKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    NOTE = "note"  # footnotes, cautions set apart from the body


class TextSource(StrEnum):
    NATIVE = "native"  # the file's own text layer
    OCR = "ocr"  # local OCR only; not cross-checked
    OCR_VERIFIED = "ocr_verified"  # local OCR confirmed by an independent vision reading
    VISION = "vision"  # vision reading replaced a disagreeing OCR reading (see alt_text)


class TableCell(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str
    column_header: bool = False
    row_header: bool = False
    char_start: int | None = None  # offsets into DocAST.text
    char_end: int | None = None
    bbox: BBox | None = None


class TableData(BaseModel):
    num_rows: int
    num_cols: int
    cells: list[TableCell]

    def grid(self) -> list[list[str]]:
        rows = [[""] * self.num_cols for _ in range(self.num_rows)]
        for c in self.cells:
            rows[c.row][c.col] = c.text
        return rows


class DiagramNodeKind(StrEnum):
    START = "start"
    END = "end"
    TASK = "task"
    DECISION = "decision"
    DOCUMENT = "document"
    OTHER = "other"


class DiagramNode(BaseModel):
    id: str
    label: str
    kind: DiagramNodeKind = DiagramNodeKind.TASK
    lane: str | None = Field(default=None, description="Swimlane / actor the shape sits in")


class DiagramEdge(BaseModel):
    source: str
    target: str
    label: str | None = Field(default=None, description="Edge text, e.g. 'Yes' / 'No'")


class DiagramGraph(BaseModel):
    """A process diagram read from a figure. Compared against the text flow in Layer 2 (XD004)."""

    title: str | None = None
    lanes: list[str] = Field(default_factory=list)
    nodes: list[DiagramNode] = Field(default_factory=list)
    edges: list[DiagramEdge] = Field(default_factory=list)


class DiagramStatus(StrEnum):
    SKIPPED = "skipped"  # too small to be a diagram (logos, icons)
    PENDING = "pending"  # not analysed yet (e.g. quota exhausted); retried next run
    NOT_A_DIAGRAM = "not_a_diagram"
    EXTRACTED = "extracted"


class FigureData(BaseModel):
    image_key: str | None = None  # storage key of the cropped PNG
    caption: str | None = None
    diagram_status: DiagramStatus = DiagramStatus.PENDING
    description: str | None = None  # one-line description of what the figure shows
    diagram: DiagramGraph | None = None


class DocNode(BaseModel):
    id: str  # "n0001", stable within one AST
    kind: NodeKind
    parent_id: str | None = None  # enclosing heading (section tree)
    level: int | None = None  # headings only: 1 = top level
    number: str | None = None  # clause numbering as printed, e.g. "4.3", "(2)", "a)"
    text: str  # verbatim text, numbering included; tables: rows as "a | b"; figures: caption
    spans: list[SourceSpan]
    text_source: TextSource = TextSource.NATIVE
    alt_text: str | None = None  # the other reading when OCR and vision disagreed
    table: TableData | None = None
    figure: FigureData | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.kind}\x00{self.text}".encode()).hexdigest()


class PageInfo(BaseModel):
    page_no: int
    width: float
    height: float
    text_source: TextSource = TextSource.NATIVE


class DocClass(StrEnum):
    PROCEDURAL = "procedural"  # SOPs, playbooks: steps, actors, sequence
    NORMATIVE = "normative"  # policies, rules: obligations, permissions, limits
    DESCRIPTIVE = "descriptive"  # reports, KPI documents: facts and claims
    MIXED = "mixed"
    OTHER = "other"


class GroundedValue(BaseModel):
    value: str
    quote: str  # verbatim evidence found in the document text or page furniture


class DocumentProfile(BaseModel):
    """What kind of document this is, plus control metadata. Values without evidence are dropped."""

    doc_class: DocClass
    rationale: str
    title: GroundedValue | None = None
    document_code: GroundedValue | None = None
    version: GroundedValue | None = None
    effective_date: GroundedValue | None = None
    owner: GroundedValue | None = None
    model: str  # which model produced it


class IngestWarning(BaseModel):
    code: str  # e.g. "ocr_unverified", "ocr_corrected", "diagram_pending", "profile_pending"
    message: str
    node_id: str | None = None
    page: int | None = None


class DocAST(BaseModel):
    schema_version: int = DOCAST_SCHEMA_VERSION
    document_id: str
    sha256: str
    filename: str
    media_type: str
    parser: str  # e.g. "docling 2.139.0"
    pages: list[PageInfo] = Field(default_factory=list)
    text: str
    nodes: list[DocNode]
    furniture: list[str] = Field(default_factory=list)  # running headers/footers, de-duplicated
    profile: DocumentProfile | None = None
    warnings: list[IngestWarning] = Field(default_factory=list)

    def node(self, node_id: str) -> DocNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def span_text(self, span: SourceSpan) -> str:
        return self.text[span.char_start : span.char_end]

    @property
    def is_complete(self) -> bool:
        """True when no enrichment is still pending (pending ones are retried on the next run)."""
        pending = {"ocr_unverified", "diagram_pending", "profile_pending"}
        return not any(w.code in pending for w in self.warnings)
