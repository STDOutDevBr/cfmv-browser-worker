"""O fluxo real da consulta PF (secao 2.1 e 7 do plano), e a classificacao da
resposta em found/not_found/ambiguous/blocked/error (secao 4.1, passo 6).

`classify_response` e pura de proposito: recebe o que a consulta devolveu (ja
sem token, cookie ou objeto de rede) e decide o status. E o que os testes
exercitam sem precisar de navegador nenhum.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from playwright.async_api import BrowserContext, Page

from app.models import LookupData, LookupErrorDetail, LookupMeta, LookupResponse

SEARCH_URL = "https://app.cfmv.gov.br/paginas/busca"
LOOKUP_PATH_PF = "/pf/consultaInscricao/"
FOTO_PATH_PF = "/pf/fotoConsultaPublica/"
METODO_IDENTICO = "1"
CAMPO_INSCRICAO = "2"

# Nem todo bloqueio chega como 403/429: o CFMV as vezes devolve 200 com um
# corpo que fala de captcha em vez do JSON de sucesso. Palavras vistas no
# proprio codigo da pagina e em respostas de erro tipicas do reCAPTCHA v3.
_RECAPTCHA_HINTS = ("recaptcha", "captcha")


def normalize_inscricao(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    return digits.zfill(5)


def _raw_hash(body_text: str) -> str:
    return "sha256:" + hashlib.sha256(body_text.encode("utf-8")).hexdigest()


def _meta(duration_ms: int, raw_hash: str | None = None) -> LookupMeta:
    return LookupMeta(
        fetchedAt=datetime.now(UTC).isoformat(),
        durationMs=duration_ms,
        rawHash=raw_hash,
    )


def _blocked(reason: str, duration_ms: int, raw_hash: str | None = None) -> LookupResponse:
    return LookupResponse(
        status="blocked",
        error=LookupErrorDetail(code="CFMV_BLOCKED", message=reason),
        meta=_meta(duration_ms, raw_hash),
    )


def _error(
    code: str, message: str, duration_ms: int, raw_hash: str | None = None
) -> LookupResponse:
    return LookupResponse(
        status="error",
        error=LookupErrorDetail(code=code, message=message),
        meta=_meta(duration_ms, raw_hash),
    )


def classify_response(
    *,
    status: int,
    content_type: str,
    body_text: str,
    uf: str,
    duration_ms: int,
) -> LookupResponse:
    raw_hash = _raw_hash(body_text)

    if status in (403, 429):
        return _blocked(f"HTTP {status} da consulta publica.", duration_ms, raw_hash)

    try:
        parsed: Any = json.loads(body_text)
    except json.JSONDecodeError:
        # O Content-Type do CFMV nao e confiavel para decidir bloqueio: a API
        # real devolve `text/html` mesmo quando o corpo e o JSON de sucesso
        # (visto ao vivo em 2026-09-15, junto com o achado do `.preloader`).
        # Por isso a decisao e sobre o corpo em si, e nao sobre o cabecalho: so
        # vira "HTML no lugar do JSON" quando o corpo de fato comeca parecendo
        # uma pagina.
        stripped = body_text.strip().lower()
        if stripped.startswith("<") or "<html" in stripped:
            return _blocked("Resposta veio como HTML, nao JSON.", duration_ms, raw_hash)
        return _blocked(
            f"Corpo nao decodificou como JSON (content-type: {content_type or '(nenhum)'}).",
            duration_ms,
            raw_hash,
        )

    if status >= 500:
        # Nao e um dos bloqueios documentados (secao 6), e tambem nao e sucesso:
        # visto ao vivo em 2026-09-15, "An Internal Error Has Occurred" com os
        # parametros corretos (1/2). Fica como "error", e nao "blocked", porque
        # nao ha evidencia de que seja o mesmo mecanismo de bloqueio do
        # reCAPTCHA, so que classificar errado dispara o resfriamento de bloqueio
        # sem necessidade.
        return _error("CFMV_SERVER_ERROR", f"HTTP {status} da consulta publica.", duration_ms, raw_hash)

    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
        lower_body = body_text.lower()
        if any(hint in lower_body for hint in _RECAPTCHA_HINTS):
            return _blocked("Corpo indica falha do reCAPTCHA.", duration_ms, raw_hash)
        return _error(
            "UNEXPECTED_SHAPE", "JSON valido, mas fora do formato esperado.", duration_ms, raw_hash
        )

    registros = parsed["data"]
    if len(registros) == 0:
        return LookupResponse(status="not_found", meta=_meta(duration_ms, raw_hash))
    if len(registros) > 1:
        return LookupResponse(status="ambiguous", meta=_meta(duration_ms, raw_hash))

    registro = registros[0]
    try:
        especializacoes = registro.get("pf_titulo_especialista")
        if not isinstance(especializacoes, list):
            # Campo informativo, nao essencial: um formato inesperado aqui
            # nao deve derrubar o "found" inteiro (ao contrario dos campos
            # abaixo, que sim viram UNEXPECTED_SHAPE se faltarem).
            especializacoes = []

        data = LookupData(
            name=str(registro["nome_preferencial"]).strip(),
            registration=str(registro["pf_inscricao"]),
            uf=uf,
            class_=str(registro["pf_classe"]),
            active=bool(registro["atuante"]),
            registrationDate=str(registro["dt_inscricao"]).split("T")[0],
            cfmvInternalId=int(registro["id_pf_inscricao"]),
            specializations=especializacoes,
        )
    except (KeyError, TypeError, ValueError) as error:
        return _error("UNEXPECTED_SHAPE", f"Registro sem o campo esperado: {error}", duration_ms)

    return LookupResponse(status="found", data=data, meta=_meta(duration_ms, raw_hash))


async def perform_lookup_pf(
    page: Page, uf: str, inscricao: str, timeout_ms: int
) -> tuple[int, str, str]:
    """Abre a pagina, pede o token pelo fluxo normal dela e consulta.

    Mesma sequencia do `scripts/go_no_go.py`, so que assincrona e devolvendo a
    resposta crua (status, content-type, corpo) para `classify_response`
    decidir. Nao guarda nem devolve token, cookie ou o objeto de rede.
    """
    await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=timeout_ms)

    await page.wait_for_function(
        """() => {
            const field = document.querySelector('input[name="g-recaptcha-response"]');
            return Boolean(field && field.value && field.value.length > 0);
        }""",
        timeout=timeout_ms,
    )

    # A pagina cobre o formulario com um `.preloader` ate terminar de montar a
    # tela (jQuery + DataTables). Clicar antes disso com `force=True` "funciona"
    # sem erro, mas nao marca o radio de verdade: o clique force pula a
    # checagem de que o elemento esta de fato clicavel, e o navegador some com
    # um valor default (visto ao vivo em 2026-09-15: os radios voltavam para
    # "Iniciado com" + "Tudo" em vez de "Identico" + "Inscricao"). A espera
    # aqui, e o clique sem `force`, sao o oposto de mascarar: e esperar a
    # pagina ficar pronta como um navegador de verdade esperaria.
    preloader = page.locator(".preloader")
    if await preloader.count() > 0:
        await preloader.first.wait_for(state="hidden", timeout=timeout_ms)

    await page.locator(f'input[name="filtro_tp_texto"][value="{METODO_IDENTICO}"]').click()
    await page.locator(f'input[name="filtro_procurar"][value="{CAMPO_INSCRICAO}"]').click()
    await page.locator('input[name="filtro_texto"]').fill(inscricao)
    await page.locator('select[name="filtro_uf"]').select_option(uf)

    async with page.expect_response(
        lambda response: LOOKUP_PATH_PF in response.url and response.request.method == "GET",
        timeout=timeout_ms,
    ) as response_info:
        await page.locator('input[type="submit"][value="Filtrar"]').click()

    response = await response_info.value
    body_text = await response.text()
    return response.status, response.headers.get("content-type", ""), body_text


def parse_foto_response(body_text: str) -> str | None:
    """Extrai a foto (data URI base64) da resposta de `fotoConsultaPublica`.

    Pura de proposito, como `classify_response`: quando o profissional nao
    tem foto cadastrada, a propria API devolve `{"data": {"foto": null}}` (
    visto ao vivo), entao `None` aqui cobre tanto esse caso quanto qualquer
    corpo mal formado ou inesperado.
    """
    try:
        parsed: Any = json.loads(body_text)
        foto = parsed["data"]["foto"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return foto if isinstance(foto, str) else None


async def fetch_foto(context: BrowserContext, cfmv_internal_id: int, timeout_ms: int) -> str | None:
    """Busca a foto do profissional, best-effort (secao 4.2, campo opcional).

    Rota separada da busca (`fotoConsultaPublica`, visto ao vivo): nao pede
    token de recaptcha, entao da pra chamar direto via `context.request`,
    reaproveitando o cookie de sessao do contexto, sem abrir pagina nova.
    """
    response = await context.request.get(
        f"https://app.cfmv.gov.br{FOTO_PATH_PF}{cfmv_internal_id}", timeout=timeout_ms
    )
    return parse_foto_response(await response.text())


_UF_PATTERN = re.compile(r"^[A-Z]{2}$")


def is_valid_uf(uf: str) -> bool:
    return bool(_UF_PATTERN.match(uf))
