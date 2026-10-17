"""`incluir_foto` no `CfmvBrowser.lookup_pf`: so busca a foto quando pedido e
quando a consulta principal deu `found`, e nunca deixa uma falha na busca da
foto derrubar o resultado principal (best-effort, secao "Abordagem" do plano
da foto). O navegador de verdade nunca entra aqui: `perform_lookup_pf` e
`fetch_foto` sao trocados por dublês, do mesmo espírito de `test_api.py`.
"""

from __future__ import annotations

import json

import pytest

import app.browser as browser_module
from app.browser import CfmvBrowser
from tests.test_cfmv import REGISTRO_VALIDO


class _FakePage:
    async def close(self) -> None:
        pass


class _FakeContext:
    async def new_page(self) -> _FakePage:
        return _FakePage()


def _body_encontrado() -> str:
    return json.dumps({"type": "sucess", "data": [REGISTRO_VALIDO]})


@pytest.fixture
def browser_pronto(monkeypatch: pytest.MonkeyPatch) -> CfmvBrowser:
    browser = CfmvBrowser()
    browser._context = _FakeContext()  # pula o start() real (sem Chromium aqui)

    async def fake_perform_lookup_pf(page, uf, inscricao, timeout_ms):
        return 200, "application/json", _body_encontrado()

    monkeypatch.setattr(browser_module, "perform_lookup_pf", fake_perform_lookup_pf)
    return browser


async def test_sem_incluir_foto_nao_chama_fetch_foto(
    browser_pronto: CfmvBrowser, monkeypatch: pytest.MonkeyPatch
):
    chamadas = []

    async def fake_fetch_foto(context, cfmv_internal_id, timeout_ms):
        chamadas.append(cfmv_internal_id)
        return "data:image/jpeg;base64,xyz"

    monkeypatch.setattr(browser_module, "fetch_foto", fake_fetch_foto)

    resultado = await browser_pronto.lookup_pf("AM", "01234", None)

    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.photo is None
    assert chamadas == []


async def test_com_incluir_foto_preenche_photo(
    browser_pronto: CfmvBrowser, monkeypatch: pytest.MonkeyPatch
):
    async def fake_fetch_foto(context, cfmv_internal_id, timeout_ms):
        assert cfmv_internal_id == REGISTRO_VALIDO["id_pf_inscricao"]
        return "data:image/jpeg;base64,xyz"

    monkeypatch.setattr(browser_module, "fetch_foto", fake_fetch_foto)

    resultado = await browser_pronto.lookup_pf("AM", "01234", None, incluir_foto=True)

    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.photo == "data:image/jpeg;base64,xyz"


async def test_falha_na_busca_da_foto_nao_derruba_o_resultado(
    browser_pronto: CfmvBrowser, monkeypatch: pytest.MonkeyPatch
):
    async def fake_fetch_foto_com_erro(context, cfmv_internal_id, timeout_ms):
        raise TimeoutError("simulado")

    monkeypatch.setattr(browser_module, "fetch_foto", fake_fetch_foto_com_erro)

    resultado = await browser_pronto.lookup_pf("AM", "01234", None, incluir_foto=True)

    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.photo is None
