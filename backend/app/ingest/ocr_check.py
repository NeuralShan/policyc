"""Second, independent reading of OCR'd pages with Gemini vision.

Local OCR can silently corrupt exactly the clause that matters, so every OCR'd page is read twice.
The page image goes to Gemini, which returns the page's text blocks in reading order. The blocks
are aligned to the OCR items with a global sequence alignment (Needleman-Wunsch on text
similarity), so a badly garbled line still pairs with its counterpart when its neighbours agree.
For each aligned pair:

- identical apart from whitespace/punctuation: ``OCR_VERIFIED`` (vision spacing kept)
- different: ``VISION``. The vision text replaces the OCR text, the OCR reading is kept in
  ``alt_text``, and a large disagreement adds an ``ocr_corrected`` warning for human review.

Items with no counterpart keep their OCR text and get an ``ocr_disputed`` warning. Layout (page,
bounding box) always comes from the local OCR. Vision only supplies text.
"""

import difflib
import io
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.llm.gateway import CallContext, LLMGateway, LLMOutputError, LLMUnavailable
from app.ingest.assemble import ParsedDocument, RawItem, clean_text, linearize_table
from app.schemas.docast import IngestWarning, NodeKind, TextSource

AGREE = 0.98  # similarity (alphanumerics only) at or above which the readings agree
MAJOR = 0.90  # below this a correction is reported as a warning
ANCHOR = 0.80  # neighbours this similar make a weak pair trustworthy
WEAK = 0.50
GAP = -0.6  # alignment gap penalty; pair score is 2 * similarity - 1
TEXT_KINDS = {
    NodeKind.TITLE,
    NodeKind.HEADING,
    NodeKind.PARAGRAPH,
    NodeKind.LIST_ITEM,
    NodeKind.NOTE,
}


class PageBlock(BaseModel):
    kind: Literal["text", "table"]
    text: str = Field(default="", description="The block's text exactly as printed (text blocks)")
    rows: list[list[str]] = Field(
        default_factory=list, description="Table blocks: cell texts row by row, as printed"
    )


class PageReading(BaseModel):
    blocks: list[PageBlock]


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(a: list[str], b: list[str]) -> list[tuple[int | None, int | None, float]]:
    """Global alignment of two sequences of strings. Returns (i, j, similarity) steps in order;
    ``None`` on one side is a gap."""
    n, m = len(a), len(b)
    sim = [[similarity(x, y) for y in b] for x in a]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * GAP
    for j in range(1, m + 1):
        score[0][j] = j * GAP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            score[i][j] = max(
                score[i - 1][j - 1] + 2 * sim[i - 1][j - 1] - 1,
                score[i - 1][j] + GAP,
                score[i][j - 1] + GAP,
            )
    steps = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and score[i][j] == score[i - 1][j - 1] + 2 * sim[i - 1][j - 1] - 1:
            steps.append((i - 1, j - 1, sim[i - 1][j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and score[i][j] == score[i - 1][j] + GAP:
            steps.append((i - 1, None, 0.0))
            i -= 1
        else:
            steps.append((None, j - 1, 0.0))
            j -= 1
    return steps[::-1]


def _trusted_pairs(steps) -> dict[int, tuple[int, float]]:
    """Keep strong pairs, and weak pairs whose aligned neighbours on both sides are strong."""
    pairs = [(i, j, s) for i, j, s in steps if i is not None and j is not None]
    trusted: dict[int, tuple[int, float]] = {}
    for k, (i, j, s) in enumerate(pairs):
        if s >= WEAK:
            trusted[i] = (j, s)
            continue
        before = pairs[k - 1][2] if k > 0 else 1.0
        after = pairs[k + 1][2] if k + 1 < len(pairs) else 1.0
        if before >= ANCHOR and after >= ANCHOR:
            trusted[i] = (j, s)
    return trusted


def render_page_png(pdf_path: Path, page_no: int, scale: float = 2.0) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_path)
    try:
        image = pdf[page_no - 1].render(scale=scale).to_pil()
    finally:
        pdf.close()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def verify_ocr(
    parsed: ParsedDocument, pdf_path: Path, llm: LLMGateway, context: CallContext
) -> tuple[ParsedDocument, list[IngestWarning]]:
    """Cross-check every OCR'd page; returns updated items and warnings."""
    warnings: list[IngestWarning] = []
    items = list(parsed.items)
    pages = list(parsed.pages)
    for p_idx, page in enumerate(pages):
        if page.text_source != TextSource.OCR:
            continue
        on_page = [
            idx
            for idx, it in enumerate(items)
            if it.text_source == TextSource.OCR and it.regions[0].page == page.page_no
        ]
        try:
            reading = llm.structured(
                "ocr_second_reading",
                PageReading,
                images=[render_page_png(pdf_path, page.page_no)],
                context=context,
            )
        except (LLMUnavailable, LLMOutputError) as exc:
            warnings.append(
                IngestWarning(
                    code="ocr_unverified",
                    page=page.page_no,
                    message=f"OCR not cross-checked ({exc}); retried on the next run",
                )
            )
            continue

        text_idx = [i for i in on_page if items[i].kind in TEXT_KINDS]
        text_blocks = [b.text for b in reading.blocks if b.kind == "text" and b.text.strip()]
        steps = align([items[i].text for i in text_idx], text_blocks)
        trusted = _trusted_pairs(steps)
        for pos, item_idx in enumerate(text_idx):
            item = items[item_idx]
            if pos not in trusted:
                warnings.append(
                    IngestWarning(
                        code="ocr_disputed",
                        page=page.page_no,
                        message=f"no matching vision reading for OCR text {item.text[:60]!r}",
                    )
                )
                continue
            j, sim = trusted[pos]
            items[item_idx] = _reconciled(
                item, clean_text(text_blocks[j]), sim, warnings, page.page_no
            )

        table_idx = [i for i in on_page if items[i].kind == NodeKind.TABLE]
        table_blocks = [b for b in reading.blocks if b.kind == "table"]
        for k, item_idx in enumerate(table_idx):
            block = table_blocks[k] if k < len(table_blocks) else None
            items[item_idx] = _reconciled_table(items[item_idx], block, warnings, page.page_no)

        pages[p_idx] = page.model_copy(update={"text_source": TextSource.OCR_VERIFIED})
    return parsed.model_copy(update={"items": items, "pages": pages}), warnings


def _reconciled(item: RawItem, vision: str, sim: float, warnings, page_no: int) -> RawItem:
    if sim >= AGREE:
        return item.model_copy(update={"text": vision, "text_source": TextSource.OCR_VERIFIED})
    if sim < MAJOR:
        warnings.append(
            IngestWarning(
                code="ocr_corrected",
                page=page_no,
                message=f"OCR read {item.text[:60]!r}, vision read {vision[:60]!r}: using vision",
            )
        )
    return item.model_copy(
        update={"text": vision, "text_source": TextSource.VISION, "alt_text": item.text}
    )


def _reconciled_table(item: RawItem, block: PageBlock | None, warnings, page_no: int) -> RawItem:
    table = item.table
    shape_ok = (
        block is not None
        and len(block.rows) == table.num_rows
        and all(len(r) == table.num_cols for r in block.rows)
    )
    if not shape_ok:
        warnings.append(
            IngestWarning(
                code="ocr_disputed",
                page=page_no,
                message="OCR table not cross-checked: vision read a different shape",
            )
        )
        return item
    cells = []
    changed = 0
    for cell in table.cells:
        vision = clean_text(block.rows[cell.row][cell.col])
        if similarity(cell.text, vision) < AGREE:
            changed += 1
        cells.append(cell.model_copy(update={"text": vision}))
    text, new_table = linearize_table(table.model_copy(update={"cells": cells}))
    if changed:
        warnings.append(
            IngestWarning(
                code="ocr_corrected",
                page=page_no,
                message=f"{changed} table cell(s) corrected by the vision reading",
            )
        )
    return item.model_copy(
        update={
            "text": text,
            "table": new_table,
            "text_source": TextSource.VISION if changed else TextSource.OCR_VERIFIED,
            "alt_text": item.text if changed else None,
        }
    )
