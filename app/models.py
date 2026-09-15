"""Os tipos do contrato entre a Vercel e o worker (secao 4.2 do plano).

O nome dos campos aqui e o nome dos campos no JSON: quem le o body no lado do
Nuxt (cfmvProvider.ts) espera exatamente estas chaves.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LookupStatus = Literal["found", "not_found", "ambiguous", "blocked", "error"]


class LookupRequest(BaseModel):
    uf: str
    inscricao: str
    requestId: str | None = None


class LookupData(BaseModel):
    # FastAPI serializa response_model por alias por padrao, entao "class_"
    # aqui (nome python valido) sai como "class" no JSON. populate_by_name
    # deixa o codigo interno tambem construir por class_=... sem passar pelo
    # alias.
    model_config = ConfigDict(populate_by_name=True)

    name: str
    registration: str
    uf: str
    class_: str = Field(alias="class")
    active: bool
    registrationDate: str
    cfmvInternalId: int


class LookupErrorDetail(BaseModel):
    code: str
    message: str


class LookupMeta(BaseModel):
    fetchedAt: str
    durationMs: int
    rawHash: str | None = None


class LookupResponse(BaseModel):
    status: LookupStatus
    data: LookupData | None = None
    error: LookupErrorDetail | None = None
    meta: LookupMeta


class HealthResponse(BaseModel):
    browser: Literal["up", "down"]
    lastLookupAt: str | None
    queue: int
    blockedCount: int
    blockedUntil: str | None
