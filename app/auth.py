"""Bearer estatico, mesmo molde do CRON_SECRET do lado da aplicacao principal:
sem a variavel configurada, toda chamada e recusada (secao 6 do plano).
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from app.config import settings


async def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.cfmv_worker_token:
        raise HTTPException(status_code=401, detail="Worker sem CFMV_WORKER_TOKEN configurado.")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Cabecalho Authorization ausente ou invalido.")

    token = authorization.removeprefix("Bearer ")
    if not secrets.compare_digest(token, settings.cfmv_worker_token):
        raise HTTPException(status_code=401, detail="Token invalido.")
