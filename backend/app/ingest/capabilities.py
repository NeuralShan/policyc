"""What this deployment can parse.

The full image has Docling (PDF/DOCX/HTML with page layout, tables, OCR). The "lite" image used on
free 512 MB hosts leaves Docling and PyTorch out: it reads plain text and Markdown with the built-in
text parser and politely refuses the rest. Everything after parsing (extraction, analysis, tests,
findings, explain & fix) is identical.
"""

from __future__ import annotations

import importlib.util

LITE_SUFFIXES = {".txt", ".md"}
DOCLING_ONLY_SUFFIXES = {".pdf", ".docx", ".html", ".htm"}

LITE_MESSAGE = (
    "This deployment has no PDF/Word/HTML reader (lightweight mode). Upload a .txt or .md file, "
    "open one of the sample procedures, or run PolicyC locally for full document parsing."
)


def full_parsing() -> bool:
    """True when Docling is installed."""
    return importlib.util.find_spec("docling") is not None


def can_parse(media_type: str) -> bool:
    if full_parsing():
        return True
    return media_type in ("text/plain", "text/markdown")
