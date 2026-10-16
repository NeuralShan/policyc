"""Parser-neutral items, and assembly of items into a DocAST.

Parsers (Docling, plain text) emit ``RawItem``s in reading order. Enrichment steps that change text
(the OCR cross-check) run on items, *before* assembly, because assembly fixes the character
offsets that every span points to.
"""

import re

from pydantic import BaseModel, Field

from app.ingest.numbering import depth, split_number
from app.schemas.docast import (
    DocAST,
    DocNode,
    FigureData,
    NodeKind,
    PageInfo,
    TableData,
    TextSource,
)
from app.schemas.provenance import BBox, SourceSpan

SEPARATOR = "\n\n"
HEADING_KINDS = {NodeKind.TITLE, NodeKind.HEADING}


class Region(BaseModel):
    page: int | None = None
    bbox: BBox | None = None


class RawItem(BaseModel):
    kind: NodeKind
    text: str
    regions: list[Region] = Field(default_factory=lambda: [Region()])
    number: str | None = None
    level: int | None = None  # headings: level reported by the parser, if any
    text_source: TextSource = TextSource.NATIVE
    alt_text: str | None = None
    table: TableData | None = None
    figure: FigureData | None = None


class ParsedDocument(BaseModel):
    """Deterministic parser output, cached per (file content, parser version)."""

    parser: str
    items: list[RawItem]
    pages: list[PageInfo] = Field(default_factory=list)
    furniture: list[str] = Field(default_factory=list)


def clean_text(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text.replace(" ", " ")).strip()


def _number(item: RawItem) -> str | None:
    """Printed numbering: from the parser (list markers) or else the start of the text."""
    return item.number or split_number(clean_text(item.text))[0]


def _promote_title(items: list[RawItem]) -> list[RawItem]:
    """Layout models label the document title as an ordinary heading. If there is no title, the
    first heading becomes it, provided it is unnumbered."""
    if any(i.kind == NodeKind.TITLE for i in items):
        return items
    for idx, item in enumerate(items):
        if item.kind == NodeKind.HEADING:
            if _number(item) is None:
                items = list(items)
                items[idx] = item.model_copy(update={"kind": NodeKind.TITLE})
            break
    return items


def _heading_levels(items: list[RawItem]) -> list[int | None]:
    """Heading depth per item: dotted numbering wins, then the parser's level, normalised so the
    shallowest heading is level 1. The title is level 0."""
    levels: list[int | None] = []
    for item in items:
        if item.kind == NodeKind.TITLE:
            levels.append(0)
        elif item.kind == NodeKind.HEADING:
            levels.append(depth(_number(item)) or item.level or 1)
        else:
            levels.append(None)
    heading_levels = [lv for lv in levels if lv]
    shift = min(heading_levels) - 1 if heading_levels else 0
    return [lv - shift if lv else lv for lv in levels]


def assemble(
    parsed: ParsedDocument, *, document_id: str, sha256: str, filename: str, media_type: str
) -> DocAST:
    text_parts: list[str] = []
    length = 0
    nodes: list[DocNode] = []
    stack: list[DocNode] = []  # open headings, shallow to deep

    items = _promote_title(parsed.items)
    for item, level in zip(items, _heading_levels(items), strict=True):
        text = item.text
        if item.kind != NodeKind.TABLE:
            text = clean_text(text)
        if not text and item.kind != NodeKind.FIGURE:
            continue
        numbered = HEADING_KINDS | {NodeKind.PARAGRAPH, NodeKind.LIST_ITEM}
        number = _number(item) if item.kind in numbered else item.number

        if text:
            start = length + (len(SEPARATOR) if text_parts else 0)
            text_parts.append(text)
            length = start + len(text)
        else:
            start = length
        end = start + len(text)

        node_id = f"n{len(nodes) + 1:04d}"
        if item.kind in HEADING_KINDS:
            while stack and (stack[-1].level or 0) >= (level or 0):
                stack.pop()
        table = item.table
        if table is not None:
            table = _offset_table(table, start)
        node = DocNode(
            id=node_id,
            kind=item.kind,
            parent_id=stack[-1].id if stack else None,
            level=level,
            number=number,
            text=text,
            spans=[
                SourceSpan(
                    document_id=document_id,
                    page=r.page,
                    bbox=r.bbox,
                    char_start=start,
                    char_end=end,
                    quote=text,
                )
                for r in item.regions
            ],
            text_source=item.text_source,
            alt_text=item.alt_text,
            table=table,
            figure=item.figure,
        )
        nodes.append(node)
        if item.kind in HEADING_KINDS:
            stack.append(node)

    return DocAST(
        document_id=document_id,
        sha256=sha256,
        filename=filename,
        media_type=media_type,
        parser=parsed.parser,
        pages=parsed.pages,
        text=SEPARATOR.join(text_parts),
        nodes=nodes,
        furniture=parsed.furniture,
    )


def linearize_table(table: TableData) -> tuple[str, TableData]:
    """Table text as rows of ``cell | cell`` lines, with each cell's offset within that text."""
    by_row: dict[int, list] = {}
    for cell in sorted(table.cells, key=lambda c: (c.row, c.col)):
        by_row.setdefault(cell.row, []).append(cell)
    lines: list[str] = []
    cells = []
    pos = 0
    for row in sorted(by_row):
        parts: list[str] = []
        for cell in by_row[row]:
            if parts:
                pos += 3  # " | "
            value = clean_text(cell.text)
            cells.append(
                cell.model_copy(
                    update={"text": value, "char_start": pos, "char_end": pos + len(value)}
                )
            )
            parts.append(value)
            pos += len(value)
        lines.append(" | ".join(parts))
        pos += 1  # newline
    return "\n".join(lines), table.model_copy(update={"cells": cells})


def _offset_table(table: TableData, start: int) -> TableData:
    cells = [
        c.model_copy(update={"char_start": c.char_start + start, "char_end": c.char_end + start})
        if c.char_start is not None
        else c
        for c in table.cells
    ]
    return table.model_copy(update={"cells": cells})
