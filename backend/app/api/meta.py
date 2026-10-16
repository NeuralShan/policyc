from fastapi import APIRouter

from app.pipeline.graph import IMPLEMENTED_STAGES
from app.pipeline.stages import STAGES
from app.schemas.api import StageOut
from app.schemas.taxonomy import TAXONOMY, GapCode

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/pipeline/stages")
def pipeline_stages() -> list[StageOut]:
    return [
        StageOut(
            key=s.key,
            label=s.label,
            layer=s.layer,
            compiler_analogy=s.compiler_analogy,
            description=s.description,
            implemented=s.key in IMPLEMENTED_STAGES,
        )
        for s in STAGES
    ]


@router.get("/taxonomy")
def taxonomy() -> list[GapCode]:
    return list(TAXONOMY.values())
