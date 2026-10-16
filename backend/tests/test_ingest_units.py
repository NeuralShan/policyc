"""Layer 1 building blocks, without Docling: numbering, assembly, text parsing, OCR alignment."""

import pytest

from app.ingest.assemble import ParsedDocument, RawItem, Region, assemble, linearize_table
from app.ingest.numbering import depth, marker_number, split_number
from app.ingest.ocr_check import _trusted_pairs, align, similarity
from app.ingest.text_parser import parse_text
from app.schemas.docast import NodeKind, TableCell, TableData
from app.schemas.provenance import BBox
from tests.conftest import GOLDEN


@pytest.mark.parametrize(
    ("text", "number", "rest"),
    [
        ("4.3 Refund decision", "4.3", "Refund decision"),
        ("2.2The machine is shut down", "2.2", "The machine is shut down"),  # OCR-fused
        ("10. If the customer disputes", "10", "If the customer disputes"),
        ("(1) Notify all affected employees", "(1)", "Notify all affected employees"),
        ("a) Collect proof of address", "a", "Collect proof of address"),
        ("Step 3: Approve the claim", "Step 3", "Approve the claim"),
        ("5 Purchase order", "5", "Purchase order"),
        ("5 business days are allowed", None, "5 business days are allowed"),
        ("Purpose", None, "Purpose"),
    ],
)
def test_split_number(text, number, rest):
    assert split_number(text) == (number, rest)


def test_marker_number_and_depth():
    assert marker_number("•") is None and marker_number("") is None
    assert marker_number("4.1") == "4.1" and marker_number("3.") == "3"
    assert marker_number("a)") == "a)"
    assert [depth(n) for n in ("4", "4.3", "4.3.1", "(2)", None)] == [1, 2, 3, None, None]


def _parsed(*items: RawItem) -> ParsedDocument:
    return ParsedDocument(parser="test", items=list(items))


def test_assemble_offsets_tree_and_title():
    ast = assemble(
        _parsed(
            RawItem(kind=NodeKind.HEADING, text="Refund  SOP"),  # unnumbered first heading
            RawItem(kind=NodeKind.HEADING, text="1 Scope"),
            RawItem(
                kind=NodeKind.LIST_ITEM,
                text="1.1 Applies   to refunds.",
                regions=[
                    Region(page=1, bbox=BBox(x0=1, y0=2, x1=3, y1=4)),
                    Region(page=2, bbox=BBox(x0=1, y0=2, x1=3, y1=4)),
                ],
            ),
            RawItem(kind=NodeKind.HEADING, text="2 Steps"),
            RawItem(kind=NodeKind.HEADING, text="2.1 Logging"),
            RawItem(kind=NodeKind.PARAGRAPH, text="   "),  # dropped: empty
            RawItem(kind=NodeKind.LIST_ITEM, text="The agent logs it."),
        ),
        document_id="doc_1",
        sha256="0" * 64,
        filename="x.md",
        media_type="text/markdown",
    )
    kinds = [(n.id, n.kind, n.level, n.number, n.parent_id) for n in ast.nodes]
    assert kinds == [
        ("n0001", "title", 0, None, None),
        ("n0002", "heading", 1, "1", "n0001"),
        ("n0003", "list_item", None, "1.1", "n0002"),
        ("n0004", "heading", 1, "2", "n0001"),
        ("n0005", "heading", 2, "2.1", "n0004"),
        ("n0006", "list_item", None, None, "n0005"),
    ]
    assert ast.nodes[0].text == "Refund SOP"  # whitespace normalised
    for node in ast.nodes:
        for span in node.spans:
            assert ast.text[span.char_start : span.char_end] == span.quote == node.text
    assert [s.page for s in ast.nodes[2].spans] == [1, 2]  # one span per page region


def test_table_cells_point_into_canonical_text():
    table = TableData(
        num_rows=2,
        num_cols=2,
        cells=[
            TableCell(row=0, col=0, text="Amount", column_header=True),
            TableCell(row=0, col=1, text="Approver", column_header=True),
            TableCell(row=1, col=0, text="< 5,000"),
            TableCell(row=1, col=1, text="Line  manager"),
        ],
    )
    text, table = linearize_table(table)
    assert text == "Amount | Approver\n< 5,000 | Line manager"
    ast = assemble(
        _parsed(
            RawItem(kind=NodeKind.PARAGRAPH, text="Approval limits"),
            RawItem(kind=NodeKind.TABLE, text=text, table=table),
        ),
        document_id="d",
        sha256="0" * 64,
        filename="x",
        media_type="x",
    )
    node = ast.nodes[1]
    assert node.table.grid() == [["Amount", "Approver"], ["< 5,000", "Line manager"]]
    for cell in node.table.cells:
        assert ast.text[cell.char_start : cell.char_end] == cell.text


def test_text_parser_on_osha_appendix():
    parsed = parse_text(
        GOLDEN / "OSHA_29CFR1910.147_AppendixA_Typical_Minimal_Lockout_Procedure.txt"
    )
    ast = assemble(
        parsed, document_id="d", sha256="0" * 64, filename="x.txt", media_type="text/plain"
    )
    title = ast.nodes[1]
    assert title.kind == "title" and title.text.startswith("Appendix A to")
    headings = [n.text for n in ast.nodes if n.kind == "heading"]
    assert {"Purpose", "Sequence of Lockout", "Compliance With This Program"} <= set(headings)
    steps = [n for n in ast.nodes if n.kind == "list_item"]
    assert [s.number for s in steps[:8]] == [f"({i})" for i in range(1, 9)]
    assert steps[3].text.startswith("(4) De-activate the energy isolating device(s)")
    assert all(n.parent_id for n in ast.nodes[1:] if n.kind != "title")


def test_alignment_pairs_a_garbled_line_between_good_neighbours():
    ocr = [
        "2.1 The authorized employee notifies all affected employees.",
        "2.2The machine is shut down using its normal stopping procedure.",
        "2e c (aot t ) s   ated.",
        "2.4 The authorized employee applies a personal lock and tag.",
    ]
    vision = [
        "2.1 The authorized employee notifies all affected employees.",
        "2.2 The machine is shut down using its normal stopping procedure.",
        "2.3 All energy sources (electrical, pneumatic, hydraulic) are isolated.",
        "2.4 The authorized employee applies a personal lock and tag.",
    ]
    assert similarity(ocr[1], vision[1]) == 1.0  # whitespace-only difference
    assert similarity(ocr[2], vision[2]) < 0.5
    trusted = _trusted_pairs(align(ocr, vision))
    assert {i: j for i, (j, _) in trusted.items()} == {0: 0, 1: 1, 2: 2, 3: 3}


def test_alignment_leaves_unmatched_text_unpaired():
    ocr = ["Totally different heading", "1.1 Shared clause about refunds."]
    vision = ["1.1 Shared clause about refunds.", "An extra block the OCR never saw."]
    trusted = _trusted_pairs(align(ocr, vision))
    assert trusted == {1: (0, 1.0)}
