"""BFF FastAPI application.

Phase 1 surface:
  GET /healthz          liveness
  GET /readyz           readiness (can reach the issuer JWKS)
  GET /bff/v1/whoami    verify the user's token (JWKS), then aggregate /me from
                        Identity behind a timeout — degrading to 503 if Identity
                        is down (demonstrates the fault-isolation contract).
Errors use the same envelope shape as the Django services.
"""

from __future__ import annotations

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import current_claims
from .config import settings

app = FastAPI(title="Tara BFF", version="1.0.0", docs_url="/bff/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ERROR_CODE_BY_STATUS = {
    400: "validation_error",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
    503: "dependency_unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _ERROR_CODE_BY_STATUS.get(exc.status_code, "internal_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": str(exc.detail),
                "request_id": request.headers.get("x-request-id"),
                "details": [],
            }
        },
    )


@app.get("/healthz", tags=["health"])
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    ok = True
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            resp = await client.get(settings.jwks_url)
            checks["identity_jwks"] = (
                "ok" if resp.status_code == 200 else f"status {resp.status_code}"
            )
            ok = resp.status_code == 200
    except Exception as exc:  # noqa: BLE001
        checks["identity_jwks"] = f"unreachable: {exc}"
        ok = False
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )


@app.get("/bff/v1/whoami", tags=["account"])
async def whoami(request: Request, claims: dict = Depends(current_claims)) -> JSONResponse:
    """Token is already verified locally; enrich it by aggregating /me.

    If Identity is unavailable we still return the verified token identity with a
    `degraded` flag instead of failing — graceful degradation (doc 02 §5).
    """
    auth_header = request.headers.get("authorization", "")
    profile = None
    degraded = False
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            resp = await client.get(
                f"{settings.identity_base_url}/api/v1/me/",
                headers={"Authorization": auth_header},
            )
        if resp.status_code == 200:
            profile = resp.json().get("data")
        else:
            degraded = True
    except Exception:  # noqa: BLE001 - Identity down -> degrade, don't fail
        degraded = True

    return JSONResponse(
        content={
            "data": {
                "account_id": claims.get("sub"),
                # Access tokens no longer carry the email (roadmap 8.12); /me/
                # returns it to its owner. None while identity is degraded.
                "email": (profile or {}).get("email") or claims.get("email"),
                "scopes": claims.get("scope", "").split(),
                "profile": profile,
                "degraded": degraded,
            }
        }
    )
