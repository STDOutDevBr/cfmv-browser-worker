"""O navegador de longa duracao (secao 6 do plano): um contexto so, aberto na
subida e reusado entre consultas, concorrencia 1, e o estado de bloqueio.

Nada aqui grava em disco: sem `storage_state`, o cookie de sessao do CakePHP
vive so na memoria do processo, e reiniciar zera tudo (mesma garantia do
plano). Nao ha `DATABASE_URL` em lugar nenhum deste repositorio.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app.cfmv import classify_response, is_valid_uf, normalize_inscricao, perform_lookup_pf
from app.config import settings
from app.logging import log_event
from app.models import HealthResponse, LookupErrorDetail, LookupMeta, LookupResponse


class CfmvBrowser:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

        self._lock = asyncio.Lock()
        self._queue_depth = 0

        self._started_at: datetime | None = None
        self._last_lookup_at: datetime | None = None
        self._last_request_at: datetime | None = None
        self._consecutive_failures = 0
        self._blocked_count = 0
        self._blocked_until: datetime | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=settings.headless)
        self._context = await self._browser.new_context()
        self._started_at = datetime.now(UTC)
        self._consecutive_failures = 0
        log_event("info", "browser iniciado", headless=settings.headless)

    async def stop(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = self._browser = self._playwright = None
        log_event("info", "browser encerrado")

    async def restart(self) -> None:
        log_event("warn", "reiniciando o browser", motivo="falhas seguidas ou tempo de uso")
        await self.stop()
        await self.start()

    def health(self) -> HealthResponse:
        return HealthResponse(
            browser="up" if self._browser else "down",
            lastLookupAt=self._last_lookup_at.isoformat() if self._last_lookup_at else None,
            queue=self._queue_depth,
            blockedCount=self._blocked_count,
            blockedUntil=self._blocked_until.isoformat() if self._blocked_until else None,
        )

    async def _maybe_restart_for_maintenance(self) -> None:
        if self._consecutive_failures >= settings.restart_after_failures:
            await self.restart()
            return
        if self._started_at and datetime.now(UTC) - self._started_at >= timedelta(
            hours=settings.restart_after_hours
        ):
            await self.restart()

    async def _respect_min_interval(self) -> None:
        if not self._last_request_at:
            return
        elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()
        wait = settings.min_interval_seconds - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

    def _still_cooling_down(self) -> LookupResponse | None:
        if self._blocked_until and datetime.now(UTC) < self._blocked_until:
            # Falha rapido, sem nem tentar: repetir contra um bloqueio recente
            # e o comeco da escalada que o plano proibe (secao 6).
            return LookupResponse(
                status="blocked",
                error=LookupErrorDetail(
                    code="COOLING_DOWN",
                    message="Bloqueado recentemente; aguardando o intervalo antes de tentar de novo.",
                ),
                meta=LookupMeta(fetchedAt=datetime.now(UTC).isoformat(), durationMs=0),
            )
        return None

    async def lookup_pf(self, uf: str, inscricao: str, request_id: str | None) -> LookupResponse:
        uf_normalizado = uf.upper()
        inscricao_normalizada = normalize_inscricao(inscricao)

        if not is_valid_uf(uf_normalizado):
            return LookupResponse(
                status="error",
                error=LookupErrorDetail(code="INVALID_UF", message="UF precisa ter duas letras."),
                meta=LookupMeta(fetchedAt=datetime.now(UTC).isoformat(), durationMs=0),
            )

        cooling = self._still_cooling_down()
        if cooling:
            log_event(
                "warn",
                "consulta recusada, worker em resfriamento",
                request_id=request_id,
                uf=uf_normalizado,
            )
            return cooling

        self._queue_depth += 1
        try:
            async with self._lock:
                await self._respect_min_interval()
                await self._maybe_restart_for_maintenance()
                self._last_request_at = datetime.now(UTC)

                if not self._context:
                    await self.start()
                assert self._context is not None

                page = await self._context.new_page()
                t0 = time.monotonic()
                try:
                    status, content_type, body_text = await perform_lookup_pf(
                        page, uf_normalizado, inscricao_normalizada, settings.lookup_timeout_ms
                    )
                except Exception as error:  # noqa: BLE001 - qualquer falha vira "error" normalizado
                    duration_ms = int((time.monotonic() - t0) * 1000)
                    self._consecutive_failures += 1
                    log_event(
                        "error",
                        "consulta falhou antes de obter resposta",
                        request_id=request_id,
                        uf=uf_normalizado,
                        duration_ms=duration_ms,
                        error_code=type(error).__name__,
                    )
                    return LookupResponse(
                        status="error",
                        error=LookupErrorDetail(code="LOOKUP_FAILED", message=type(error).__name__),
                        meta=LookupMeta(
                            fetchedAt=datetime.now(UTC).isoformat(), durationMs=duration_ms
                        ),
                    )
                finally:
                    await page.close()

                duration_ms = int((time.monotonic() - t0) * 1000)
                result = classify_response(
                    status=status,
                    content_type=content_type,
                    body_text=body_text,
                    uf=uf_normalizado,
                    duration_ms=duration_ms,
                )
                self._last_lookup_at = datetime.now(UTC)

                if result.status == "blocked":
                    self._consecutive_failures += 1
                    self._blocked_count += 1
                    self._blocked_until = datetime.now(UTC) + timedelta(
                        seconds=settings.block_cooldown_seconds
                    )
                elif result.status == "error":
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                log_event(
                    "info" if result.status in ("found", "not_found", "ambiguous") else "warn",
                    "consulta concluida",
                    request_id=request_id,
                    uf=uf_normalizado,
                    status=result.status,
                    duration_ms=duration_ms,
                )
                return result
        finally:
            self._queue_depth -= 1


cfmv_browser = CfmvBrowser()
