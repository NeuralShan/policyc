"""Clause numbering as printed in SOPs: "4.3", "10.", "(2)", "a)", "Step 3".

Numbering matters downstream: SOP text refers to it ("return to step 3"), and dotted numbers give
the heading depth when the layout doesn't.
"""

import re

# Order matters: the most specific forms first. Dotted numbers may be fused to the next word in
# OCR output ("2.2The machine"), so an uppercase letter also ends them.
_PATTERNS = [
    re.compile(r"^(?P<num>(?:step|STEP|Step)\s+\d+(?:\.\d+)*)[.:)]?(?:\s+|$)"),
    re.compile(r"^(?P<num>\(\s*(?:\d+|[a-zA-Z]|[ivxIVX]{1,5})\s*\))(?:\s+|$)"),
    re.compile(r"^(?P<num>\d+(?:\.\d+)+)\.?(?:\s+|(?=[A-Z])|$)"),
    re.compile(r"^(?P<num>\d{1,3})[.)]?(?:\s+(?=\S)|$)"),
    re.compile(r"^(?P<num>[a-z])\)\s+"),
    re.compile(r"^(?P<num>[A-Z])\.\s+(?=[A-Z])"),
]

_BULLETS = {"•", "-", "–", "—", "*", "·", "▪", "◦", "○", "●", "■", "□", "➢", "✓"}


def split_number(text: str) -> tuple[str | None, str]:
    """Split leading clause numbering from ``text``. Returns ``(number, rest)``.

    A bare integer only counts as numbering when the rest starts like a sentence (uppercase or
    quote), so "5 business days are allowed" is left alone.
    """
    stripped = text.lstrip()
    for i, pattern in enumerate(_PATTERNS):
        match = pattern.match(stripped)
        if not match:
            continue
        rest = stripped[match.end() :]
        if i == 3 and rest and not (rest[0].isupper() or rest[0] in "\"'“("):
            return None, text
        return match.group("num"), rest
    return None, text


def marker_number(marker: str | None) -> str | None:
    """Normalise a list marker from the layout model: bullets carry no numbering."""
    if not marker:
        return None
    marker = marker.strip()
    if not marker or marker in _BULLETS:
        return None
    return marker.rstrip(".") if re.fullmatch(r"\d+(?:\.\d+)*\.?", marker) else marker


def depth(number: str | None) -> int | None:
    """Heading depth implied by dotted numbering: "4" -> 1, "4.3" -> 2. None if not dotted."""
    if number is None:
        return None
    match = re.fullmatch(r"(?:step\s+)?(\d+(?:\.\d+)*)\.?", number.strip(), flags=re.IGNORECASE)
    return match.group(1).count(".") + 1 if match else None
