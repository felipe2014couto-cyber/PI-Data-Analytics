# RELATÓRIO — FASE 5.5 FUNCIONAL — COMPARAÇÕES

Data: 24/07/2026  
Status: **APROVADA**

> Encerramento em 24/07/2026: backend, frontend e build padrão concluídos; validações reais, comparação evento a evento, cancelamento e CSV executados; identidade `series_instance_id` aplicada também a eixos, filtros e métricas.

## 1. Resumo executivo

Foi implementado um modo opcional para comparar exatamente dois contextos A/B por período, equipamento ou categoria (`VariableType`). O modo normal permanece como padrão. O backend coordena os contextos com um único `query_id` e reutiliza o serviço de longa duração, StreamSet Recorded + Batch, registry, semáforo, retry e fallback existentes. A validação real de períodos chegou a duas janelas de 30 dias e 81.105 eventos retornados sem downsampling.

A fase foi aprovada após a execução dos cenários reais obrigatórios, comparação objetiva com a consulta normal, cancelamento real, CSV real, build minificado e migração integral da identidade visual A/B.

## 2. Objetivo

Permitir comparação A/B sem criar outro cliente PI, cache, registry, semáforo, entidade de banco ou motor gráfico, preservando tipos, eventos, qualidade, unidades e timestamps.

## 3. Estado anterior

Existia uma consulta única com filtros, eixos, gráficos, métricas, CSV, cancelamento e fluxo Recorded otimizado. O relatório técnico anterior registrava aprovação parcial; o usuário autorizou explicitamente o início desta fase em 24/07/2026. `git status --short` e `git diff --stat` não puderam operar porque o diretório `.git` disponível não constitui um repositório Git funcional.

## 4. Arquitetura implementada

- `POST /api/time-series/comparison` recebe dois contextos em ordem A/B.
- Cada contexto usa `PiLongRangeService.fetch_time_series`.
- Um único `query_id` é registrado e removido no `QueryRegistry` existente.
- A resposta mantém os contextos separados e inclui metadados consolidados.
- Resultado parcial identifica o contexto falho sem expor texto interno da exceção.

## 5. Comparação por período

O Contexto A usa as tags e datas principais. O Contexto B reutiliza as mesmas tags e aceita datas próprias, inclusive duração diferente. O timestamp original não é alterado; cada ponto recebe apenas `elapsed_ms` derivado para apresentação.

## 6. Comparação por equipamento

O Contexto B permite escolher equipamento e tags manualmente. A filtragem usa os cadastros existentes e não cria equivalências, relacionamentos ou registros. O período é compartilhado. A montagem genérica A/B foi validada automaticamente e o cenário real RB3/RB1 foi concluído.

## 7. Comparação por categoria

`VariableType` foi reutilizado como categoria. O Contexto B permite escolher a categoria e confirmar manualmente as tags. Não foi criada tabela ou migration. A validação real Temperatura/Velocidade foi concluída, inclusive com unidades distintas.

## 8. Identidade das séries

O backend gera `series_instance_id = contexto + tag_id + início + fim`, sem valores ou credenciais. No frontend, essa identidade é usada em gráficos, ordem, eixos, scatter, filtros e métricas; `tag_id` permanece o ID público real e do CSV. A validação real confirmou identificadores A/B distintos, inclusive para a mesma tag.

## 9. Alinhamento temporal

Em comparação por períodos, o gráfico usa `elapsed_ms` no eixo X. Contexto B usa traço tracejado. O tooltip mostra tempo decorrido e timestamp original. Não há merge por timestamp, preenchimento de lacunas ou criação de pontos. Séries menores terminam no seu próprio fim.

## 10. Preservação dos dados

Os schemas preservam `number`, `string`, `boolean` e `null`, além de `Good`, `Questionable`, `Substituted`, unidade, ordem dos pontos e timestamp UTC original. A comparação força `preserve_all_points=True`, ignora cache visual potencialmente reduzido e não grava resultado no cache. Recorded continua Recorded; Interpolated só é enviado quando escolhido pelo usuário.

## 11. Integração com StreamSet + Batch

Não houve reimplementação. A validação real usou `streamset-recorded-batch`; em 30 dias foram 3 requisições PI por contexto, 3 batches, 9 subconsultas e 4 divisões de janela por contexto.

## 12. Cancelamento

O registry associa o mesmo `query_id` à operação coordenadora. Cancelar a tarefa interrompe o contexto ativo e impede o início do próximo. `CancelledError` vira `QueryCancelledError`, o registro é removido em `finally` e nenhum resultado é armazenado. Testes automatizado e real: aprovados; no teste real não houve chamadas iniciadas após o cancelamento.

## 13. Cache

O cache existente não foi duplicado. Para garantir ausência de downsampling e impedir gravação parcial, a comparação executa com `refresh=True` e `store_cache=False`. A decisão é intencional: comparações exatas não reutilizam nem armazenam resultado visual reduzido ou parcial.

## 14. Frontend

Foi adicionada a seção “Comparação” com estado inicial “Desativada”, Contextos A/B e campos condicionais. Alterações locais não chamam a API; somente “Consultar” chama `compare`. O fluxo normal continua chamando o endpoint anterior e mantém o payload existente.

## 15. Gráficos

O ECharts existente foi reutilizado. Comparação por período usa eixo decorrido, tooltip original e estilo tracejado no B. O sampling visual `lttb` fica desativado para séries de comparação.

## 16. Filtros

Os filtros continuam locais e usam `series_instance_id`, inclusive quando A/B possuem o mesmo `tag_id`. Não geram nova consulta. A independência A/B possui cobertura automatizada dedicada.

## 17. Eixos

Os eixos existentes continuam preservando unidades. Não foi implementada conversão automática. Instâncias A/B podem possuir atribuições distintas por `series_instance_id`.

## 18. Parâmetros

Parâmetros visuais e troca de visualização permanecem locais. Nenhuma configuração foi persistida no banco.

## 19. CSV

No modo comparação são adicionados `comparison_type`, `context_id`, `context_label`, `series_instance_id`, `category` e `elapsed_ms`. O timestamp e `tag_id` reais são exportados. No modo normal, o cabeçalho anterior permanece inalterado. Validações automatizada e real: aprovadas.

## 20. Metadados

Incluem tipo, contagem de contextos/instâncias, eventos recebidos/retornados por contexto, duração por contexto e total, estratégia, cache hit, requisições PI, `query_id`, `complete` e `partial`.

## 21. Observabilidade

Logs registram início e fim de contexto, `query_id`, tipo, contexto, quantidade de tags, período, estratégia, duração, contagens, cache e completude, além de cancelamento. Não registram valores, Authorization, cookies ou `.env`.

## 22. Arquivos alterados

- `backend/app/api/time_series.py`
- `backend/app/schemas/pi.py`
- `backend/app/services/pi_long_range_service.py`
- `backend/tests/test_time_series_comparison.py`
- `frontend/src/api/http.ts`
- `frontend/src/api/index.ts`
- `frontend/src/components/ComparisonPanel.tsx`
- `frontend/src/components/AdvancedFiltersPanel.tsx`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/components/MetricConfigurationPanel.tsx`
- `frontend/src/components/MetricResults.tsx`
- `frontend/src/components/SeriesAssignmentsPanel.tsx`
- `frontend/src/components/TimeSeriesChart.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/src/types/index.ts`
- `frontend/src/utils/chartData.ts`
- `frontend/src/utils/csv.ts`
- `frontend/src/utils/dataFilters.ts`
- `frontend/src/utils/analysisMetrics.ts`
- `frontend/src/utils/seriesAssignments.ts`
- `frontend/tests/analysisMetrics.test.ts`
- `frontend/tests/comparisonFunctional.test.ts`
- `frontend/tests/dataVisualization.test.tsx`
- `frontend/tests/mocks/api.ts`
- `RELATORIO_FASE_5_5_COMPARACOES.md`

Nenhuma migration ou dependência foi adicionada.

## 23. Testes backend

- Suíte completa, executada em lotes fora do sandbox devido ao bloqueio conhecido de TestClient/AnyIO: **187 aprovados, 0 falhos, 0 ignorados**.
- Lotes: 32 + 7 + 1 + 73 + 74 testes.
- Após a proteção final contra downsampling e logs: foco `comparison + long_range + streamset`: **43 aprovados em 1,33 s**.
- Testes novos de comparação: **4 aprovados**.
- Warnings existentes: depreciação do atalho `httpx(app=...)` e usos de `datetime.utcnow()`.

## 24. Testes frontend

- Suíte integral final: **305 aprovados, 14 arquivos, 0 falhos, 0 ignorados**.
- Foco funcional do gráfico/CSV: 2 aprovados.
- A tela confirmou que mudar a configuração não chama API e “Consultar” chama `compare` exatamente uma vez.
- Warnings existentes de testes React sem `act(...)` permanecem.

## 25. Build

- `npm run build`: **aprovado**, saída 0; TypeScript e bundle Vite minificado concluídos, 956 módulos, 15,03 s de build Vite.
- Artefato JS final: 975,10 kB; gzip 311,67 kB. O aviso de chunk acima de 500 kB é não bloqueante.

## 26. Validações reais

Ambiente PI: conectado, servidor `PIMS`; saúde respondeu HTTP 200 e 153 ms.

| Cenário | Resultado | Estratégia | Eventos retornados | Duração HTTP | Estado |
|---|---:|---|---:|---:|---|
| Períodos, 1 tag, 10 min A/B | 0 / 0 | streamset-recorded-batch | 0 | 0,364 s | completo, sem dados na janela |
| Períodos, 2 tags, 24 h A/B | 187 / 128 | streamset-recorded-batch | 315 | 0,131 s | completo |
| Períodos, 2 tags, 30 dias A/B | 42.427 / 38.678 | streamset-recorded-batch | 81.105 | 17,484 s HTTP; 16.275 ms backend | completo |

Na janela de 30 dias: 161.105 eventos brutos recebidos antes da deduplicação estrita de fronteiras; quatro séries com `source_point_count == returned_point_count`; `sampled=false`; zero retry; zero 429; nenhum truncamento.

Além da carga de 30 dias, foram concluídos: consulta normal de referência, comparação evento a evento, mesma tag em períodos, equipamentos, categorias/unidades distintas, string/estado, cancelamento e CSV reais. Os resultados detalhados estão na seção 33.

## 27. Comparação evento a evento

Na resposta real de 30 dias foi confirmado, dentro de cada série, que todos os eventos retornados foram preservados após a deduplicação de fronteira do fluxo técnico: `source_point_count == returned_point_count`, ordem temporal monotônica, timestamp original presente e `sampled=false`. A comparação independente da tag 1 confirmou igualdade integral de três eventos entre consulta normal e Contexto A.

## 28. Limitações

- Comparações não usam cache visual para evitar reutilização de resultado reduzido.
- Contextos são processados sequencialmente; o cancelamento lógico é único, mas não há duas requisições de contexto simultâneas.
- Contextos de equipamento/categoria usam seleção manual, porém a rotulagem pública atual é genérica (“Contexto A/B”) além dos metadados próprios da série.
- Cobertura automatizada não materializa individualmente todos os 30 itens da matriz solicitada.

## 29. Pendências

Nenhuma pendência obrigatória da Fase 5.5. Otimizações futuras de bundle ou de uma política de cache exato A/B podem ser avaliadas sem bloquear o aceite funcional.

## 30. Riscos conhecidos

- Volume exato pode ser elevado: 81 mil eventos em dois contextos de 30 dias já produzem resposta significativa.
- Desabilitar cache em comparação aumenta carga e latência.
- O bundle frontend permanece grande e merece code splitting em evolução de desempenho, sem impacto no aceite funcional.

## 31. Conclusão

A funcionalidade está implementada e demonstrou consulta real exata por períodos, equipamento e categoria, sem coerção, interpolação automática ou downsampling. Todos os gates obrigatórios foram concluídos. Status: **APROVADA**.

## 32. Recomendação para a Fase 5.6

A Fase 5.5 está encerrada e libera o início da Fase 5.6 em solicitação própria, preservando a separação de escopo.

## 33. Encerramento final executado

### Correções pontuais

- Removida a alteração interna de `tag_id` para valores negativos no Contexto B.
- Ordem, eixo, scatter, chaves React e mapas do gráfico passaram a preferir `series_instance_id`.
- Filtros locais passaram a aceitar `seriesInstanceId` e distinguir a mesma tag em A/B.
- O painel de filtros passou a emitir a identidade da instância selecionada.
- Compatibilidade do modo normal por `tag_id` foi preservada.

### Automação final

| Gate | Resultado |
|---|---|
| Backend `pytest -q` | **187 aprovados**, 0 falhos, 0 ignorados, 23,22 s, saída 0 |
| Frontend `npm test -- --run` | **305 aprovados**, 14 arquivos, 0 falhos, 0 ignorados, 22,58 s, saída 0 |
| Build `npm run build` | **Aprovado**, 956 módulos, 15,03 s de build Vite, saída 0 |

Warnings: 80 warnings backend de depreciação (`httpx app shortcut` e `datetime.utcnow`); frontend mantém warnings React `act(...)`, importação estática/dinâmica do módulo API e chunk minificado de 973,59 kB.

### Comparação evento a evento

Consulta normal e Contexto A usaram tag 1, período `2026-07-16T14:00:00Z` a `2026-07-17T14:00:00Z`, Recorded e resolução automática. Resultado objetivo: 3 eventos em cada resposta; tag, nome, unidade, timestamps, valores, tipos JSON e flags `Good/Questionable/Substituted` idênticos; mesma ordem cronológica; nenhum evento criado, removido ou deslocado.

### Validações reais finais

| Cenário | Contextos | Retornados A/B | PI A/B | Duração HTTP | Resultado |
|---|---|---:|---:|---:|---|
| Normal de referência | tag 1 | 3 | 1 | 0,160 s | completo |
| Mesma tag, períodos | tag 1 / tag 1 | 3 / 3 | 1 / 1 | 0,078 s | completo |
| Equipamentos | RB3 tag 1 / RB1 tag 5 | 3 / 6 | 1 / 1 | 0,058 s | completo |
| Categorias e unidades | Temperatura ºC / Velocidade RPM | 3 / 85.916 | 1 / 6 | 12,538 s | completo |
| Textual/digital | Numérica / Tipo de aço | 3 / 12 | 1 / 1 | 0,100 s | completo; `float` e `str` preservados |

Todos utilizaram `streamset-recorded-batch`, `cache_hit=false` e retornaram identidades A/B distintas.

### Cancelamento real

Consulta de dois contextos de seis meses, duas tags por contexto. Um único POST de cancelamento foi enviado após 19,8 s. Havia 13 requisições PI contabilizadas antes do cancelamento. A consulta respondeu HTTP 499, o Contexto B não iniciou, `comparison_cancelled` foi registrado e o `query_id` foi removido do registry.

```text
Chamadas iniciadas após o cancelamento: 0
```

Não houve retry/backoff posterior nem armazenamento de resposta.

### CSV real

Foi gerado `/tmp/f55_comparison_real.csv` a partir da resposta real textual: 15 linhas de dados, Contextos A/B, colunas de comparação, `series_instance_id`, tag, equipamento, seção, categoria, timestamp, valor/tipo, qualidade e unidade. `P420A` permaneceu `string`; string vazia permaneceu string; não há `undefined` ou `NaN`; eventos repetidos em timestamps distintos foram mantidos.

### Fechamento da identidade e status

A identidade negativa foi eliminada. Eixos, filtros, ordem, scatter, configuração de métricas e cards de resultados agora priorizam `series_instance_id`, com compatibilidade retroativa por `tag_id` no modo normal. Um teste dedicado calcula corretamente uma métrica pareada entre `A-7` e `B-7`, ambas com a tag real 7. Status final: **APROVADA**.
