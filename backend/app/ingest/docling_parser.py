"""PDF, DOCX, HTML and Markdown via Docling -> ``ParsedDocument``.

PDF pages without a text layer (scans) are OCR'd locally with RapidOCR; those items are marked
``TextSource.OCR`` so the vision cross-check (``ocr_check``) knows what to verify.
"""

import io
import re
import threading
from importlib.metadata import version
from pathlib import Path

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.ingest.assemble import ParsedDocument, RawItem, Region, linearize_table
from app.ingest.models import ensure_docling_models
from app.ingest.numbering import marker_number
from app.schemas.docast import (
    DiagramStatus,
    FigureData,
    NodeKind,
    PageInfo,
    TableCell,
    TableData,
    TextSource,
)
from app.schemas.provenance import BBox

# Bump when the mapping below changes, so cached parses are rebuilt.
ITEMS_VERSION = 2
MIN_TEXT_CHARS = 20  # fewer characters on a PDF page than this: treat it as a scan
FIGURE_MIN_AREA = 0.03  # share of the page a figure must cover to be analysed as a diagram
FIGURE_MIN_SIDE_PT = 72.0
FIGURE_MIN_SIDE_PX = 200


def scanned_pages(path: Path) -> list[int]:
    """1-based numbers of PDF pages that have (almost) no text layer."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return [
            i + 1
            for i, page in enumerate(pdf)
            if len(page.get_textpage().get_text_range().strip()) < MIN_TEXT_CHARS
        ]
    finally:
        pdf.close()


def _squash(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


# Converters load their models once and are reused process-wide. Docling is CPU-bound and not
# thread-safe, so one lock serialises all conversions.
_CONVERTERS: dict[tuple, object] = {}
_LOCK = threading.Lock()


class DoclingParser:
    def __init__(self, settings: Settings, storage: LocalStorage):
        self.settings = settings
        self.storage = storage

    @property
    def name(self) -> str:
        return f"docling {version('docling')} / items v{ITEMS_VERSION}"

    def parse(self, path: Path, media_type: str) -> ParsedDocument:
        from docling.datamodel.base_models import ConversionStatus

        is_pdf = media_type == "application/pdf"
        ocr_pages = scanned_pages(path) if is_pdf else []
        with _LOCK:
            converter = self._converter(pdf=is_pdf, ocr=bool(ocr_pages))
            result = converter.convert(path, raises_on_error=False)
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            errors = "; ".join(e.error_message for e in result.errors) or str(result.status)
            raise ValueError(f"could not parse {path.name}: {errors}")
        return self._items(result.document, set(ocr_pages))

    def _converter(self, *, pdf: bool, ocr: bool):
        """Called with ``_LOCK`` held."""
        key = (
            ("pdf", ocr, str(self.settings.models_dir), self.settings.ocr_lang)
            if pdf
            else ("simple",)
        )
        if key not in _CONVERTERS:
            from docling.document_converter import DocumentConverter

            if not pdf:
                _CONVERTERS[key] = DocumentConverter()
            else:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    HeadingHierarchyOptions,
                    PdfPipelineOptions,
                    RapidOcrOptions,
                )
                from docling.document_converter import PdfFormatOption

                options = PdfPipelineOptions(
                    artifacts_path=ensure_docling_models(self.settings),
                    do_ocr=ocr,
                    do_table_structure=True,
                    generate_picture_images=True,
                    images_scale=2.0,
                    generate_parsed_pages=True,
                    heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
                )
                if ocr:
                    options.ocr_options = RapidOcrOptions(
                        lang=[self.settings.ocr_lang], backend="torch"
                    )
                _CONVERTERS[key] = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
                )
        return _CONVERTERS[key]

    def _items(self, doc, ocr_pages: set[int]) -> ParsedDocument:
        from docling_core.types.doc import (
            ContentLayer,
            DocItemLabel,
            GroupItem,
            ListItem,
            PictureItem,
            SectionHeaderItem,
            TableItem,
            TextItem,
        )
        from docling_core.types.doc.document import InlineGroup

        sizes = {n: (p.size.width, p.size.height) for n, p in doc.pages.items()}
        heights = {n: h for n, (_, h) in sizes.items()}
        pages = [
            PageInfo(
                page_no=n,
                width=p.size.width,
                height=p.size.height,
                text_source=TextSource.OCR if n in ocr_pages else TextSource.NATIVE,
            )
            for n, p in sorted(doc.pages.items())
        ]

        def regions(item) -> list[Region]:
            out = []
            for prov in getattr(item, "prov", None) or []:
                b = prov.bbox.to_top_left_origin(heights[prov.page_no])
                out.append(
                    Region(
                        page=prov.page_no,
                        bbox=BBox(x0=b.l, y0=min(b.t, b.b), x1=b.r, y1=max(b.t, b.b)),
                    )
                )
            return out or [Region()]

        def source(rs: list[Region]) -> TextSource:
            return TextSource.OCR if any(r.page in ocr_pages for r in rs) else TextSource.NATIVE

        caption_refs = {
            ref.cref
            for item in [*doc.tables, *doc.pictures]
            for ref in getattr(item, "captions", [])
        }
        furniture: list[str] = []
        for item, _ in doc.iterate_items(included_content_layers={ContentLayer.FURNITURE}):
            if isinstance(item, TextItem) and item.text.strip() and item.text not in furniture:
                furniture.append(item.text.strip())

        items: list[RawItem] = []
        first_heading: tuple[str, int | None] | None = None
        empty_list_item: ListItem | None = None  # list item whose text is an inline group
        inline_level: int | None = None  # skip the children of a merged inline group
        for item, depth in doc.iterate_items(
            with_groups=True, included_content_layers={ContentLayer.BODY}
        ):
            if inline_level is not None:
                if depth > inline_level:
                    continue
                inline_level = None
            if isinstance(item, InlineGroup):
                # Formatting ("**bold**: rest") splits one clause into fragments; rejoin them.
                inline_level = depth
                fragments = _inline_fragments(item, doc)
                text = _join_fragments([t for t, _ in fragments])
                rs = [r for _, frag in fragments for r in regions(frag) if r.page] or [Region()]
                if empty_list_item is not None:
                    number = marker_number(empty_list_item.marker)
                    if number:
                        text = f"{empty_list_item.marker.strip()} {text}"
                    items.append(
                        RawItem(
                            kind=NodeKind.LIST_ITEM,
                            text=text,
                            regions=rs,
                            number=number,
                            text_source=source(rs),
                        )
                    )
                else:
                    items.append(
                        RawItem(
                            kind=NodeKind.PARAGRAPH, text=text, regions=rs, text_source=source(rs)
                        )
                    )
                empty_list_item = None
                continue
            empty_list_item = None
            if isinstance(item, GroupItem):
                continue
            rs = regions(item)
            if isinstance(item, ListItem) and not item.text.strip():
                empty_list_item = item
                continue
            if isinstance(item, TableItem):
                caption = item.caption_text(doc).strip()
                if caption:
                    items.append(RawItem(kind=NodeKind.PARAGRAPH, text=caption, regions=rs))
                text, table = linearize_table(_table_data(item, heights))
                items.append(
                    RawItem(
                        kind=NodeKind.TABLE,
                        text=text,
                        regions=rs,
                        table=table,
                        text_source=source(rs),
                    )
                )
            elif isinstance(item, PictureItem):
                items.append(
                    RawItem(
                        kind=NodeKind.FIGURE,
                        text=item.caption_text(doc).strip(),
                        regions=rs,
                        figure=self._figure(item, doc, rs, sizes),
                    )
                )
            elif isinstance(item, TextItem):
                if item.self_ref in caption_refs or not item.text.strip():
                    continue
                text = item.text
                kind = NodeKind.PARAGRAPH
                number = None
                level = None
                if item.label == DocItemLabel.TITLE:
                    kind = NodeKind.TITLE
                elif isinstance(item, SectionHeaderItem):
                    kind, level = NodeKind.HEADING, item.level
                elif isinstance(item, ListItem):
                    kind = NodeKind.LIST_ITEM
                    number = marker_number(item.marker)
                    orig = (item.orig or "").strip()
                    if number and orig.startswith((item.marker or "").strip()):
                        text = orig
                    elif number:
                        text = f"{item.marker.strip()} {item.text}"
                elif item.label == DocItemLabel.FOOTNOTE:
                    kind = NodeKind.NOTE

                if kind in (NodeKind.TITLE, NodeKind.HEADING):
                    page = rs[0].page
                    if first_heading is None:
                        first_heading = (_squash(text), page)
                    elif _squash(text) == first_heading[0] and page != first_heading[1]:
                        furniture.append(text.strip())  # running title repeated on later pages
                        continue
                items.append(
                    RawItem(
                        kind=kind,
                        text=text,
                        regions=rs,
                        number=number,
                        level=level,
                        text_source=source(rs),
                    )
                )
        items = _adopt_captions(items)
        return ParsedDocument(parser=self.name, items=items, pages=pages, furniture=furniture)

    def _figure(self, item, doc, rs: list[Region], sizes) -> FigureData:
        """Store the figure image; mark it for diagram analysis unless it's logo/icon-sized."""
        image = item.get_image(doc)
        key = None
        large = False
        if image is not None:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            key = self.storage.put("figures", buffer, ".png", max_bytes=50 * 1024 * 1024).key
            large = min(image.size) >= FIGURE_MIN_SIDE_PX  # unpaged formats: judge by pixels
        region = rs[0]
        if region.bbox is not None and region.page in sizes:
            page_w, page_h = sizes[region.page]
            width = region.bbox.x1 - region.bbox.x0
            height = region.bbox.y1 - region.bbox.y0
            large = (
                min(width, height) >= FIGURE_MIN_SIDE_PT
                and width * height >= FIGURE_MIN_AREA * page_w * page_h
            )
        status = DiagramStatus.PENDING if key and large else DiagramStatus.SKIPPED
        return FigureData(
            image_key=key, caption=item.caption_text(doc).strip() or None, diagram_status=status
        )


_CAPTION = re.compile(r"^(figure|fig\.?|diagram|chart|exhibit)\s*\d+", re.IGNORECASE)


def _adopt_captions(items: list[RawItem]) -> list[RawItem]:
    """Word captions are separate paragraphs ("Figure 1: ..."). Attach one directly after (or
    before) an uncaptioned figure to it, so the caption reaches the diagram reader."""
    out = list(items)
    drop: set[int] = set()
    for i, item in enumerate(out):
        if item.kind != NodeKind.FIGURE or item.text or item.figure is None:
            continue
        for j in (i + 1, i - 1):
            if 0 <= j < len(out) and j not in drop:
                cand = out[j]
                if cand.kind == NodeKind.PARAGRAPH and _CAPTION.match(cand.text.strip()):
                    caption = cand.text.strip()
                    out[i] = item.model_copy(
                        update={
                            "text": caption,
                            "figure": item.figure.model_copy(update={"caption": caption}),
                        }
                    )
                    drop.add(j)
                    break
    return [it for k, it in enumerate(out) if k not in drop]


def _inline_fragments(group, doc) -> list[tuple[str, object]]:
    """(text, item) for every text-bearing descendant of an inline group, in order."""
    out = []
    for ref in group.children:
        child = ref.resolve(doc)
        text = getattr(child, "text", "")
        if text:
            out.append((text, child))
        if getattr(child, "children", None):
            out.extend(_inline_fragments(child, doc))
    return out


def _join_fragments(parts: list[str]) -> str:
    joined = " ".join(p.strip() for p in parts if p.strip())
    return re.sub(r"\s+([,.;:!?)\]])", r"\1", re.sub(r"([(\[])\s+", r"\1", joined))


def _table_data(item, heights) -> TableData:
    page = item.prov[0].page_no if item.prov else None
    cells = []
    for c in item.data.table_cells:
        bbox = None
        if c.bbox is not None and page in heights:
            b = c.bbox.to_top_left_origin(heights[page])
            bbox = BBox(x0=b.l, y0=min(b.t, b.b), x1=b.r, y1=max(b.t, b.b))
        cells.append(
            TableCell(
                row=c.start_row_offset_idx,
                col=c.start_col_offset_idx,
                row_span=c.row_span,
                col_span=c.col_span,
                text=c.text,
                column_header=c.column_header,
                row_header=c.row_header,
                bbox=bbox,
            )
        )
    return TableData(num_rows=item.data.num_rows, num_cols=item.data.num_cols, cells=cells)
