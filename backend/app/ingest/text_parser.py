"""Plain-text documents (Docling has no .txt reader).

Blocks are separated by blank lines; soft-wrapped lines inside a block are joined. A block is a
heading when it is one short line in Title Case or CAPITALS without closing punctuation, a list
item when it starts with clause numbering, otherwise a paragraph.
"""

import re
from pathlib import Path

from app.ingest.assemble import ParsedDocument, RawItem
from app.ingest.numbering import split_number
from app.schemas.docast import NodeKind

PARSER_NAME = "text v1"
_RULE = re.compile(r"^\s*([-=_*~])\1{3,}\s*$")
_CLAUSE_START = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S")
_SECTION_HEADING = re.compile(r"^\d+[.)]?\s+[A-Z][^.;:!?]{0,70}$")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _is_heading(line: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'()/-]*", line)
    if not words or len(line) > 100 or len(words) > 12:
        return False
    if line.rstrip()[-1] in ".;,!?" or (line.startswith("(") and line.endswith(")")):
        return False
    if line.isupper():
        return True
    significant = [w for w in words if w.lower() not in _SMALL_WORDS]
    capitalised = sum(w[0].isupper() for w in significant)
    return bool(significant) and capitalised / len(significant) >= 0.6


def parse_text(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks: list[list[str]] = [[]]
    for line in raw.split("\n"):
        if _RULE.match(line):
            blocks.append([])
        elif line.strip():
            text = line.strip()
            # SOP-style numbering: every numbered line starts its own clause (soft-wrapped
            # continuation lines carry no number and are still joined to the clause above)
            if _CLAUSE_START.match(text) and blocks[-1]:
                blocks.append([])
            blocks[-1].append(text)
        elif blocks[-1]:
            blocks.append([])

    items: list[RawItem] = []
    seen_heading = False
    for lines in blocks:
        if not lines:
            continue
        text = " ".join(lines)
        md = _MD_HEADING.match(text) if len(lines) == 1 else None
        if md:  # Markdown "## 4 Approval"
            text = md.group(2).strip()
            number, _ = split_number(text)
            kind = NodeKind.HEADING if seen_heading else NodeKind.TITLE
            seen_heading = True
            items.append(RawItem(kind=kind, text=text, number=number, level=len(md.group(1))))
            continue
        number, _ = split_number(text)
        if len(lines) == 1 and _SECTION_HEADING.match(text):
            # "4 Approval": a short top-level numbered line with no closing punctuation
            items.append(RawItem(kind=NodeKind.HEADING, text=text, number=number, level=1))
            seen_heading = True
            continue
        if len(lines) == 1 and _is_heading(text):
            kind = NodeKind.HEADING if seen_heading else NodeKind.TITLE
            seen_heading = True
        elif number:
            kind = NodeKind.LIST_ITEM
        else:
            kind = NodeKind.PARAGRAPH
        items.append(RawItem(kind=kind, text=text, number=number))
    return ParsedDocument(parser=PARSER_NAME, items=items)
