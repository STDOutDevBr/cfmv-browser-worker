"""Teste manual so da foto (`GET /pf/fotoConsultaPublica/{id}`), separado do
go/no-go da busca principal (`scripts/go_no_go.py`).

A rota da foto nao pede token de recaptcha, entao com um `cfmvInternalId` em
maos da pra pular direto pra ela. Sem o ID, o script primeiro roda o mesmo
fluxo de busca do go_no_go.py pra descobri-lo a partir de UF + inscricao.

Uso:
    python scripts/foto_lookup.py --cfmv-internal-id 100001
    python scripts/foto_lookup.py --uf AM --inscricao 01234 [--headless] [--timeout 20000]

Sem nenhum desses, cai no default de TEST_UF/TEST_INSCRICAO do .env (mesmo
esquema do go_no_go.py; o worker em si nunca le essas duas variaveis).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://app.cfmv.gov.br/paginas/busca"
LOOKUP_PATH = "/pf/consultaInscricao/"
FOTO_PATH = "/pf/fotoConsultaPublica/"
METODO_IDENTICO = "1"
CAMPO_INSCRICAO = "2"


def parse_args() -> argparse.Namespace:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cfmv-internal-id", type=int, help="pula a busca e vai direto na foto")
    parser.add_argument("--uf", default=os.environ.get("TEST_UF"))
    parser.add_argument("--inscricao", default=os.environ.get("TEST_INSCRICAO"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=20000, help="milissegundos")
    args = parser.parse_args()

    if args.cfmv_internal_id is None and not (args.uf and args.inscricao):
        parser.error(
            "passe --cfmv-internal-id, ou --uf e --inscricao (direto ou via "
            "TEST_UF/TEST_INSCRICAO no .env)"
        )

    if args.uf:
        args.uf = args.uf.upper()
    if args.inscricao:
        args.inscricao = "".join(c for c in args.inscricao if c.isdigit()).zfill(5)
    return args


def _encontrar_cfmv_internal_id(page, uf: str, inscricao: str, timeout_ms: int) -> int | None:
    """Mesmo fluxo do go_no_go.py, so que devolvendo o `id_pf_inscricao`."""
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=timeout_ms)

    page.wait_for_function(
        """() => {
            const field = document.querySelector('input[name="g-recaptcha-response"]');
            return Boolean(field && field.value && field.value.length > 0);
        }""",
        timeout=timeout_ms,
    )

    preloader = page.locator(".preloader")
    if preloader.count() > 0:
        preloader.first.wait_for(state="hidden", timeout=timeout_ms)

    page.locator(f'input[name="filtro_tp_texto"][value="{METODO_IDENTICO}"]').click()
    page.locator(f'input[name="filtro_procurar"][value="{CAMPO_INSCRICAO}"]').click()
    page.locator('input[name="filtro_texto"]').fill(inscricao)
    page.locator('select[name="filtro_uf"]').select_option(uf)

    with page.expect_response(
        lambda response: LOOKUP_PATH in response.url and response.request.method == "GET",
        timeout=timeout_ms,
    ) as response_info:
        page.locator('input[type="submit"][value="Filtrar"]').click()

    response = response_info.value
    parsed = json.loads(response.text())
    registros = parsed.get("data") or []
    if len(registros) != 1:
        print(f"[foto-lookup] busca nao achou exatamente 1 registro (achou {len(registros)}).")
        return None
    return int(registros[0]["id_pf_inscricao"])


def run() -> int:
    args = parse_args()
    started_at = datetime.now(UTC)
    print(f"[foto-lookup] {started_at.isoformat()} headless={args.headless}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless)
        context = browser.new_context()
        try:
            cfmv_internal_id = args.cfmv_internal_id
            if cfmv_internal_id is None:
                page = context.new_page()
                try:
                    print(f"[foto-lookup] buscando id_pf_inscricao para uf={args.uf} inscricao={args.inscricao}")
                    cfmv_internal_id = _encontrar_cfmv_internal_id(page, args.uf, args.inscricao, args.timeout)
                finally:
                    page.close()
                if cfmv_internal_id is None:
                    return 1

            print(f"[foto-lookup] cfmvInternalId={cfmv_internal_id}")
            response = context.request.get(
                f"https://app.cfmv.gov.br{FOTO_PATH}{cfmv_internal_id}", timeout=args.timeout
            )
            body_text = response.text()
            print(f"[foto-lookup] HTTP {response.status}")

            parsed = json.loads(body_text)
            foto = parsed.get("data", {}).get("foto")
            if foto is None:
                print("[foto-lookup] profissional sem foto cadastrada (\"foto\": null).")
                return 0

            print(f"[foto-lookup] foto recebida ({len(foto)} caracteres): {foto[:60]}...")
            return 0
        except Exception as error:  # noqa: BLE001 - resultado do teste, nao um bug a tratar
            print(f"[foto-lookup] falhou: {error}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(run())
