# `/plan` — Capacidade de análise CEP

## 1. Visão geral

### 1.1 Objetivo

Implementar a capacidade de análise de conformidade CEP (Controle Estatístico de Processo) para a RB1, conforme decisões consolidadas na D7 e D8.

### 1.2 Escopo

- 3 endpoints REST: `POST /analyze`, `GET /analyze/{query_id}`, `POST /analyze/{query_id}/cancel`
- Execução assíncrona com `CepQueryStore` in-memory
- Aquisição de Interpolated 5m (interno) e Recorded (opcional)
- Cálculo de conformidade via `cep_calculator.py` existente
- Limites de Recorded: 10.000 pontos/tag, 100.000 pontos agregados
- Timeout operacional, TTL terminal e limpeza periódica

### 1.3 Fora do escopo

- Persistência histórica de resultados
- Redis ou armazenamento distribuído
- Paginação ou download
- Limite em bytes
- Multi-worker

---

## 2. Arquivos a serem criados

| Arquivo | Responsabilidade |
|---|---|
| `backend/app/api/cep.py` | Router FastAPI com 3 endpoints |
| `backend/app/schemas/cep_analysis.py` | Schemas Pydantic de request/response |
| `backend/app/services/cep_analysis_service.py` | Orquestrador assíncrono |
| `backend/app/services/cep_pi_adapter.py` | Conversão PiValue → CepSample |
| `backend/app/services/cep_query_store.py` | Armazenamento in-memory de operações |
| `backend/tests/test_cep_api.py` | Testes de contrato dos endpoints |
| `backend/tests/test_cep_analysis_service.py` | Testes do orquestrador |
| `backend/tests/test_cep_pi_adapter.py` | Testes do adaptador |
| `backend/tests/test_cep_query_store.py` | Testes do armazenamento |

---

## 3. Arquivos a serem alterados

| Arquivo | Alteração |
|---|---|
| `backend/app/api/router.py` | Registrar `cep_router` com proteção JWT + CSRF |
| `backend/app/core/config.py` | Adicionar 6 configs CEP |
| `backend/app/main.py` | Adicionar lifecycle da limpeza periódica |

---

## 4. Arquivos existentes reutilizados (sem alteração)

| Arquivo | Componente reutilizado |
|---|---|
| `backend/app/services/cep_calculator.py` | `calculate_compliance()` — puro, sem IO |
| `backend/app/services/streamset_client.py` | `fetch_streamset_batch()` para Interpolated 5m |
| `backend/app/services/cache.py` | `WebIdCache` |
| `backend/app/services/query_registry.py` | `QueryRegistry` para cancelamento de tasks |
| `backend/app/integrations/pi/provider.py` | `PiDataProvider`, `PiValue`, `PiPoint` |
| `backend/app/integrations/pi/webapi_provider.py` | `PiWebApiDataProvider` — `get_recorded_values()` para Recorded |
| `backend/app/integrations/pi/errors.py` | Hierarquia de exceções PI |
| `backend/app/models/cep_variable.py` | `CepVariable` ORM |
| `backend/app/models/pi_tag.py` | `PiTag` ORM |
| `backend/app/core/exceptions.py` | `AppError`, `ConflictError`, `NotFoundError`, etc. |
| `backend/app/api/errors.py` | Handlers de exceção |
| `backend/app/api/deps.py` | `get_current_user`, `validate_csrf`, `get_db_session` |

Total: 12 componentes reutilizados sem alteração.

Nota sobre Recorded: a aquisição usa diretamente `provider.get_recorded_values()` (consulta regressiva), não `fetch_recorded_streamsets_batch()`.

---

## 5. Configurações a serem adicionadas

Em `backend/app/core/config.py` — exatamente 6 configs:

```python
# CEP Analysis
pi_cep_max_variables: int = Field(default=24)
pi_cep_result_ttl_seconds: int = Field(default=3600)
pi_cep_operation_timeout_seconds: int = Field(default=1800)
pi_cep_cleanup_interval_seconds: int = Field(default=60)
pi_cep_recorded_max_points_per_tag: int = Field(default=10000)
pi_cep_recorded_max_total_points: int = Field(default=100000)
```

Os valores são defaults configuráveis, não constantes imutáveis.

---

## 6. Schemas Pydantic — `backend/app/schemas/cep_analysis.py`

### 6.1 Request

```python
class CepAnalysisRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    equipment_id: Optional[int] = None
    section_id: Optional[int] = None
    variable_ids: Optional[List[int]] = None
    include_recorded: bool = False
```

Validações:
- `start_time` e `end_time` devem ter timezone explícito (rejeitar se naive com 422)
- Valores com `Z` ou offset válido são aceitos e normalizados para UTC
- Saída serializada em UTC com sufixo `Z`
- `start_time < end_time`
- `(end_time - start_time) <= pi_query_max_period_days`
- Interseção dos filtros resulta em ≥1 CepVariable ativa
- `len(selected_distinct_variables) <= pi_cep_max_variables`

### 6.2 Aceite

```python
class CepAnalysisAccepted(BaseModel):
    query_id: str
    query_status: Literal["pending"]
    message: str
```

### 6.3 Acompanhamento

```python
class CepQueryPending(BaseModel):
    query_id: str
    query_status: Literal["pending"]

class CepQueryRunning(BaseModel):
    query_id: str
    query_status: Literal["running"]
    started_at: datetime  # UTC com Z

class CepQueryCancelled(BaseModel):
    query_id: str
    query_status: Literal["cancelled"]
    message: str
```

### 6.4 Resultado

```python
class CepAnalysisResult(BaseModel):
    query_id: str
    query_status: Literal["completed", "failed"]
    summary: CepAnalysisSummary
    variables: List[CepVariableResult]
    diagnostics: List[CepDiagnostic] = Field(default_factory=list)
    recorded_series: Optional[List[CepRecordedSeries]] = None
    metadata: CepAnalysisMetadata

class CepAnalysisSummary(BaseModel):
    analysis_status: Literal["completed", "partial", "failed"]
    overall_pct: Optional[float] = None
    total_variables: int
    conformant_variables: int = 0
    non_conformant_variables: int = 0
    no_data_variables: int = 0
    failed_variables: int = 0
    period_start: datetime  # UTC com Z
    period_end: datetime    # UTC com Z

class CepVariableResult(BaseModel):
    variable_id: int
    code: str
    name: str
    equipment_id: int
    section_id: int
    variable_type_id: int
    conformity_pct: Optional[float] = None
    total_points: int = 0
    conformant: int = 0
    non_conformant: int = 0
    no_data: int = 0
    status: Literal["processed", "no_data", "error"]

class CepDiagnostic(BaseModel):
    tag_id: int
    tag_name: str
    variable_ids: List[int]
    error_code: str
    message: str

class CepRecordedSeries(BaseModel):
    tag_id: int
    tag_name: str
    variable_ids: List[int]
    points: List[CepRecordedPoint]
    truncated: bool = False
    source_point_count: Optional[int] = None  # null quando truncado

class CepRecordedPoint(BaseModel):
    timestamp: datetime  # UTC com Z
    value: Optional[float] = None
    good: bool = True
    questionable: bool = False
    substituted: bool = False

class CepAnalysisMetadata(BaseModel):
    pi_request_count: Optional[int] = None
    pi_points_received: Optional[int] = None
    points_returned: Optional[int] = None
    webid_cache_hits: Optional[int] = None
    webid_cache_misses: Optional[int] = None
    duration_ms: Optional[int] = None
    tags_processed: Optional[int] = None
    tags_failed: Optional[int] = None
    webid_resolved: Optional[int] = None
    recorded_total_point_limit: int  # Valor efetivo de pi_cep_recorded_max_total_points
    recorded_returned_point_count: int = 0
    recorded_total_limit_reached: bool = False
    recorded_tags_not_acquired: List[str] = Field(default_factory=list)
```

### 6.5 Omissão de `recorded_series`

Mecanismo único: `JSONResponse` com `model_dump(mode="json", exclude={"recorded_series"})`.

O decorator do GET usa `response_model` com a união dos modelos de resposta para documentar o contrato OpenAPI:

```python
CepQueryResponse = Union[
    CepQueryPending,
    CepQueryRunning,
    CepQueryCancelled,
    CepAnalysisResult,
]

@router.get(
    "/analyze/{query_id}",
    response_model=CepQueryResponse,
    responses={
        200: {"model": CepQueryResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_analysis(...) -> JSONResponse:
    # Serialização manual para controlar omissão de recorded_series
    ...
```

O endpoint retorna `JSONResponse` diretamente, mas o contrato OpenAPI é documentado pelo `response_model`.

### 6.6 Serialização com `mode="json"`

Todas as serializações usam `mode="json"` para converter `datetime` em strings ISO 8601:

```python
# Pending, running, cancelled:
JSONResponse(content=response.model_dump(mode="json"))

# Completed/failed com recorded omitido:
JSONResponse(content=result.model_dump(mode="json", exclude={"recorded_series"}))

# Completed/failed com recorded incluído:
JSONResponse(content=result.model_dump(mode="json"))
```

Propriedades garantidas:
- `datetime` serializado como string ISO 8601 com `Z`
- Campos nullable como `overall_pct=None` permanecem com `null`
- Não usa `exclude_unset` nem exclusão global de `None`

---

## 7. CepQueryStore — `backend/app/services/cep_query_store.py`

### 7.1 Estrutura

```python
@dataclass
class CepQueryEntry:
    query_id: str
    query_status: str  # pending, running, completed, failed, cancelled
    created_at: float  # time.monotonic() — para timeout
    terminal_at: Optional[float] = None  # time.monotonic() — para TTL
    started_at: Optional[datetime] = None  # datetime UTC — para resposta pública
    request: Optional[CepAnalysisRequest] = None
    result: Optional[CepAnalysisResult] = None
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)  # Libera execução da task
```

Nota: `main_task` NÃO está em `CepQueryEntry`. As tasks asyncio são mantidas exclusivamente no `QueryRegistry`.

### 7.2 Classe

```python
class CepQueryStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._entries: Dict[str, CepQueryEntry] = {}

    async def register(self, query_id: str, request: CepAnalysisRequest) -> CepQueryEntry
    async def set_running(self, query_id: str) -> bool  # False se já terminal
    async def set_result(self, query_id: str, result: CepAnalysisResult, status: str) -> bool
    async def set_cancelled(self, query_id: str) -> CancelResult
    async def get(self, query_id: str) -> Optional[CepQueryEntry]
    async def apply_timeout(self, query_id: str) -> Optional[CepQueryEntry]  # Atômico
    async def get_or_remove_expired(self, query_id: str) -> Optional[CepQueryEntry]  # Atômico
    async def remove_unaccepted(self, query_id: str) -> None  # Rollback de registro falho
    async def cleanup_expired(self) -> CleanupResult
```

### 7.3 Operação atômica de cancelamento

```python
class CancelResult(Enum):
    CANCELLED = "cancelled"              # pending/running → cancelled (HTTP 200)
    ALREADY_CANCELLED = "already_cancelled"  # já cancelled (HTTP 200 idempotente)
    ALREADY_TERMINAL = "already_terminal"    # completed/failed (HTTP 409)
    NOT_FOUND = "not_found"              # inexistente ou expirado (HTTP 404)

async def set_cancelled(self, query_id: str) -> CancelResult:
    async with self._lock:
        entry = self._entries.get(query_id)
        if entry is None:
            return CancelResult.NOT_FOUND
        if entry.query_status == "cancelled":
            return CancelResult.ALREADY_CANCELLED
        if entry.query_status in ("completed", "failed"):
            return CancelResult.ALREADY_TERMINAL
        # Transição: pending/running → cancelled
        entry.query_status = "cancelled"
        entry.terminal_at = time.monotonic()
        return CancelResult.CANCELLED
```

### 7.4 Operação atômica de timeout

```python
async def apply_timeout(self, query_id: str) -> Optional[CepQueryEntry]:
    """Aplica timeout operacional se deadline vencido.

    Retorna o entry se timeout foi aplicado (estado mudou para failed),
    None caso contrário (operação não existe, já terminal, ou não expirou).
    Todas as mutações ocorrem sob o lock.
    """
    async with self._lock:
        entry = self._entries.get(query_id)
        if entry is None:
            return None
        if entry.query_status not in ("pending", "running"):
            return None  # Já terminal
        now = time.monotonic()
        if now - entry.created_at > settings.pi_cep_operation_timeout_seconds:
            entry.query_status = "failed"
            entry.terminal_at = now
            entry.result = self._build_timeout_result(entry)
            return entry
        return None
```

### 7.5 Operação atômica de consulta/remoção de entrada terminal expirada

```python
async def get_or_remove_expired(self, query_id: str) -> Optional[CepQueryEntry]:
    """Consulta entrada, removendo-a se terminal e com TTL expirado.

    Operação atômica sob o lock:
    - Se entrada não existe: retorna None (→ 404)
    - Se entrada é terminal e TTL expirou: remove e retorna None (→ 404)
    - Se entrada é terminal e TTL válido: retorna entry (→ resposta normal)
    - Se entrada não é terminal: retorna entry (→ resposta normal)
    """
    async with self._lock:
        entry = self._entries.get(query_id)
        if entry is None:
            return None
        if entry.query_status in ("completed", "failed", "cancelled"):
            if entry.terminal_at is not None:
                now = time.monotonic()
                if now - entry.terminal_at > settings.pi_cep_result_ttl_seconds:
                    self._entries.pop(query_id, None)
                    return None  # Expirado e removido
        return entry
```

### 7.6 Rollback de registro falho

```python
async def remove_unaccepted(self, query_id: str) -> None:
    """Remove entrada que não chegou a ser aceita (registro no QueryRegistry falhou).

    Operação atômica sob o lock. Chamada apenas pelo endpoint durante rollback.
    A entrada deve estar em estado 'pending' (nunca chegou a 'running').
    """
    async with self._lock:
        self._entries.pop(query_id, None)
```

### 7.7 Cleanup sem dependência direta do QueryRegistry

```python
@dataclass
class CleanupResult:
    expired: List[str]    # IDs removidos (TTL terminal vencido)
    timed_out: List[str]  # IDs que viraram failed (timeout operacional)

async def cleanup_expired(self) -> CleanupResult:
    """Remove operações expiradas e aplica timeout.

    Retorna os query_ids que precisam de cancelamento técnico.
    O chamador é responsável por coordenar com o QueryRegistry.
    Todas as leituras e mutações ocorrem sob o lock.
    """
    async with self._lock:
        now = time.monotonic()
        expired_ids = []
        timeout_ids = []

        for entry in list(self._entries.values()):
            if entry.query_status in ("completed", "failed", "cancelled"):
                if entry.terminal_at is not None:
                    if now - entry.terminal_at > settings.pi_cep_result_ttl_seconds:
                        expired_ids.append(entry.query_id)
            elif entry.query_status in ("pending", "running"):
                if now - entry.created_at > settings.pi_cep_operation_timeout_seconds:
                    entry.query_status = "failed"
                    entry.terminal_at = now
                    entry.result = self._build_timeout_result(entry)
                    timeout_ids.append(entry.query_id)

        # Remover expirados DENTRO do lock
        for qid in expired_ids:
            self._entries.pop(qid, None)

        return CleanupResult(expired=expired_ids, timed_out=timeout_ids)
```

### 7.8 Transições

```
pending → running (set_running)
pending → cancelled (set_cancelled)
pending → failed (set_result ou apply_timeout)
running → completed (set_result)
running → failed (set_result ou apply_timeout)
running → cancelled (set_cancelled)
```

### 7.9 Invariantes

- Transição terminal é única: `set_result` não sobrescreve `completed`, `failed` ou `cancelled`
- `set_result` retorna `False` se já terminal
- `set_cancelled` é atômico: produz resultado dentro do lock
- `apply_timeout` é atômico: verifica deadline e aplica failed dentro do lock
- `get_or_remove_expired` é atômico: consulta e remove sob o mesmo lock
- `set_running` recusa operação já terminal (retorna `False`)
- Todas as leituras e mutações do dicionário, inclusive remoções, ocorrem sob o lock
- `CepQueryStore` não depende diretamente de `QueryRegistry`

### 7.10 Relógio monotônico vs timestamps públicos

- `created_at` e `terminal_at` usam `time.monotonic()` para cálculos internos de timeout/TTL
- `started_at` usa `datetime` UTC para resposta pública (`CepQueryRunning.started_at`)
- Conversão: `started_at = datetime.now(timezone.utc)` quando `set_running` é chamado
- Serialização pública: UTC com sufixo `Z` via `model_dump(mode="json")`

---

## 8. CepPiAdapter — `backend/app/services/cep_pi_adapter.py`

### 8.1 Função principal

```python
def pi_value_to_cep_sample(pi_value: PiValue) -> CepSample
```

### 8.2 Regras de conversão

| PiValue | CepSample |
|---|---|
| `float` finito | `CepSample(ts, float(v), Q)` |
| `int` finito | `CepSample(ts, float(v), Q)` |
| `bool` | Rejeitado (valor não numérico) |
| `None` | `CepSample(ts, None, Q)` |
| `NaN`, `Inf` | `CepSample(ts, None, Q)` |
| `-999.0` | `CepSample(ts, -999.0, Q)` — preservado |
| `str` | `CepSample(ts, None, Q)` |
| `dict` (digital state) | `CepSample(ts, None, Q)` |

### 8.3 Quality flags

```python
PointQuality(
    good=pi_value.good,
    questionable=pi_value.questionable,
    substituted=pi_value.substituted,
)
```

---

## 9. CepAnalysisService — `backend/app/services/cep_analysis_service.py`

### 9.1 Responsabilidades

1. Deduplicar tags PI utilizadas pelas variáveis selecionadas
2. Resolver WebIds (reutilizando infraestrutura existente)
3. Solicitar aquisição de Interpolated 5m via `streamset_client.py`
4. Solicitar aquisição de Recorded (quando `include_recorded=true`)
5. Converter PiValue → CepSample via `CepPiAdapter`
6. Calcular conformidade via `cep_calculator.py`
7. Agregar resultados e diagnósticos
8. Classificar `query_status` e `analysis_status`

Nota: o serviço NÃO carrega CepVariable do banco. Os dados materializados são recebidos do endpoint.

### 9.2 Construtor

```python
class CepAnalysisService:
    def __init__(self, provider: PiDataProvider):
        self._provider = provider
```

O serviço recebe apenas o provider PI. Não recebe `session_factory` nem `Session`.

### 9.3 Fluxo principal

```python
async def run_analysis(
    self,
    query_id: str,
    materialized_data: MaterializedAnalysisData,
    store: CepQueryStore,
    registry: QueryRegistry,
) -> None:
    """Executa a análise CEP para uma operação já registrada no store.

    Args:
        query_id: ID da operação já registrada
        materialized_data: dados materializados pelo endpoint (variáveis, tags, request)
        store: CepQueryStore (operação já registrada)
        registry: QueryRegistry (para cancelamento técnico)
    """
    try:
        # 1. Aguardar registro no QueryRegistry (liberado pelo endpoint)
        entry = await store.get(query_id)
        if entry is None:
            return
        await entry.ready_event.wait()

        # 2. Transição para running (recusa se já terminal)
        if not await store.set_running(query_id):
            return  # Operação já terminal

        # 3. Deduplicar tags
        unique_tags = self._deduplicate_tags(materialized_data.variables)

        # 4. Resolver WebIds
        web_ids = await self._resolve_web_ids(unique_tags)

        # 5. Adquirir Interpolated 5m
        interpolated_data = await self._fetch_interpolated(
            web_ids, materialized_data.request
        )

        # 6. Para cada variável: calcular conformidade
        variable_results = self._calculate_compliance(
            materialized_data.variables, interpolated_data
        )

        # 7. Se include_recorded: adquirir Recorded
        recorded_series = None
        recorded_metadata = None
        if materialized_data.request.include_recorded:
            recorded_series, recorded_metadata = await self._fetch_recorded(
                unique_tags, materialized_data.request, materialized_data.tag_variable_map
            )

        # 8. Montar resultado
        result = self._build_result(
            query_id, materialized_data.request, variable_results,
            recorded_series, recorded_metadata
        )

        # 9. Transição para completed/failed (conforme resultado)
        status = self._determine_status(variable_results)
        await store.set_result(query_id, result, status)

    except asyncio.CancelledError:
        # Cancelamento técnico do QueryRegistry
        # NÃO converter failed em cancelled
        entry = await store.get(query_id)
        if entry is not None and entry.query_status not in ("completed", "failed", "cancelled"):
            await store.set_cancelled(query_id)
        raise
    except Exception as exc:
        # Exceções não tratadas → failed
        result = self._build_error_result(query_id, exc)
        await store.set_result(query_id, result, "failed")
    finally:
        # Remover task do QueryRegistry (idempotente: pop(query_id, None))
        # Executado incondicionalmente em todas as saídas:
        # conclusão, falha, cancelamento (inclusive durante ready_event.wait()),
        # timeout, ou retorno antecipado (entry=None, set_running recusou)
        await registry.unregister(query_id)
```

Nota: `QueryRegistry.unregister()` usa `self._active.pop(query_id, None)`, portanto é idempotente e seguro mesmo quando chamado sem registro prévio (ex: task cancelada durante `ready_event.wait()` antes do endpoint completar o registro, ou retorno antecipado por `entry=None`). O `finally` incondicional garante que nenhuma task permanece registrada em qualquer cenário de saída.

### 9.4 Dados materializados

O endpoint carrega e materializa todos os dados necessários antes de criar a task:

```python
@dataclass
class MaterializedAnalysisData:
    """Dados materializados pelo endpoint, independentes de sessão ORM."""
    request: CepAnalysisRequest
    variables: List[MaterializedVariable]  # CepVariable detached da sessão
    tag_variable_map: Dict[int, List[int]]  # tag_id → [variable_ids]
    unique_tags: List[MaterializedTag]  # Tags únicas, detached

@dataclass
class MaterializedVariable:
    """CepVariable materializado, sem relacionamentos lazy."""
    id: int
    code: str
    name: str
    equipment_id: int
    section_id: int
    variable_type_id: int
    reading_tag_id: int
    lower_limit_tag_id: int
    upper_limit_tag_id: int
    target_tag_id: Optional[int] = None

@dataclass
class MaterializedTag:
    """PiTag materializado, sem relacionamentos lazy."""
    id: int
    pi_tag_name: str
    pi_server: str
    pi_web_id: Optional[str] = None
```

### 9.5 Aquisição de Interpolated 5m

```python
# Usar fetch_streamset_batch() existente
# Intervalo fixo de 5min (não configurável)
# Não expor no contrato público
```

### 9.6 Aquisição de Recorded (quando include_recorded=true)

#### Capacidade real do cliente existente

O cliente PI existente (`get_recorded_values` em `webapi_provider.py:665-704`) aceita:
- `web_id`: WebId da tag
- `start_time`: datetime
- `end_time`: datetime
- `max_count`: Optional[int] — limita o número de pontos retornados

O cliente formata os timestamps e envia como parâmetros `startTime` e `endTime` para o PI Web API.

#### Estratégia para obter os pontos mais recentes

O PI Web API suporta busca regressiva: quando `startTime` é posterior a `endTime`, os valores são retornados em ordem cronológica decrescente. Para obter os pontos mais recentes:

1. Inverter a direção da consulta: `startTime = end_time` (fim do período), `endTime = start_time` (início do período)
2. Solicitar `budget + 1` pontos via `max_count`
3. O PI Web API retornará os `budget + 1` pontos mais recentes em ordem decrescente
4. Selecionar os `budget` mais recentes
5. Reordenar cronologicamente (crescente) para a resposta

O cliente existente aceita `start_time` e `end_time` como `datetime` e os formata internamente. A inversão é transparente para o cliente.

#### Separação entre limite individual e agregado

```python
individual_limit = settings.pi_cep_recorded_max_points_per_tag
aggregate_limit = settings.pi_cep_recorded_max_total_points

# Indicadores separados:
any_individual_truncation = False  # Truncamento por limite individual
any_aggregate_truncation = False   # Truncamento por orçamento agregado
```

#### Fluxo detalhado

```python
# 1. Ordenar tags únicas lexicograficamente
sorted_tags = sorted(unique_tags, key=lambda t: t.pi_tag_name)

# 2. Para cada tag:
remaining_aggregate = aggregate_limit

for tag in sorted_tags:
    if remaining_aggregate <= 0:
        not_acquired.append(tag.pi_tag_name)
        continue

    # Orçamento da tag: menor entre limite individual e restante agregado
    budget = min(individual_limit, remaining_aggregate)

    # Consulta regressiva: startTime=fim, endTime=início
    raw_values = await provider.get_recorded_values(
        web_id=tag.pi_web_id,
        start_time=request.end_time,    # Invertido: fim como startTime
        end_time=request.start_time,    # Invertido: início como endTime
        max_count=budget + 1
    )

    # Pontos retornados em ordem decrescente (mais recentes primeiro)
    points_desc = raw_values.values

    if len(points_desc) > budget:
        # Truncamento confirmado
        truncated = True
        source_point_count = None
        selected_desc = points_desc[:budget]
        selected = sorted(selected_desc, key=lambda p: p.timestamp)  # Crescente

        # Determinar causa do truncamento
        if budget == individual_limit:
            # Truncamento por limite individual
            any_individual_truncation = True
        else:
            # Truncamento por orçamento agregado (budget < individual_limit)
            any_aggregate_truncation = True

        remaining_aggregate -= budget
    elif len(points_desc) > 0:
        # Série completa com eventos
        truncated = False
        source_point_count = len(points_desc)
        selected = sorted(points_desc, key=lambda p: p.timestamp)
        remaining_aggregate -= len(points_desc)
    else:
        # Série sem eventos
        truncated = False
        source_point_count = 0
        selected = []
        # Não decrementar orçamento

    # Montar CepRecordedSeries
    series = CepRecordedSeries(
        tag_id=tag.id,
        tag_name=tag.pi_tag_name,
        variable_ids=tag_variable_map[tag.id],
        points=[_to_recorded_point(p) for p in selected],
        truncated=truncated,
        source_point_count=source_point_count,
    )
    recorded_series.append(series)
```

#### Nota sobre ponto adicional

O ponto adicional (`budget + 1`) é técnico: não aparece em `points`, não contabiliza em `recorded_returned_point_count`, não consome orçamento.

### 9.7 Impacto efetivo do limite agregado

Conforme D8, `recorded_total_limit_reached` e `CEP_RECORDED_TOTAL_LIMIT_REACHED` somente podem ser definidos quando existir impacto efetivamente confirmado do limite agregado.

#### Mecanismo de confirmação

O único mecanismo de confirmação é o ponto técnico adicional obtido com `budget + 1`:

- **Truncamento individual**: tag retornou `budget + 1` pontos e `budget == individual_limit` → truncamento por limite individual → NÃO aciona `recorded_total_limit_reached`
- **Truncamento agregado**: tag retornou `budget + 1` pontos e `budget < individual_limit` → truncamento por orçamento agregado → aciona `recorded_total_limit_reached`
- **Série completa**: retornou ≤ `budget` → impacto NÃO confirmado

#### O que NÃO confirma impacto agregado

- Truncamento exclusivamente individual (budget == individual_limit)
- Igualdade entre `recorded_returned_point_count` e `recorded_total_point_limit`
- Orçamento zero para tags posteriores
- Existência de tags posteriores
- Consumo exatamente do orçamento sem ponto adicional

#### Regra para tags não adquiridas

Tags não adquiridas só sustentam impacto agregado se `any_aggregate_truncation == True`.

```python
# Após o loop:
recorded_total_limit_reached = any_aggregate_truncation
# CEP_RECORDED_TOTAL_LIMIT_REACHED somente se any_aggregate_truncation == True
```

### 9.8 Classificação de resultados

```python
# Variáveis:
# - status="processed": ≥1 ponto elegível (conformant + non_conformant > 0)
# - status="no_data": sem falha técnica, sem pontos elegíveis
# - status="error": falha técnica impediu processamento

# Summary:
# - analysis_status="completed": nenhuma falha técnica
# - analysis_status="partial": ≥1 resultado útil + ≥1 error
# - analysis_status="failed": nenhuma variável com resultado útil + falha técnica

# overall_pct:
# eligible_conformant = sum(v.conformant for v in variables if v.status == "processed")
# eligible_total = sum(v.conformant + v.non_conformant for v in variables if v.status == "processed")
# overall_pct = eligible_conformant / eligible_total * 100 if eligible_total > 0 else None
```

### 9.9 Diagnósticos de Recorded

Conforme D7, cada entrada de `diagnostics[]` contém: `tag_id`, `tag_name`, `variable_ids[]`, `error_code`, `message`. Todos os campos usam identificação real.

#### Tag corrente truncada pelo limite agregado

Quando uma tag é truncada pelo orçamento agregado (ponto adicional confirmado, `budget < individual_limit`):

```python
CepDiagnostic(
    tag_id=tag.id,                    # ID real da tag
    tag_name=tag.pi_tag_name,         # Nome real da tag
    variable_ids=tag_variable_map[tag.id],  # Variáveis reais consumidoras
    error_code="CEP_RECORDED_TOTAL_LIMIT_REACHED",
    message=f"Tag {tag.pi_tag_name} truncada devido ao limite agregado de pontos Recorded."
)
```

#### Tags não adquiridas (somente se any_aggregate_truncation == True)

```python
if any_aggregate_truncation:
    for tag_name in not_acquired:
        tag = tag_map[tag_name]
        CepDiagnostic(
            tag_id=tag.id,                    # ID real da tag
            tag_name=tag.pi_tag_name,         # Nome real da tag
            variable_ids=tag_variable_map[tag.id],  # Variáveis reais consumidoras
            error_code="CEP_RECORDED_TOTAL_LIMIT_REACHED",
            message=f"Tag {tag.pi_tag_name} não adquirida devido ao limite agregado de pontos Recorded."
        )
```

#### Regras

- Diagnósticos de truncamento agregado: emitidos quando `truncated=True` E `budget < individual_limit`
- Diagnósticos de tags não adquiridas: emitidos SOMENTE quando `any_aggregate_truncation == True`
- Truncamento exclusivamente individual: `truncated=True` mas sem diagnóstico `CEP_RECORDED_TOTAL_LIMIT_REACHED`
- Sem impacto confirmado → sem diagnósticos `CEP_RECORDED_TOTAL_LIMIT_REACHED`

---

## 10. Endpoints — `backend/app/api/cep.py`

### 10.1 POST /api/cep/analyze

```python
@router.post("/analyze", status_code=202)
async def create_analysis(
    payload: CepAnalysisRequest,
    db: Session = Depends(get_db_session),
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> CepAnalysisAccepted:
    # 1. Validar timezone de start_time e end_time (422 se naive)
    # 2. Validar período (start < end, ≤ max_period_days) (400 se inválido)

    # 3. Carregar, filtrar e materializar CepVariable (sessão request-scoped)
    materialized = _load_and_materialize(db, payload)

    # 4. Validar quantidade (≤ pi_cep_max_variables) (422 se exceder)
    # 5. Validar que há ≥1 variável (422 se nenhuma)

    # 6. Gerar query_id
    query_id = str(uuid.uuid4())

    # 7. Registrar no store (timeout começa aqui)
    entry = await store.register(query_id, payload)

    # 8. Criar task assíncrona (não inicia execução imediatamente)
    service = CepAnalysisService(provider=provider)
    task = asyncio.create_task(
        service.run_analysis(query_id, materialized, store, registry)
    )

    # 9. Registrar task no QueryRegistry (com rollback em caso de falha)
    try:
        await registry.register(query_id, main_task=task)
    except Exception:
        # Rollback: cancelar task, aguardar encerramento, remover do store
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await store.remove_unaccepted(query_id)
        raise  # Propagar falha (não retornar 202)

    # 10. Liberar execução da task (garante que registry já contém a task)
    entry.ready_event.set()

    # 11. Retornar 202
    return CepAnalysisAccepted(
        query_id=query_id,
        query_status="pending",
        message="Análise CEP aceita para processamento."
    )


def _load_and_materialize(
    db: Session, request: CepAnalysisRequest
) -> MaterializedAnalysisData:
    """Carrega CepVariable do banco e materializa dados independentes de sessão."""
    # Query com JOINs para carregar CepVariable + PiTags
    query = db.query(CepVariable).filter(CepVariable.active == True)

    if request.equipment_id is not None:
        query = query.filter(CepVariable.equipment_id == request.equipment_id)
    if request.section_id is not None:
        query = query.filter(CepVariable.section_id == request.section_id)
    if request.variable_ids is not None:
        query = query.filter(CepVariable.id.in_(request.variable_ids))

    cep_variables = query.all()

    # Materializar para objetos independentes de sessão
    variables = []
    tag_variable_map: Dict[int, List[int]] = {}
    unique_tag_ids: Set[int] = set()

    for cv in cep_variables:
        variables.append(MaterializedVariable(
            id=cv.id, code=cv.code, name=cv.name,
            equipment_id=cv.equipment_id, section_id=cv.section_id,
            variable_type_id=cv.variable_type_id,
            reading_tag_id=cv.reading_tag_id,
            lower_limit_tag_id=cv.lower_limit_tag_id,
            upper_limit_tag_id=cv.upper_limit_tag_id,
            target_tag_id=cv.target_tag_id,
        ))

        for tag_id in [cv.reading_tag_id, cv.lower_limit_tag_id,
                        cv.upper_limit_tag_id, cv.target_tag_id]:
            if tag_id is not None:
                unique_tag_ids.add(tag_id)
                tag_variable_map.setdefault(tag_id, []).append(cv.id)

    # Carregar tags materializadas
    tags = db.query(PiTag).filter(PiTag.id.in_(unique_tag_ids)).all()
    unique_tags = [
        MaterializedTag(
            id=t.id, pi_tag_name=t.pi_tag_name,
            pi_server=t.pi_server, pi_web_id=t.pi_web_id,
        )
        for t in tags
    ]

    return MaterializedAnalysisData(
        request=request,
        variables=variables,
        tag_variable_map=tag_variable_map,
        unique_tags=unique_tags,
    )
```

### 10.2 GET /api/cep/analyze/{query_id}

```python
CepQueryResponse = Union[
    CepQueryPending,
    CepQueryRunning,
    CepQueryCancelled,
    CepAnalysisResult,
]

@router.get(
    "/analyze/{query_id}",
    response_model=CepQueryResponse,
    responses={
        200: {"model": CepQueryResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_analysis(
    query_id: str,
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> JSONResponse:
    # 1. Aplicar timeout operacional (atômico)
    timed_out_entry = await store.apply_timeout(query_id)
    if timed_out_entry is not None:
        await registry.cancel(query_id)

    # 2. Consultar entrada, removendo se terminal expirado (atômico)
    entry = await store.get_or_remove_expired(query_id)
    if entry is None:
        raise NotFoundError("Análise não encontrada ou expirada.")

    # 3. Retornar conforme query_status
    if entry.query_status == "pending":
        response = CepQueryPending(query_id=query_id, query_status="pending")
        return JSONResponse(content=response.model_dump(mode="json"))
    elif entry.query_status == "running":
        response = CepQueryRunning(
            query_id=query_id,
            query_status="running",
            started_at=entry.started_at
        )
        return JSONResponse(content=response.model_dump(mode="json"))
    elif entry.query_status == "cancelled":
        response = CepQueryCancelled(
            query_id=query_id,
            query_status="cancelled",
            message="Operação cancelada."
        )
        return JSONResponse(content=response.model_dump(mode="json"))
    else:
        # completed ou failed
        result = entry.result
        if not entry.request.include_recorded:
            content = result.model_dump(mode="json", exclude={"recorded_series"})
            return JSONResponse(content=content)
        else:
            return JSONResponse(content=result.model_dump(mode="json"))
```

### 10.3 POST /api/cep/analyze/{query_id}/cancel

```python
@router.post("/analyze/{query_id}/cancel")
async def cancel_analysis(
    query_id: str,
    store: CepQueryStore = Depends(get_cep_query_store),
    registry: QueryRegistry = Depends(get_query_registry_dep),
) -> Union[CepQueryCancelled, ErrorResponse]:
    # 1. Aplicar timeout operacional (atômico)
    timed_out_entry = await store.apply_timeout(query_id)
    if timed_out_entry is not None:
        await registry.cancel(query_id)
        raise ConflictError("Operação já finalizada e não pode ser cancelada.")

    # 2. Consultar entrada, removendo se terminal expirado (atômico)
    entry = await store.get_or_remove_expired(query_id)
    if entry is None:
        raise NotFoundError("Análise não encontrada ou expirada.")

    # 3. Tentar cancelar (atômico)
    result = await store.set_cancelled(query_id)

    if result == CancelResult.NOT_FOUND:
        raise NotFoundError("Análise não encontrada ou expirada.")

    if result == CancelResult.ALREADY_TERMINAL:
        raise ConflictError("Operação já finalizada e não pode ser cancelada.")

    if result == CancelResult.CANCELLED:
        await registry.cancel(query_id)

    # result == CancelResult.ALREADY_CANCELLED → 200 idempotente
    return CepQueryCancelled(
        query_id=query_id,
        query_status="cancelled",
        message="Operação cancelada."
    )
```

---

## 11. Lifecycle e limpeza — alterações em `backend/app/main.py`

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    await startup_pi_provider()

    # Iniciar tarefa de limpeza CEP
    cleanup_task = asyncio.create_task(_cep_cleanup_loop())

    try:
        yield
    finally:
        # Encerramento seguro da tarefa periódica
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass  # Esperado durante shutdown
        await shutdown_pi_provider()
        logger.info("Shutting down %s", settings.app_name)


async def _cep_cleanup_loop():
    store = get_cep_query_store()
    registry = get_query_registry()
    interval = settings.pi_cep_cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            result = await store.cleanup_expired()
            # Coordenar cancelamento técnico com QueryRegistry
            for qid in result.timed_out:
                await registry.cancel(qid)
        except asyncio.CancelledError:
            raise  # Propagar cancelamento
        except Exception:
            logger.exception("CEP cleanup failed")
```

---

## 12. Router — alteração em `backend/app/api/router.py`

```python
from app.api.cep import router as cep_router

# No final da função:
api_router.include_router(cep_router, dependencies=protected)
```

---

## 13. Máquina de estados

```
        register() (endpoint POST /analyze)
            │
            ▼
       ┌─────────┐
       │ pending │ ← timeout operacional começa
       └────┬────┘
            │
  ┌─────────┼─────────┐
  │         │         │
  ▼         ▼         ▼
cancel   set_running  timeout (apply_timeout)
  │         │         │
  ▼         ▼         ▼
cancelled running   failed (diagnóstico)
            │
  ┌─────────┼─────────┐
  │         │         │
  ▼         ▼         ▼
cancel   success    error
  │         │         │
  ▼         ▼         ▼
cancelled completed  failed
```

Estados terminais: `completed`, `failed`, `cancelled`

---

## 14. Comportamento dos endpoints por estado

### GET /api/cep/analyze/{query_id}

| Estado | Antes da expiração | Após timeout operacional | Após TTL terminal |
|---|---|---|---|
| `pending` | 200 `CepQueryPending` | → `failed` → 200 (resultado com diagnóstico) | 404 |
| `running` | 200 `CepQueryRunning` | → `failed` → 200 (resultado com diagnóstico) | 404 |
| `completed` | 200 `CepAnalysisResult` | N/A | 404 |
| `failed` | 200 — dados previstos pelo contrato da D7 | N/A | 404 |
| `cancelled` | 200 `CepQueryCancelled` | N/A | 404 |
| (inexistente) | 404 | 404 | 404 |

### POST /api/cep/analyze/{query_id}/cancel

| Estado | Antes da expiração | Após timeout operacional | Após TTL terminal |
|---|---|---|---|
| `pending` | 200 `CepQueryCancelled` | → `failed` → 409 | 404 |
| `running` | 200 `CepQueryCancelled` | → `failed` → 409 | 404 |
| `completed` | 409 | N/A | 404 |
| `failed` | 409 | N/A | 404 |
| `cancelled` | 200 (idempotente) | N/A | 404 |
| (inexistente) | 404 | 404 | 404 |

---

## 15. Recorded — regras de aquisição

### 15.1 Condições

- `include_recorded=false` → Recorded não consultada; `recorded_series` omitido
- `include_recorded=true` → aquisição conforme regras abaixo

### 15.2 Orçamento

```python
budget_per_tag = min(
    settings.pi_cep_recorded_max_points_per_tag,
    remaining_aggregate_budget
)
```

### 15.3 Aquisição (busca regressiva)

1. Ordenar tags únicas lexicograficamente
2. Para cada tag:
   - Consultar em sentido regressivo: `startTime=end_time`, `endTime=start_time`, `max_count=budget+1`
   - O PI Web API retorna os pontos mais recentes em ordem decrescente
   - Se receber `budget + 1` pontos: truncamento confirmado; preservar os `budget` mais recentes
   - Se receber ≤ `budget` pontos e > 0: série completa; usar todos
   - Se receber 0 pontos: série sem eventos
   - Reordenar cronologicamente (crescente) para a resposta
   - Decrementar orçamento agregado
3. Se orçamento esgotado: interromper; tags restantes em `recorded_tags_not_acquired`

### 15.4 Detecção de truncamento

- Consultar `budget + 1` pontos em sentido regressivo
- Se receber `budget + 1`: há mais pontos → `truncated=True`
- Se receber ≤ `budget`: série completa → `truncated=False`
- Ponto adicional é técnico: não aparece em `points`, não contabiliza

### 15.5 Impacto efetivo do limite agregado

Conforme D8:
- `recorded_total_limit_reached=true` SOMENTE quando houver truncamento confirmado por orçamento agregado (`budget < individual_limit`)
- `CEP_RECORDED_TOTAL_LIMIT_REACHED` SOMENTE quando truncamento por orçamento agregado
- Truncamento exclusivamente individual (`budget == individual_limit`) NÃO aciona flag agregado
- Igualdade entre `recorded_returned_point_count` e `recorded_total_point_limit` não confirma impacto
- Orçamento zero para tags posteriores não confirma impacto
- Existência de tags posteriores não confirma que possuem eventos
- Tags não adquiridas só sustentam impacto se existir pelo menos uma confirmação de truncamento agregado anterior

### 15.6 Metadados

```python
recorded_total_point_limit = settings.pi_cep_recorded_max_total_points
recorded_returned_point_count = total_pontos_retornados
recorded_total_limit_reached = any_aggregate_truncation  # SOMENTE com confirmação real
recorded_tags_not_acquired = [tags não consultadas, ordenadas lexicograficamente]
```

---

## 16. Invariantes de concorrência

- Transição terminal é semanticamente única
- `CepQueryStore._lock` protege todas as operações, inclusive remoções
- `set_cancelled` é atômico: produz resultado dentro do lock
- `apply_timeout` é atômico: verifica deadline e aplica failed dentro do lock
- `get_or_remove_expired` é atômico: consulta e remove sob o mesmo lock
- `set_result` não sobrescreve estado terminal
- `set_running` recusa operação já terminal
- Task cancelada por timeout não transforma `failed` em `cancelled`
- `CepQueryStore` não depende diretamente de `QueryRegistry`
- Task não inicia execução antes de estar registrada no QueryRegistry (via `ready_event`)

---

## 17. Comportamento após reinício

- `CepQueryStore` é in-memory: todas as operações perdidas
- Após reinício: GET/cancel de qualquer `query_id` retorna 404
- Tarefa de limpeza inicia sobre armazenamento vazio
- Não há recuperação de operações interrompidas

---

## 18. Restrição de único worker

- Todos os endpoints devem ser atendidos pelo mesmo processo
- `query_id`, estado, resultado e tasks não são compartilhados
- Implantação deve usar um único worker
- Suporte distribuído exigirá armazenamento compartilhado futuro

---

## 19. Estratégia de testes

### 19.1 Testes unitários

| Arquivo | Cobertura |
|---|---|
| `test_cep_pi_adapter.py` | Conversão PiValue → CepSample; qualidade; rejeição de valores inválidos |
| `test_cep_query_store.py` | Transições de estado; TTL; timeout; limpeza; concorrência |
| `test_cep_analysis_service.py` | Carregamento; deduplicação; cálculo; classificação; Recorded |

### 19.2 Testes de contrato

| Arquivo | Cobertura |
|---|---|
| `test_cep_api.py` | 3 endpoints; códigos HTTP; schemas de response; cancelamento idempotente; 409 pós-terminal; omissão de `recorded_series`; timezone |

### 19.3 Cenários obrigatórios

1. Análise completa sem filtros (24 variáveis)
2. Análise com filtro por equipment_id
3. Análise com filtro por section_id
4. Análise com filtro por variable_ids
5. Filtros sem configuração ativa → 422
6. Período inválido → 400
7. Seleção > pi_cep_max_variables → 422
8. Sucesso total (analysis_status=completed)
9. Sucesso parcial (analysis_status=partial)
10. Falha total (analysis_status=failed)
11. Cancelamento de pending
12. Cancelamento de running
13. Cancelamento de completed → 409
14. Cancelamento idempotente de cancelled
15. Timeout operacional contado desde register()
16. Timeout não reiniciado em running
17. TTL terminal contado da transição terminal
18. TTL não renovado por GET
19. TTL não renovado por cancelamento idempotente
20. Limpeza no acesso (apply_timeout)
21. Limpeza periódica (cleanup_expired)
22. Coordenação do timeout com QueryRegistry
23. Task tecnicamente cancelada sem trocar failed por cancelled
24. Corrida entre conclusão, cancelamento e timeout
25. Cancelamento durante aquisição
26. Omissão real de recorded_series (chave ausente no JSON)
27. Ausência total de chamadas Recorded quando include_recorded=false
28. Recorded com include_recorded=true (presente)
29. Recorded com truncamento por limite individual (flag agregado false)
30. Recorded com truncamento por limite agregado (flag agregado true)
31. Recorded com tags não adquiridas
32. source_point_count null quando truncado
33. source_point_count exato quando completo
34. source_point_count 0 quando sem eventos
35. Tags compartilhadas consultadas uma vez
36. Ordem lexicográfica das tags
37. Pontos mais recentes de todo o intervalo (busca regressiva)
38. Igualdade com o limite sem impacto confirmado
39. Contagem de pontos retornados
40. Valor configurado efetivo em recorded_total_point_limit
41. recorded_tags_not_acquired em ordem lexicográfica
42. Recorded sem alterar Interpolated 5m, conformidade, percentuais ou contadores
43. overall_pct com denominador > 0
44. overall_pct com denominador = 0 (None)
45. Variáveis no_data não participam do overall_pct
46. Variáveis error não participam do overall_pct
47. Timestamps públicos normalizados para UTC Z
48. Sessão de banco encerrada com segurança
49. Comportamento após reinício
50. Execução com um único worker
51. Orçamento agregado exatamente consumido, sem ponto adicional, flag false
52. Tags posteriores não adquiridas sem confirmação agregada, flag false
53. Task não executa antes de registro no QueryRegistry
54. registry.register() falha: task cancelada e aguardada, entrada removida, nenhum 202
55. Cancelamento enquanto task aguarda ready_event
56. unregister() executado em conclusão, falha, cancelamento e timeout
57. Nenhuma operação pending órfã após falha de registro
58. Nenhuma task permanece no registry após qualquer saída

---

## 20. Riscos técnicos

| Risco | Impacto | Mitigação |
|---|---|---|
| PI Web API indisponível durante análise | Alto | Falha parcial com diagnósticos; não converte em failed se houver resultados úteis |
| Resposta Recorded muito grande | Médio | Limites individual e agregado; truncamento explícito |
| Operações presas por crash | Baixo | Timeout operacional; limpeza periódica |
| Concorrência entre conclusão e timeout | Médio | Transição terminal única; lock no store |
| Tags compartilhadas com muitos pontos | Médio | Deduplicação; orçamento agregado |

---

## 21. Ordem de implementação

### Fase 1: Fundações
1. `backend/app/core/config.py` — Adicionar 6 configs CEP
2. `backend/app/services/cep_query_store.py` — CepQueryStore
3. `backend/app/services/cep_pi_adapter.py` — CepPiAdapter
4. `backend/tests/test_cep_query_store.py` — Testes do store
5. `backend/tests/test_cep_pi_adapter.py` — Testes do adaptador

### Fase 2: Schemas
6. `backend/app/schemas/cep_analysis.py` — Todos os schemas

### Fase 3: Orquestrador
7. `backend/app/services/cep_analysis_service.py` — CepAnalysisService
8. `backend/tests/test_cep_analysis_service.py` — Testes do orquestrador

### Fase 4: Endpoints
9. `backend/app/api/cep.py` — Router com 3 endpoints
10. `backend/app/api/router.py` — Registrar router
11. `backend/app/main.py` — Lifecycle da limpeza
12. `backend/tests/test_cep_api.py` — Testes de contrato

### Fase 5: Validação
13. Executar testes existentes (não devem quebrar)
14. Executar novos testes
15. Verificar lint e typecheck

---

## 22. Dependências

| Dependência | Status |
|---|---|
| `cep_calculator.py` | Existente, 87 testes aprovados |
| `streamset_client.py` | Existente — `fetch_streamset_batch()` para Interpolated 5m |
| `WebIdCache` | Existente |
| `QueryRegistry` | Existente — `register()`, `unregister()`, `cancel()` |
| `CepVariable` model | Existente, 24 variáveis |
| `PiTag` model | Existente |
| `PiDataProvider` | Existente — `get_recorded_values()` para Recorded |
| Pydantic 2.6.4 | Existente |
| FastAPI | Existente |
| SQLAlchemy | Existente |

---

## 23. Validações

Antes de implementar:
- [ ] D7 e D8 completamente lidas e compreendidas
- [ ] Código existente inspecionado
- [ ] Padrões do repositório identificados
- [ ] Configurações existentes verificadas
- [ ] Testes existentes passam

Durante implementação:
- [ ] Cada fase testada antes de avançar
- [ ] Testes existentes continuam passando
- [ ] Novos testes escritos para cada componente
- [ ] Lint e typecheck sem erros

Após implementação:
- [ ] Todos os cenários de teste cobertos
- [ ] Contrato público idêntico ao D7
- [ ] Comportamento de Recorded idêntico ao D8
- [ ] TTL e limpeza funcionando
- [ ] Cancelamento idempotente

---

## 24. Resumo do plano

O plano implementa a capacidade de análise CEP conforme D7 e D8:

- **3 endpoints**: POST /analyze (202), GET /analyze/{query_id} (200), POST /analyze/{query_id}/cancel (200/409)
- **Execução assíncrona**: CepQueryStore in-memory, QueryRegistry para cancelamento
- **Cálculo**: cep_calculator.py existente, sem alterações
- **Recorded**: opcional, limites individual (10.000) e agregado (100.000), truncamento explícito, busca regressiva via `provider.get_recorded_values()`
- **Timeout operacional**: configurável (default 1800s), começa em register()
- **TTL terminal**: configurável (default 3600s), começa na transição terminal
- **Limpeza**: periódica (default 60s) + verificação no acesso (`get_or_remove_expired`)
- **Concorrência**: single-process, transições terminais únicas
- **Persistência**: nenhuma nesta primeira implementação

Total: 9 novos arquivos, 3 arquivos alterados, 12 componentes reutilizados sem alteração.
