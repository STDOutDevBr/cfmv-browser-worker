# Worker do CFMV: o que o comunidade.pet precisa saber

> Escrito em **2026-10-18**, a partir do repositório do worker
> ([`STDOutDevBr/cfmv-browser-worker`](https://github.com/STDOutDevBr/cfmv-browser-worker), commit
> `a944734`) e do deploy feito no mesmo dia. **Complementa o plano
> `docs/plans/crmv-conferido-cfmv.md`, que continua sendo a fonte das decisões.** Este documento registra o que foi construído, onde a construção se afastou do plano
> e o que falta deste lado.
>
> Item de fila: **`T-14`**, com o Victor desde 2026-10-12 (`docs/tasks/victor/my-tasks.md`).

## Em uma frase

O worker existe, está em produção em **`https://cfmv.comunidade.pet`**, e o go/no-go deu **"vai"**
na máquina de desenvolvimento e também na VPS. Do lado do worker, as fatias 0, 3 e 4 da seção 8 do
plano estão feitas. O que falta mora todo neste repositório: as fatias 1, 2 e 5, e o pedaço da Vercel
na fatia 4.

## 1. O resultado do go/no-go (para o journal e o `done.md`)

O plano (seção 7) pede o teste duas vezes, primeiro na máquina de quem desenvolve e depois na VPS,
e pede que o resultado entre no journal com a saída. Este é o resultado:

| Data       | Onde                                      | Como                                              | Resultado                                                                                    |
| ---------- | ----------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 2026-09-14 | Máquina de dev (IP residencial)           | `scripts/go_no_go.py`, três vezes                 | HTTP 200 e um registro, três vezes: **vai**                                                  |
| 2026-09-15 | Máquina de dev                            | `go_no_go.py` e o worker                          | HTTP 500 genérico três vezes seguidas; cerca de 40 min depois, 200 de novo (ver abaixo)      |
| 2026-10-18 | Máquina de dev (IP residencial)           | Worker local, `POST /lookup/pf`                   | `found` em 13 s, com foto                                                                    |
| 2026-10-18 | **VPS (IP de datacenter, São Paulo)**     | Worker de produção, às 20:11, 20:36 e 20:41 UTC   | **`found` três vezes**, um registro, de 3,6 a 4,9 s, com foto: **vai**                       |

- **O risco da seção 11 não se confirmou.** O plano temia que um IP de datacenter recebesse uma nota
  pior do reCAPTCHA v3 que o IP residencial do relatório. Em 2026-10-18, a VPS foi até mais rápida.
- **A diferença em relação ao critério do plano:** na VPS, as três consultas passaram pelo próprio
  worker, e não pelo script de go/no-go. O fluxo na página do CFMV é o mesmo nos dois.
- **O HTTP 500 de 2026-09-15** (`"An Internal Error Has Occurred."`) não é nenhum dos bloqueios
  documentados, e o worker o trata como `error`, e não como `blocked`. Passou sozinho em cerca de
  40 minutos, e a causa nunca foi confirmada. O caminho daquele dia também revelou e corrigiu dois
  bugs do worker: um `.preloader` que anulava os cliques nos rádios, e o CFMV que serve o JSON de
  sucesso com `Content-Type: text/html`.

## 2. Onde a construção se afastou do plano

| Plano                                                         | O que foi feito                                                                                                                                   |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Node + Playwright, em `infra/cfmv-browser-worker/` (seção 6)  | **Python 3.12 + FastAPI + Playwright para Python**, em **repositório separado**. O contrato vive no README de lá, e mudar o contrato exige espelhar aqui à mão |
| Pedir o token com `grecaptcha.execute` e chamar o `GET`       | **Preenche o formulário real** (UF, inscrição, "Idêntico", "Inscrição"), clica em "Filtrar" e captura a resposta do XHR da própria página             |
| Caddy como proxy                                              | **Traefik**, que já servia os outros serviços da VPS                                                                                              |
| VPS nova, custo não cotado (seções 9 e 11)                    | **A VPS da Stdout que já existia** (Hostinger KVM 2, São Paulo). Sem custo novo                                                                   |
| Contrato da seção 4.2                                         | Igual, **mais** `incluirFoto` / `data.photo`, `data.specializations` e, no `/health`, `blockedCount` e `blockedUntil` (seção 3 abaixo)             |
| Sem endpoint público (seção 4.3)                              | As duas rotas exigem Bearer, mas **`/docs`, `/redoc` e `/openapi.json` são públicos** (seção 8 abaixo)                                            |

O resto segue o plano: um escritor só (o worker não tem `DATABASE_URL`), concorrência 1, `blocked`
como estado e não como erro a vencer, nenhum mascaramento de navegador, e log sem token, cookie ou
HTML.

## 3. O contrato, como está em produção

```
POST https://cfmv.comunidade.pet/lookup/pf
Authorization: Bearer <CFMV_WORKER_TOKEN>
Content-Type: application/json

{ "uf": "AM", "inscricao": "01234", "requestId": "<id do requestContext>", "incluirFoto": false }
```

- **`uf`:** duas letras. O worker passa para maiúsculas.
- **`inscricao`:** o worker tira tudo que não é dígito e completa até cinco dígitos (`3156` vira
  `03156`). O service deste lado deve normalizar do mesmo jeito antes de usar a chave no snapshot.
- **`requestId`:** opcional. Aparece no log do worker; passe o mesmo do `requestContext`, para o log
  dos dois lados casar (plano, seção 4.2).
- **`incluirFoto`:** opcional, `false` por padrão. Ver a seção 4.

**Resposta `found`:**

```json
{
  "status": "found",
  "data": {
    "name": "MARIA EXEMPLO DA SILVA",
    "registration": "01234",
    "uf": "AM",
    "class": "VP",
    "active": true,
    "registrationDate": "2020-07-10",
    "cfmvInternalId": 100001,
    "photo": null,
    "specializations": []
  },
  "error": null,
  "meta": { "fetchedAt": "2026-10-18T20:41:57.37+00:00", "durationMs": 4434, "rawHash": "sha256:..." }
}
```

- **`name`** já vem sem os espaços que o CFMV às vezes põe na frente.
- **`registrationDate`** vem como `YYYY-MM-DD`.
- **`cfmvInternalId`** é o `id_pf_inscricao` do CFMV: serve para rastrear, **não** como identificador
  estável (plano, seção 2.2). Também é o que a busca da foto usa.
- **`rawHash`** é o SHA-256 do corpo bruto que o CFMV devolveu, e vai para o
  `cfmv_verifications.rawResponseHash`. **Cuidado:** duas consultas com os mesmos dados deram hashes
  diferentes em 2026-10-18. O hash identifica *aquela resposta*, não o registro, e não serve para
  detectar mudança cadastral. Para isso, compare os campos.

### 3.1 Os estados, e o que fazer com cada um

**O worker devolve HTTP 200 para todos os estados abaixo.** Quem chama decide pelo campo `status`,
nunca pelo código HTTP.

| `status`    | `error.code`        | Quando                                                                                           | O que o comunidade.pet faz (plano, seção 4.1)                        |
| ----------- | ------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| `found`     | —                   | A chave devolveu um registro                                                                     | Grava o snapshot, fonte `cfmv`, nota curta                            |
| `not_found` | —                   | Nenhum registro                                                                                  | Mantém `manual`, com nota                                             |
| `ambiguous` | —                   | Mais de um registro (o relatório nunca viu)                                                      | Tratar, **nunca pegar o primeiro**. Mantém `manual`                   |
| `blocked`   | `CFMV_BLOCKED`      | 403, 429, HTML no lugar do JSON, ou corpo que fala de reCAPTCHA                                  | Job `blocked`, mantém `manual`, e-mail de aviso. **Sem retry**        |
| `blocked`   | `COOLING_DOWN`      | Até 15 min depois de um bloqueio. Responde **na hora, sem consultar o CFMV**                      | Igual ao de cima                                                      |
| `error`     | `CFMV_SERVER_ERROR` | 5xx genérico do CFMV (o caso de 2026-09-15)                                                      | Job `failed`, mantém `manual`; dá para pedir de novo à mão, mais tarde |
| `error`     | `LOOKUP_FAILED`     | O navegador falhou ou estourou o tempo antes de ter resposta                                     | Job `failed`, mantém `manual`                                         |
| `error`     | `UNEXPECTED_SHAPE`  | JSON válido fora do formato esperado                                                             | Job `failed` e **aviso**: a página do CFMV pode ter mudado            |
| `error`     | `INVALID_UF`        | UF sem duas letras                                                                               | Bug de quem chamou                                                    |

**Fora do 200, pela camada HTTP:**

- **`401`:** token ausente ou errado. Para o service, conta como falha de configuração (mantém
  `manual` e avisa).
- **`422`:** corpo inválido, por exemplo sem `uf` ou sem `inscricao`. É bug de quem chamou.
- **`502`/`504`, ou falha de rede:** o worker ou a VPS estão fora. Job `failed`, mantém `manual`.
  Não é urgência: a aprovação nunca depende do CFMV (plano, seção 4.1).

### 3.2 Tempo e fila

- **Uma consulta por vez**, com pelo menos 3 s entre uma e outra. Se duas chegam juntas, a segunda
  espera na fila do worker (o `queue` do `/health` mostra isso).
- **O limite de 20 s vale por etapa**, e não para a consulta inteira: carregar a página, esperar o
  formulário montar e esperar a resposta têm 20 s cada. A foto é uma ida a mais, com o mesmo limite.
- **Medido em produção:** de 3,6 a 4,9 s, com foto. Na máquina de dev, até 13 s.
- **O timeout do lado de cá:** use pelo menos 30 s sem foto e 45 s com foto. O pior caso (fila mais
  etapas lentas) pode passar disso. Se acontecer, o job fica `failed` e a aprovação segue `manual`,
  o que é aceitável. O plano lista como não conferido o tempo limite de uma função da Vercel no plano
  atual (seção 11), e é ele que define se o síncrono da seção 10 cabe. **Confira isso antes de fechar
  a fatia 2.**

### 3.3 O `/health`

```
GET https://cfmv.comunidade.pet/health        Authorization: Bearer <CFMV_WORKER_TOKEN>
200 { "browser": "up", "lastLookupAt": "...", "queue": 0, "blockedCount": 0, "blockedUntil": null }
```

`blockedUntil` preenchido quer dizer que o worker está em resfriamento, e qualquer consulta até lá
volta `blocked` / `COOLING_DOWN`. O `/health` não consulta o CFMV.

## 4. A foto: é uma decisão deste lado

Com `"incluirFoto": true` e resultado `found`, o worker faz uma segunda chamada ao CFMV
(`fotoConsultaPublica`, uma rota que não pede reCAPTCHA) e devolve:

- **`data.photo`:** `data:image/jpeg;base64,...`, pronto para um `<img src>`. Em 2026-10-18, um JPEG
  de 16 KB, ou cerca de 21 mil caracteres.
- **`null`:** quando o profissional não tem foto cadastrada. É a resposta normal, e não um erro.
- **Best-effort:** se a foto falhar, o `status` continua `found` e `photo` volta `null`.

**O que o plano não cobre:** a foto é um dado pessoal novo. Ela não está nas colunas do snapshot
(seção 5) nem no parágrafo da política de privacidade (seção 9). Antes de usar, decidir:

- se a foto só é mostrada na hora, se é guardada (e onde: Neon, ou o R2 do `cdn.comunidade.pet`), ou
  se não entra;
- e incluir a foto no texto da `/privacy`, se ela for exibida ou guardada.

Sem essa decisão, mande `incluirFoto: false`, que é o padrão e não acrescenta nenhuma chamada ao
CFMV. E **não logue o campo `photo`**: além de pesado, é dado pessoal.

## 5. `specializations`

`specializations` é o repasse cru do `pf_titulo_especialista` do CFMV, e não faz nenhuma chamada a
mais. **O formato de um item preenchido nunca foi visto:** nenhum dos cerca de 100 registros reais
amostrados tinha título de especialista. Trate como `unknown[]` e não tipe com rigor até aparecer
um exemplo real.

## 6. O que configurar deste lado

**Variáveis**, com os nomes do plano (seção 8, fatia 4):

| Variável            | Valor                                          |
| ------------------- | ---------------------------------------------- |
| `CFMV_WORKER_URL`   | `https://cfmv.comunidade.pet`                  |
| `CFMV_WORKER_TOKEN` | o Bearer de produção (ver abaixo como pegar)   |

- **No `infra/env-contract.mjs`:** um grupo opcional, "as duas ou nenhuma", no mesmo molde do Serpro.
  Sem o grupo, o service devolve `null` e a aprovação segue `manual`, que é o comportamento de hoje
  (plano, seção 6).
- **Na Vercel, só em Production.** Um deploy de Preview com o grupo faria consultas reais ao CFMV a
  partir de branches. Em Preview e em dev, deixe sem o grupo, ou aponte para um worker local.

**Como pegar o token:** ele existe só no `.env` da stack na VPS (modo 600). Rode no seu terminal, e
não em chat nenhum:

```bash
ssh tiago@srv746288.hstgr.cloud 'sed -n "s/^CFMV_WORKER_TOKEN=//p" /opt/stacks/cfmv-worker/.env'
```

**O token nunca entra** em commit, issue, PR, log, journal ou conversa com assistente.

**Em desenvolvimento:** rode o worker na sua máquina (README do worker, seção "Rodando o worker
localmente") com **outro token**, gerado com `openssl rand -hex 32`, e use
`CFMV_WORKER_URL=http://localhost:8000`. Nos testes automatizados, use o `CfmvProvider` falso
(plano, seção 4); a suíte não deve depender do worker.

## 7. Exemplo da chamada

```ts
// a implementação do CfmvProvider que fala com o worker
const res = await fetch(`${process.env.CFMV_WORKER_URL}/lookup/pf`, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${process.env.CFMV_WORKER_TOKEN}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ uf, inscricao, requestId, incluirFoto: false }),
  signal: AbortSignal.timeout(30_000),
})

if (!res.ok) {
  // 401: configuração; 422: bug nosso; 5xx: worker fora. Em todos, manual + job failed.
}

const body = await res.json()
switch (body.status) {
  case 'found': /* body.data */ break
  case 'not_found': break
  case 'ambiguous': break
  case 'blocked': /* body.error.code: CFMV_BLOCKED | COOLING_DOWN, sem retry */ break
  case 'error': /* body.error.code */ break
}
```

Como em `callMp` (`layers/0.payments/server/utils/mercadopago.ts`), o erro original vai só para o
log, e nunca para a resposta ao usuário.

## 8. Como testar o worker de produção à mão

**Pelo navegador:** abra `https://cfmv.comunidade.pet/docs`, clique em **Authorize** e cole **só o
token**, sem "Bearer" (o Swagger acrescenta sozinho). Depois use o "Try it out" de cada rota.

**Pelo terminal:**

```bash
export CFMV_TOKEN=$(ssh tiago@srv746288.hstgr.cloud 'sed -n "s/^CFMV_WORKER_TOKEN=//p" /opt/stacks/cfmv-worker/.env')

curl -s -H "Authorization: Bearer $CFMV_TOKEN" https://cfmv.comunidade.pet/health

curl -s -X POST https://cfmv.comunidade.pet/lookup/pf \
  -H "Authorization: Bearer $CFMV_TOKEN" -H "Content-Type: application/json" \
  -d '{"uf":"AM","inscricao":"03156","requestId":"teste-manual"}'
```

A chave do exemplo é a da prova de conceito do relatório (plano, seção 2.2).

**Cada `/lookup/pf` vai ao CFMV de verdade.** Nada de loop, teste de carga ou varredura: o plano
(seção 9) limita o uso a uma consulta por aprovação mais o "verificar agora" de um admin.

**Sobre o `/docs` público:** hoje qualquer pessoa vê o formato da API ali, mas sem o token não
consegue chamar nada. Isso contradiz em parte a seção 4.3 do plano, e a decisão de desligar o
`/docs` em produção (e usá-lo só com o worker local) está em aberto do lado do worker.

## 9. Operação: onde mora e como mexer

- **Onde roda:** na VPS da Stdout, em Docker, atrás do Traefik, sem porta publicada.
  - Código: `~/projetos/cfmv-browser-worker`.
  - Stack: `/opt/stacks/cfmv-worker/`.
  - O registro da infra está no repositório `STDOutDevBr/infrastdout_1`, em `docs/onde-paramos.md`.
- **DNS:** registro A `cfmv` em `comunidade.pet`, no Cloudflare, em modo **DNS only**. **Não ligue
  o proxy (nuvem laranja)**: o certificado é validado por TLS-ALPN, e o proxy do Cloudflare quebra
  a renovação.
- **Logs:** no Dozzle (`https://logs.stdout.dev.br`, com login) ou com `docker logs cfmv-worker` na
  VPS. Cada consulta gera duas linhas JSON com o `requestId`.
- **Saúde da VPS inteira:** `stacks health` na VPS. O worker entra lá como
  `https://cfmv.comunidade.pet/health`, com 401 esperado (sem token).
- **Atualizar o worker** (na VPS, como `tiago`):

  ```bash
  cd ~/projetos/cfmv-browser-worker && git pull
  # trocar a tag em /opt/stacks/cfmv-worker/docker-compose.yml pelo novo `git rev-parse --short HEAD`
  cd /opt/stacks/cfmv-worker && docker compose up -d --build
  ```

- **Rodar o token** (no espírito do `FU-11`):
  1. Gerar um novo no `.env` da stack.
  2. `docker compose up -d` (o contêiner é recriado e lê o `.env` de novo).
  3. Trocar na Vercel e fazer o redeploy.

  Entre o passo 2 e o 3, as chamadas tomam 401 e a aprovação cai para `manual`. É aceitável, mas
  faça os passos em sequência.
- **Se a VPS cair:** a aprovação segue `manual` (plano, seção 4.1). Não é urgência.

## 10. O que falta, e de quem é

**Deste repositório (`T-14`):**

1. **Registrar o go/no-go** (seção 1 acima) no journal e no `done.md`, como pede a seção 7 do plano.
   Em `docs/tasks/victor/my-tasks.md`, o item "Onde está" ainda diz "Não registrado".
2. **Atualizar a seção 11 do plano:** a dúvida do IP de datacenter está respondida ("vai"), o custo
   da VPS também (VPS que já existia), e "nenhuma consulta foi feita por este projeto" deixou de ser
   verdade.
3. **Fatia 1:** `crmvState` no perfil, e o convite pelo CRMV casando UF + número. Em 2026-10-12, o
   `master` não tinha nada disso.
4. **Fatia 2:** as tabelas `cfmv_verifications` e `cfmv_jobs`, o valor `cfmv` no enum, o
   `CfmvProvider` (real e falso), o service com TTL, a rota de admin e o gancho na aprovação. **O
   timeout da função da Vercel precisa ser conferido aqui.**
5. **Fatia 4, parte da Vercel:** o grupo `CFMV_WORKER_URL` + `CFMV_WORKER_TOKEN` no
   `env-contract.mjs` e na Vercel (só Production). Pronta quando a aprovação de um veterinário de
   verdade gravar fonte `cfmv` com data.
6. **Fatia 5:** o texto da página da clínica, o roadmap e a `/privacy`, que **agora também precisa
   decidir sobre a foto** (seção 4 acima).

**Do lado do worker:**

- **Decidir sobre o `/docs` público em produção.** O caminho sugerido é desligá-lo por padrão e
  ligá-lo por variável em dev.
- **Mudanças de contrato** acontecem no repositório do worker e precisam ser espelhadas aqui. A
  fonte é o README de lá, na seção "O contrato com a aplicação principal".
