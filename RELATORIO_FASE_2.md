# Relatorio da Fase 2 - PI Analytics Data

## 1. Resumo do que foi implementado

A Fase 2 entregou a integracao do catalogo de tags com o PI Web API, mantendo
o banco de dados SQLite restrito a dados cadastrais. Os valores historicos
**nao** sao persistidos localmente; eles sao consultados diretamente no PI
Web API no momento da requisicao.

Componentes principais adicionados:

- Camada `app/integrations/pi/` com provedor abstrato (`PiDataProvider`) e
  implementacao concreta `PiWebApiDataProvider` usando HTTPX `AsyncClient`.
- Servico `PiService` que combina o catalogo local com o PI remoto
  (resolver, validar, consultar series).
- Endpoints REST adicionais: `GET /api/pi/health`,
  `POST /api/pi-tags/{id}/validate`, `POST /api/pi-tags/validate`,
  `GET /api/time-series`.
- Frontend com botao de validacao individual, validacao em lote, indicador
  de conexao com o PI, exibicao de WebId (com copia), mensagem de
  validacao e data de validacao.
- 31 novos testes automatizados no backend e 11 novos no frontend, sem
  perder nenhum teste da Fase 1. Sao 22 testes da Fase 1 mais 31 da Fase 2,
  totalizando 53 (o `pytest --collect-only` confirma o numero). A diferenca
  entre a contagem manual de funcoes e o total coletado se deve a testes
  parametrizados: `test_pi_health.py` tem 3 funcoes + 4 parametros = 7 testes,
  e `test_pi_validate.py` tem 7 funcoes + 4 parametros = 11 testes.

Validacao: 53/53 testes de backend e 21/21 testes de frontend passam, alem do
build de producao. Testes contra um PI real permanecem como validacao manual
(documentada no item 12).

## 2. Arquivos criados e alterados

### Criados (backend)

- `backend/app/integrations/__init__.py`
- `backend/app/integrations/pi/__init__.py`
- `backend/app/integrations/pi/provider.py` (interface e dataclasses)
- `backend/app/integrations/pi/webapi_provider.py` (cliente HTTPX)
- `backend/app/integrations/pi/manager.py` (ciclo de vida do provedor)
- `backend/app/integrations/pi/errors.py` (erros normalizados)
- `backend/app/schemas/pi.py` (Pydantic da Fase 2)
- `backend/app/services/pi_service.py` (regras de negocio)
- `backend/app/api/pi.py` (endpoint de health)
- `backend/app/api/time_series.py` (endpoint de series)
- `backend/tests/pi_fakes.py` (`FakePiDataProvider` e helpers)
- `backend/tests/test_pi_health.py` (7 testes, sendo 3 funcoes + 1 parametrizada com 4 casos)
- `backend/tests/test_pi_validate.py` (11 testes, sendo 7 funcoes + 1 parametrizada com 4 casos)
- `backend/tests/test_pi_time_series.py` (13 testes)

### Criados (frontend)

- `frontend/src/components/PiConnectionStatus.tsx`
- `frontend/src/components/WebIdDisplay.tsx`

### Alterados (backend)

- `backend/app/core/config.py`: adicionadas configuracoes `PI_WEB_API_*`,
  `PI_DATA_SERVER_NAME`, `PI_REQUEST_*`, `PI_QUERY_*`; campo `pi_web_api_password`
  como `SecretStr`; metodo `is_pi_configured()`.
- `backend/app/core/error_codes.py`: novos codigos `PI_*` e `TAG_INACTIVE`,
  `TIME_RANGE_INVALID`, `PI_QUERY_LIMIT_EXCEEDED`.
- `backend/app/core/exceptions.py`: novas excecoes `Pi*`, `TagInactiveError`,
  `TimeRangeInvalidError`, `QueryLimitExceededError`.
- `backend/app/main.py`: lifespan agora inicia/encerra o provedor PI.
- `backend/app/api/router.py`: inclui os novos routers.
- `backend/app/api/pi_tags.py`: novos endpoints de validacao.
- `backend/app/api/deps.py`: adicionada `get_pi_provider` e `get_pi_service`.
- `backend/.env.example`: bloco com as variaveis `PI_*`.
- `backend/tests/conftest.py`: adiciona fixtures `fake_provider` e
  `client` que injetam o fake; atualiza o cache de settings entre testes.
- `backend/app/schemas/__init__.py`: exporta os novos schemas.

### Alterados (frontend)

- `frontend/src/api/index.ts`: novos modulos `piApi`, `timeSeriesApi`,
  metodos `piTagsApi.validate` e `piTagsApi.validateBatch`.
- `frontend/src/api/index.ts` (tipos): `PiHealth`, `PiTagValidationResult`,
  `PiTagValidationBatchResponse`, `TimeSeries`, etc.
- `frontend/src/pages/PiTagsPage.tsx`: habilita validacao individual e em
  lote, indicador de conexao, modal de resultado, exibicao de WebId
  truncado, selecao multipla.
- `frontend/src/types/index.ts`: tipos da Fase 2.
- `frontend/tests/app.test.tsx` e `frontend/tests/mocks/api.ts`: mocks e
  testes adicionais.

### Documentacao

- `README.md` atualizado com a arquitetura, variaveis de ambiente, modos de
  autenticacao, exemplos de chamadas, procedimentos de diagnostico e
  limitacoes.
- `RELATORIO_FASE_2.md` (este arquivo).

## 3. Variaveis de ambiente adicionadas

| Variavel | Padrao | Descricao |
| --- | --- | --- |
| `PI_WEB_API_BASE_URL` | (vazio) | URL base do PI Web API. |
| `PI_WEB_API_AUTH_MODE` | `none` | `none` ou `basic`. |
| `PI_WEB_API_USERNAME` | (vazio) | Usuario para Basic Auth. |
| `PI_WEB_API_PASSWORD` | (vazio) | Senha para Basic Auth (SecretStr). |
| `PI_WEB_API_VERIFY_SSL` | `true` | Verificacao de SSL/TLS. |
| `PI_DATA_SERVER_NAME` | (vazio) | Nome do PI Data Archive. |
| `PI_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout HTTP em segundos. |
| `PI_REQUEST_MAX_RETRIES` | `2` | Retries em GETs idempotentes. |
| `PI_QUERY_MAX_TAGS` | `10` | Maximo de tags por consulta. |
| `PI_QUERY_MAX_POINTS_PER_TAG` | `20000` | Maximo de pontos por tag. |

## 4. Endpoints adicionados

| Metodo | Rota | Descricao |
| --- | --- | --- |
| GET | `/api/pi/health` | Verifica a conexao com o PI Web API. |
| POST | `/api/pi-tags/{id}/validate` | Valida uma tag especifica. |
| POST | `/api/pi-tags/validate` | Valida varias tags (ou todas ativas, se vazio). |
| GET | `/api/time-series` | Consulta series temporais. |

## 5. Estrategia de autenticacao implementada

- Apenas `none` e `basic` sao suportados.
- A senha e armazenada como `SecretStr` (Pydantic) e nunca e serializada em
  logs ou respostas.
- Se um modo nao suportado for configurado, o sistema retorna 501
  (`PI_UNSUPPORTED_AUTH`).
- A comunicacao usa HTTPS por padrao. SSL e validado por padrao; a opcao
  `PI_WEB_API_VERIFY_SSL=false` existe apenas para diagnostico.

## 6. Resolucao e cache de WebId

- Toda tag nova nasce com `validation_status = PENDING` e `pi_web_id = NULL`.
- A validacao monta o caminho `\\{PI_DATA_SERVER_NAME}\{pi_tag_name}` e usa
  `GET /points?path=...` no PI Web API. Caminhos e parametros sao enviados
  via query params do HTTPX (com encoding apropriado).
- Quando o ponto existe, o `WebId` retornado e salvo e o status passa a
  `VALID`. Quando o PI retorna 404, o status passa a `INVALID` e o WebId
  e limpo. Outras falhas (timeout, SSL, 5xx, autenticacao) geram `ERROR`
  preservando os dados cadastrais.
- Na consulta de series temporais, se a tag nao tiver `pi_web_id`, o
  backend resolve automaticamente e segue. Se o WebId armazenado ficar
  obsoleto (a consulta retorna 404), o backend resolve uma unica vez e
  refaz a consulta.

## 7. Formato normalizado das series temporais

```json
{
  "start_time": "2026-07-01T00:00:00Z",
  "end_time": "2026-07-01T01:00:00Z",
  "mode": "recorded",
  "series": [
    {
      "tag_id": 1,
      "tag_name": "RB3.TEMP",
      "display_name": "Temperatura do forno",
      "equipment": "RB3",
      "section": "ENTRADA",
      "variable_type": "TEMPERATURE",
      "unit": "C",
      "points": [
        {"timestamp": "2026-07-01T00:00:00Z", "value": 80.0, "good": true, "questionable": false, "substituted": false},
        {"timestamp": "2026-07-01T00:01:00Z", "value": 80.5, "good": false, "questionable": false, "substituted": true},
        {"timestamp": "2026-07-01T00:02:00Z", "value": "RUN", "good": true, "questionable": false, "substituted": false}
      ]
    }
  ],
  "errors": []
}
```

Regras:

- Datas em ISO 8601 UTC.
- `value` preserva o tipo retornado pelo PI (numero, texto, booleano, null).
- Indicadores `good`, `questionable`, `substituted` preservam o codigo do PI.
- Falhas em tags individuais nao interrompem a consulta; elas aparecem em
  `errors`.

## 8. Tratamento de erros

| Codigo | HTTP | Significado |
| --- | --- | --- |
| `PI_NOT_CONFIGURED` | 503 | PI Web API nao configurado. |
| `PI_AUTH_FAILED` | 502 | Falha de autenticacao. |
| `PI_TIMEOUT` | 504 | Timeout. |
| `PI_SSL_ERROR` | 502 | Erro de SSL/TLS. |
| `PI_UNAVAILABLE` | 502 | PI Web API indisponivel. |
| `PI_INVALID_RESPONSE` | 502 | Resposta invalida do PI. |
| `PI_TAG_NOT_FOUND` | 404 | Tag nao encontrada no PI. |
| `PI_UNSUPPORTED_AUTH` | 501 | Modo de autenticacao nao suportado. |
| `PI_QUERY_LIMIT_EXCEEDED` | 400 | Limite de tags excedido. |
| `TAG_INACTIVE` | 409 | Tag local inativa. |
| `TIME_RANGE_INVALID` | 400 | Periodo invalido. |
| `NOT_FOUND` | 404 | Tag local inexistente. |
| `DUPLICATE_*` | 409 | Codigo duplicado. |
| `VALIDATION_ERROR` | 422 | Erro de validacao do payload. |
| `INTERNAL_ERROR` | 500 | Erro interno. |

As respostas de erro nunca incluem `Authorization`, cookies, tokens, senhas
ou stack traces. Logs tecnicos podem ser emitidos com a URL, status e
mensagem, mas o conteudo sensivel e mascarado.

## 9. Resultado dos testes do backend

- Comando: `pytest` (executado em `backend/`, dentro do `.venv`).
- Total: 53 testes.
- Aprovados: 53.
- Falhos: 0.
- Ignorados: 0.

Distribuicao por arquivo (verificada via `pytest --collect-only`):

- `test_health.py` (1)
- `test_equipments.py` (7)
- `test_sections.py` (5)
- `test_variable_types.py` (4)
- `test_pi_tags.py` (4) (Fase 1, CRUD da entidade)
- `test_seed.py` (1)
- `test_pi_health.py` (7) (novo)
- `test_pi_validate.py` (11) (novo)
- `test_pi_time_series.py` (13) (novo)

Cobertura da Fase 2 inclui:

- health check com sucesso, nao configurado, indisponivel, autenticacao,
  timeout, SSL, resposta invalida.
- resolucao de tag com sucesso (status `VALID`, `pi_web_id` salvo).
- tag inexistente no PI (status `INVALID`).
- falhas de comunicacao (status `ERROR` para `PI_AUTH_FAILED`,
  `PI_TIMEOUT`, `PI_SSL_ERROR`, `PI_UNAVAILABLE`, `PI_INVALID_RESPONSE`).
- validacao em lote com resultados mistos.
- consulta `recorded` e `interpolated`.
- validacao de datas (intervalo obrigatorio em `interpolated`,
  `start_time < end_time`).
- limite de tags (`PI_QUERY_LIMIT_EXCEEDED`).
- bloqueio de tag local inexistente e tag inativa.
- resolucao automatica quando nao ha WebId.
- re-resolucao quando o WebId esta obsoleto.
- normalizacao dos indicadores de qualidade.
- preservacao de tipos de valor (numero, texto, null).
- erro em uma tag nao bloqueia as demais.
- ausencia de persistencia de valores (verificacao de tabelas).
- ausencia de credenciais nas respostas.

## 10. Resultado dos testes do frontend

- Comando: `npm test` (executado em `frontend/`).
- Total: 21 testes.
- Aprovados: 21.
- Falhos: 0.
- Ignorados: 0.

Casos adicionados na Fase 2:

- Indicador de conexao com o PI (status `conectado` / `nao configurado`).
- Botao de validacao individual.
- Estado de carregamento durante a validacao.
- Apresentacao de `VALID` / `INVALID` / `ERROR`.
- Validacao em lote.
- Falha de conexao com o backend (endpoint `/api/pi/health`).
- Botoes desabilitados quando o PI esta nao configurado.

## 11. Resultado do build

- Comando: `npm run build`.
- Resultado: `built in ~5s` sem erros. Artefatos gerados em
  `frontend/dist/` (`index.html`, CSS, JS, fonts).

## 12. Evidencias de que nenhuma serie historica foi persistida

- O alembic cria apenas 4 tabelas: `equipments`, `sections`,
  `variable_types`, `pi_tags` (alem de `alembic_version`).
- O teste `test_time_series_does_not_persist_values` consulta
  `inspect(...).get_table_names()` e verifica que nao existem tabelas
  contendo `tag_value`, `time_series` ou `historical` no schema.
- A integracao e somente leitura: o servico nao escreve em nenhuma
  tabela ao consultar o PI. O unico efeito colateral de uma consulta
  bem-sucedida e atualizar `pi_web_id` / `validation_status` /
  `validated_at` quando a tag ainda nao tinha WebId (ou quando o WebId
  foi marcado como obsoleto por um 404).

## 13. Limitacoes conhecidas

- Apenas `none` e `basic` sao suportados. Kerberos / Windows Integrated
  Authentication nao sao implementados.
- Nenhum valor historico e persistido. Consultas com janelas muito
  grandes podem exceder `PI_QUERY_MAX_POINTS_PER_TAG`.
- O cache de WebId e apenas local (SQLite). Nao ha cache distribuido.
- Nao ha graficos, correlacao, estatistica descritiva, CEP, alertas,
  autenticacao de usuarios ou dashboards (escopo das proximas fases).
- O teste com um PI Web API real permanece como validacao manual.

## 14. Pendencias reais

- Validar a integracao contra um PI Web API real (recomendado em
  ambiente controlado).
- Adicionar testes de carga para series temporais com grande volume
  de pontos.
- Considerar politicas de revalidacao automatica periodica.

## 15. Comandos para execucao

```bash
# Backend
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
# Editar .env com PI_WEB_API_BASE_URL, PI_DATA_SERVER_NAME, etc.
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Testes do backend
pytest

# Frontend
cd ../frontend
npm install
cp .env.example .env
npm run dev

# Testes do frontend
npm test

# Build do frontend
npm run build
```

## 16. Exemplos de chamadas

```bash
# Health check
curl -s http://localhost:8000/api/pi/health

# Validar uma tag
curl -s -X POST http://localhost:8000/api/pi-tags/1/validate

# Validar em lote
curl -s -X POST http://localhost:8000/api/pi-tags/validate \
  -H "Content-Type: application/json" \
  -d '{"tag_ids":[1,2,3]}'

# Valores registrados
curl -s "http://localhost:8000/api/time-series?tag_ids=1,2&start_time=2026-07-01T00:00:00Z&end_time=2026-07-01T01:00:00Z&mode=recorded"

# Valores interpolados
curl -s "http://localhost:8000/api/time-series?tag_ids=1&start_time=2026-07-01T00:00:00Z&end_time=2026-07-01T01:00:00Z&mode=interpolated&interval=1m"
```

## 17. Preparacao recomendada para a Fase 3

A estrutura entregue ja prepara a chegada dos modulos analiticos:

- O provedor `PiDataProvider` e o servico `PiService` separam
  completamente o transporte HTTP da logica de negocio, o que facilita a
  adicao de um cliente paralelo (ECharts, servico de correlacao) sem
  duplicar regras.
- O endpoint `/api/time-series` retorna uma estrutura consistente, pronta
  para alimentar graficos e calculos estatisticos.
- O sistema de validacao permite identificar rapidamente tags sem WebId
  ou com erro, base para rotinas de CEP/alertas.
- A autenticacao de usuarios e os perfis podem ser adicionados como uma
  camada transversal (middleware do FastAPI) sem reescrever a logica de
  catalogo/integracao.
- A ausencia de persistencia de valores historicos simplifica a politica
  de retencao: cada chamada ao PI e idempotente e o banco cresce apenas
  com metadados.
