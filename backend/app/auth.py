"""Optional Firebase Auth (Google sign-in) verification.

Enabled only when ``PC_FIREBASE_PROJECT_ID`` is set; otherwise every request is treated as an
authorised local user and nothing changes. The ID token comes from ``Authorization: Bearer`` or,
for EventSource (which cannot set headers), the ``access_token`` query parameter. A missing or
invalid token means "guest" (``uid=None``).
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Annotated, Any

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from google.auth import jwt as google_jwt

from app.ingest.capabilities import full_parsing

log = logging.getLogger(__name__)

CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
_CERT_TTL_S = 3600.0
_certs: tuple[float, dict[str, str]] | None = None
_certs_lock = threading.Lock()


@dataclass(frozen=True)
class User:
    uid: str | None = None
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    open_access: bool = False  # auth disabled (PC_FIREBASE_PROJECT_ID unset): everything allowed

    @property
    def signed_in(self) -> bool:
        return self.uid is not None


GUEST = User()
OPEN_USER = User(open_access=True)


def _signing_certs() -> dict[str, str]:
    """Firebase signing certs, cached for an hour (stale copy is reused if a refresh fails)."""
    global _certs
    with _certs_lock:
        now = time.monotonic()
        if _certs is None or now - _certs[0] > _CERT_TTL_S:
            try:
                resp = requests.get(CERTS_URL, timeout=5)
                resp.raise_for_status()
                _certs = (now, resp.json())
            except requests.RequestException:
                if _certs is None:
                    raise
                log.warning("could not refresh Firebase certs; using cached copy")
        return _certs[1]


def verify_token(token: str, project_id: str) -> dict[str, Any] | None:
    """Returns the verified Firebase ID-token claims, or None if invalid. Tests monkeypatch this."""
    try:
        claims = google_jwt.decode(token, certs=_signing_certs(), audience=project_id)
    except Exception as exc:  # bad signature/expired/wrong audience/network
        log.info("rejected Firebase token: %s", exc)
        return None
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        return None
    if not claims.get("sub"):
        return None
    return claims


def auth_enabled(request: Request) -> bool:
    return bool(request.app.state.settings.firebase_project_id)


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.query_params.get("access_token") or None


def get_current_user(request: Request) -> User:
    project_id = request.app.state.settings.firebase_project_id
    if not project_id:
        return OPEN_USER
    token = _extract_token(request)
    claims = verify_token(token, project_id) if token else None
    if not claims:
        return GUEST
    return User(
        uid=claims.get("user_id") or claims["sub"],
        email=claims.get("email"),
        name=claims.get("name"),
        picture=claims.get("picture"),
    )


UserDep = Annotated[User, Depends(get_current_user)]


def assert_can_write(user: User) -> None:
    """Raises 401 {"detail": "Sign in required"} for guests when auth is enabled."""
    if not user.open_access and not user.signed_in:
        raise HTTPException(status_code=401, detail="Sign in required")


router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me")
def me(request: Request, user: UserDep) -> dict[str, Any]:
    return {
        "auth_enabled": auth_enabled(request),
        "parsing": "full" if full_parsing() else "lite",
        "uid": user.uid,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }
