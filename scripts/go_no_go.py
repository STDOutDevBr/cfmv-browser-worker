"""Teste go/no-go da secao 7 do plano (comunidade.pet, docs/plans/crmv-conferido-cfmv.md).

Abre a pagina publica de consulta do CFMV com Chromium sem nenhuma alteracao de identidade
(sem stealth, sem user agent customizado, sem proxy), espera o token que a propria pagina ja
gera com grecaptcha.execute ao carregar, preenche o formulario real (UF + inscricao, metodo
"Identico", campo "Inscricao") e clica no botao "Filtrar", que e o mesmo fluxo que um
visitante faria. Nao contorna nem mascara o reCAPTCHA de jeito nenhum: se a pagina bloquear,
o resultado e "nao vai", e fica registrado assim.

Uso: python scripts/go_no_go.py --uf AM --inscricao 03156 [--headless] [--timeout 20000]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from playwright.sync_api import sync_playwright

SEARCH_URL = "https://app.cfmv.gov.br/paginas/busca"
LOOKUP_PATH = "/pf/consultaInscricao/"
METODO_IDENTICO = "1"
CAMPO_INSCRICAO = "2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", required=True)
    parser.add_argument("--inscricao", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout", type=int, default=20000, help="milissegundos")
    args = parser.parse_args()
    args.uf = args.uf.upper()
    args.inscricao = "".join(c for c in args.inscricao if c.isdigit()).zfill(5)
    return args


def run() -> int:
    args = parse_args()
    started_at = datetime.now(UTC)
    print(f"[go-no-go] {started_at.isoformat()} uf={args.uf} inscricao={args.inscricao} "
          f"headless={args.headless}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless)
        page = browser.new_page()
        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=args.timeout)

            # A pagina pede um token assim que carrega e guarda no campo escondido do form.
            # E esse token, gerado pelo fluxo normal dela, que a consulta usa.
            page.wait_for_function(
                """() => {
                    const field = document.querySelector('input[name="g-recaptcha-response"]');
                    return Boolean(field && field.value && field.value.length > 0);
                }""",
                timeout=args.timeout,
            )

            # A pagina cobre o formulario com um `.preloader` ate terminar de
            # montar a tela. Clicar antes disso com `force=True` nao gera erro,
            # mas tambem nao marca o radio de verdade: visto ao vivo em
            # 2026-09-15, o clique "funcionava" e a consulta saia com os valores
            # default ("Iniciado com" + "Tudo") em vez dos escolhidos. Esperar o
            # preloader sumir e clicar sem `force` e o oposto de mascarar: e
            # esperar a pagina ficar pronta como ela pede.
            preloader = page.locator(".preloader")
            if preloader.count() > 0:
                preloader.first.wait_for(state="hidden", timeout=args.timeout)

            page.locator(f'input[name="filtro_tp_texto"][value="{METODO_IDENTICO}"]').click()
            page.locator(f'input[name="filtro_procurar"][value="{CAMPO_INSCRICAO}"]').click()
            page.locator('input[name="filtro_texto"]').fill(args.inscricao)
            page.locator('select[name="filtro_uf"]').select_option(args.uf)

            with page.expect_response(
                lambda response: LOOKUP_PATH in response.url and response.request.method == "GET",
                timeout=args.timeout,
            ) as response_info:
                page.locator('input[type="submit"][value="Filtrar"]').click()

            response = response_info.value
            status = response.status
            content_type = response.headers.get("content-type", "")
            body_text = response.text()

            print(f"[go-no-go] HTTP {status}, content-type: {content_type or '(nenhum)'}")

            parsed = None
            try:
                parsed = json.loads(body_text)
            except json.JSONDecodeError:
                parsed = None

            if status == 200 and isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
                print(f"[go-no-go] VAI: JSON valido com {len(parsed['data'])} registro(s).")
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
                return 0
            if status in (403, 429):
                print(f"[go-no-go] NAO VAI: bloqueio HTTP {status}.")
                print(body_text[:500])
                return 1
            print("[go-no-go] NAO VAI: resposta fora do esperado (nao e o JSON de sucesso).")
            print(f"corpo (primeiros 500 caracteres):\n{body_text[:500]}")
            return 1
        except Exception as error:  # noqa: BLE001 - resultado do teste, nao um bug a tratar
            print(f"[go-no-go] NAO VAI: {error}")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(run())
