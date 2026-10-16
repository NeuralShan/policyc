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
            blocks[-1].append(line.strip())
        elif blocks[-1]:
            blocks.append([])

    items: list[RawItem] = []
    seen_heading = False
    for lines in blocks:
        if not lines:
            continue
        text = " ".join(lines)
        number, _ = split_number(text)
        if len(lines) == 1 and _is_heading(text):
            kind = NodeKind.HEADING if seen_heading else NodeKind.TITLE
            seen_heading = True
        elif number:
            kind = NodeKind.LIST_ITEM
        else:
            kind = NodeKind.PARAGRAPH
        items.append(RawItem(kind=kind, text=text, number=number))
    return ParsedDocument(parser=PARSER_NAME, items=items)
