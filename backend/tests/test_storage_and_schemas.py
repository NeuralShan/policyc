import io

import pytest
from pydantic import ValidationError

from app.core.storage import LocalStorage, UploadTooLarge
from app.schemas.provenance import BBox, SourceSpan
from app.schemas.taxonomy import TAXONOMY, GapCategory


def test_storage_is_content_addressed_and_deduplicates(tmp_path):
    storage = LocalStorage(tmp_path)
    a = storage.put("prj_1", io.BytesIO(b"hello"), ".PDF", max_bytes=100)
    b = storage.put("prj_1", io.BytesIO(b"hello"), ".pdf", max_bytes=100)
    assert a == b
    assert a.key == f"prj_1/{a.sha256}.pdf"
    assert storage.path(a.key).read_bytes() == b"hello"
    assert [p.name for p in (tmp_path / "prj_1").iterdir()] == [f"{a.sha256}.pdf"]


def test_storage_enforces_limits_and_rejects_escapes(tmp_path):
    storage = LocalStorage(tmp_path)
    with pytest.raises(UploadTooLarge):
        storage.put("prj_1", io.BytesIO(b"x" * 101), ".txt", max_bytes=100)
    assert list((tmp_path / "prj_1").iterdir()) == []  # temp file cleaned up
    for namespace in ("../evil", "a/b", ""):
        with pytest.raises(ValueError):
            storage.put(namespace, io.BytesIO(b"x"), ".txt", max_bytes=100)
    with pytest.raises(ValueError):
        storage.put("prj_1", io.BytesIO(b"x"), "/../x", max_bytes=100)
    with pytest.raises(ValueError):
        storage.path("../outside.txt")


def test_source_span_validation_and_quote_hash():
    span = SourceSpan(document_id="doc_1", page=2, char_start=10, char_end=20, quote="promptly")
    assert len(span.quote_sha256) == 64
    with pytest.raises(ValidationError):
        SourceSpan(document_id="doc_1", char_start=10, quote="x")  # end missing
    with pytest.raises(ValidationError):
        SourceSpan(document_id="doc_1", char_start=10, char_end=5, quote="x")
    with pytest.raises(ValidationError):
        SourceSpan(document_id="doc_1", page=0, quote="x")
    with pytest.raises(ValidationError):
        BBox(x0=10, y0=0, x1=5, y1=1)


def test_taxonomy_codes_are_well_formed():
    for code, gap in TAXONOMY.items():
        assert code == gap.code
        assert len(code) == 5 and code[2:].isdigit()
        assert gap.category == GapCategory[code[:2]]
    assert {code[:2] for code in TAXONOMY} == {c.name for c in GapCategory}
