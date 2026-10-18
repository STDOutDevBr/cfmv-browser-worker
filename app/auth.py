"""Bearer estatico, mesmo molde do CRON_SECRET do lado da aplicacao principal:
sem a variavel configurada, toda chamada e recusada (secao 6 do plano).

Declarado como `HTTPBearer`, e nao como um `Header()` comum: a spec do OpenAPI
manda ignorar parametro de header chamado Authorization, entao o Swagger do
/docs mostrava o campo mas nunca enviava o valor (visto em producao: 401
"ausente" com o token preenchido). Como esquema de seguranca, o /docs ganha o
botao "Authorize" e passa a mandar o token de verdade.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# auto_error=False: o HTTPBearer devolve None em vez de responder sozinho, e
# quem decide o 401 e a mensagem continua sendo esta funcao.
_bearer = HTTPBearer(auto_error=False)


async def require_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not settings.cfmv_worker_token:
        raise HTTPException(status_code=401, detail="Worker sem CFMV_WORKER_TOKEN configurado.")

    if credentials is None:
        raise HTTPException(status_code=401, detail="Cabecalho Authorization ausente ou invalido.")

    if not secrets.compare_digest(credentials.credentials, settings.cfmv_worker_token):
        raise HTTPException(status_code=401, detail="Token invalido.")
