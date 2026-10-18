# cfmv-browser-worker

Worker que consulta o registro publico de profissionais no CFMV, pelo fluxo real da pagina
`app.cfmv.gov.br/paginas/busca` (sem API oficial disponivel). Nasce a partir do plano
`docs/plans/crmv-conferido-cfmv.md` do projeto comunidade.pet, e fala com ele pelo contrato
HTTP da secao 4.2 daquele plano.

Stack: Python 3.12+, FastAPI, Playwright para Python (fixado em `1.62.0`, mesma versao da
imagem Docker). Sem banco aqui: um escritor so (a aplicacao principal), e este worker nunca
recebe `DATABASE_URL`.

## Estado atual (2026-10-18)

**Em produção em `https://cfmv.comunidade.pet`, e o go/no-go passou saindo da VPS.** Três
consultas reais pelo worker de produção, às 20:11, 20:36 e 20:41 UTC, devolveram HTTP 200,
`found` e um registro, com foto. Isso cumpre o critério de "vai" (seção "Rodando o
go/no-go"), com uma diferença: as três passaram pelo próprio worker (`app/cfmv.py`), não
pelo `scripts/go_no_go.py`. O fluxo na página do CFMV é o mesmo. Antes, no mesmo dia, uma
consulta de IP residencial tinha dado o mesmo resultado, com dados e foto idênticos.

O risco que mais pesava não se confirmou: o reCAPTCHA v3 costuma pontuar mal IP de
datacenter, e as consultas da VPS saíram até mais rápidas (3,6 a 4,9 s, contra 13 s do
IP residencial).

O worker em si: `/health` e `/lookup/pf`, com Bearer obrigatório nos dois. O navegador de
longa duração abre na subida (sem cold start por consulta). Concorrência 1 com intervalo
mínimo, resfriamento após bloqueio (sem retry automático), e reinício do navegador por
falhas seguidas ou por tempo de uso. O log é estruturado e nunca carrega token, cookie ou
o corpo bruto da resposta. Inclui a busca da foto (`incluirFoto`, best-effort, rota
separada) e o repasse cru de `pf_titulo_especialista` como `data.specializations`.

São 36 testes, todos sem navegador real: a lógica de classificação é pura, e as rotas HTTP
usam um navegador falso via `dependency_overrides`.

**Pendências conhecidas:**

- **`incluirFoto` ainda precisa ser espelhado em `cfmvProvider.ts`** (ver "O contrato com
  a aplicação principal").
- **O teste de ponta a ponta pelo comunidade.pet (Vercel → worker) não foi feito até este
  registro.** Falta configurar na Vercel o `CFMV_WORKER_TOKEN` de produção e a URL do
  worker (ver "Produção").

### Histórico: o HTTP 500 de 2026-09-15, e os dois bugs achados no caminho

Em 2026-09-14 o `go_no_go.py` tinha passado três vezes seguidas. A re-checagem de
2026-09-15 encontrou e corrigiu um bug: os cliques nos radios (`force=True`) não marcavam
o campo, porque a página cobre o formulário com um `.preloader` até terminar de montar, e
o clique forçado não espera isso. A consulta saía com os parâmetros default ("Iniciado com"
+ "Tudo") em vez de "Idêntico" + "Inscrição". A correção, em `app/cfmv.py` e no
`go_no_go.py`, foi esperar o `.preloader` sumir e clicar sem `force`.

Com os parâmetros corretos, o CFMV devolveu `HTTP 500 "An Internal Error Has Occurred."`
três vezes seguidas, e as tentativas pararam aí para não virar volume. Não é nenhum dos
bloqueios que o plano documenta (403, 429, HTML no lugar do JSON, erro do reCAPTCHA). Por
isso, `classify_response` trata esse caso como `error`, com o código `CFMV_SERVER_ERROR`, e
não como `blocked`: classificar sem certeza dispararia o resfriamento por uma suposição.

Cerca de 40 minutos depois, o backend do CFMV tinha voltado, e o `go_no_go.py` recebeu
HTTP 200 de novo. Foi aí que apareceu o segundo bug: a API do CFMV serve o JSON de sucesso
com `Content-Type: text/html`, e `classify_response` recusava como bloqueio qualquer
resposta sem "json" no Content-Type. A correção (commit `876be09`) passou a decidir pelo
corpo: só é "HTML no lugar do JSON" quando o corpo parece uma página. Com isso veio, no
mesmo dia, o primeiro sucesso pelo próprio contrato do worker.

A causa do 500 nunca foi confirmada. Pode ter sido um problema pontual do backend do
CFMV, ou uma rejeição do reCAPTCHA disfarçada de erro genérico. Como passou sozinho em
cerca de 40 minutos, a primeira hipótese é a mais provável, mas isso não prova nada.
**Se o 500 voltar em sequência, não insistir.** A decisão de quando tentar de novo, ou de
perguntar ao CFMV pelo canal oficial, é de quem acompanha o `T-14`.

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
  -d '{"uf":"AM","inscricao":"01234","requestId":"teste-manual"}'
```

## Rodando com Docker

```bash
docker compose up --build
```

A imagem (`mcr.microsoft.com/playwright/python:v1.62.0-noble`) já traz o Chromium
compatível com a versão fixada em `pyproject.toml`; não há `playwright install` no
`Dockerfile`.

## Produção

Roda em `https://cfmv.comunidade.pet`, na VPS da Stdout (Hostinger, São Paulo,
`srv746288.hstgr.cloud`), em Docker atrás do Traefik que já serve os outros serviços de
lá. A configuração da stack e o registro do deploy ficam no repositório da infra
(`STDOutDevBr/infrastdout_1`): a stack em `/opt/stacks/cfmv-worker/` e o registro em
`docs/onde-paramos.md`. Aqui fica só o que importa para quem mexe no worker:

- **Código e imagem:** o código roda do clone em `~/projetos/cfmv-browser-worker`. A
  imagem é marcada com o commit (`cfmv-browser-worker:<sha>`), nunca com `latest`.
- **Acesso:** sem porta publicada, só o Traefik alcança o contêiner. O
  `CFMV_WORKER_TOKEN` de produção está no `.env` da stack (modo 600), e é o mesmo que a
  Vercel precisa mandar.
- **DNS:** registro A `cfmv` em `comunidade.pet` no Cloudflare, em modo **DNS only**. O
  certificado é validado por TLS-ALPN, que não passa pelo proxy do Cloudflare.

Para atualizar depois de um push na `main` (na VPS, como `tiago`):

```bash
cd ~/projetos/cfmv-browser-worker && git pull
# trocar a tag em /opt/stacks/cfmv-worker/docker-compose.yml pelo novo `git rev-parse --short HEAD`
cd /opt/stacks/cfmv-worker && docker compose up -d --build
```

Para testar em produção sem o token aparecer na tela:

```bash
export CFMV_TOKEN=$(ssh tiago@srv746288.hstgr.cloud 'sed -n "s/^CFMV_WORKER_TOKEN=//p" /opt/stacks/cfmv-worker/.env')

curl -s -H "Authorization: Bearer $CFMV_TOKEN" https://cfmv.comunidade.pet/health

curl -s -X POST https://cfmv.comunidade.pet/lookup/pf \
  -H "Authorization: Bearer $CFMV_TOKEN" -H "Content-Type: application/json" \
  -d '{"uf":"AM","inscricao":"01234","requestId":"teste-prod"}'
```

Pelo navegador, também dá para testar em `https://cfmv.comunidade.pet/docs`. A página
pede primeiro um login: o mesmo basic auth do painel do Traefik e do Homepage da VPS. Depois,
clique em **Authorize** e cole só o token, sem o prefixo "Bearer", que o Swagger acrescenta
sozinho.

O código do worker serve `/docs`, `/redoc` e `/openapi.json` sem autenticação (os
defaults do FastAPI). Quem fecha essas três páginas em produção é o Traefik, com um
segundo roteador (`cfmv-docs`) no compose da stack. As rotas da API só exigem o Bearer.
Fechar as páginas evita que o worker se descreva para quem chega pelo certificado público,
como pede o "sem endpoint público" da seção 4.3 do plano.

Cada `/lookup/pf` vai ao CFMV de verdade: nada de rodar em loop. O worker devolve HTTP 200
para todos os resultados, então quem chama decide pelo campo `status`, não pelo código
HTTP. A única exceção é o 401, de token ausente ou errado.

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
python scripts/go_no_go.py --uf AM --inscricao 01234
# ou, sem --uf/--inscricao, usando o default de TEST_UF/TEST_INSCRICAO do .env:
python scripts/go_no_go.py
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

## Rodando o teste manual da foto

```bash
python scripts/foto_lookup.py --cfmv-internal-id 100001
# ou, sem o id em maos:
python scripts/foto_lookup.py --uf AM --inscricao 01234
# ou, sem nenhum dos dois, usando o default de TEST_UF/TEST_INSCRICAO do .env:
python scripts/foto_lookup.py
```

A foto vem de uma rota separada da busca (`GET /pf/fotoConsultaPublica/{id}`, achada
inspecionando o botão "Visualizar" do site), que não pede token de recaptcha. Com o
`cfmvInternalId` em mãos, o script pula direto pra ela; sem ele, roda primeiro o mesmo
fluxo do go/no-go para descobri-lo. Imprime a foto recebida (truncada) ou avisa quando o
profissional não tem foto cadastrada (`"foto": null`, resposta normal da API, não erro).

## O contrato com a aplicação principal

```
POST /lookup/pf            Authorization: Bearer <CFMV_WORKER_TOKEN>
{ "uf": "AM", "inscricao": "01234", "requestId": "...", "incluirFoto": false }

200 { "status": "found",
      "data": { "name": "...", "registration": "01234", "uf": "AM",
                "class": "VP", "active": true, "registrationDate": "2026-07-17",
                "cfmvInternalId": 100001, "photo": null, "specializations": [] },
      "meta": { "fetchedAt": "...", "durationMs": 0, "rawHash": "sha256:..." } }
200 { "status": "not_found" | "ambiguous", "meta": {...} }
200 { "status": "blocked" | "error", "error": { "code": "...", "message": "..." }, "meta": {...} }

GET  /health                Authorization: Bearer <CFMV_WORKER_TOKEN>
200 { "browser": "up", "lastLookupAt": "...", "queue": 0, "blockedCount": 0, "blockedUntil": null }
```

`incluirFoto` é opcional (default `false`) e não muda a latência nem o número de
requisições quando omitido. Quando `true` e o resultado é `found`, o worker faz um
segundo request ao CFMV (`fotoConsultaPublica`, best-effort: uma falha nele nunca muda o
`status` da consulta principal) e preenche `data.photo` com a foto em
`data:image/jpeg;base64,...`, ou `null` quando o profissional não tem foto cadastrada no
CFMV. **Campo novo no contrato:** ainda precisa ser espelhado em `cfmvProvider.ts`, no
repositório `comunidade-pet-app`, antes de ir para produção.

`data.specializations` vem direto do campo `pf_titulo_especialista` da própria consulta
(sem request extra, ao contrário da foto), mas o formato de um item não-vazio **não foi
confirmado contra o CFMV real** — em ~100 registros reais amostrados ao vivo, nenhum tinha
título de especialista cadastrado. Por isso o worker repassa a lista crua como veio, em vez
de tentar validar/tipar cada item. Se um dia aparecer um exemplo real preenchido, vale
ajustar o tipo em `LookupData.specializations` pra refletir o formato de verdade.

Detalhes de cada campo, e por que o worker nunca escreve em banco nenhum, estão na seção
4.2 de `docs/plans/crmv-conferido-cfmv.md`, no repositório `comunidade-pet-app`.
