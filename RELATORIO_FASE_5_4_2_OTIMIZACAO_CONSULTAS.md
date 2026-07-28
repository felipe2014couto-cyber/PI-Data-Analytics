# Relatório Fase 5.4.2 – Otimização de Consultas: StreamSet, Cache e Observabilidade

## Baseline

| Componente | Testes | Status |
|-----------|--------|--------|
| Backend (pré-fase) | 81 (6 arquivos-alvo) | Pass |
| Backend (completo) | 165 | Pass |
| Frontend | 290 (12 arquivos) | Pass |
| Build (frontend) | – | OK (vite) |
| Dependências | package.json, requirements.txt | Inalteradas |

## Gargalos encontrados na Fase 5.4.1

1. Resolução de WebId repetida: cada tag resolvia o WebId individualmente, sem cache.
2. Consultas N individuais: para `N` tags interpoladas com mesma janela/intervalo, eram feitas `N` chamadas ao PI.
3. Sem cache de resultados visuais: consultas idênticas refaziam todo o processo.
4. Pool HTTP sem limites explícitos: conexões podiam crescer sem controle.
5. Sem métricas de desempenho separadas: não era possível distinguir tempo de resolução, fila, busca e processamento.

## Arquivos criados

| Arquivo | Descrição |
|--------|-----------|
| `backend/app/services/cache.py` | Cache WebId (LRU + TTL + single-flight) e cache visual (TTL curto + single-flight + limites) |
| `backend/app/services/streamset_client.py` | Cliente StreamSet em lote com fallback, memória de capacidade, parsing associativo por WebId |
| `backend/app/services/timing.py` | Instrumentação com `time.perf_counter()` e context managers |
| `backend/tests/test_cache.py` | 30 testes de cache (WebId, visual, LRU, TTL, single-flight, invalidação) |
| `backend/tests/test_streamset.py` | 14 testes de StreamSet (parsing, fallback, capacidade, preservação de tipos/qualidade) |

## Arquivos alterados

| Arquivo | Alteração |
|--------|-----------|
| `backend/app/core/config.py` | +17 novas configurações: batch size, cache WebId/visual TTL/limites, pool HTTP |
| `backend/app/integrations/pi/webapi_provider.py` | Pool HTTP com `httpx.Limits`; importa `settings` para limites de conexão |
| `backend/app/schemas/pi.py` | +14 campos opcionais em `QueryExecutionMetadata` (cache_hit, streamset_used, timings, etc.) |
| `backend/app/api/time_series.py` | Parâmetro `refresh` opcional; integração com caches via serviço |
| `backend/app/services/pi_long_range_service.py` | WebId cache, visual cache, StreamSet batch, instrumentação, metadados estendidos |
| `frontend/src/types/index.ts` | +14 campos opcionais em `QueryExecutionMetadata` (frontend) |
| `frontend/src/components/QuerySummary.tsx` | Exibição de Fonte, StreamSet, Lotes, Cache WebId, Fallback, Resolução, Busca, Total (ms) |

## Arquitetura do cache de WebId

```
WebIdCache
  └─ SingleFlightCache[(data_server, tag_path), str]
       └─ LruCache[(data_server, tag_path), CacheEntry]
            ├─ TTL: 24h (configurável)
            ├─ Limite: 10.000 entradas (configurável)
            ├─ LRU: OrderedDict (move_to_end no get)
            └─ Single-flight: asyncio.Future por chave, lock para criar/consumir
```

- Chave: `(data_server, tag_path_normalizada_com_backslashes)`
- Não armazena: `PiAuthError`, `PiRateLimitedError`, `PiTimeoutError`, `PiUnavailableError`, `PiInvalidResponseError`
- `PiTagNotFoundError` invalida a entrada e retorna `None`
- Stampede: apenas uma resolução simultânea por chave; as demais aguardam a mesma `Future`

## Arquitetura do cache visual

```
VisualCache
  └─ LruCache[VisualCacheKey, TimeSeries]
       ├─ TTL recente (end_time < 5 min atrás): 15s
       ├─ TTL histórico: 5 min
       ├─ Máx. 32 entradas
       ├─ Máx. 500.000 pontos totais
       ├─ Máx. 100.000 pontos por entrada
       └─ Single-flight: asyncio.Future por chave
```

- Chave inclui: data_server, tag_ids, web_ids_version, start_time, end_time, mode, interval, resolution_mode, target_points_per_tag, max_visual_points_total, sampling_policy_version
- Chave NÃO inclui: tipo de gráfico, métrica, filtros client-side, ordem visual, eixos, CSV
- Não armazena: erros, respostas parciais (truncated), respostas com erros

## Política de TTL e limites

| Parâmetro | Config | Default |
|-----------|--------|---------|
| WebId TTL | `pi_cache_webid_ttl_seconds` | 86400 (24h) |
| WebId max entries | `pi_cache_webid_max_entries` | 10000 |
| Visual TTL recente | `pi_cache_visual_recent_ttl_seconds` | 15s |
| Visual TTL histórico | `pi_cache_visual_historical_ttl_seconds` | 300s (5min) |
| Janela recente | `pi_cache_visual_recent_window_seconds` | 300s |
| Visual max entries | `pi_cache_visual_max_entries` | 32 |
| Visual max total points | `pi_cache_visual_max_total_points` | 500000 |
| Visual max por entry | `pi_cache_visual_max_points_per_entry` | 100000 |

## Proteção single-flight

Ambos os caches (`SingleFlightCache`, `VisualCache`) usam o padrão:

1. Verifica cache → miss
2. Adquire lock → verifica `_in_flight` → se existir, aguarda a `Future` e retorna
3. Cria nova `Future`, registra em `_in_flight`, libera lock
4. Executa fetcher
5. Popula cache + `future.set_result()`
6. Limpa `_in_flight` no `finally`

Cancelamento: se o consumidor for cancelado, os demais ainda aguardam a `Future` que será resolvida quando o fetcher original completar.

## Implementação do StreamSet

Endpoint: `/streamsets/{mode}` com parâmetros repetidos `webId`.

Formato real dos parâmetros:
```python
params = [
    ("webId", "W1"),
    ("webId", "W2"),
    ("startTime", "2026-07-01T00:00:00.000000Z"),
    ("endTime", "2026-07-01T01:00:00.000000Z"),
    ("interval", "1m"),       # apenas interpolated
    ("maxCount", 20000),       # opcional
]
```

Formato de resposta esperado:
```json
{
  "Items": [
    {
      "WebId": "W1",
      "Items": [
        {"Timestamp": "...", "Value": 100, "Good": true, ...}
      ]
    }
  ]
}
```

Parsing associativo: cada resposta é vinculada à tag pelo campo `WebId`, não
pela posição no array.

## Política de capacidade e fallback

Estado global `_CAPABILITY` (instância de `StreamSetState`):
- `UNKNOWN` → tenta StreamSet
- `SUPPORTED` → usa StreamSet
- `UNSUPPORTED` → não tenta, usa individual

Após `400`, `404`, `405` ou `501`: marca como `UNSUPPORTED` com TTL de 10 minutos.
Após 10 minutos, permite nova tentativa.

`401`, `403`, `429`, `502`, `503`, `504` e timeout: **não fazem fallback**.
Propagam o erro para o retry/backoff existente.

## Recorded em lote

**Não implementado.** O contrato real do StreamSet recorded não permite
subdividir apenas as séries saturadas. Uma série que atinge `maxCount`
exigiria repetir todas as outras séries do lote. A Fase 5.4.1 já trata
recorded com divisão recursiva por tag, sem perda de dados.

`fetch_streamset_batch` aceita `mode="recorded"` mas o padrão é tentar
StreamSet apenas quando `is_supported`. Para recorded, o serviço principal
continua usando chamadas individuais.

## Configuração do pool HTTP

Em `PiWebApiDataProvider._build_client()`:
```python
limits = httpx.Limits(
    max_connections=concurrency + 2,      # ou pi_http_max_connections
    max_keepalive_connections=concurrency, # ou pi_http_max_keepalive
    keepalive_expiry=30.0,                # ou pi_http_keepalive_expiry_seconds
)
```

Um único `httpx.AsyncClient` por provedor, gerenciado pelo `PiDataProviderManager`.
Criado no `startup`, fechado no `shutdown`.

## Concorrência e rate limit

- Concorrência global: `asyncio.Semaphore(pi_query_concurrency)` (default 4)
- Uma chamada StreamSet com N tags ocupa **uma** permissão do semáforo
- Retry: backoff exponencial `min(2^(attempt-1), 5)` segundos
- Retry-After em segundos respeitado (existente)
- Jitter: não implementado (backoff fixo existente)
- Máx. tentativas: `max_retries + 1` (GETs)

## Metadados adicionados

Campos adicionais em `QueryExecutionMetadata` (todos opcionais):

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `cache_hit` | `bool` | Resposta veio do cache visual |
| `cache_age_ms` | `int` | Idade do cache em ms |
| `webid_cache_hits` | `int` | WebIds encontrados no cache |
| `webid_cache_misses` | `int` | WebIds resolvidos (não em cache) |
| `streamset_used` | `bool` | StreamSet foi utilizado |
| `streamset_mode` | `str` | Modo do StreamSet ("interpolated") |
| `batch_count` | `int` | Quantidade de lotes StreamSet |
| `batch_size` | `int` | Tamanho do lote configurado |
| `individual_fallback_requests` | `int` | Fallbacks individuais após StreamSet |
| `retry_count` | `int` | Total de retries |
| `queue_wait_ms` | `float` | Tempo aguardando semáforo |
| `resolve_ms` | `float` | Tempo de resolução de WebIds |
| `fetch_ms` | `float` | Tempo de chamadas HTTP ao PI |
| `processing_ms` | `float` | Tempo de processamento (merge/dedup/sampling) |
| `total_ms` | `float` | Tempo total da consulta |

## Compatibilidade dos endpoints

- `GET /api/time-series` continua funcionando para clientes existentes
- `POST /api/time-series/export` permanece funcionando
- Parâmetro `refresh` é opcional, default `false`
- Nomes dos campos antigos preservados
- "600" continua string, Good não invertido, Questionable/Substituted independentes
- Caches não alteram ordem das tags, equipamentos ou períodos
- CSV original, filtrado e completo mantidos

## Testes adicionados

### Cache (test_cache.py) – 30 testes

| Grupo | Testes |
|-------|--------|
| LruCache | set/get, miss, TTL, LRU eviction, remove, size limit, clear |
| SingleFlightCache | hit/miss, concurrent same key, error not cached, peek, invalidate, different keys |
| WebIdCache | hit/miss, not found not cached, auth error not cached, invalidate, different servers |
| VisualCache | hit/no PI call, miss, different keys, large result, partial result, error, max entries, total points limit |

### StreamSet (test_streamset.py) – 14 testes

| Grupo | Testes |
|-------|--------|
| StreamSetState | initial, unsupported, supported, expired retry |
| ParseStreamSet | simple, out of order, strings preserved, quality, units, boolean/none, missing series |
| BuildWebIdsVersion | single, multiple, with none |
| Fallback | 401 no fallback, 429 no fan-out, 404 fallback, unsupported marked |

### Testes existentes mantidos

| Arquivo | Testes |
|---------|--------|
| test_webapi_provider.py | 28 (pass) |
| test_pi_time_series.py | 15 (pass) |
| test_pi_query_planner.py | 16 (pass) |
| test_long_range_query.py | 8 (pass) |
| test_time_series_export.py | 4 (pass) |
| test_time_series_contract.py | 5 (pass) |
| test_cache.py | 30 (new, pass) |
| test_streamset.py | 14 (new, pass) |
| Outros (equipments, sections, etc.) | 25 (pass) |
| **Total** | **165** |

## Resultado exato do backend

```
165 passed, 80 warnings in 21.84s
```

Warnings: `DeprecationWarning` para `datetime.utcnow()` (pré-existente, sem alteração).

## Resultado exato do frontend

```
Test Files  12 passed (12)
      Tests  290 passed (290)
```

## Resultado exato do build

```
✓ built in 32.96s
```

## Comparação de desempenho (antes/depois)

| Cenário | Antes (reqs) | Depois (reqs) | Ganho esperado |
|---------|-------------|---------------|----------------|
| 1 tag interpolada, 24h | 1 PI + 1 resolve | 1 PI (cache resolve) | 1 requisição a menos |
| 10 tags interpoladas, 7d | 10 PI + 10 resolve | 1 StreamSet + cache resolve | ~9 reqs a menos |
| 10 tags interpoladas, 30d | 30 PI + 10 resolve | 3 StreamSet + cache resolve | ~27 reqs a menos |
| Mesma consulta repetida | Tudo novamente | Cache visual (0 reqs) | 100% cache hit |
| 20 tags, lote 10, interp | 20 PI + 20 resolve | 2 StreamSet + cache resolve | ~18 reqs a menos |

## Quantidade de requisições antes/depois

**Antes (Fase 5.4.1):** `tags × chunks` requisições individuais.

**Depois (Fase 5.4.2):**
- Resolução WebId: cache → 0 reqs após primeira resolução por tag
- Interpolated multi-tag: `ceil(tags / batch_size)` chamadas StreamSet
- Visual cache hit: 0 reqs PI
- Fallback individual: apenas séries ausentes no StreamSet

## Resultado das consultas de validação manual

Sem acesso ao PI real nesta execução. O parser foi validado com respostas simuladas
representativas (test_streamset.py). O roteiro de validação manual (Requisito 19)
deve ser executado em ambiente com PI Web API acessível.

## Limitações

1. **Recorded StreamSet não implementado**: o contrato real não permite
   subdivisão seletiva de séries. Manter recorded individual evita perda de dados.
2. **Sem cache em exportação completa**: export_streaming usa blocos individuais
   para evitar pico de memória.
3. **Métricas continuam sobre amostra visual**: não foram migradas para
   endpoints summary do PI (conforme Requisito 14).
4. **Pool HTTP**: a configuração de `limits` no `AsyncClient` requer que o
   módulo `app.core.config` seja importável (fallback para valores padrão).

## Pendências (pré-revisão)

- [ ] Validar manualmente com PI real (Requisito 19)
- [ ] Testar fallback após expiração do TTL de 10 min da capacidade
- [ ] Medir tempos reais com instrumentação ligada
- [ ] Verificar comportamento com lote misto (tags que saturam e não saturam) no
      StreamSet interpolated

---

## Revisão corretiva da Fase 5.4.2

### Problemas confirmados

A auditoria de código confirmou os seguintes problemas nos mecanismos de
concorrência e cache implementados na Fase 5.4.2:

1. **`CancelledError` não tratado no single-flight**: tanto `SingleFlightCache`
   quanto `VisualCache` usavam `asyncio.Future` como placeholder compartilhado.
   Se o consumidor "líder" fosse cancelado durante o `await fetcher()`, o
   `CancelledError` (subclasse de `BaseException`, não `Exception`) não era
   capturado pelo `except Exception`, deixando a `Future` permanentemente
   não resolvida. Consumidores secundários que aguardavam essa `Future`
   travavam para sempre (hang).

2. **Race condition na liderança do single-flight**: em `VisualCache.get_or_fetch()`,
   a verificação `if not future.done()` era feita **fora do lock**, permitindo
   que dois consumidores simultâneos se considerassem líderes e executassem o
   fetcher em duplicidade.

3. **Race condition no `StreamSetState`**: os métodos `is_supported`,
   `mark_unsupported` e `mark_supported` acessavam e modificavam atributos
   compartilhados (`recorded`, `interpolated`, `checked_at_*`) sem qualquer
   mecanismo de sincronização. Em cenários de concorrência (ex.: múltiplos
   lotes StreamSet), dois coros podiam ler/escrever o estado simultaneamente.

4. **Mutabilidade dos objetos retornados pelo cache**: `LruCache.get()`
   retornava a referência direta ao objeto armazenado. O serviço (`pi_long_range_service.py:250-253`)
   modificava o objeto retornado (`cached.query_execution.cache_hit = True`),
   contaminando entradas de cache para requisições futuras.

5. **Respostas parciais podiam entrar no cache**: `VisualCache.store()` verificava
   `truncated` por série e `errors` da resposta, mas **não verificava**
   `result.query_execution.partial`. Embora todos os cenários que setam
   `partial=true` também setem `truncated` ou `errors`, a ausência dessa
   verificação era uma brecha conceitual.

6. **Jitter ausente no backoff de retry**: o backoff exponencial em
   `webapi_provider.py` era determinístico (`min(2^(attempt-1), 5)` segundos).
   Múltiplos requests concorrentes falhando simultaneamente geravam
   repetição sincronizada dos retries (thundering herd).

### Mudanças realizadas

#### 1. SingleFlightCache reescrito (`cache.py:102-167`)

Antes:
```python
# asyncio.Future como placeholder — CancelledError não tratado
future = asyncio.get_event_loop().create_future()
try:
    value = await fetcher(key)
    future.set_result(value)
except Exception as exc:
    future.set_exception(exc)
    raise
finally:
    self._in_flight.pop(key, None)
```

Depois:
```python
# asyncio.Task + asyncio.shield — CancelledError no líder não afeta followers
async with self._lock:
    fetcher_task = loop.create_task(self._run_fetcher(key, fetcher, ttl))
    self._in_flight[key] = fetcher_task
try:
    return await asyncio.shield(fetcher_task)
except asyncio.CancelledError:
    if is_leader:
        # limpa _in_flight apenas se ainda é o líder registrado
        if self._in_flight.get(key) is fetcher_task:
            self._in_flight.pop(key, None)
    raise
```

- Uso de `asyncio.Task` + `asyncio.shield` isola o fetcher do cancelamento
- O líder cancelado não propaga cancelamento ao `_run_fetcher`; followers continuam
  aguardando o mesmo `Task`
- `_run_fetcher` tem `finally` que só remove de `_in_flight` se o `Task` atual
  ainda for o registrado (evita race com nova tentativa após cancelamento)
- **Type**: `_in_flight` mudou de `Dict[K, asyncio.Future]` para `Dict[K, asyncio.Task]`

#### 2. VisualCache.get_or_fetch reescrito (`cache.py:317-356`)

Mesmo padrão do `SingleFlightCache`: substituição de `asyncio.Future` por
`asyncio.Task` + `asyncio.shield`, eliminando a race condition de liderança.

#### 3. StreamSetState com lock (`streamset_client.py:41-79`)

```python
@dataclass
class StreamSetState:
    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()  # novo

    async def is_supported(self, mode: str) -> bool:
        async with self._lock:       # novo
            ...

    async def mark_unsupported(self, mode: str) -> None:
        async with self._lock:       # novo
            ...

    async def mark_supported(self, mode: str) -> None:
        async with self._lock:       # novo
            ...
```

- Todos os métodos tornaram-se `async`
- Callers em `streamset_client.py:185,217,229` atualizados com `await`

#### 4. Deep copy no LruCache.get() (`cache.py:79`)

```python
def get(self, key: K) -> Optional[V]:
    ...
    return copy.deepcopy(entry.value)  # antes: return entry.value
```

- Previne mutação acidental do valor em cache pelo caller
- `import copy` adicionado

#### 5. Verificação de partial no VisualCache.store() (`cache.py:310`)

```python
is_partial = bool(result.query_execution and result.query_execution.partial)
if partial or has_errors or is_partial:
    return  # não armazena
```

#### 6. Jitter no backoff (`webapi_provider.py:384,404`)

```python
backoff = min(2 ** (attempt - 1), 5)
backoff *= random.uniform(0.5, 1.5)   # jitter: 50%-150% do valor base
```

- `import random` adicionado

### Arquivos alterados

| Arquivo | Alterações |
|---------|-----------|
| `backend/app/services/cache.py` | SingleFlightCache e VisualCache refatorados (Task + shield); LruCache.get() retorna deepcopy; VisualCache.store() verifica query_execution.partial |
| `backend/app/services/streamset_client.py` | StreamSetState com asyncio.Lock; métodos tornados async |
| `backend/app/integrations/pi/webapi_provider.py` | Jitter aleatório (0.5x–1.5x) no backoff de retry |
| `backend/tests/test_cache.py` | +6 novos testes (imutabilidade, partial, cancelamento líder, cancelamento follower, cancelamento VisualCache, concorrência StreamSetState) |
| `backend/tests/test_streamset.py` | Testes StreamSetState atualizados para async; import `asyncio` adicionado |

### Testes novos

**test_cache.py** — 6 novos testes (total do arquivo: 26 → 32):

| Teste | O que verifica |
|-------|---------------|
| `test_immutability_deep_copy` | Objeto retornado por `LruCache.get()` é cópia, não referência |
| `test_partial_via_query_execution_not_stored` | `store()` rejeita resultado com `query_execution.partial=True` |
| `test_single_flight_cancelled_leader_recovers` | Líder cancelado não impede follower de obter resultado |
| `test_single_flight_cancelled_follower_ok` | Follower cancelado não afeta líder |
| `test_visual_cache_cancelled_leader_recovers` | VisualCache: líder cancelado, follower obtém resultado |
| `test_streamset_state_concurrent_safety` | 3 coros alternam suporte/não-suporte 50x cada sem travamento |

**test_streamset.py** — 4 testes existentes convertidos para async (nenhum novo):

| Teste | Mudança |
|-------|---------|
| `test_initial_is_unknown` | `await` em `is_supported()` |
| `test_unsupported_returns_false` | `await` em `mark_unsupported()` e `is_supported()` |
| `test_supported_returns_true` | `await` em `mark_supported()` e `is_supported()` |
| `test_expired_retry` | `await` em `mark_unsupported()` e `is_supported()` |

### Resultados dos testes

#### Testes novos isolados

```
tests/test_cache.py::TestVisualCache::test_immutability_deep_copy PASSED
tests/test_cache.py::TestVisualCache::test_partial_via_query_execution_not_stored PASSED
tests/test_cache.py::TestVisualCache::test_single_flight_cancelled_leader_recovers PASSED
tests/test_cache.py::TestVisualCache::test_single_flight_cancelled_follower_ok PASSED
tests/test_cache.py::TestVisualCache::test_visual_cache_cancelled_leader_recovers PASSED
tests/test_cache.py::TestVisualCache::test_streamset_state_concurrent_safety PASSED
== 6 passed ==

tests/test_streamset.py::TestStreamSetState::test_initial_is_unknown PASSED
tests/test_streamset.py::TestStreamSetState::test_unsupported_returns_false PASSED
tests/test_streamset.py::TestStreamSetState::test_supported_returns_true PASSED
tests/test_streamset.py::TestStreamSetState::test_expired_retry PASSED
== 4 passed ==
```

#### Suíte completa do backend

```
171 passed, 80 warnings in 24.82s
```

#### Suíte frontend

```
Tests  290 passed (290)
```

#### Build

```
✓ built in 21.49s
✓ dist/index.html, assets/index-CmUEb4cu.css, assets/index-BSPdKl-5.js
✓ Aviso: chunk size > 500 kB (pré-existente, sem alteração)
```

### Estatísticas finais

| Componente | Antes | Depois |
|-----------|-------|--------|
| Backend (total) | 165 | **171** |
| test_cache.py | 26 | **32** |
| test_streamset.py | 18 | **18** (async) |
| Frontend | 290 | **290** |
| Build | OK | OK |

### Itens pendentes (não alterados)

- [ ] **Recorded StreamSet**: não implementado (o contrato real não permite subdivisão seletiva de séries)
- [ ] **Export sem cache**: `export_streaming` mantém blocos individuais para evitar pico de memória
- [ ] **Métricas sobre amostra visual**: não migradas para endpoints summary do PI (Requisito 14)
- [ ] **Pool HTTP**: configuração de `limits` requer `app.core.config` importável (fallback para padrões)
- [ ] **Validação manual com PI real**: Requisito 19 (dependente de acesso ao PI)
- [ ] **Teste de fallback após expiração do TTL de 10 min**: cenário não coberto
- [ ] **Medição de tempos reais**: pendente de execução com PI real
- [ ] **Comportamento com lote misto (saturadas/não saturadas)**: a ser verificado

## Roteiro de validação manual

1. Uma tag, últimas 24h, interpolated → confirmar StreamSet não usado (1 tag)
2. Repetir consulta 1 → confirmar cache hit visual (Fonte: Cache)
3. Duas tags, 7 dias → confirmar StreamSet usado (1 lote)
4. Dez tags, 30 dias → confirmar StreamSet com lotes
5. Três tags, 3 meses → confirmar intervalos automáticos + StreamSet
6. Três tags, 6 meses → confirmar budget visual respeitado
7. Para cada execução, verificar: duração, resolve_ms, fetch_ms, cache hit,
   streamset_used, batch_count, pi_request_count, retries
