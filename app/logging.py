"""Log estruturado em JSON, uma linha por evento, no stdout.

Regra sem exceção (seção 6 do plano): **nenhuma linha carrega token, cookie ou
o HTML/JSON bruto que o CFMV devolveu.** Quem chama `log_event` só recebe os
campos escolhidos a dedo abaixo; não existe um parâmetro "extra" genérico que
alguém possa usar para despejar a resposta inteira por engano.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Literal

Level = Literal["info", "warn", "error"]


def log_event(
    level: Level,
    event: str,
    *,
    request_id: str | None = None,
    uf: str | None = None,
    status: str | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    **extra: str | float | bool | None,
) -> None:
    line = {
        "ts": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "requestId": request_id,
        "uf": uf,
        "status": status,
        "durationMs": duration_ms,
        "errorCode": error_code,
        **extra,
    }
    # None sai da linha em vez de aparecer como "null" em todo log que não usa
    # aquele campo.
    compact = {k: v for k, v in line.items() if v is not None}
    print(json.dumps(compact, ensure_ascii=False), file=sys.stdout, flush=True)
