"""A app FastAPI: o contrato da secao 4.2 do plano, e nada mais.

Sobe e desce o navegador junto do processo (lifespan), em vez de abrir um por
consulta: e o que evita pagar o cold start do Chromium a cada chamada (secao
6). Sem rota publica (secao 4.3): as duas rotas exigem Bearer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.auth import require_bearer_token
from app.browser import CfmvBrowser, cfmv_browser
from app.logging import log_event
from app.models import HealthResponse, LookupRequest, LookupResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await cfmv_browser.start()
    try:
        yield
    finally:
        await cfmv_browser.stop()


app = FastAPI(title="cfmv-browser-worker", lifespan=lifespan)


def get_browser() -> CfmvBrowser:
    return cfmv_browser


@app.post("/lookup/pf", response_model=LookupResponse, dependencies=[Depends(require_bearer_token)])
async def lookup_pf(
    body: LookupRequest, browser: CfmvBrowser = Depends(get_browser)
) -> LookupResponse:
    log_event("info", "consulta recebida", request_id=body.requestId, uf=body.uf.upper())
    return await browser.lookup_pf(body.uf, body.inscricao, body.requestId)


@app.get("/health", response_model=HealthResponse, dependencies=[Depends(require_bearer_token)])
async def health(browser: CfmvBrowser = Depends(get_browser)) -> HealthResponse:
    return browser.health()
