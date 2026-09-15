"""O estado do `CfmvBrowser` que nao depende de abrir navegador nenhum: o
resfriamento apos bloqueio (secao 6, "nao existe retry automatico de
bloqueio") e o `/health`. As partes que abrem Chromium de verdade ficam para
o go/no-go e para o teste manual descrito no README.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.browser import CfmvBrowser


def test_health_antes_de_iniciar_diz_browser_down():
    browser = CfmvBrowser()
    saude = browser.health()
    assert saude.browser == "down"
    assert saude.queue == 0
    assert saude.blockedCount == 0
    assert saude.blockedUntil is None


def test_sem_bloqueio_recente_nao_esta_em_resfriamento():
    browser = CfmvBrowser()
    assert browser._still_cooling_down() is None


def test_bloqueio_recente_recusa_sem_tentar():
    browser = CfmvBrowser()
    browser._blocked_until = datetime.now(UTC) + timedelta(minutes=10)
    resultado = browser._still_cooling_down()
    assert resultado is not None
    assert resultado.status == "blocked"
    assert resultado.error is not None
    assert resultado.error.code == "COOLING_DOWN"


def test_bloqueio_vencido_nao_recusa_mais():
    browser = CfmvBrowser()
    browser._blocked_until = datetime.now(UTC) - timedelta(seconds=1)
    assert browser._still_cooling_down() is None


def test_health_reflete_contador_de_bloqueio():
    browser = CfmvBrowser()
    browser._blocked_count = 3
    browser._blocked_until = datetime.now(UTC) + timedelta(minutes=5)
    saude = browser.health()
    assert saude.blockedCount == 3
    assert saude.blockedUntil is not None
