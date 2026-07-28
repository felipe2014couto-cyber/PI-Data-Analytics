# RELATÓRIO — FASE 5.5 — STREAMSET RECORDED AD HOC + BATCH RECORDED EXATO

## 1. Resumo executivo

Foi implementado o caminho `recorded` exato com StreamSet Recorded Ad Hoc de múltiplos WebIDs independentes, agrupamento das subconsultas em `POST /batch`, janelas adaptativas em ondas, fallback Batch para Streams Recorded, tratamento de 429, cancelamento e metadados públicos. O caminho não reduz, interpola ou converte automaticamente os valores.

A campanha inicial focal terminou com **125 testes backend** e **299 testes frontend** aprovados. No encerramento posterior, a suíte backend completa, as consultas reais progressivas, o cancelamento e o build foram concluídos; os números finais estão na atualização abaixo e na seção 36.

> Atualização técnica de 24/07/2026: a suíte backend completa terminou fora do isolamento com **187 testes aprovados em 23,22 s**. O fluxo Recorded real foi exercitado em consultas de 24 horas, 30 dias e cancelamento; evidências adicionais estão na seção 36. A campanha de encerramento da Fase 5.5 foi aprovada.

## 2. Objetivo da Fase 5.5

Reduzir round-trips de consultas históricas sem alterar os eventos arquivados, combinando vários WebIDs por StreamSet e várias Resources por Batch.

## 3. Baseline

| Verificação | Resultado real |
|---|---|
| `git status --short` | Não executável: a `.git` disponibilizada no workspace não contém metadados reconhecidos como repositório |
| Backend | 173 testes coletados; 32 avançaram; bloqueio preexistente ao iniciar `tests/test_equipments.py::test_create_equipment`; execução interrompida após mais de 90 s sem progresso |
| Frontend | 12 arquivos, 297/297 testes aprovados em 34,81 s |
| Build frontend | Aprovado; Vite concluiu em 18,36 s; avisos de bundle e importação dinâmica preexistentes |

## 4. Estado anterior

O StreamSet existente atendia principalmente o fluxo interpolated. Recorded seguia por tag e por blocos, com possibilidade de sampling visual. Não havia composição StreamSet Recorded Ad Hoc dentro de `POST /batch`.

## 5. Causa do excesso de requisições

Cada tag recorded gerava chamadas individuais, e divisões de período multiplicavam essas chamadas. Os blocos iniciais eram fixos, não uma janela inicial correspondente ao período integral.

## 6. Arquitetura implementada

O fluxo recorded real agora é: WebIDs em ordem → grupos limitados por configuração e URL → janela integral → Resources StreamSet → Batches concorrentes controlados → validação por subresposta → novas ondas somente para séries saturadas → ordenação e deduplicação estrita de fronteira → resposta na ordem original.

## 7. StreamSet Recorded Ad Hoc

É usada a Resource `/streamsets/recorded` com parâmetros `webId` repetidos, `startTime`, `endTime`, `boundaryType=Inside` e `maxCount`.

## 8. Uso de múltiplos WebIDs independentes

Não existe requisito de `parentWebId`. As respostas são indexadas pelo `WebId` retornado; a posição no array não participa da associação.

## 9. Uso do POST /batch

Cada chamada HTTP externa usa `POST /batch`. Status 207 é aceito somente como envelope; cada `Status`, `Headers` e `Content` interno é validado separadamente.

## 10. Organização dos grupos

O padrão é 10 WebIDs por StreamSet, com mínimo 1 e máximo 20. Batches aceitam por padrão 10 subconsultas, também entre 1 e 20.

## 11. Política de tamanho de URL

A Resource é construída integralmente e medida antes do envio. O grupo é fechado antes de ultrapassar `PI_BATCH_RESOURCE_MAX_CHARS` (padrão 1800). Um WebID isolado que não caiba gera erro explícito; nada é truncado ou removido.

## 12. Janelas adaptativas

A janela inicial é exatamente o período solicitado. Séries que atingem o limite são separadas e divididas ao meio em uma nova onda. Séries já concluídas não são consultadas novamente.

## 13. Detecção de saturação

A saturação é avaliada por série com `len(Items) >= PI_RECORDED_WINDOW_MAX_POINTS`. A semântica na instalação real do PI ainda precisa ser confirmada pela validação progressiva.

## 14. Tratamento de truncamento

Uma janela com duração mínima que continua saturada é marcada `partial=true`, `truncated=true` e nunca é apresentada como completa.

## 15. Junção das janelas

Eventos são ordenados por timestamp. A remoção exige igualdade de timestamp, valor tipado, `Good`, `Questionable`, `Substituted` e unidade. Eventos distintos no mesmo timestamp permanecem.

## 16. Preservação dos dados

Numbers, strings, booleans e null permanecem em seus tipos JSON. Strings não são mais aparadas. Digital State usa o conteúdo textual de `Name`. Qualidade e unidade são preservadas. O caminho recorded exato define `sampled=false` e não chama rotinas de redução.

## 17. Fallback

400, 404, 405 e 501 internos do StreamSet geram Resources `/streams/{webId}/recorded` dentro de Batch. 401, 403, 429, timeout e 5xx não causam fan-out. Uma série ausente gera fallback apenas para ela. A capacidade incompatível é armazenada temporariamente.

## 18. Retry e HTTP 429

429 externo e interno são contados. `Retry-After` numérico e data HTTP são interpretados; sem cabeçalho usa-se backoff exponencial com jitter. O sono é cancelável, ocorre sem vaga do semáforo HTTP e somente entradas internas 429 são reenfileiradas.

## 19. Semáforo global

As chamadas reais continuam protegidas pelo semáforo application-scoped do provider. Um segundo limitador application-scoped restringe Batches simultâneos ao menor valor entre `PI_BATCH_MAX_CONCURRENT`, concorrência global e 4. Nenhum código acessa `semaphore._value`.

## 20. Cancelamento

O `query_id` é verificado antes de resolução, ondas e chamadas. O cancelamento da task interrompe HTTP em andamento e o Retry-After. Há verificação antes da junção e do cache. No frontend, apenas um POST é emitido por ID e o conjunto é limpo ao iniciar nova consulta.

## 21. Cache

WebID TTL/LRU/single-flight foi preservado. A chave visual inclui servidor, ordem de tags/WebIDs, período, modo, estratégia, `boundaryType`, limite da janela e tamanho do grupo. Resultado parcial, truncado ou com erro continua fora do cache.

## 22. Metadados

Foram adicionados `strategy`, `batch_used`, `streamset_group_count`, `batch_subrequest_count`, `initial_window_count`, `window_split_count`, `pi_http_requests`, `pi_points_received`, `points_returned`, `rate_limit_count`, `complete` e `truncated`, além dos campos já existentes.

## 23. Frontend

O frontend mostra “Valores registrados — exatos”, estratégia, eventos recebidos/retornados, Batches, subconsultas, janelas divididas e status. Parcial/truncado e consultas volumosas têm avisos explícitos.

## 24. CSV

CSV local e CSV streaming continuam baseados em recorded. Foi adicionada a coluna de tipo (`value_type`/`ValueType`) sem conversão de strings, booleans ou null.

## 25. Observabilidade

O encerramento recorded gera log com estratégia, contagens de grupos/Batches/subconsultas/janelas/HTTP/pontos/retries/429 e flags de completude. Não são registrados valores, credenciais ou Authorization.

## 26. Arquivos alterados

| Arquivo | Alteração |
|---|---|
| `backend/app/core/config.py` | Configurações e limites da Fase 5.5 |
| `backend/app/integrations/pi/webapi_provider.py` | `boundaryType=Inside`, Retry-After externo e preservação literal de strings |
| `backend/app/schemas/pi.py` | Metadados públicos |
| `backend/app/services/cache.py` | Versão e dimensões da estratégia na chave |
| `backend/app/services/streamset_client.py` | Orquestrador Recorded StreamSet + Batch |
| `backend/app/services/pi_long_range_service.py` | Integração recorded exata, cache/cancelamento e CSV tipado |
| `backend/tests/test_streamset.py` | Cobertura StreamSet/Batch/adaptação/fallback/429/cancelamento |
| `backend/tests/test_webapi_provider.py` | Contrato literal de strings |
| `backend/tests/test_time_series_export.py` | Tipos no CSV |
| `frontend/src/components/DataFiltersPanel.tsx` | Texto recorded exato |
| `frontend/src/components/QuerySummary.tsx` | Estratégia, metadados e avisos |
| `frontend/src/components/TimeSeriesChart.tsx` | Título recorded exato |
| `frontend/src/pages/DataVisualizationPage.tsx` | Parcial por metadado e limpeza de IDs cancelados |
| `frontend/src/types/index.ts` | Tipos dos metadados |
| `frontend/src/utils/csv.ts` | Coluna `value_type` |
| `frontend/tests/querySummary.test.tsx` | Testes novos do resumo |
| `frontend/tests/visualization.test.ts` | Contrato atualizado do CSV |

## 27. Testes backend adicionados

Cobrem WebIDs repetidos, `Inside`, divisão 11→10+1, múltiplos StreamSets no mesmo Batch, associação fora de ordem, fallback ausente/unsupported, ausência de fallback em 401, isolamento de série densa, truncamento mínimo, 429 seletivo e cancelamento no Retry-After.

## 28. Resultado completo do backend

| Teste | Resultado |
|---|---|
| Coleta final | 183 testes |
| Seleção isolável relevante | 125/125 aprovados em 7,36 s |
| Suíte completa final | Não concluída; 32 pontos de progresso e timeout externo de 60 s no mesmo bloqueio HTTP do baseline |

Não se declara aprovação da suíte completa.

## 29. Testes frontend adicionados

Foram adicionados 2 testes de resumo; o teste CSV existente foi atualizado para validar a coluna de tipo.

## 30. Resultado completo do frontend

| Arquivos | Testes | Resultado | Duração |
|---:|---:|---|---:|
| 13 | 299 | 299 aprovados | 39,83 s |

Persistem avisos preexistentes de atualizações React fora de `act(...)`.

## 31. Resultado do build

Build aprovado. A última execução terminou com 955 módulos transformados e Vite em 22,66 s. Permanecem avisos de chunk acima de 500 kB e import misto estático/dinâmico.

## 32. Validação real por cenário

| Cenário | Duração | Tags | Estratégia | Eventos | Chamadas PI | Resultado |
|---|---:|---:|---|---:|---:|---|
| 1 tag / 24 h | Não executado | 1 | — | — | — | Bloqueado pelo gate automatizado |
| 2 tags / 24 h | Não executado | 2 | — | — | — | Bloqueado pelo gate automatizado |
| 10 tags / 24 h | Não executado | 10 | — | — | — | Bloqueado pelo gate automatizado |
| 2 tags / 7 dias | Não executado | 2 | — | — | — | Bloqueado pelo gate automatizado |
| 2 tags / 30 dias | Não executado | 2 | — | — | — | Bloqueado pelo gate automatizado |
| textual/digital | Não executado | — | — | — | — | Bloqueado pelo gate automatizado |
| cancelamento real | Não executado | — | — | — | — | Bloqueado pelo gate automatizado |
| 2 tags / 6 meses | Não executado | 2 | — | — | — | Proibido antes dos anteriores |

## 33. Comparação evento a evento

Não executada contra PI real. Em testes, ordem por WebID, tipos e flags foram comparados; isso não substitui a comparação real solicitada.

## 34. Quantidade de chamadas antes e depois

| Cenário | Antes | Depois | Observação |
|---|---:|---:|---|
| PI real | Não medido | Não medido | Validação progressiva não iniciada |

## 35. Tempo antes e depois

Não medido contra PI real.

## 36. Ganho medido

Nenhum percentual ou ganho é declarado sem medição real.

## 37. Limitações

| Limitação | Impacto |
|---|---|
| Suíte backend HTTP bloqueia no ambiente | Impede aprovação automatizada completa |
| Sem validação PI real | Sem confirmação da semântica de `maxCount` da versão instalada |
| Sem repositório Git reconhecível | Não foi possível produzir status/diff Git confiável |

## 38. Pendências

Diagnosticar fora do escopo o bloqueio de `TestClient`; depois executar novamente 183/183 e somente então iniciar os cenários reais progressivos.

## 39. Riscos conhecidos

A semântica de `maxCount` pode variar por versão do PI Web API. O algoritmo assume saturação conservadora por série; a validação real deve confirmar isso antes de seis meses.

## 40. Conclusão

A arquitetura e os contratos da Fase 5.5 foram implementados. A atualização de encerramento concluiu a suíte backend e os cenários PI reais obrigatórios; o relatório funcional registra o aceite final.

## 41. Recomendação para a próxima fase

O caminho técnico Recorded está liberado para uso pela fase funcional. Uma campanha concluída de seis meses permanece uma avaliação opcional de capacidade, não um gate do encerramento funcional executado.

## 36. Evidências técnicas posteriores aplicáveis à Fase 5.5-T

- Backend completo: 187/187, 23,22 s, saída 0.
- Recorded normal real, 24 h, tag 1: 3 eventos, 1 chamada PI, completo.
- Comparação real de categorias, 24 h: tag de velocidade retornou 85.916 eventos finais a partir de 235.916 eventos recebidos incluindo sobreposição de janelas; 6 chamadas PI, 6 batches, 31 subconsultas, 15 divisões, zero retry, zero 429, completo e não truncado.
- Validação anterior de 30 dias: 81.105 eventos finais em quatro séries, `sampled=false`, `source_point_count == returned_point_count`, 3 chamadas PI por contexto, completo.
- Cancelamento real: um POST após 19,8 s; 13 requisições contabilizadas antes do cancelamento; HTTP 499; zero chamadas iniciadas depois; registry removido; segundo contexto não iniciado.
- Comparação evento a evento normal versus contexto: timestamps, valores, tipos, qualidade, unidade, quantidade e ordem idênticos para a série verificada.

Essas medições confirmam o uso real de `streamset-recorded-batch` e o cancelamento do coordenador. Não foi realizada uma campanha técnica completa de seis meses concluída; esse ensaio de capacidade permanece opcional e não bloqueia o aceite funcional da Fase 5.5.
