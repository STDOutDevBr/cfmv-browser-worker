"""`classify_response` decide o status a partir do que a consulta devolveu
(secao 4.1, passo 6 do plano). Cada teste e um jeito real de a pagina
responder, incluindo os dois jeitos de bloqueio que nao sao so status HTTP.
"""

from __future__ import annotations

import json

from app.cfmv import classify_response, is_valid_uf, normalize_inscricao, parse_foto_response

JSON_CT = "application/json; charset=utf-8"

REGISTRO_VALIDO = {
    "id_pf_inscricao": 100001,
    "pf_inscricao": "01234",
    "pf_classe": "VP",
    "pf_uf": "AM",
    "nome_preferencial": " MARIA EXEMPLO DA SILVA",
    "atuante": True,
    "dt_inscricao": "2026-07-17T00:00:00+00:00",
    "pf_titulo_especialista": [],
}


def _body(registros: list[dict]) -> str:
    return json.dumps(
        {"type": "sucess", "data": registros, "haveMoreThanLimitConsultaRegisters": False}
    )


def test_um_registro_e_found_e_normaliza_o_nome():
    resultado = classify_response(
        status=200, content_type=JSON_CT, body_text=_body([REGISTRO_VALIDO]), uf="AM", duration_ms=42
    )
    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.name == "MARIA EXEMPLO DA SILVA"
    assert resultado.data.registration == "01234"
    assert resultado.data.class_ == "VP"
    assert resultado.data.active is True
    assert resultado.data.registrationDate == "2026-07-17"
    assert resultado.data.cfmvInternalId == 100001
    assert resultado.data.specializations == []
    assert resultado.meta.rawHash and resultado.meta.rawHash.startswith("sha256:")


def test_titulo_especialista_preenchido_passa_direto():
    # Formato do item nao confirmado ao vivo (nenhum dos ~100 registros
    # amostrados tinha titulo cadastrado), entao o campo e repassado cru.
    registro = {**REGISTRO_VALIDO, "pf_titulo_especialista": [{"titulo": "Cirurgia"}]}
    resultado = classify_response(
        status=200, content_type=JSON_CT, body_text=_body([registro]), uf="AM", duration_ms=42
    )
    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.specializations == [{"titulo": "Cirurgia"}]


def test_titulo_especialista_ausente_ou_invalido_vira_lista_vazia():
    registro_sem_campo = {k: v for k, v in REGISTRO_VALIDO.items() if k != "pf_titulo_especialista"}
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=_body([registro_sem_campo]),
        uf="AM",
        duration_ms=42,
    )
    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.specializations == []

    registro_campo_invalido = {**REGISTRO_VALIDO, "pf_titulo_especialista": "nao e lista"}
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=_body([registro_campo_invalido]),
        uf="AM",
        duration_ms=42,
    )
    assert resultado.status == "found"
    assert resultado.data is not None
    assert resultado.data.specializations == []


def test_zero_registros_e_not_found():
    resultado = classify_response(
        status=200, content_type=JSON_CT, body_text=_body([]), uf="AM", duration_ms=10
    )
    assert resultado.status == "not_found"
    assert resultado.data is None


def test_dois_registros_e_ambiguous():
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=_body([REGISTRO_VALIDO, REGISTRO_VALIDO]),
        uf="AM",
        duration_ms=10,
    )
    assert resultado.status == "ambiguous"


def test_http_403_e_blocked():
    resultado = classify_response(
        status=403, content_type=JSON_CT, body_text="{}", uf="AM", duration_ms=5
    )
    assert resultado.status == "blocked"
    assert resultado.error is not None
    assert resultado.error.code == "CFMV_BLOCKED"


def test_http_429_e_blocked():
    resultado = classify_response(
        status=429, content_type=JSON_CT, body_text="{}", uf="AM", duration_ms=5
    )
    assert resultado.status == "blocked"


def test_json_de_sucesso_com_content_type_html_e_found():
    # Visto ao vivo em 2026-09-15: a API real do CFMV devolve `text/html` no
    # Content-Type mesmo quando o corpo e o JSON de sucesso. Confiar no
    # cabecalho classificava isso como bloqueio por engano.
    resultado = classify_response(
        status=200,
        content_type="text/html; charset=UTF-8",
        body_text=_body([REGISTRO_VALIDO]),
        uf="AM",
        duration_ms=900,
    )
    assert resultado.status == "found"


def test_html_no_lugar_do_json_e_blocked():
    resultado = classify_response(
        status=200,
        content_type="text/html; charset=utf-8",
        body_text="<html><body>bloqueado</body></html>",
        uf="AM",
        duration_ms=5,
    )
    assert resultado.status == "blocked"


def test_json_de_erro_do_recaptcha_e_blocked():
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=json.dumps({"error": "recaptcha validation failed"}),
        uf="AM",
        duration_ms=5,
    )
    assert resultado.status == "blocked"


def test_http_500_e_error_nao_blocked():
    # Visto ao vivo em 2026-09-15: "An Internal Error Has Occurred" com os
    # parametros corretos. Nao e um dos bloqueios documentados na secao 6, e
    # classificar como "blocked" sem certeza dispararia o resfriamento a toa.
    resultado = classify_response(
        status=500,
        content_type=JSON_CT,
        body_text=json.dumps({"message": "An Internal Error Has Occurred."}),
        uf="AM",
        duration_ms=4000,
    )
    assert resultado.status == "error"
    assert resultado.error is not None
    assert resultado.error.code == "CFMV_SERVER_ERROR"


def test_json_valido_fora_do_formato_e_error_nao_blocked():
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=json.dumps({"ok": True}),
        uf="AM",
        duration_ms=5,
    )
    assert resultado.status == "error"
    assert resultado.error is not None
    assert resultado.error.code == "UNEXPECTED_SHAPE"


def test_registro_sem_campo_esperado_e_error():
    registro_incompleto = {"nome_preferencial": "Fulano"}
    resultado = classify_response(
        status=200,
        content_type=JSON_CT,
        body_text=_body([registro_incompleto]),
        uf="AM",
        duration_ms=5,
    )
    assert resultado.status == "error"
    assert resultado.error is not None
    assert resultado.error.code == "UNEXPECTED_SHAPE"


def test_corpo_json_invalido_e_blocked():
    resultado = classify_response(
        status=200, content_type=JSON_CT, body_text="isto nao e json", uf="AM", duration_ms=5
    )
    assert resultado.status == "blocked"


def test_rawhash_nunca_guarda_o_corpo():
    resultado = classify_response(
        status=200, content_type=JSON_CT, body_text=_body([]), uf="AM", duration_ms=5
    )
    # E hash, nao o corpo: nada do texto original aparece dentro do hash.
    assert resultado.meta.rawHash is not None
    assert "sucess" not in resultado.meta.rawHash


def test_normalize_inscricao_completa_com_zeros():
    assert normalize_inscricao("1234") == "01234"
    assert normalize_inscricao("AM-01234") == "01234"
    assert normalize_inscricao("01234") == "01234"


def test_is_valid_uf():
    assert is_valid_uf("AM") is True
    assert is_valid_uf("am") is False  # espera maiuscula, quem chama normaliza antes
    assert is_valid_uf("AMZ") is False
    assert is_valid_uf("") is False


def test_parse_foto_response_com_foto():
    # Formato real visto ao vivo em app.cfmv.gov.br/pf/fotoConsultaPublica/{id}.
    body = json.dumps({"data": {"foto": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="}})
    assert parse_foto_response(body) == "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_parse_foto_response_sem_foto():
    # Visto ao vivo: profissional sem foto cadastrada devolve "foto": null,
    # nao um erro.
    body = json.dumps({"data": {"foto": None}})
    assert parse_foto_response(body) is None


def test_parse_foto_response_corpo_inesperado_nao_estoura():
    assert parse_foto_response("isto nao e json") is None
    assert parse_foto_response(json.dumps({"ok": True})) is None
    assert parse_foto_response(json.dumps({"data": {}})) is None
