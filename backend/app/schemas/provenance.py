"""Provenance: the compiler's "debug symbols".

Every DocAST node, IR element, graph node, test and finding carries one or more ``SourceSpan``s so
any claim the system makes can be traced back to the exact place in the source document.
"""

import hashlib

from pydantic import BaseModel, Field, model_validator


class BBox(BaseModel):
    """Bounding box on a page, in PDF points, origin top-left."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox corners must satisfy x0 <= x1 and y0 <= y1")
        return self


class SourceSpan(BaseModel):
    document_id: str
    page: int | None = Field(default=None, ge=1, description="1-based; None for unpaged formats")
    bbox: BBox | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote: str = Field(description="Verbatim source text this span covers")
    quote_sha256: str = ""

    @model_validator(mode="after")
    def _check(self) -> "SourceSpan":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must be given together")
        if self.char_start is not None and self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if not self.quote_sha256:
            self.quote_sha256 = hashlib.sha256(self.quote.encode()).hexdigest()
        return self
