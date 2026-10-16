"""Local model weights for Docling (layout, table structure, OCR), kept inside the project.

    uv run python -m app.ingest.models      # download once (about 730 MB)

Downloads use the operating system's certificate store (``truststore``) so they work behind a
corporate TLS-inspecting proxy, where Python's bundled CA list fails with CERTIFICATE_VERIFY_FAILED.
"""

import logging
import sys
import threading
from pathlib import Path

from app.core.config import Settings

log = logging.getLogger(__name__)
_lock = threading.Lock()

REQUIRED = ("docling-project--docling-layout-heron", "docling-project--docling-models", "RapidOcr")


def docling_artifacts(settings: Settings) -> Path:
    return settings.models_dir / "docling"


def models_present(path: Path) -> bool:
    return all((path / name).is_dir() and any((path / name).iterdir()) for name in REQUIRED)


def ensure_docling_models(settings: Settings) -> Path:
    path = docling_artifacts(settings)
    with _lock:
        if models_present(path):
            return path
        log.info("downloading Docling models to %s (first run only)", path)
        import truststore
        from docling.utils.model_downloader import download_models

        truststore.inject_into_ssl()
        download_models(
            output_dir=path,
            with_layout=True,
            with_tableformer=True,
            with_rapidocr=True,
            with_code_formula=False,
            with_picture_classifier=False,
        )
        if not models_present(path):
            raise RuntimeError(f"Docling model download incomplete in {path}")
        return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(ensure_docling_models(Settings()))
    sys.exit(0)
