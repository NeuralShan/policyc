"""Independent check of span accuracy on PDFs with a text layer.

For every node, the text inside its bounding box is re-extracted with pdfium (a different engine
from Docling's parser) and compared with the node text. This is the Layer 1 exit metric "span
accuracy". OCR'd pages have no text layer to compare against and are not counted.
"""

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from app.ingest.ocr_check import similarity
from app.schemas.docast import DocAST, NodeKind, TextSource

TEXT_THRESHOLD = 0.9
TABLE_THRESHOLD = 0.8
MARGIN_PT = 1.5


class SpanFailure(BaseModel):
    node_id: str
    page: int
    expected: str
    found: str
    score: float


class SpanReport(BaseModel):
    checked: int = 0
    ok: int = 0
    failures: list[SpanFailure] = []

    @property
    def accuracy(self) -> float:
        return self.ok / self.checked if self.checked else 1.0


def _word_overlap(a: str, b: str) -> float:
    wa, wb = Counter(re.findall(r"\w+", a.lower())), Counter(re.findall(r"\w+", b.lower()))
    if not wa:
        return 1.0
    return sum((wa & wb).values()) / sum(wa.values())


def check_spans(ast: DocAST, pdf_path: Path) -> SpanReport:
    import pypdfium2 as pdfium

    native = {p.page_no: p for p in ast.pages if p.text_source == TextSource.NATIVE}
    report = SpanReport()
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        textpages = {}
        for node in ast.nodes:
            if node.kind == NodeKind.FIGURE or not node.text:
                continue
            for span in node.spans:
                if span.bbox is None or span.page not in native:
                    continue
                if span.page not in textpages:
                    textpages[span.page] = pdf[span.page - 1].get_textpage()
                height = native[span.page].height
                found = textpages[span.page].get_text_bounded(
                    left=span.bbox.x0 - MARGIN_PT,
                    bottom=height - span.bbox.y1 - MARGIN_PT,
                    right=span.bbox.x1 + MARGIN_PT,
                    top=height - span.bbox.y0 + MARGIN_PT,
                )
                if node.kind == NodeKind.TABLE:
                    score, threshold = _word_overlap(node.text, found), TABLE_THRESHOLD
                else:
                    score, threshold = similarity(node.text, found), TEXT_THRESHOLD
                report.checked += 1
                if score >= threshold:
                    report.ok += 1
                else:
                    report.failures.append(
                        SpanFailure(
                            node_id=node.id,
                            page=span.page,
                            expected=node.text[:200],
                            found=found[:200],
                            score=round(score, 3),
                        )
                    )
    finally:
        pdf.close()
    return report
