# Relatorio da Fase 3 - PI Analytics Data

## 1. Resultado da verificacao inicial

Antes de qualquer alteracao foi feita a verificacao obrigatoria exigida
pelo escopo da Fase 3.

- `README.md`, `RELATORIO_FASE_1.md` e `RELATORIO_FASE_2.md` foram lidos
  integralmente.
- A estrutura do projeto foi inspecionada (`backend/app/`,
  `backend/tests/`, `frontend/src/`, `frontend/tests/`).
- Os testes existentes foram executados como linha de base:
  - `pytest` (backend) -> 53/53 passando.
  - `npm test` (frontend) -> 21/21 passando.
- `pytest --collect-only -q` foi executado para confirmar a quantidade
  exata de testes (53).

## 2. Explicacao da divergencia entre 49 e 53 testes

O `RELATORIO_FASE_2.md` declarava "53 testes" no total mas somava 49
quando os valores por arquivo eram adicionados. A diferenca nao era
refeita a erro humano, mas sim a testes parametrizados, que expandem
em varios casos no momento da execucao.

Resultado da verificacao (`pytest --collect-only`):

| Arquivo | Funcoes | Parametros | Total |
| --- | --- | --- | --- |
| `tests/test_health.py` | 1 | 0 | 1 |
| `tests/test_equipments.py` | 7 | 0 | 7 |
| `tests/test_sections.py` | 5 | 0 | 5 |
| `tests/test_variable_types.py` | 4 | 0 | 4 |
| `tests/test_pi_tags.py` | 4 | 0 | 4 |
| `tests/test_seed.py` | 1 | 0 | 1 |
| `tests/test_pi_health.py` | 3 | 4 | 7 |
| `tests/test_pi_validate.py` | 7 | 4 | 11 |
| `tests/test_pi_time_series.py` | 13 | 0 | 13 |
| **Total** | **45** | **8** | **53** |

O relatorio da Fase 2 foi corrigido para refletir a contagem real (53
testes, sendo 31 novos na Fase 2, distribuidos conforme a tabela
acima).

## 3. Resumo da implementacao

A Fase 3 implementou a primeira analise visual funcional do sistema:
a pagina "Visualizacao de Dados" com grafico de linha. Os valores
historicos continuam sendo consultados diretamente no PI Web API,
sem persistencia local.

Componentes adicionados:

- Componente reutilizavel de ECharts (`EChartsWrapper`) com `ResizeObserver`
  e cleanup adequado.
- Painel de filtros em cascata (`DataFiltersPanel`).
- Componente de selecao multipla de tags (`TagMultiSelect`) que bloqueia
  tags inativas e com status diferente de `VALID`/`PENDING`.
- Grafico de linha (`TimeSeriesChart`) com eixo X temporal, ate dois
  eixos Y, tooltips ricos, legenda interativa, zoom interno e por slider
  e toolbox com `saveAsImage` e `restore`.
- Resumo da consulta (`QuerySummary`).
- Utilitarios para datas/periodos, formatacao de valores em pt-BR,
  geracao de CSV e transformacao de dados para o ECharts.
- 32 novos testes no frontend (19 unitarios + 13 de pagina).
- 4 novos testes no backend para o contrato de `GET /api/time-series`
  (CSV e parametros repetidos, cap de `max_count`).

Tambem foi feita a correcao de um pequeno problema do relatorio da
Fase 2 (contagem de testes).

## 4. Arquivos criados

### Backend

- `backend/tests/test_time_series_contract.py` (4 testes)

### Frontend

- `frontend/src/components/EChartsWrapper.tsx`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/components/TagMultiSelect.tsx`
- `frontend/src/components/TimeSeriesChart.tsx`
- `frontend/src/components/QuerySummary.tsx`
- `frontend/src/utils/period.ts`
- `frontend/src/utils/values.ts`
- `frontend/src/utils/chartData.ts`
- `frontend/src/utils/csv.ts`
- `frontend/tests/mocks/echarts.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`

## 5. Arquivos alterados

### Backend

- `backend/app/api/time_series.py` (aceita CSV e parametros repetidos,
  aplica cap de `max_count`).
- `backend/app/services/pi_service.py` (helper `_resolve_max_count` para
  impedir `max_count` acima de `PI_QUERY_MAX_POINTS_PER_TAG`).
- `backend/app/api/pi_tags.py` (sem alteracao alem do que ja existia;
  validacao individual ja estava implementada na Fase 2).

### Frontend

- `frontend/src/api/index.ts` (cliente HTTP passou a enviar arrays como
  parametros repetidos via `appendQuery`).
- `frontend/src/api/http.ts` (suporte a `AbortSignal` em `get`).
- `frontend/src/pages/DataVisualizationPage.tsx` (substitui o placeholder
  por uma pagina funcional completa).
- `frontend/src/types/index.ts` (novos tipos: `PiHealth`,
  `PiTagValidationResult`, `TimeSeries`, etc.).
- `frontend/src/utils/format.ts` (preservado; novo arquivo
  `frontend/src/utils/values.ts` para formatadores numericos).
- `frontend/tests/mocks/api.ts` (novo mock `timeSeriesQuery`).
- `frontend/tests/app.test.tsx` (teste do placeholder atualizado).
- `README.md` (documentacao da Fase 3).
- `RELATORIO_FASE_2.md` (correcao da contagem de testes).

## 6. Componentes frontend

| Componente | Responsabilidade |
| --- | --- |
| `EChartsWrapper` | Encapsula `echarts.init`/`setOption`/`dispose` e gerencia
  redimensionamento. |
| `DataFiltersPanel` | Formulario completo (periodo, equipamento, secao,
  tipo de variavel, tags, modo, intervalo, max pontos, qualidade). |
| `TagMultiSelect` | Lista de tags com checkbox, badge de validacao,
  bloqueio de inativas/invalidas. |
| `TimeSeriesChart` | Configura `EChartsOption` (line, time, value,
  tooltip, legend, dataZoom, toolbox, animacao desligada, etc.). |
| `QuerySummary` | Cards com metricas da consulta (series, pontos,
  descartados, duracao, status). |

## 7. Dependencias adicionadas

- Frontend: `echarts@5.5.1` (adicionado em `package.json`).
- Backend: nenhuma nova dependencia.

## 8. Funcionamento dos filtros

1. **Periodo**: presets pre-definidos ou modo personalizado com
   `datetime-local` (horario do navegador). A data/hora e convertida
   para ISO 8601 UTC antes de enviar ao backend.
2. **Equipamento**: obrigatorio; filtra secoes e tags.
3. **Secao**: opcional; filtra tags.
4. **Tipo de variavel**: opcional; filtra tags.
5. **Tags**: selecao multipla; somente `active=true` e
   `validation_status` `VALID` ou `PENDING` sao selecionaveis. Quando
   o equipamento ou secao muda, as tags selecionadas que saem do
   filtro sao removidas da selecao (efeito de cascata).
6. **Modo de consulta**: `recorded` ou `interpolated`. Em `interpolated`
   o campo `interval` e obrigatorio (8 opcoes pre-definidas).
7. **Max pontos por tag**: limitado por `PI_QUERY_MAX_POINTS_PER_TAG`.
8. **Ignorar qualidade ruim**: ligado por padrao. Quando ligado,
   pontos com `good=false` viram lacunas; quando desligado, mantem-se
   no grafico e o tooltip mostra a qualidade.

Validacoes aplicadas antes da consulta:

- equipamento obrigatorio;
- ao menos uma tag;
- data inicial menor que data final (quando personalizado);
- intervalo obrigatorio em `interpolated`;
- `max_count` >= 1 e <= limite configurado;
- ate 2 unidades distintas entre as tags selecionadas.

## 9. Contrato utilizado em `GET /api/time-series`

O backend aceita os dois formatos abaixo, valida o limite de
`PI_QUERY_MAX_TAGS` e rejeita `max_count` acima de
`PI_QUERY_MAX_POINTS_PER_TAG`:

- Parametros repetidos: `tag_ids=1&tag_ids=2&tag_ids=3`.
- CSV: `tag_ids=1,2,3`.

O frontend envia parametros repetidos (formato padrao do `URLSearchParams`).
A documentacao e os testes cobrem ambos os formatos.

## 10. Funcionamento do grafico

- `type: "line"`, `sampling: "lttb"`, `connectNulls: false`.
- Eixo X: `type: "time"` (temporal real).
- Eixo Y: ate 2 eixos por unidade distinta; nomes das unidades nos
  eixos correspondentes.
- Tooltip compartilhado por eixo, formatado em pt-BR, com data local,
  nome amigavel, nome tecnico, valor, unidade e qualidade.
- Legenda clicavel (`type: "scroll"`).
- Zoom interno (`dataZoom` `inside`) e por slider.
- Toolbox: `restore` e `saveAsImage` (nome do arquivo:
  `pi-analytics-data-grafico-linha`).
- Simbolos automaticos: visiveis para series pequenas, ocultos
  quando ha muitos pontos.
- Animacao desativada (`animation: false`).

## 11. Tratamento de unidades

- Series com a mesma unidade compartilham o mesmo eixo.
- Ate 2 unidades: 1 ou 2 eixos Y.
- Mais de 2 unidades: a consulta e bloqueada com mensagem
  "Selecione tags com no maximo duas unidades diferentes."
- Os rotulos dos eixos preservam a capitalizacao original (a chave
  de comparacao e lowercase, mas o rotulo exibido e o que veio do
  catalogo).
- Nao ha conversao automatica de unidades.

## 12. Tratamento da qualidade

- Quando "Ignorar qualidade ruim" esta ativado (padrao):
  - Apenas `good=true` e plotado.
  - Pontos com `good=false` viram `null` no array `points`, gerando
    lacunas (`connectNulls: false`).
  - O card de resumo "Descartados" mostra a contagem.
- Quando esta desativado:
  - Valores numericos com qualidade ruim sao plotados.
  - O tooltip mostra a qualidade como `OK`, `Substituido`,
    `Questionavel` ou `Ruim` (mapeamento dos codigos `Good=0/1/2/3`
    do PI).
- Os dados retornados pela API nao sao modificados.

## 13. Exportacao CSV

- Botao "Baixar dados CSV" na area de cabecalho da pagina.
- Habilitado somente apos uma consulta com series retornadas.
- Nome do arquivo: `pi-analytics-data_<equipamento>_<YYYYMMDD>_<HHMMSS>.csv`.
- Formato longo, separador `;`, CRLF, BOM UTF-8.
- Colunas: `timestamp_utc`, `timestamp_local`, `tag_id`, `tag_name`,
  `display_name`, `equipment`, `section`, `variable_type`, `unit`,
  `value`, `good`, `questionable`, `substituted`.
- Escaping automatico de aspas (`"` -> `""`), separador e quebras de
  linha.
- Preserva valores textuais, booleanos e `null`.
- Exporta exatamente o resultado da consulta atual (sem nova chamada
  a API).

## 14. Exportacao da imagem

- Feature `saveAsImage` do ECharts.
- Nome sugerido: `pi-analytics-data-grafico-linha`.
- Conteudo: apenas o grafico (titulo, eixos, legenda, linhas).
- Sem credenciais no arquivo gerado (o ECharts embute o conteudo
  atual do canvas; o backend nunca expoe dados sensiveis).

## 15. Resultado dos testes do backend

- Comando: `pytest` (a partir de `backend/`, dentro do `.venv`).
- Total: 57 testes.
- Aprovados: 57.
- Falhos: 0.
- Ignorados: 0.

Novos testes da Fase 3:

- `tests/test_time_series_contract.py` (4):
  - `test_time_series_accepts_repeated_tag_ids`
  - `test_time_series_accepts_csv_tag_ids`
  - `test_time_series_max_count_limit_enforced`
  - `test_time_series_max_tags_enforced_via_query`

## 16. Resultado dos testes do frontend

- Comando: `npm test` (a partir de `frontend/`).
- Total: 53 testes.
- Aprovados: 53.
- Falhos: 0.
- Ignorados: 0.

Novos testes da Fase 3:

- `tests/visualization.test.ts` (19) - utilidades e CSV:
  - `period utilities` (5): preset, conversao UTC, round-trip
    `datetime-local`, validacao, presets.
  - `value formatters` (4): pt-BR, null, numeric detection, quality.
  - `chart data builder` (4): numeric vs nao numerico, qualidade ruim,
    y-axis, timestamps invalidos.
  - `CSV exporter` (4): header, escaping, BOM, filename.
- `tests/dataVisualization.test.tsx` (13) - pagina completa:
  - carregamento dos lookups;
  - filtro de secoes por equipamento;
  - bloqueio de tags invalidas/inativas;
  - cascata limpar tags;
  - bloqueio de consulta sem tag;
  - intervalo em `interpolated`;
  - construcao da requisicao (UTC ISO + `tag_ids=1&tag_ids=1`);
  - cancelamento da consulta anterior;
  - estado de erro;
  - resultado parcial;
  - CSV habilitado apos sucesso;
  - alerta de "PI nao configurado";
  - bloqueio de mais de 2 unidades.

## 17. Resultado do build

- Comando: `npm run build`.
- Resultado: `built in ~22s` sem erros de TypeScript.
- Bundle final: `dist/assets/index-Daph2MB-.js` (854.93 kB, gzip 278.22 kB)
  e `dist/assets/index-CmUEb4cu.css` (312.15 kB, gzip 45.87 kB).
- O warning sobre o tamanho do bundle e apenas uma recomendacao de
  code-splitting; o build foi concluido com sucesso.

## 18. Resultado da validacao em PI real

Nao foi possivel validar contra um PI Web API real no ambiente desta
POC. Toda a integracao foi exercitada com `FakePiDataProvider` e o
backend foi validado com `TestClient` injetando o provider via
`app.dependency_overrides`. A pendencia de validar contra um PI real
permanece como validacao manual recomendada.

## 19. Limitacoes conhecidas

- Apenas grafico de linha e suportado nesta fase.
- Nao ha correlacao, estatistica descritiva, CEP, alertas, dashboards
  ou autenticacao.
- O CSV usa `;` como separador. XLSX nao e gerado.
- Nao ha downsampling destrutivo. Series muito grandes podem ter
  performance inferior; a POC adota o `sampling: "lttb"` do proprio
  ECharts.
- Nao ha cache de WebId alem do que ja existe no banco.
- A validacao contra um PI real precisa ser feita em ambiente
  apropriado antes de promocao para producao.

## 20. Pendencias reais

- Validar a integracao contra um PI Web API real.
- Avaliar performance com milhoes de pontos (downsampling explicito
  ou servidor de tiles, se necessario).
- Considerar distribuicao do grafico por `dynamic import` para
  reduzir o bundle inicial.

## 21. Preparacao recomendada para a Fase 4

A estrutura entregue ja prepara os proximos passos:

- O `EChartsWrapper` aceita uma `option` arbitraria, o que facilita
  adicionar histogramas, boxplots, dispersao e barras. Cada novo
  tipo de grafico pode reusar a infraestrutura de loading, error,
  eixos por unidade e exportacao CSV/imagem.
- O servico `PiService` ja expoe os pontos normalizados via
  `TimeSeries`, com datas em UTC, qualidade e valor (numerico ou
  string). Isso serve de base para correlacao e estatistica
  descritiva sem alteracoes no backend.
- O `DataVisualizationPage` ja carrega `equipments`, `sections`,
  `variable_types` e `tags` em paralelo. Adicionar mais selecoes
  para tipos de analise (ex.: tags para correlacao) e trivial.
- O sistema de filtros em cascata pode ser reaproveitado para
  selecao de faixas de CEP e dashboards.
- O cache de WebId e o tratamento de re-resolucao ja estao
  implementados, o que ajuda no caminho para alertas.
