"""Deterministic readers for common clause patterns.

These are the safety net behind the LLM: they turn "claims below INR 10,000", "submitted by a
manager" or "no person may approve their own claim" into conditions/constraints without a model
call, so the flow normaliser still produces checkable structure when the LLM output is weak.
Every function returns ``None`` when the text does not clearly match: they never guess.
"""

from __future__ import annotations

import re

from app.logic import norm_text
from app.schemas.ir_sop import (
    CompareCondition,
    ConditionExpr,
    LogicalCondition,
    RoleRef,
    TimeUnit,
    TypedValue,
    ValueType,
)

_CURRENCY = r"(?P<cur>INR|Rs\.?|USD|US\$|\$|EUR|€|GBP|£|₹|IDR|SGD|JPY|¥)?"
_NUM = r"(?P<num>\d[\d,]*(?:\.\d+)?)"
_AMT = rf"{_CURRENCY}\s*{_NUM}"

_AMOUNT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("le", re.compile(rf"(?:up\s+to(?:\s+and\s+including)?|at\s+most|not\s+more\s+than|not\s+exceeding|no\s+more\s+than)\s+{_AMT}", re.I)),
    ("le", re.compile(rf"{_AMT}\s+or\s+(?:below|less|under|lower)", re.I)),
    ("ge", re.compile(rf"(?:at\s+least|minimum\s+of|not\s+less\s+than|no\s+less\s+than)\s+{_AMT}", re.I)),
    ("ge", re.compile(rf"{_AMT}\s+or\s+(?:more|above|over|higher|greater)", re.I)),
    ("lt", re.compile(rf"(?:below|under|less\s+than|lower\s+than|smaller\s+than)\s+{_AMT}", re.I)),
    ("gt", re.compile(rf"(?:above|over|more\s+than|greater\s+than|exceed(?:s|ing)?|higher\s+than)\s+{_AMT}", re.I)),
]

_AGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ge", re.compile(r"(\d+)\s*(?:years?)?\s*(?:of\s+age\s+)?(?:or|and)\s+(?:older|above|over|more)", re.I)),
    ("lt", re.compile(r"(?:under|below|younger\s+than)\s+(\d+)\s*(?:years?)", re.I)),
    ("ge", re.compile(r"aged\s+(\d+)\s*(?:years?)?\s*(?:and|or)\s+(?:above|over|older)", re.I)),
]

_REQUESTER = re.compile(
    r"(?:submitted|requested|raised|initiated|made|filed|created)\s+by\s+(?:an?\s+|the\s+|any\s+)?"
    r"(?P<who>[A-Za-z][A-Za-z '’\-]{1,40}?)(?=[,.;:]|\s+(?:are|is|must|shall|require|will|need|should|may|to)\b|$)",
    re.I,
)
_OWN = re.compile(
    r"(?:(?:the\s+)?(?P<who1>[A-Za-z][A-Za-z \-]{1,30}?)['’]s\s+own\s+\w+)"
    r"|(?:own\s+\w+\s+of\s+(?:the\s+|an?\s+)?(?P<who2>[A-Za-z][A-Za-z \-]{1,30}?)(?=[,.;:]|\s+(?:must|shall|are|is)\b|$))",
    re.I,
)

_NO_SELF = re.compile(
    r"\b(?:no\s+(?:person|one|employee|individual|staff\s+member)|nobody|never|must\s+not|may\s+not"
    r"|shall\s+not|do\s+not|does\s+not|cannot|can\s+not|not\s+permitted\s+to)\b"
    r".{0,80}\b(?:own|themselves?|himself|herself|oneself)\b",
    re.I,
)
_APPROVE_VERB = re.compile(r"\b(?:approv\w*|authori[sz]\w*|sign\w*\s+off|review\w*|verif\w*|release\w*)\b", re.I)

_DEADLINE = re.compile(
    r"\b(?:within|in\s+under|no\s+later\s+than|not\s+later\s+than)\s+(?P<n>\d+(?:\.\d+)?)\s+"
    r"(?P<unit>calendar\s+days?|working\s+days?|business\s+days?|days?|hours?|weeks?)\b"
    r"(?:\s+(?:of|from|after)\s+(?P<anchor>[a-z ]{3,40}))?",
    re.I,
)

_EXCEPTION_START = re.compile(
    r"^\s*(?:if|where|when|whenever|upon|in\s+(?:the\s+)?(?:event|case)|for\s+(?:minor|exceptional|urgent)|"
    r"unless|except|should\s+\w+\s+be\s+(?:escalated|referred))\b",
    re.I,
)
_EXCEPTION_ANYWHERE = re.compile(r"\b(?:escalated\s+by|referred\s+by|exception|exceptional|override)\b", re.I)

_NON_OPERATIONAL_HEADING = re.compile(
    r"\b(?:purpose|scope|objectives?|applicability|definitions?|glossary|abbreviations?|background|"
    r"overview|introduction|references?|document\s+control|revision\s+history|related\s+documents|"
    r"policy\s+statement|intent)\b",
    re.I,
)

_RULE_HEADING = re.compile(
    r"\b(?:controls?|general\s+(?:rules?|provisions?|principles?)|principles?|rules?|"
    r"policy\s+rules?|compliance)\b",
    re.I,
)

_UNIT = {
    "calendar day": TimeUnit.CALENDAR_DAYS,
    "working day": TimeUnit.BUSINESS_DAYS,
    "business day": TimeUnit.BUSINESS_DAYS,
    "day": TimeUnit.DAYS,
    "hour": TimeUnit.HOURS,
    "week": TimeUnit.WEEKS,
}


def is_non_operational_heading(text: str) -> bool:
    return bool(_NON_OPERATIONAL_HEADING.search(text or ""))


def is_rule_heading(text: str) -> bool:
    """Section of standing rules (controls, principles) rather than sequential steps."""
    return bool(_RULE_HEADING.search(text or ""))


def is_exception_text(text: str) -> bool:
    """Clause that begins with a trigger/condition: it is entered on an event, not in sequence."""
    return bool(_EXCEPTION_START.search(text or "") or _EXCEPTION_ANYWHERE.search(text or ""))


def top_number(number: str | None) -> str | None:
    m = re.match(r"\s*(\d+)", number or "")
    return m.group(1) if m else None


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _currency(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip().rstrip(".").upper()
    return {"RS": "INR", "₹": "INR", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}.get(raw, raw)


def parse_amount_condition(text: str) -> CompareCondition | None:
    """``claims below INR 10,000`` → ``amount lt 10000 INR``."""
    for op, pattern in _AMOUNT_PATTERNS:
        m = pattern.search(text or "")
        if not m:
            continue
        cur = _currency(m.groupdict().get("cur"))
        has_money_word = re.search(r"\b(?:claims?|amounts?|value|cost|price|payments?|invoice|spend)\b", text, re.I)
        if cur is None and not has_money_word:
            continue
        return CompareCondition(
            left="amount",
            op=op,
            right=TypedValue(
                value_type=ValueType.MONEY if cur else ValueType.NUMBER,
                number=_to_float(m.group("num")),
                currency=cur,
            ),
        )
    return None


def parse_age_condition(text: str) -> CompareCondition | None:
    if not re.search(r"\b(?:age|aged|years?\s+old|minors?|adults?)\b", text or "", re.I):
        return None
    for op, pattern in _AGE_PATTERNS:
        m = pattern.search(text)
        if m:
            return CompareCondition(
                left="age", op=op, right=TypedValue(value_type=ValueType.NUMBER, number=float(m.group(1)))
            )
    return None


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _match_role(who: str | None, roles: list[RoleRef]) -> str | None:
    """Role id for ``who`` (exact name/id, singular or plural); else the cleaned literal text."""
    if not who:
        return None
    who_n = _singular(norm_text(who))
    if not who_n or len(who_n.split("_")) > 3:
        return None
    for role in roles:
        if who_n in {_singular(norm_text(role.name)), _singular(norm_text(role.id))}:
            return role.id
    return who_n


def parse_requester_condition(text: str, roles: list[RoleRef]) -> CompareCondition | None:
    """``submitted by a manager`` / ``the Finance Head's own claims`` → ``requester_role eq <role>``."""
    for pattern, group in ((_REQUESTER, "who"), (_OWN, "who1"), (_OWN, "who2")):
        for m in pattern.finditer(text or ""):
            role_id = _match_role(m.groupdict().get(group), roles)
            if role_id:
                return CompareCondition(
                    left="requester_role",
                    op="eq",
                    right=TypedValue(value_type=ValueType.ENUM, text=role_id),
                )
    return None


def parse_applicability(text: str, roles: list[RoleRef]) -> ConditionExpr | None:
    """Condition under which a clause applies (amount, age and/or requester), else None."""
    parts: list[ConditionExpr] = []
    for cond in (
        parse_amount_condition(text),
        parse_age_condition(text),
        parse_requester_condition(text, roles),
    ):
        if cond is not None:
            parts.append(cond)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return LogicalCondition(logical_op="and", operands=parts)


def is_no_self_action(text: str) -> bool:
    return bool(_NO_SELF.search(text or "") and _APPROVE_VERB.search(text or ""))


def parse_deadline(text: str) -> tuple[float, TimeUnit, str | None] | None:
    """``within 7 calendar days of submission`` → (7, calendar_days, 'submission')."""
    m = _DEADLINE.search(text or "")
    if not m:
        return None
    unit_raw = re.sub(r"s$", "", re.sub(r"\s+", " ", m.group("unit").lower()))
    unit = _UNIT.get(unit_raw, TimeUnit.DAYS)
    anchor = (m.group("anchor") or "").strip() or None
    return float(m.group("n")), unit, anchor


REFERENCE = re.compile(r"(?:section|clause|para(?:graph)?|annex|appendix)\s+(?P<num>\d+(?:\.\d+)*)", re.I)
_SEPARATE_FLOW_HEADING = re.compile(
    r"(?:audit|recertif|periodic|annual|quarterly|monitor|retention|records?|exceptions?|escalat|"
    r"emergency|appeals?|disputes?|complaints?|reporting|review\s+of)",
    re.I,
)
_OUTCOME = re.compile(
    r"\b(?:reject\w*|declin\w*|den(?:y|ies|ied)|approv\w*|open(?:s|ed)?\s+(?:the\s+|an?\s+)?account|"
    r"clos\w+|resolv\w*|cancel\w*|terminat\w*|issu\w+|grant\w*|complet\w*|refund\w*|escalat\w*)\b",
    re.I,
)


def has_reference(text: str) -> bool:
    """Clause that hands off to another section/document (``as described in Section 9``)."""
    return bool(REFERENCE.search(text or ""))


def is_separate_flow_heading(text: str) -> bool:
    """Section describing a periodic or exceptional process rather than the main request flow."""
    return bool(_SEPARATE_FLOW_HEADING.search(text or ""))


def is_outcome_text(text: str) -> bool:
    return bool(_OUTCOME.search(text or ""))
