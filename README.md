# PI Analytics Data

## Configuração permanente da autenticação

O backend já carrega variáveis de ambiente e o arquivo local `backend/.env` pelo mecanismo único de `pydantic-settings`. Não versione esse arquivo quando ele contiver credenciais.

- `AUTH_JWT_SECRET`: segredo estável, aleatório e com pelo menos 32 caracteres. Deve ser armazenado no gerenciador de segredos/variáveis do ambiente e permanecer igual entre reinicializações. A aplicação não gera fallback.
- `AUTH_JWT_EXPIRE_MINUTES`: duração da sessão, entre 5 e 1440 minutos (padrão documentado: 60).
- `AUTH_COOKIE_SECURE=false`: somente para desenvolvimento local em HTTP.
- `AUTH_COOKIE_SECURE=true`: obrigatório em produção servida por HTTPS.

O `.env.example` contém apenas nomes e exemplos não secretos. Gere e instale o segredo fora do repositório; nunca o coloque no código, em logs ou relatórios.

Sistema para cadastro e gestao de tags do PI Web API, com consulta a valores
historicos, visualizacao de dados, correlacao, estatistica descritiva, CEP,
dashboards e alertas.

Este repositorio contem:

- **Fase 1 (POC)**: cadastros administrativos de equipamentos, secoes, tipos
  de variavel e tags PI.
- **Fase 2 (POC)**: integracao com o PI Web API (resolucao de WebId,
  validacao individual e em lote, consulta de series temporais).
- **Fase 3 (POC)**: pagina funcional de Visualizacao de Dados com grafico
  de linha, filtros em cascata, escolha de recorded/interpolated, eixos
  por unidade, qualidade, zoom, tooltip, legenda interativa, exportacao
  CSV e exportacao de imagem.

- **Fase 5.4**: filtros avancados client-side (qualidade, numerico, texto,
  dias da semana, horario, exclusoes) sobre a ultima consulta; CSV filtrado;
  contadores por motivo de remocao.

A Fase 3 nao inclui histograma, boxplot, dispersao, barras, correlacao,
estatistica descritiva, CEP, alertas, dashboards ou autenticacao de
usuarios. Esses modulos estao previstos para fases futuras.

## Stack

### Backend

- Python 3.12;
- FastAPI;
- SQLAlchemy 2;
- Alembic;
- Pydantic v2;
- HTTPX (cliente assincrono para o PI Web API);
- Pytest.

### Frontend

- React 18;
- TypeScript;
- Vite;
- Bootstrap 5;
- Bootstrap Icons;
- React Router DOM;
- React Bootstrap;
- ECharts 5 (grafico de linha);
- Vitest;
- React Testing Library.

### Banco

- SQLite (arquivo local `backend/pi_analytics_data.db`);
- Apenas dados cadastrais. Nenhuma tabela de valores historicos.

## Estrutura de pastas

```
project-root/
  backend/
    app/
      api/                # Roteadores FastAPI e handlers de erro
      core/               # Configuracao, excecoes, logging
      database/           # Engine e sessao SQLAlchemy
      integrations/pi/    # Cliente e provedor do PI Web API
      models/             # Modelos ORM
      repositories/       # Acesso a dados
      schemas/            # Schemas Pydantic
      services/           # Regras de negocio
      main.py             # Entrypoint FastAPI
    alembic/              # Migrations
    scripts/              # Seed e utilitarios
    tests/                # Testes pytest (com fake provider)
    requirements.txt
    requirements-dev.txt
    .env.example
    alembic.ini
  frontend/
    src/
      api/                # Cliente HTTP e modulos de API
      components/         # Componentes reutilizaveis
      layouts/            # Layout principal
      pages/              # Paginas
      types/              # Tipos TypeScript compartilhados
      utils/              # Utilidades
      styles/             # CSS customizado
    tests/                # Testes Vitest
    public/
    index.html
    package.json
    tsconfig.json
    vite.config.ts
    vitest.config.ts
    .env.example
  README.md
  RELATORIO_FASE_1.md
  RELATORIO_FASE_2.md
  RELATORIO_FASE_3.md
```

## Configuracao do backend

1. Criar o ambiente virtual:

   ```bash
   cd backend
   python3.12 -m venv .venv
   ```

2. Instalar as dependencias:

   ```bash
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements-dev.txt
   ```

3. Configurar o arquivo `.env` (copiar a partir do exemplo):

   ```bash
   cp .env.example .env
   ```

   Preencha `PI_WEB_API_BASE_URL` e `PI_DATA_SERVER_NAME` com os dados do
   seu ambiente. Para autenticacao basica, preencha tambem
   `PI_WEB_API_USERNAME` e `PI_WEB_API_PASSWORD`.

4. Executar as migrations:

   ```bash
   alembic upgrade head
   ```

5. Executar o seed (idempotente):

   ```bash
   python scripts/seed.py
   ```

6. Iniciar o backend:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   Documentacao automatica disponivel em:

   - Swagger UI: <http://localhost:8000/api/docs>
   - ReDoc: <http://localhost:8000/api/redoc>
   - OpenAPI: <http://localhost:8000/api/openapi.json>

## Configuracao do frontend

1. Instalar as dependencias:

   ```bash
   cd frontend
   npm install
   ```

2. Configurar o arquivo `.env`:

   ```bash
   cp .env.example .env
   ```

3. Iniciar em modo desenvolvimento:

   ```bash
   npm run dev
   ```

   Aplicacao disponivel em <http://localhost:5173>.

### Períodos da visualização de dados

A consulta temporal aceita períodos predefinidos, absolutos e relativos. Datas
informadas na interface são interpretadas explicitamente no fuso
`America/Sao_Paulo`; ao clicar em **Consultar**, o frontend resolve o intervalo
uma única vez e envia `start_time` e `end_time` em UTC para o endpoint existente
`GET /api/time-series`. Períodos relativos em dias e semanas seguem o calendário
local, inclusive nas transições históricas de horário de verão.

A seleção de período não cria consultas por si só. O intervalo efetivamente
resolvido fica associado ao resultado exibido até uma nova consulta. Base
cíclica não faz parte deste mecanismo.

## Endpoints adicionados nas fases anteriores

| Metodo | Rota | Finalidade |
| --- | --- | --- |
| GET | `/api/health` | Health check geral. |
| GET | `/api/pi/health` | Verificar conexao com o PI Web API. |
| POST | `/api/pi-tags/validate` | Validar varias tags. |
| POST | `/api/pi-tags/{id}/validate` | Validar uma tag especifica. |
| GET | `/api/time-series` | Consultar series temporais. |

### Health check do PI (`/api/pi/health`)

O endpoint de health do PI Web API consulta a **raiz** do PI Web API
(`GET {PI_WEB_API_BASE_URL}/`) e **nao** `/system/status`, pois este
ultimo pode exigir permissoes adicionais (por exemplo, `401 Unauthorized`
em ambientes com restricao de acesso ao endpoint de status).

A validacao considera o PI como conectado apenas quando:
- o status HTTP e 2xx;
- o corpo e JSON valido;
- o objeto `Links` esta presente;
- `Links.Self` ou `Links.System` existe dentro de `Links`.

**Nota:** Todas as chamadas HTTP ao PI Web API (health check, resolucao
de tags, consulta de valores) usam o valor de `PI_WEB_API_BASE_URL`
configurado no `.env`. O health check **nao** segue os links HTTPS que
o PI Web API pode retornar; ele continua usando a URL original. Isso
permite trabalhar com PI Web API via HTTP quando necessario.

### Formato de `tag_ids` no `GET /api/time-series`

O backend aceita os dois formatos abaixo (e os normaliza para uma lista
de inteiros unicos, validando o limite `PI_QUERY_MAX_TAGS`):

- parametros repetidos: `tag_ids=1&tag_ids=2&tag_ids=3`
- valores separados por virgula: `tag_ids=1,2,3`

O frontend envia parametros repetidos por padrao. A documentacao da API
tambem admite o formato CSV para flexibilidade.

## Visualizacao de Dados (Fase 4)

A pagina `Visualizacao de Dados` permite consultar o PI Web API e reutilizar a
resposta em oito visualizacoes: Automatica, Linha temporal, Estados,
Histograma, Boxplot, Dispersao, Barras — ultimo valor e Valor unico.

### Acesso

No menu lateral, clique em **Analises** > **Visualizacao de Dados**. O
endereco e `/analises/visualizacao`.

### Filtros disponiveis

1. **Periodo**
   - Ultimos 15 minutos (`PT15M`).
   - Ultima hora (`PT1H`).
   - Ultimas 8 horas (`PT8H`).
   - Ultimas 24 horas (`P1D`).
   - Ultimos 7 dias (`P7D`).
   - **Personalizado**: data/hora inicial e final (horario local do
     navegador). Ao consultar, a data e convertida para ISO 8601 UTC.

2. **Modelo**: Base Unidade é o modelo funcional atual. Base Cíclica, Base OEE,
   Base Paradas e Base Qualidade aparecem desabilitadas para indicar evolução
   futura, sem executar a consulta comum.

3. **Máquina** (obrigatorio): reutiliza diretamente o cadastro e os IDs de
   `Equipment` e filtra secoes e tags.

4. **Secao** (opcional): filtra tags vinculadas aquela secao.

5. **Tipo de variavel** (opcional): filtra tags daquele tipo.

6. **Tags** (obrigatorio, selecao multipla): apenas tags ativas e com
   validacao `VALID` ou `PENDING` podem ser selecionadas. Tags com
   `INVALID`, `ERROR` ou inativas sao bloqueadas. Ao mudar o equipamento
   ou a secao, as tags selecionadas que nao pertencem mais ao filtro sao
   removidas.

7. **Configuração das séries e eixos**: permite ordenar tags, atribuir séries
   numéricas ao eixo Y principal ou secundário e escolher explicitamente X/Y
   da dispersão. Tags do mesmo eixo Y precisam ter a mesma unidade.

8. **Modo de consulta**:
   - `recorded` (valores registrados).
   - `interpolated` (valores interpolados). Quando selecionado, o campo
     **Intervalo** aparece com opcoes como `1s`, `10s`, `30s`, `1m`,
     `5m`, `10m`, `30m`, `1h`.

9. **Max. pontos por tag**: limitado pela configuracao do backend
   (`PI_QUERY_MAX_POINTS_PER_TAG`, padrao 20000).

10. **Ignorar qualidade ruim** (ativado por padrao): descarta pontos com
   `good=false` (lacuna no grafico). Quando desativado, os valores sao
   plotados mesmo com qualidade ruim.

11. **Visualizacao**: escolhe um dos oito modos implementados sem refazer a
   consulta. Valor unico aceita numeros finitos, strings e booleanos sem
   coercao e apresenta a qualidade do PI por cor e texto.

### Fluxo

1. Selecione o periodo (ou marque **Personalizado**).
2. Confirme Base Unidade e selecione a maquina. A lista de secoes e atualizada.
3. Selecione a secao (opcional). A lista de tags e filtrada.
4. Selecione o tipo de variavel (opcional).
5. Marque uma ou mais tags validas e configure ordem/eixos.
6. Escolha o modo de consulta e, se for o caso, o intervalo.
7. Clique em **Consultar**.
8. O grafico e renderizado e o resumo da consulta aparece logo abaixo.

A exibicao das datas segue o fuso do navegador; a comunicacao com o
backend e em UTC.

### Graficos e interacoes

- Seletor tipado com oito modos: automatico, linha, estados, histograma,
  boxplot, dispersao, barras e valor unico.
- Valor unico usa o ponto exibivel de maior timestamp de cada tag e mostra
  Good, Questionable e Substituted; `"600"` permanece string.

- Eixo X temporal real (`type: "time"`).
- Eixo Y principal à esquerda e secundário à direita, atribuídos manualmente.
  Um eixo aceita várias tags desde que todas tenham a mesma unidade; unidades
  diferentes podem ser usadas em eixos separados, sem conversão automática.
- Dispersão com seletores explícitos de X e Y por ID de tag. A ordem da resposta
  não redefine os papéis e remover uma tag não escolhe substituta silenciosa.
- Ordem explícita com botões de mover para cima/baixo, aplicada às projeções dos
  oito modos. A resposta original e o CSV não são reordenados.
- Tooltip compartilhado por eixo mostrando:
  - data/hora local;
  - nome amigavel;
  - nome tecnico;
  - valor (formatado em pt-BR com ate 3 casas decimais);
  - unidade;
  - situacao da qualidade (OK, Substituido, Questionavel, Ruim).
- Legenda clicavel para ocultar ou exibir series.
- Zoom interno pelo mouse (selecao horizontal).
- Barra de zoom inferior (slider).
- Ferramentas (toolbox): restaurar zoom e salvar imagem
  (`pi-analytics-data-grafico-linha`).
- `connectNulls: false`: lacunas (valores nao numericos ou com qualidade
  ruim ignorada) nao sao conectadas.
- Simbolos automaticos: ocultos quando ha muitos pontos, visiveis para
  series pequenas.
- Animacao desativada por padrao para grandes volumes.
- Cores consistentes vindas de uma paleta fixa (12 tons contrastantes).
  A mesma tag mantem a mesma cor durante a consulta atual.

### Qualidade dos valores

Quando **Ignorar qualidade ruim** esta ativado:

- Apenas pontos com `good=true` sao plotados;
- Pontos com `good=false` viram lacuna (nao conectam a linha);
- O card **Descartados** mostra quantos pontos foram descartados.

Quando esta desativado:

- Valores numericos com qualidade ruim sao plotados;
- O tooltip exibe a situacao (`OK`, `Questionavel`, `Substituido`).

Os dados originais nao sao modificados: a transformacao para o grafico e
apenas uma projecao. A exportacao CSV preserva os valores originais.

### Estados da pagina

- **Inicial**: orientacao com os passos para preencher os filtros.
- **Carregando**: indicador "Carregando serie temporal...".
- **Sucesso**: grafico renderizado e resumo.
- **Resultado vazio**: mensagem indicando ausencia de valores numericos.
- **Erro total**: alerta de erro com botao **Tentar novamente**.
- **Resultado parcial**: card com a lista de series que falharam.
- **PI nao configurado**: alerta de aviso no painel de filtros.
- **PI indisponivel**: botao de consulta desabilitado.

### Resumo da consulta

Apos cada consulta, cards Bootstrap exibem:

- Quantidade de series;
- Total de pontos recebidos;
- Pontos numericos exibidos;
- Pontos descartados por qualidade;
- Pontos nao numericos;
- Periodo consultado (inicio e fim local);
- Duracao aproximada da requisicao;
- Modo (`recorded` ou `interpolated`);
- Status (Completo ou Parcial).

### Exportacao CSV

O botao **Baixar dados CSV** fica habilitado apos uma consulta com dados.
Gera um arquivo `pi-analytics-data_<equipamento>_<timestamp>.csv` no
formato longo, com colunas:

- `timestamp_utc`
- `timestamp_local`
- `tag_id`
- `tag_name`
- `display_name`
- `equipment`
- `section`
- `variable_type`
- `unit`
- `value`
- `good`
- `questionable`
- `substituted`

Os dados exportados sao exatamente os retornados pela consulta atual; o
CSV preserva valores textuais, booleanos e `null`, escapa aspas/quebras
de linha, usa `;` como separador e inclui BOM UTF-8 para Excel.

### Exportacao de imagem

A ferramenta **saveAsImage** do ECharts gera um arquivo PNG contendo
apenas o grafico (titulo, eixos, legenda). O nome de arquivo sugerido e
`pi-analytics-data-grafico-linha`.

### Cancelamento e tratamento de erro

Cada consulta usa um `AbortController`. Se o usuario disparar uma nova
consulta antes da anterior terminar, a anterior e cancelada e a resposta
antiga e descartada (evita sobrescrever com dados obsoletos). Erros
vindos do backend sao exibidos no painel de filtros e/ou na area do
grafico, com mensagens em portugues. Series que falham individualmente
nao impedem o retorno das demais: elas aparecem em `errors` na resposta
e no card **Resultado parcial** da UI.

## Testes

### Backend

```bash
cd backend
source .venv/bin/activate
pytest
```

Os testes usam `FakePiDataProvider` e nao dependem de um PI Web API real.

### Frontend

```bash
cd frontend
npm test
```

A suite cobre:

- Renderizacao do layout e dos estados da pagina.
- Filtros em cascata (equipamento, secao, tipo de variavel).
- Bloqueio de tags invalidas ou inativas.
- Conversao de horario local para UTC.
- Validacao de formulario (sem tag, sem equipamento, intervalo em
  interpolated, etc.).
- Construcao correta da requisicao `tag_ids=1&tag_ids=2&...`.
- Cancelamento da consulta anterior.
- Estados: carregando, vazio, erro, parcial, PI nao configurado.
- Transformacao de pontos (numericos, nao numericos, qualidade ruim).
- Dois eixos Y por unidade.
- Geracao e escaping do CSV.
- Preservacao dos valores originais no CSV.

## Build do frontend

```bash
cd frontend
npm run build
```

Gera os arquivos estaticos em `frontend/dist/`.

## Retry e tratamento de erros

O cliente PI Web API (`PiWebApiDataProvider`) aplica retry
automatico em requisicoes GET somente para erros transitorios:

**Recebem retry:**
- Timeout de conexao (HTTP 504 / `httpx.TimeoutException`)
- Resposta HTTP 429 (Too Many Requests)
- Resposta HTTP 502 (Bad Gateway)
- Resposta HTTP 503 (Service Unavailable)
- Falhas de conexao transitorias (SSL, DNS, socket)

**Nao recebem retry:**
- Resposta HTTP 400 (Bad Request)
- Resposta HTTP 401 (Unauthorized)
- Resposta HTTP 403 (Forbidden)
- Resposta HTTP 404 (Not Found)
- Resposta HTTP 500 (Internal Server Error)

O numero maximo de retentativas e configurado por `PI_REQUEST_MAX_RETRIES`
(padrao 2). Requisicoes POST/PUT/DELETE nao sao retentadas.

## Diagnostico de problemas

- **PI Web API nao configurado**: o backend retorna `status: "not_configured"`.
  Configure `PI_WEB_API_BASE_URL` e `PI_DATA_SERVER_NAME` no servidor.
- **PI indisponivel**: o endpoint `/api/pi/health` retorna
  `status: "unavailable"`. Verifique a conectividade, o certificado SSL e
  as credenciais.
- **Sem dados no grafico**: verifique o periodo e se as tags possuem
  WebId resolvido. Tags com `validation_status` `INVALID` ou `ERROR`
  nao serao desenhadas.
- **Unidades incompatíveis**: distribua as tags entre os eixos principal e
  secundário; todas as tags de um mesmo eixo precisam ter a mesma unidade.
- **Erro ao exportar CSV**: confirme que a consulta terminou com sucesso
  (o botao so fica habilitado apos sucesso).

## Limitacoes atuais

## Métricas de análise

A tela de Visualização de Dados oferece 20 métricas estatísticas opcionais.
Elas são calculadas no frontend sobre a última resposta em memória, respeitam o
filtro de qualidade e não alteram os oito gráficos, a consulta ao PI ou o CSV
original. Métricas de erro pareiam Real e Referência somente por timestamp UTC
exatamente igual. Limites LIE/LSE e LIC/LSC permanecem apenas em memória.

- Nao ha parametrizacao avancada, limites operacionais configuraveis,
  comparacao por periodos, CEP, alertas, dashboards
  ou autenticacao.
- Nao ha cache de valores historicos; cada consulta vai ao PI Web API.
- O CSV usa ponto e virgula como separador. Nao ha XLSX nesta fase.
- O downsampling visual (LTTB) ja e aplicado, mas nao ha
  downsampling destrutivo.

## Funcionalidades futuras

- Parametrizacao avancada e comparacao por periodos.
- CEP, alertas e dashboards.
- Autenticacao de usuarios e perfis.
- Cache distribuido de valores.
