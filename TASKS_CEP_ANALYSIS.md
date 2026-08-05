# `/tasks` — Capacidade de análise CEP

## Fase 1: Fundações

### T1.1 — Configurações CEP em `config.py`

**Objetivo:** Adicionar as 6 configurações CEP ao Settings existente.

**Arquivo:** `backend/app/core/config.py`

**Alteração:** Inserir após o último campo PI existente:

```python
# CEP Analysis
pi_cep_max_variables: int = Field(default=24)
pi_cep_result_ttl_seconds: int = Field(default=3600)
pi_cep_operation_timeout_seconds: int = Field(default=1800)
pi_cep_cleanup_interval_seconds: int = Field(default=60)
pi_cep_recorded_max_points_per_tag: int = Field(default=10000)
pi_cep_recorded_max_total_points: int = Field(default=100000)
```

**Dependências:** Nenhuma

**Critérios de conclusão:**
- [ ] 6 campos adicionados ao `Settings`
- [ ] Defaults idênticos ao plano
- [ ] `settings.pi_cep_*` acessível em runtime
- [ ] Testes existentes continuam passando

**Validação:** `cd backend && python -c "from app.core.config import settings; print(settings.pi_cep_max_variables)"`

---

### T1.2 — CepQueryStore

**Objetivo:** Implementar o armazenamento in-memory de operações CEP.

**Arquivo:** `backend/app/services/cep_query_store.py` (novo)

**Dependências:** T1.1, T2.1 (usa `CepAnalysisRequest` e `CepAnalysisResult`)

**Componentes:**
- `CepQueryEntry` dataclass (query_id, query_status, created_at, terminal_at, started_at, request, result, ready_event)
- `CancelResult` enum (CANCELLED, ALREADY_CANCELLED, ALREADY_TERMINAL, NOT_FOUND)
- `CleanupResult` dataclass (expired, timed_out)
- `CepQueryStore` classe com:
  - `register(query_id, request) → CepQueryEntry`
  - `set_running(query_id) → bool`
  - `set_result(query_id, result, status) → bool`
  - `set_cancelled(query_id) → CancelResult`
  - `get(query_id) → Optional[CepQueryEntry]`
  - `apply_timeout(query_id) → Optional[CepQueryEntry]`
  - `get_or_remove_expired(query_id) → Optional[CepQueryEntry]`
  - `remove_unaccepted(query_id) → None`
  - `cleanup_expired() → CleanupResult`
  - `_build_timeout_result(entry) → CepAnalysisResult`

**Invariantes:**
- Lock asyncio protege todas as operações
- Transição terminal única (não sobrescreve completed/failed/cancelled)
- `set_cancelled` atômico
- `apply_timeout` atômico
- `get_or_remove_expired` atômico (consulta + remove sob mesmo lock)
- `remove_unaccepted` atômico
- Monotonic para deadlines internos, datetime UTC para resposta pública

**Critérios de conclusão:**
- [ ] Todas as operações implementadas
- [ ] Lock protege todas as mutações
- [ ] Transições corretas (pending→running→completed/failed, pending/running→cancelled)
- [ ] Timeout aplica failed com diagnóstico
- [ ] TTL remove entradas terminais expiradas
- [ ] `remove_unaccepted` remove entrada pendente
- [ ] `get_or_remove_expired` é atômico

**Validação:** T1.4

---

### T1.3 — CepPiAdapter

**Objetivo:** Implementar conversão PiValue → CepSample.

**Arquivo:** `backend/app/services/cep_pi_adapter.py` (novo)

**Dependências:** Nenhuma (usa tipos existentes)

**Componentes:**
- `pi_value_to_cep_sample(pi_value: PiValue) → CepSample`

**Regras de conversão:**
| PiValue | CepSample |
|---|---|
| float finito | CepSample(ts, float(v), Q) |
| int finito | CepSample(ts, float(v), Q) |
| bool | Rejeitado |
| None | CepSample(ts, None, Q) |
| NaN, Inf | CepSample(ts, None, Q) |
| -999.0 | CepSample(ts, -999.0, Q) |
| str | CepSample(ts, None, Q) |
| dict | CepSample(ts, None, Q) |

**Quality flags:** Preservar good, questionable, substituted.

**Critérios de conclusão:**
- [ ] Todos os tipos de PiValue tratados
- [ ] Bool rejeitado explicitamente
- [ ] -999.0 preservado
- [ ] Quality flags preservadas

**Validação:** T1.5

---

### T1.4 — Testes do CepQueryStore

**Objetivo:** Testar transições, TTL, timeout, limpeza, concorrência.

**Arquivo:** `backend/tests/test_cep_query_store.py` (novo)

**Dependências:** T1.2

**Cenários (conforme matriz de rastreabilidade):**
1. register cria entrada em pending
2. set_running transiciona pending→running
3. set_running recusa estado terminal
4. set_result transiciona para completed/failed
5. set_result não sobrescreve terminal
6. set_cancelled transiciona pending/running→cancelled
7. set_cancelled retorna ALREADY_CANCELLED para cancelled
8. set_cancelled retorna ALREADY_TERMINAL para completed/failed
9. set_cancelled retorna NOT_FOUND para inexistente
10. apply_timeout aplica failed quando deadline vencido
11. apply_timeout não aplica quando não expirado
12. apply_timeout não aplica para estado terminal
13. get_or_remove_expired remove terminal expirado
14. get_or_remove_expired mantém terminal válido
15. remove_unaccepted remove entrada pendente
16. cleanup_expired aplica timeout e remove expirados
17. Concorrência: múltiplas operações simultâneas

**Critérios de conclusão:**
- [ ] Todos os cenários passam
- [ ] Nenhum race condition detectado

---

### T1.5 — Testes do CepPiAdapter

**Objetivo:** Testar conversão e casos inválidos.

**Arquivo:** `backend/tests/test_cep_pi_adapter.py` (novo)

**Dependências:** T1.3

**Cenários:**
1. float finito → CepSample com valor correto
2. int finito → CepSample com float
3. bool → rejeitado
4. None → CepSample com value=None
5. NaN → CepSample com value=None
6. Inf → CepSample com value=None
7. -999.0 → preservado
8. str → CepSample com value=None
9. dict → CepSample com value=None
10. Quality flags preservadas (good, questionable, substituted)

**Critérios de conclusão:**
- [ ] Todos os cenários passam
- [ ] Comportamento determinístico

---

## Fase 2: Schemas

### T2.1 — Schemas Pydantic

**Objetivo:** Criar todos os schemas de request/response.

**Arquivo:** `backend/app/schemas/cep_analysis.py` (novo)

**Dependências:** Nenhuma

**Schemas:**
- `CepAnalysisRequest` (start_time, end_time, equipment_id, section_id, variable_ids, include_recorded)
- `CepAnalysisAccepted` (query_id, query_status, message)
- `CepQueryPending` (query_id, query_status)
- `CepQueryRunning` (query_id, query_status, started_at)
- `CepQueryCancelled` (query_id, query_status, message)
- `CepAnalysisResult` (query_id, query_status, summary, variables, diagnostics, recorded_series, metadata)
- `CepAnalysisSummary` (analysis_status, overall_pct, total_variables, conformant_variables, non_conformant_variables, no_data_variables, failed_variables, period_start, period_end)
- `CepVariableResult` (variable_id, code, name, equipment_id, section_id, variable_type_id, conformity_pct, total_points, conformant, non_conformant, no_data, status)
- `CepDiagnostic` (tag_id, tag_name, variable_ids, error_code, message)
- `CepRecordedSeries` (tag_id, tag_name, variable_ids, points, truncated, source_point_count)
- `CepRecordedPoint` (timestamp, value, good, questionable, substituted)
- `CepAnalysisMetadata` (pi_request_count, pi_points_received, points_returned, webid_cache_hits, webid_cache_misses, duration_ms, tags_processed, tags_failed, webid_resolved, recorded_total_point_limit, recorded_returned_point_count, recorded_total_limit_reached, recorded_tags_not_acquired)
- `CepQueryResponse` (Union dos 4 modelos de resposta)
- `MaterializedAnalysisData`, `MaterializedVariable`, `MaterializedTag` (dataclasses)

**Validações em CepAnalysisRequest (apenas estruturais — 422):**
- `start_time` e `end_time` exigem timezone explícito (rejeitar naive com 422)
- Body incompatível com schema → 422 (Pydantic)

**Validações semânticas no endpoint (400):**
- `start_time >= end_time` → `TimeRangeInvalidError` (400)
- `(end_time - start_time) > pi_query_max_period_days` → `TimeRangeInvalidError` (400)

**Validações semânticas no endpoint (422):**
- `len(selected_distinct_variables) > pi_cep_max_variables` → `ValidationError` (422)
- Filtros sem variável ativa → `ValidationError` (422)

Não implementar `start_time < end_time` e duração máxima como validators Pydantic que impeçam o endpoint de retornar os códigos aprovados.

**Critérios de conclusão:**
- [ ] Todos os schemas definidos
- [ ] Validações de timezone implementadas (422)
- [ ] Validações semânticas documentadas para o endpoint (400/422)
- [ ] `Field(default_factory=list)` para listas vazias
- [ ] `Optional[float] = None` para overall_pct e conformity_pct
- [ ] `source_point_count: Optional[int] = None`

**Validação:** `cd backend && python -c "from app.schemas.cep_analysis import CepAnalysisRequest; print('OK')"`

---

## Fase 3: Orquestrador

### T3.1 — CepAnalysisService

**Objetivo:** Implementar o orquestrador assíncrono da análise CEP.

**Arquivo:** `backend/app/services/cep_analysis_service.py` (novo)

**Dependências:** T1.2, T1.3, T2.1

**Componentes:**
- `CepAnalysisService.__init__(provider: PiDataProvider)`
- `CepAnalysisService.run_analysis(query_id, materialized_data, store, registry)`
- `_deduplicate_tags(variables) → List[MaterializedTag]`
- `_resolve_web_ids(unique_tags) → List[str]`
- `_fetch_interpolated(web_ids, request) → Dict`
- `_fetch_recorded(unique_tags, request, tag_variable_map) → Tuple[List, Metadata]`
- `_calculate_compliance(variables, interpolated_data) → List[VariableResult]`
- `_build_result(...) → CepAnalysisResult`
- `_build_error_result(query_id, exc) → CepAnalysisResult`
- `_determine_status(variable_results) → str`

**Fluxo (conforme §9.3 do plano):**
1. Aguardar ready_event
2. set_running (recusa se terminal)
3. Deduplicar tags
4. Resolver WebIds
5. Adquirir Interpolated 5m (fetch_streamset_batch)
6. Calcular conformidade (cep_calculator)
7. Se include_recorded: adquirir Recorded (get_recorded_values regressivo)
8. Montar resultado
9. Transição para completed/failed

**Tratamento de erros:**
- CancelledError: preservar failed, set_cancelled se não terminal
- Exception: set_result com failed
- finally: registry.unregister(query_id) incondicional

**Regras Recorded (conforme §9.6 do plano):**
- Nenhuma chamada Recorded quando `include_recorded=false`
- Tags únicas ordenadas lexicograficamente
- Consulta regressiva: `start_time=request.end_time`, `end_time=request.start_time`
- Solicitação de `budget + 1` pontos
- Preservação dos pontos mais recentes por timestamp
- Reordenação crescente somente para a resposta
- Ponto técnico adicional fora da resposta e dos contadores públicos
- Separação entre truncamento individual e agregado usando indicadores derivados dos limites:
  ```python
  individual_bound = individual_limit <= aggregate_remaining
  aggregate_bound = aggregate_remaining <= individual_limit
  ```
  - No empate (`individual_limit == aggregate_remaining`): ambos `individual_bound` e `aggregate_bound` são `true`
  - Com ponto adicional: ambos truncamentos são confirmados
  - Sem ponto adicional: nenhum truncamento é confirmado
- `recorded_total_limit_reached` somente com impacto agregado confirmado (`aggregate_bound` e ponto adicional)
- Truncamento exclusivamente individual (`individual_bound` e não `aggregate_bound`) mantém flag agregado em `false`
- `source_point_count=None` quando truncado
- `source_point_count` exato quando completo
- Diagnósticos com identificação real (tag_id, tag_name)
- Tags não adquiridas não confirmam impacto isoladamente
- Recorded não altera o cálculo baseado exclusivamente no Interpolated 5m

**Critérios de conclusão:**
- [ ] Fluxo completo implementado
- [ ] ready_event.wait() dentro do try
- [ ] finally chama unregister incondicionalmente
- [ ] CancelledError não converte failed em cancelled
- [ ] Exception gera failed com diagnóstico
- [ ] Todas as regras Recorded implementadas

---

### T3.2 — Testes do CepAnalysisService

**Objetivo:** Testar orquestração, deduplicação, cálculo, classificação e Recorded.

**Arquivo:** `backend/tests/test_cep_analysis_service.py` (novo)

**Dependências:** T3.1

**Cenários (conforme matriz de rastreabilidade):**
1. Sucesso total (todas variáveis processed)
2. Sucesso parcial (mix processed + error)
3. Falha total (todas error)
4. Variáveis no_data (sem pontos elegíveis)
5. overall_pct com denominador > 0
6. overall_pct com denominador = 0 (None)
7. Tags compartilhadas deduplicadas
8. Cancelamento durante execução
9. Exception gera failed
10. Recorded com include_recorded=false (nenhuma chamada)
11. Recorded com include_recorded=true (presente)
12. Recorded com truncamento por limite individual (flag agregado false)
13. Recorded com truncamento por limite agregado (flag agregado true)
14. Recorded com tags não adquiridas
15. source_point_count null quando truncado
16. source_point_count exato quando completo
17. source_point_count 0 quando sem eventos
18. Tags compartilhadas consultadas uma vez
19. Ordem lexicográfica das tags
20. Pontos mais recentes de todo o intervalo (busca regressiva)
21. Igualdade com o limite sem impacto confirmado
22. recorded_total_limit_reached somente com truncamento agregado
23. Recorded sem alterar Interpolated 5m, conformidade, percentuais ou contadores
24. Empate de limites com ponto adicional → ambos individual e agregado confirmados
25. Empate de limites sem ponto adicional → flag agregado false

**Critérios de conclusão:**
- [ ] Todos os cenários passam

---

## Fase 4: Endpoints

### T4.1 — Router CEP

**Objetivo:** Implementar os 3 endpoints.

**Arquivo:** `backend/app/api/cep.py` (novo)

**Dependências:** T1.2, T2.1, T3.1

**Endpoints:**

**POST /analyze (202):**
1. Validar timezone (422 se naive — validação estrutural)
2. Validar período: `start_time >= end_time` → `TimeRangeInvalidError` (400)
3. Validar período: `> pi_query_max_period_days` → `TimeRangeInvalidError` (400)
4. Carregar e materializar CepVariable (_load_and_materialize)
5. Validar quantidade: `> pi_cep_max_variables` → `ValidationError` (422)
6. Validar: filtros sem variável ativa → `ValidationError` (422)
7. Gerar query_id
8. Registrar no store
9. Criar task
10. Registrar no QueryRegistry (com rollback em caso de falha)
11. Liberar ready_event
12. Retornar 202

**GET /analyze/{query_id}:**
- response_model=CepQueryResponse
- JSONResponse com model_dump(mode="json")
- Coordenar timeout com QueryRegistry:
  1. `store.apply_timeout(query_id)`
  2. Se timeout aplicado: `registry.cancel(query_id)`
  3. `store.get_or_remove_expired(query_id)`
  4. Se None: 404
- Cancelamento após timeout retorna 409 durante TTL terminal
- CancelledError técnico não substitui failed por cancelled
- recorded_series omitido quando include_recorded=false

**POST /analyze/{query_id}/cancel:**
- Coordenar timeout com QueryRegistry:
  1. `store.apply_timeout(query_id)`
  2. Se timeout aplicado: `registry.cancel(query_id)` → 409
  3. `store.get_or_remove_expired(query_id)`
  4. Se None: 404
- `store.set_cancelled(query_id)`
- 200 para CANCELLED/ALREADY_CANCELLED
- 409 para ALREADY_TERMINAL
- 404 para NOT_FOUND

**Critérios de conclusão:**
- [ ] 3 endpoints implementados
- [ ] Serialização com mode="json"
- [ ] Omissão de recorded_series quando include_recorded=false
- [ ] Rollback em falha de registry.register()
- [ ] Códigos HTTP conforme D7 (422 estrutural, 400 semântico)
- [ ] Coordenação timeout com QueryRegistry em GET e cancel

---

### T4.2 — Registrar router

**Objetivo:** Adicionar cep_router ao router principal.

**Arquivo:** `backend/app/api/router.py`

**Dependências:** T4.1

**Alteração:** Adicionar import e include_router com dependencies=protected.

**Critérios de conclusão:**
- [ ] Router registrado
- [ ] Proteção JWT + CSRF aplicada

---

### T4.3 — Lifecycle da limpeza

**Objetivo:** Adicionar tarefa periódica de limpeza ao lifespan.

**Arquivo:** `backend/app/main.py`

**Dependências:** T1.2

**Alteração:**
- Criar task `_cep_cleanup_loop` no lifespan
- No loop: `store.cleanup_expired()` retorna `CleanupResult`
- Cada ID em `result.timed_out` é cancelado por `registry.cancel(query_id)`
- O store não depende do registry
- No shutdown: cleanup task cancelada e aguardada
- `CancelledError` propagado dentro do loop e tratado no encerramento
- Falha de uma execução é registrada sem encerrar o loop permanentemente

**Critérios de conclusão:**
- [ ] Task iniciada no startup
- [ ] Task cancelada e aguardada no shutdown
- [ ] CancelledError propagado e tratado
- [ ] Falha de cleanup registrada sem encerrar loop
- [ ] Coordenação com QueryRegistry para timeout

---

### T4.4 — Testes de contrato

**Objetivo:** Testar códigos HTTP, schemas, omissão de recorded_series e lifecycle.

**Arquivo:** `backend/tests/test_cep_api.py` (novo)

**Dependências:** T4.1, T4.2, T4.3

**Critérios de conclusão:**
- [ ] Cenários atribuídos a T4.4 na matriz passam
- [ ] Nenhum teste existente quebrado

---

## Fase 5: Validação

### T5.1 — Novos testes

**Objetivo:** Executar todos os novos testes primeiro.

**Comando:**
```bash
cd backend && python -m pytest tests/test_cep_query_store.py tests/test_cep_pi_adapter.py tests/test_cep_analysis_service.py tests/test_cep_api.py -v
```

**Dependências:** T1.4, T1.5, T3.2, T4.4

**Critérios de conclusão:**
- [ ] Todos os novos testes passam

---

### T5.2 — Regressão global

**Objetivo:** Executar suíte completa incluindo novos e existentes.

**Comando:**
```bash
cd backend && python -m pytest tests/ -x -q
```

**Dependências:** T5.1

**Critérios de conclusão:**
- [ ] Todos os testes passam (novos e existentes)
- [ ] Nenhum novo warning

---

### T5.3 — Lint e typecheck

**Objetivo:** Verificar qualidade do código.

**Comandos:**
```bash
cd backend && python -m ruff check app/api/cep.py app/schemas/cep_analysis.py app/services/cep_query_store.py app/services/cep_pi_adapter.py app/services/cep_analysis_service.py app/core/config.py app/api/router.py app/main.py tests/test_cep_query_store.py tests/test_cep_pi_adapter.py tests/test_cep_analysis_service.py tests/test_cep_api.py
cd backend && python -m mypy app/api/cep.py app/schemas/cep_analysis.py app/services/cep_query_store.py app/services/cep_pi_adapter.py app/services/cep_analysis_service.py app/core/config.py app/api/router.py app/main.py --ignore-missing-imports
```

**Dependências:** T1.1, T1.2, T1.3, T1.4, T1.5, T2.1, T3.1, T3.2, T4.1, T4.2, T4.3, T4.4

**Critérios de conclusão:**
- [ ] Nenhum erro de lint
- [ ] Nenhum erro de typecheck

---

## Resumo

| Fase | Tarefas | Arquivos novos | Arquivos alterados |
|---|---|---|---|
| 1: Fundações | 5 | 4 | 1 |
| 2: Schemas | 1 | 1 | 0 |
| 3: Orquestrador | 2 | 2 | 0 |
| 4: Endpoints | 4 | 2 | 2 |
| 5: Validação | 3 | 0 | 0 |
| **Total** | **15** | **9** | **3** |

## Dependências

```
T1.1 (configs) ──────────────────────────┐
T2.1 (schemas) ──────────────────────────┤ (independentes entre si)
T1.2 (store) ← T1.1, T2.1 ─────────────┤
T1.3 (adapter) ──────────────────────────┤ (independente)
T1.4 (test store) ← T1.2 ───────────────┤
T1.5 (test adapter) ← T1.3 ─────────────┤
T3.1 (service) ← T1.2, T1.3, T2.1 ─────┤
T3.2 (test service) ← T3.1 ─────────────┤
T4.1 (endpoints) ← T1.2, T2.1, T3.1 ───┤
T4.2 (router) ← T4.1 ───────────────────┤
T4.3 (lifecycle) ← T1.2 ────────────────┤
T4.4 (test api) ← T4.1, T4.2, T4.3 ────┤
T5.1 (novos testes) ← T1.4, T1.5, T3.2, T4.4
T5.2 (regressão) ← T5.1
T5.3 (lint) ← T1.1, T1.2, T1.3, T1.4, T1.5, T2.1, T3.1, T3.2, T4.1, T4.2, T4.3, T4.4
```

## Ordem crítica

```
T1.1 ──┐
       ├─→ T1.2 ──→ T1.4 ──┐
T2.1 ──┘         └─→ T4.3  │
T1.3 ──→ T1.5              ├─→ T5.1 → T5.2
       └─→ T3.1 ──→ T3.2 ──┤
                            │
       T3.1 ──→ T4.1 ──→ T4.2 ──→ T4.4 ──┘

T1.1, T1.2, T1.3, T1.4, T1.5, T2.1, T3.1, T3.2, T4.1, T4.2, T4.3, T4.4 → T5.3 (paralelo a T5.1/T5.2)
```

## Tarefas paralelizáveis

- T1.1, T2.1, T1.3: independentes entre si, podem começar simultaneamente
- T1.4 e T1.5: independentes entre si após T1.2 e T1.3 respectivamente
- T5.3: pode executar em paralelo com T5.1/T5.2

## Matriz de rastreabilidade: cenários → tarefas → arquivos

| # | Cenário | Tarefa principal | Arquivo de teste |
|---|---|---|---|
| 1 | Análise completa sem filtros (24 variáveis) | T3.2 | test_cep_analysis_service.py |
| 2 | Análise com filtro por equipment_id | T4.4 | test_cep_api.py |
| 3 | Análise com filtro por section_id | T4.4 | test_cep_api.py |
| 4 | Análise com filtro por variable_ids | T4.4 | test_cep_api.py |
| 5 | Filtros sem configuração ativa → 422 | T4.4 | test_cep_api.py |
| 6 | Período inválido → 400 | T4.4 | test_cep_api.py |
| 7 | Seleção > pi_cep_max_variables → 422 | T4.4 | test_cep_api.py |
| 8 | Sucesso total (analysis_status=completed) | T3.2 | test_cep_analysis_service.py |
| 9 | Sucesso parcial (analysis_status=partial) | T3.2 | test_cep_analysis_service.py |
| 10 | Falha total (analysis_status=failed) | T3.2 | test_cep_analysis_service.py |
| 11 | Cancelamento de pending | T1.4 | test_cep_query_store.py |
| 12 | Cancelamento de running | T1.4 | test_cep_query_store.py |
| 13 | Cancelamento de completed → 409 | T1.4 | test_cep_query_store.py |
| 14 | Cancelamento idempotente de cancelled | T1.4 | test_cep_query_store.py |
| 15 | Timeout operacional contado desde register() | T1.4 | test_cep_query_store.py |
| 16 | Timeout não reiniciado em running | T1.4 | test_cep_query_store.py |
| 17 | TTL terminal contado da transição terminal | T1.4 | test_cep_query_store.py |
| 18 | TTL não renovado por GET | T4.4 | test_cep_api.py |
| 19 | TTL não renovado por cancelamento idempotente | T1.4 | test_cep_query_store.py |
| 20 | Limpeza no acesso (apply_timeout) | T1.4 | test_cep_query_store.py |
| 21 | Limpeza periódica (cleanup_expired) | T1.4 | test_cep_query_store.py |
| 22 | Coordenação do timeout com QueryRegistry | T4.4 | test_cep_api.py |
| 23 | Task tecnicamente cancelada sem trocar failed por cancelled | T3.2 | test_cep_analysis_service.py |
| 24 | Corrida entre conclusão, cancelamento e timeout | T1.4 | test_cep_query_store.py |
| 25 | Cancelamento durante aquisição | T3.2 | test_cep_analysis_service.py |
| 26 | Omissão real de recorded_series (chave ausente no JSON) | T4.4 | test_cep_api.py |
| 27 | Ausência total de chamadas Recorded quando include_recorded=false | T3.2 | test_cep_analysis_service.py |
| 28 | Recorded com include_recorded=true (presente) | T3.2 | test_cep_analysis_service.py |
| 29 | Recorded com truncamento por limite individual (flag agregado false) | T3.2 | test_cep_analysis_service.py |
| 30 | Recorded com truncamento por limite agregado (flag agregado true) | T3.2 | test_cep_analysis_service.py |
| 31 | Recorded com tags não adquiridas | T3.2 | test_cep_analysis_service.py |
| 32 | source_point_count null quando truncado | T3.2 | test_cep_analysis_service.py |
| 33 | source_point_count exato quando completo | T3.2 | test_cep_analysis_service.py |
| 34 | source_point_count 0 quando sem eventos | T3.2 | test_cep_analysis_service.py |
| 35 | Tags compartilhadas consultadas uma vez | T3.2 | test_cep_analysis_service.py |
| 36 | Ordem lexicográfica das tags | T3.2 | test_cep_analysis_service.py |
| 37 | Pontos mais recentes de todo o intervalo (busca regressiva) | T3.2 | test_cep_analysis_service.py |
| 38 | Igualdade com o limite sem impacto confirmado | T3.2 | test_cep_analysis_service.py |
| 39 | Contagem de pontos retornados | T3.2 | test_cep_analysis_service.py |
| 40 | Valor configurado efetivo em recorded_total_point_limit | T3.2 | test_cep_analysis_service.py |
| 41 | recorded_tags_not_acquired em ordem lexicográfica | T3.2 | test_cep_analysis_service.py |
| 42 | Recorded sem alterar Interpolated 5m, conformidade, percentuais ou contadores | T3.2 | test_cep_analysis_service.py |
| 43 | overall_pct com denominador > 0 | T3.2 | test_cep_analysis_service.py |
| 44 | overall_pct com denominador = 0 (None) | T3.2 | test_cep_analysis_service.py |
| 45 | Variáveis no_data não participam do overall_pct | T3.2 | test_cep_analysis_service.py |
| 46 | Variáveis error não participam do overall_pct | T3.2 | test_cep_analysis_service.py |
| 47 | Timestamps públicos normalizados para UTC Z | T4.4 | test_cep_api.py |
| 48 | Sessão de banco encerrada com segurança | T4.4 | test_cep_api.py |
| 49 | Comportamento após reinício | T1.4 | test_cep_query_store.py |
| 50 | Execução com um único worker | T1.4 | test_cep_query_store.py |
| 51 | Orçamento agregado exatamente consumido, sem ponto adicional, flag false | T3.2 | test_cep_analysis_service.py |
| 52 | Tags posteriores não adquiridas sem confirmação agregada, flag false | T3.2 | test_cep_analysis_service.py |
| 53 | Task não executa antes de registro no QueryRegistry | T3.2 | test_cep_analysis_service.py |
| 54 | registry.register() falha: task cancelada e aguardada, entrada removida, nenhum 202 | T4.4 | test_cep_api.py |
| 55 | Cancelamento enquanto task aguarda ready_event | T3.2 | test_cep_analysis_service.py |
| 56 | unregister() executado em conclusão, falha, cancelamento e timeout | T3.2 | test_cep_analysis_service.py |
| 57 | Nenhuma operação pending órfã após falha de registro | T4.4 | test_cep_api.py |
| 58 | Nenhuma task permanece no registry após qualquer saída | T3.2 | test_cep_analysis_service.py |

---

## Rastreabilidade D7/D8 → Tarefas

| Decisão | Tarefa |
|---|---|
| D7.1 (POST /analyze, 202) | T4.1 |
| D7.2 (filtros opcionais) | T4.1 |
| D7.3 (include_recorded) | T4.1, T3.1 |
| D7.4 (max_period_days) | T2.1, T4.1 |
| D7.5 (assíncrono) | T1.2, T3.1, T4.1 |
| D7.6 (estrutura resposta) | T2.1 |
| D7.7 (granularidade) | T2.1 |
| D7.8 (Interpolated não exposta) | T3.1 |
| D7.9 (overall_pct) | T3.1 |
| D7.10 (diagnósticos) | T3.1 |
| D7.11 (analysis_status) | T3.1 |
| D7.12 (AppError) | T4.1 |
| D7.13 (GET status/resultado) | T4.1 |
| D7.14 (cancelamento) | T4.1 |
| D7.15 (validação entrada) | T2.1, T4.1 |
| D7.16 (409 pós-terminal) | T1.4, T4.1 |
| D7.17 (24 variáveis) | T1.1 |
| D7.18 (timestamps UTC Z) | T2.1, T4.1 |
| D7.19 (pi_cep_max_variables) | T1.1, T4.1 |
| D7.20 (sem versionamento) | — |
| D7.21 (falhas assíncronas) | T3.1 |
| D8.1.1 (CepQueryStore in-memory) | T1.2 |
| D8.1.2 (single-process) | T1.2 |
| D8.1.3 (separação QueryRegistry) | T1.2, T3.1 |
| D8.2.1 (TTL terminal) | T1.2 |
| D8.2.2 (timeout operacional) | T1.2 |
| D8.2.3 (limpeza) | T1.2, T4.3 |
| D8.3.1 (sem persistência) | — |
| D8.4.1 (limite por tag) | T1.1, T3.1 |
| D8.4.5 (limite agregado) | T1.1, T3.1 |
| D8.4.11 (source_point_count) | T2.1, T3.1 |

---

## Arquivos previstos

**Novos (9):**
- `backend/app/services/cep_query_store.py`
- `backend/app/services/cep_pi_adapter.py`
- `backend/app/schemas/cep_analysis.py`
- `backend/app/services/cep_analysis_service.py`
- `backend/app/api/cep.py`
- `backend/tests/test_cep_query_store.py`
- `backend/tests/test_cep_pi_adapter.py`
- `backend/tests/test_cep_analysis_service.py`
- `backend/tests/test_cep_api.py`

**Alterados (3):**
- `backend/app/core/config.py`
- `backend/app/api/router.py`
- `backend/app/main.py`
