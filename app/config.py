"""Configuracao do worker, lida do ambiente (.env em dev, variaveis reais na VPS).

Os tres numeros sem valor fixo no plano (intervalo minimo entre consultas, tentativas
seguidas e horas ate reiniciar o navegador, e o tempo de resfriamento apos um bloqueio)
sao decididos aqui, com o motivo de cada default.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Sem isto, nenhuma chamada é aceita (nem /health): "recusa tudo sem a
    # variavel", mesmo molde do CRON_SECRET do lado da aplicacao principal.
    cfmv_worker_token: str = ""

    host: str = "0.0.0.0"
    port: int = 8000

    # False em producao (o worker roda sem cabeca numa VPS). True so entra por
    # quem estiver depurando na propria maquina e quiser ver o navegador.
    headless: bool = True

    lookup_timeout_ms: int = 20_000

    # Concorrencia 1: nunca duas consultas ao mesmo tempo, e um intervalo minimo
    # entre uma e outra mesmo em fila, para nunca parecer um robo disparando
    # requisicao atras de requisicao.
    min_interval_seconds: float = 3.0

    # Depois de N falhas seguidas (bloqueio ou erro), o navegador reinicia antes
    # da proxima tentativa: um contexto que acumulou erro pode estar com estado
    # ruim (cookie de sessao invalido, por exemplo). N=5 é conservador: uma
    # falha isolada não derruba o navegador à toa.
    restart_after_failures: int = 5

    # Reinicio preventivo por tempo, mesmo sem falha: um processo Chromium de
    # longa duração vaza memória aos poucos, e reiniciar a cada 6h é mais barato
    # que descobrir isso numa madrugada.
    restart_after_hours: float = 6.0

    # Depois de um "blocked", o worker para de tentar por este tempo em vez de
    # insistir: repetir contra um bloqueio é o começo da escalada que o plano
    # proíbe (seção 6). 15 minutos é um meio-termo: curto o bastante para o
    # "verificar agora" de um admin não ficar preso o dia inteiro, longo o
    # bastante para não parecer que o worker está tentando de novo na hora.
    block_cooldown_seconds: float = 900.0


settings = Settings()
