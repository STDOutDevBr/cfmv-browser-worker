"""O contrato HTTP (secao 4.2 do plano) pelo lado de fora: Bearer obrigatorio
nas duas rotas, e o formato exato do JSON, com `class` (nao `class_`) na
resposta. O navegador de verdade nunca entra aqui: `get_browser` e trocado
por um falso via `dependency_overrides`, do mesmo jeito que os testes do lado
Nuxt injetam um `CfmvProvider` falso.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, get_browser
from app.models import (
    HealthResponse,
    LookupData,
    LookupErrorDetail,
    LookupMeta,
    LookupResponse,
)

TOKEN = "segredo-de-teste"


class FakeBrowser:
    def __init__(self, resposta: LookupResponse) -> None:
        self._resposta = resposta
        self.chamadas: list[tuple[str, str, str | None]] = []

    async def lookup_pf(self, uf: str, inscricao: str, request_id: str | None) -> LookupResponse:
        self.chamadas.append((uf, inscricao, request_id))
        return self._resposta

    def health(self) -> HealthResponse:
        return HealthResponse(
            browser="up", lastLookupAt=None, queue=0, blockedCount=0, blockedUntil=None
        )


RESPOSTA_ENCONTRADA = LookupResponse(
    status="found",
    data=LookupData(
        name="NAIONE DE SOUZA BRANDAO",
        registration="03156",
        uf="AM",
        class_="VP",
        active=True,
        registrationDate="2026-07-17",
        cfmvInternalId=363609,
    ),
    meta=LookupMeta(fetchedAt=datetime.now(UTC).isoformat(), durationMs=120, rawHash="sha256:abc"),
)


@pytest.fixture(autouse=True)
def token_configurado():
    original = settings.cfmv_worker_token
    settings.cfmv_worker_token = TOKEN
    yield
    settings.cfmv_worker_token = original


@pytest.fixture
def client():
    # Sem `with`: o lifespan da app (que sobe um Chromium de verdade) so roda
    # dentro do context manager do TestClient. Aqui o navegador real nunca
    # entra em cena, so o `FakeBrowser` que o dependency_overrides injeta.
    app.dependency_overrides[get_browser] = lambda: FakeBrowser(RESPOSTA_ENCONTRADA)
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_lookup_sem_authorization_e_401(client: TestClient):
    r = client.post("/lookup/pf", json={"uf": "AM", "inscricao": "03156"})
    assert r.status_code == 401


def test_lookup_com_token_errado_e_401(client: TestClient):
    r = client.post(
        "/lookup/pf",
        json={"uf": "AM", "inscricao": "03156"},
        headers={"Authorization": "Bearer token-errado"},
    )
    assert r.status_code == 401


def test_lookup_com_token_certo_devolve_found_com_class_por_extenso(client: TestClient):
    r = client.post(
        "/lookup/pf",
        json={"uf": "AM", "inscricao": "03156", "requestId": "req-1"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "found"
    assert body["data"]["class"] == "VP"  # alias, nao "class_"
    assert "class_" not in body["data"]
    assert body["meta"]["rawHash"] == "sha256:abc"


def test_health_exige_token_tambem(client: TestClient):
    assert client.get("/health").status_code == 401
    r = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["browser"] == "up"


def test_sem_token_configurado_no_servidor_recusa_mesmo_com_bearer(client: TestClient):
    settings.cfmv_worker_token = ""
    r = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 401


def test_resposta_de_bloqueio_nunca_carrega_html_ou_token(client: TestClient):
    app.dependency_overrides[get_browser] = lambda: FakeBrowser(
        LookupResponse(
            status="blocked",
            error=LookupErrorDetail(code="CFMV_BLOCKED", message="HTTP 403 da consulta publica."),
            meta=LookupMeta(fetchedAt=datetime.now(UTC).isoformat(), durationMs=30),
        )
    )
    r = client.post(
        "/lookup/pf",
        json={"uf": "AM", "inscricao": "99999"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert "token" not in str(body).lower()
    assert "<html" not in str(body).lower()
