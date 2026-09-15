# cfmv-browser-worker

Worker que consulta o registro publico de profissionais no CFMV, pelo fluxo real da pagina
`app.cfmv.gov.br/paginas/busca` (sem API oficial disponivel). Nasce a partir do plano
`docs/plans/crmv-conferido-cfmv.md` do projeto comunidade.pet, e fala com ele pelo contrato
HTTP da secao 4.2 daquele plano.

Stack: Python 3.12+, FastAPI, Playwright para Python (fixado em `1.62.0`, mesma versao da
imagem Docker). Sem banco aqui: um escritor so (a aplicacao principal), e este worker nunca
recebe `DATABASE_URL`.

## Estado atual (2026-09-15)

O servidor HTTP existe e passa nos proprios testes: `/health` e `/lookup/pf`, Bearer
obrigatorio nos dois, navegador de longa duracao aberto na subida (sem cold start por
consulta), concorrencia 1 com intervalo minimo, resfriamento apos bloqueio (sem retry
automatico), reinicio do navegador por falhas seguidas ou por tempo de uso, e log
estruturado que nunca carrega token, cookie ou o corpo bruto da resposta. 25 testes, todos
sem precisar de navegador real (a logica de classificacao e pura, e as rotas HTTP usam um
navegador falso via `dependency_overrides`).

**A re-checagem ao vivo do go/no-go, feita hoje, deu "nao vai".** Em 2026-09-14 o mesmo
script tinha passado tres vezes seguidas (AM + 03156, HTTP 200). Hoje, rodando de novo:

1. Achado e corrigido no caminho: os cliques nos radios (`force=True`) nao estavam
   marcando o campo de verdade, porque a pagina cobre o formulario com um `.preloader` ate
   terminar de montar, e clique forcado nao espera isso. Sem o clique valendo, a consulta
   saia com os parametros default ("Iniciado com" + "Tudo") em vez dos escolhidos
   ("Identico" + "Inscricao"), o que sozinho já explica por que os retornos vinham fora do
   esperado. Corrigido em `app/cfmv.py` e no `scripts/go_no_go.py`: esperar o `.preloader`
   sumir, e clicar sem `force`.
2. **Com os parametros corretos, a consulta real (AM + 03156) devolveu `HTTP 500 "An
   Internal Error Has Occurred."` tres vezes seguidas**, a ultima gerada pelo proprio
   `app/cfmv.py` corrigido rodando dentro do worker. Nao e nenhum dos bloqueios que o
   plano documenta (403, 429, HTML no lugar do JSON, erro do reCAPTCHA): e um erro
   generico do backend do CFMV, e por isso `classify_response` trata como `error` com o
   codigo `CFMV_SERVER_ERROR`, e nao como `blocked` (classificar sem certeza dispararia o
   resfriamento de bloqueio por uma suposicao).

**O que isso significa, sem concluir por conta propria:** pode ser problema pontual do
backend do CFMV hoje, ou pode ser o mesmo tipo de rejeicao por pontuacao baixa do reCAPTCHA
v3 que o relatorio original ja avisava, so que se manifestando como erro generico em vez de
bloqueio limpo. **Nao rodei mais tentativas depois da terceira**, para nao virar volume
contra um servidor que ja respondeu nao tres vezes. A decisao de proxima tentativa (outro
dia, outro horario, ou perguntar ao CFMV pelo canal oficial) e de quem acompanha o `T-14`.

Ate aqui, o unico teste bem-sucedido de ponta a ponta contra o CFMV real continua sendo o
de 2026-09-14 (tres consultas, HTTP 200). O worker em si (servidor, contrato, testes) esta
pronto; o que falta e o CFMV voltar a responder.

## Rodando o worker localmente

```bash
python -m venv .venv
.venv\Scripts\activate   # no Windows; source .venv/bin/activate no Linux/Mac
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env      # preencher CFMV_WORKER_TOKEN
uvicorn app.main:app --reload
```

```bash
curl -H "Authorization: Bearer $CFMV_WORKER_TOKEN" http://localhost:8000/health

curl -X POST http://localhost:8000/lookup/pf \
  -H "Authorization: Bearer $CFMV_WORKER_TOKEN" -H "Content-Type: application/json" \
  -d '{"uf":"AM","inscricao":"03156","requestId":"teste-manual"}'
```

## Rodando com Docker

```bash
docker compose up --build
```

A imagem (`mcr.microsoft.com/playwright/python:v1.62.0-noble`) já traz o Chromium
compatível com a versão fixada em `pyproject.toml`; não há `playwright install` no
`Dockerfile`.

## Testes

```bash
pytest
ruff check .
```

Nenhum teste abre um Chromium de verdade: `classify_response` (o coração da decisão
found/not_found/ambiguous/blocked/error) é pura, o estado de resfriamento do
`CfmvBrowser` é testado direto, e as rotas HTTP usam um navegador falso via
`app.dependency_overrides`. O único jeito de testar contra o CFMV de verdade é o
go/no-go abaixo, e ele é manual de propósito.

## Rodando o go/no-go

```bash
python scripts/go_no_go.py --uf AM --inscricao 03156
```

Abre um Chromium comum (sem stealth, sem user agent trocado, sem proxy), espera o token
que a própria página já gera ao carregar, preenche o formulário real (UF, inscrição,
método "Idêntico", campo "Inscrição") e clica em "Filtrar". Imprime o HTTP, o tipo do
corpo e, se vier o JSON de sucesso, o número de registros.

**Critério de "vai":** HTTP 200 e JSON com um registro, três vezes seguidas com alguns
minutos de intervalo, pelo fluxo normal. **Qualquer bloqueio (403, 429, HTML no lugar de
JSON, erro do reCAPTCHA) é "não vai", e não é motivo para mascarar o navegador.** Um
`HTTP 500` genérico também não é sucesso, mesmo sem estar na lista acima (ver "Estado
atual" para o que isso significa hoje).

## O contrato com a aplicação principal

```
POST /lookup/pf            Authorization: Bearer <CFMV_WORKER_TOKEN>
{ "uf": "AM", "inscricao": "03156", "requestId": "..." }

200 { "status": "found",
      "data": { "name": "...", "registration": "03156", "uf": "AM",
                "class": "VP", "active": true, "registrationDate": "2026-07-17",
                "cfmvInternalId": 363609 },
      "meta": { "fetchedAt": "...", "durationMs": 0, "rawHash": "sha256:..." } }
200 { "status": "not_found" | "ambiguous", "meta": {...} }
200 { "status": "blocked" | "error", "error": { "code": "...", "message": "..." }, "meta": {...} }

GET  /health                Authorization: Bearer <CFMV_WORKER_TOKEN>
200 { "browser": "up", "lastLookupAt": "...", "queue": 0, "blockedCount": 0, "blockedUntil": null }
```

Detalhes de cada campo, e por que o worker nunca escreve em banco nenhum, estão na seção
4.2 de `docs/plans/crmv-conferido-cfmv.md`, no repositório `comunidade-pet-app`.
