# Especificação Frontend — Módulo de Análise CEP

## 1. Objetivo e escopo

Especificar uma nova página no frontend existente para executar e visualizar análises CEP assíncronas, integrada ao backend já implementado.

A página deve permitir:
- Configurar e enviar uma análise CEP
- Acompanhar o processamento assíncrono
- Cancelar operações em andamento
- Visualizar resultados concluídos
- Consultar diagnósticos e erros
- Visualizar dados Recorded opcionais

---

## 2. Inventário do frontend atual

| Aspecto | Tecnologia/Padrão |
|---|---|
| Framework | React 18.2.0 |
| Linguagem | TypeScript 5.4.3 |
| Build | Vite 5.2.6 |
| UI | Bootstrap 5.3.3 + react-bootstrap 2.10.2 |
| Ícones | Bootstrap Icons 1.11.3 |
| Gráficos | ECharts 5.5.1 |
| Roteamento | react-router-dom 6.22.3 |
| Testes | Vitest 1.4.0 + Testing Library |
| HTTP | Fetch API com wrapper customizado (`httpClient`) |
| Autenticação | JWT em cookie + CSRF double-submit |
| Layout | Sidebar + Topbar + Content (`MainLayout.tsx`) |
| Páginas | Dashboard, Cadastros, Visualização de Dados |
| Navegação | Sidebar com seções "Cadastros" e "Analises" |

### Estrutura de diretórios

```
frontend/src/
├── api/              # Cliente HTTP e endpoints
├── auth/             # Autenticação e proteção de rotas
├── components/       # Componentes reutilizáveis
├── constants/        # Constantes
├── layouts/          # Layout principal (MainLayout)
├── pages/            # Páginas da aplicação
├── styles/           # CSS global (app.css)
├── types/            # Tipos TypeScript
├── utils/            # Utilitários
├── App.tsx           # Roteamento principal
└── main.tsx          # Entry point
```

### Padrão de páginas existentes

- `PageHeader` com título, subtítulo e ações
- Cards (`react-bootstrap`) para conteúdo
- `DataFiltersPanel` para filtros
- `EChartsWrapper` para gráficos
- `ErrorAlert` e `FeedbackAlert` para mensagens
- `LoadingState` e `EmptyState` para estados
- `StatusBadge` e `ActiveBadge` para status
- `ConfirmModal` para confirmações

### Menu lateral (seção "Analises")

```typescript
const ANALISES_ITEMS: NavItem[] = [
  { to: "/analises/visualizacao", label: "Visualizacao de Dados", icon: "bi-graph-up" },
];
```

---

## 3. Contrato real dos endpoints

### 3.1 POST /api/cep/analyze

| Aspecto | Valor |
|---|---|
| Método | POST |
| URL | `/api/cep/analyze` |
| Content-Type | `application/json` |
| Autenticação | JWT cookie + CSRF |
| Sucesso | HTTP 202 |

**Request body:**
```json
{
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-01-02T00:00:00Z",
  "equipment_id": null,
  "section_id": null,
  "variable_ids": null,
  "include_recorded": false
}
```

**Response 202:**
```json
{
  "query_id": "uuid",
  "query_status": "pending",
  "message": "Análise CEP aceita para processamento."
}
```

**Erros:**
- 400: período inválido (start >= end ou > max_period_days)
- 422: body inválido, filtros sem variáveis, seleção > 24, timestamp sem timezone

### 3.2 GET /api/cep/analyze/{query_id}

| Aspecto | Valor |
|---|---|
| Método | GET |
| URL | `/api/cep/analyze/{query_id}` |
| Autenticação | JWT cookie |
| Sucesso | HTTP 200 |

**Responses possíveis:**

**pending:**
```json
{
  "query_id": "uuid",
  "query_status": "pending"
}
```

**running:**
```json
{
  "query_id": "uuid",
  "query_status": "running",
  "started_at": "2026-08-04T12:00:00Z"
}
```

**cancelled:**
```json
{
  "query_id": "uuid",
  "query_status": "cancelled",
  "message": "Operação cancelada."
}
```

**completed/failed:**
```json
{
  "query_id": "uuid",
  "query_status": "completed",
  "summary": {
    "analysis_status": "completed",
    "overall_pct": 95.5,
    "total_variables": 24,
    "conformant_variables": 20,
    "non_conformant_variables": 3,
    "no_data_variables": 1,
    "failed_variables": 0,
    "period_start": "2026-01-01T00:00:00Z",
    "period_end": "2026-01-02T00:00:00Z"
  },
  "variables": [...],
  "diagnostics": [...],
  "recorded_series": null,
  "metadata": {
    "pi_request_count": 8,
    "duration_ms": 5000,
    "recorded_total_point_limit": 100000,
    "recorded_returned_point_count": 0,
    "recorded_total_limit_reached": false,
    "recorded_tags_not_acquired": []
  }
}
```

**Erros:**
- 404: query_id inexistente ou expirado

### 3.3 POST /api/cep/analyze/{query_id}/cancel

| Aspecto | Valor |
|---|---|
| Método | POST |
| URL | `/api/cep/analyze/{query_id}/cancel` |
| Autenticação | JWT cookie + CSRF |
| Sucesso | HTTP 200 |

**Response 200:**
```json
{
  "query_id": "uuid",
  "query_status": "cancelled",
  "message": "Operação cancelada."
}
```

**Erros:**
- 404: query_id inexistente ou expirado
- 409: operação já em estado terminal (completed/failed)

---

## 4. Schemas relevantes

### 4.1 CepVariableResult

```typescript
interface CepVariableResult {
  variable_id: number;
  code: string;
  name: string;
  equipment_id: number;
  section_id: number;
  variable_type_id: number;
  conformity_pct: number | null;
  total_points: number;
  conformant: number;
  non_conformant: number;
  no_data: number;
  status: "processed" | "no_data" | "error";
}
```

### 4.2 CepAnalysisSummary

```typescript
interface CepAnalysisSummary {
  analysis_status: "completed" | "partial" | "failed";
  overall_pct: number | null;
  total_variables: number;
  conformant_variables: number;
  non_conformant_variables: number;
  no_data_variables: number;
  failed_variables: number;
  period_start: string;
  period_end: string;
}
```

### 4.3 CepDiagnostic

```typescript
interface CepDiagnostic {
  tag_id: number;
  tag_name: string;
  variable_ids: number[];
  error_code: string;
  message: string;
}
```

### 4.4 CepRecordedSeries

```typescript
interface CepRecordedSeries {
  tag_id: number;
  tag_name: string;
  variable_ids: number[];
  points: CepRecordedPoint[];
  truncated: boolean;
  source_point_count: number | null;
}

interface CepRecordedPoint {
  timestamp: string;
  value: number | null;
  good: boolean;
  questionable: boolean;
  substituted: boolean;
}
```

### 4.5 CepAnalysisMetadata

```typescript
interface CepAnalysisMetadata {
  pi_request_count: number | null;
  pi_points_received: number | null;
  points_returned: number | null;
  webid_cache_hits: number | null;
  webid_cache_misses: number | null;
  duration_ms: number | null;
  tags_processed: number | null;
  tags_failed: number | null;
  webid_resolved: number | null;
  recorded_total_point_limit: number;
  recorded_returned_point_count: number;
  recorded_total_limit_reached: boolean;
  recorded_tags_not_acquired: string[];
}
```

---

## 5. Fluxo da operação assíncrona

```
┌─────────────┐     POST /analyze      ┌──────────────┐
│  Formulário │ ──────────────────────► │  HTTP 202    │
│  de análise  │                         │  query_id    │
└─────────────┘                         └──────┬───────┘
                                               │
                                               ▼
                                    ┌──────────────────┐
                                    │  Polling GET     │
                                    │  /analyze/{id}   │
                                    └────────┬─────────┘
                                             │
                          ┌──────────────────┼──────────────────┐
                          │                  │                  │
                          ▼                  ▼                  ▼
                    ┌──────────┐      ┌──────────┐      ┌──────────┐
                    │ pending  │      │ running  │      │completed │
                    │          │      │          │      │  failed  │
                    │ Polling  │      │ Polling  │      │  Result  │
                    │ continua │      │ continua │      │          │
                    └──────────┘      └──────────┘      └──────────┘
                          │
                          ▼
                    ┌──────────┐
                    │cancelled │
                    └──────────┘
```

**Regras de polling:**
- Intervalo: 2 segundos enquanto `pending` ou `running`
- Parar quando: `completed`, `failed`, `cancelled`, ou erro 404
- Timeout do polling: 30 minutos (igual ao backend)
- Cancelar polling ao desmontar componente

---

## 6. Rota proposta

```
/analises/cep
```

Integrada à seção "Analises" existente no sidebar.

---

## 7. Ponto de integração na navegação

### 7.1 Sidebar (`MainLayout.tsx`)

Adicionar ao array `ANALISES_ITEMS`:

```typescript
const ANALISES_ITEMS: NavItem[] = [
  { to: "/analises/visualizacao", label: "Visualizacao de Dados", icon: "bi-graph-up" },
  { to: "/analises/cep", label: "Analise CEP", icon: "bi-clipboard-data" },
];
```

### 7.2 Router (`App.tsx`)

Adicionar rota:

```tsx
<Route path="analises/cep" element={<CepAnalysisPage />} />
```

---

## 8. Estrutura visual da página

### Wireframe textual

```
┌─────────────────────────────────────────────────────────────────┐
│ PageHeader: "Analise CEP"                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─ Configuração ─────────────────────────────────────────────┐ │
│  │                                                             │ │
│  │  Equipamento: [Select]     Seção: [Select]                 │ │
│  │  Variáveis: [MultiSelect]                                  │ │
│  │                                                             │ │
│  │  Data início: [DateTimePicker]   Data fim: [DateTimePicker]│ │
│  │                                                             │ │
│  │  ☐ Incluir dados Recorded                                  │ │
│  │                                                             │ │
│  │  ┌─ Resumo ──────────────────────────────────────────┐     │ │
│  │  │ Equipamento: RB1    Seção: Todas                   │     │ │
│  │  │ Variáveis: 24       Período: 01/01 - 02/01/2026   │     │ │
│  │  │ Recorded: Não                                      │     │ │
│  │  └────────────────────────────────────────────────────┘     │ │
│  │                                                             │ │
│  │  [Iniciar Análise]                                         │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ Acompanhamento ──────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  Estado: ▶ Running                                         │  │
│  │  ID: abc-123-def                                           │  │
│  │  Início: 2026-08-04 12:00:00                               │  │
│  │                                                            │  │
│  │  [Cancelar Análise]                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Resultado ────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌─ Resumo Geral ────────────────────────────────────┐     │  │
│  │  │ Status: ✓ Completed    Conformidade: 95.5%        │     │  │
│  │  │ Conformes: 20  Não conformes: 3  Sem dados: 1     │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                            │  │
│  │  ┌─ Resultados por Variável ──────────────────────────┐     │  │
│  │  │ Variável      Status    Conformidade  Total        │     │  │
│  │  │ ─────────────────────────────────────────────────── │     │  │
│  │  │ Escova 01     ✓ proc    100.0%       1000          │     │  │
│  │  │ Escova 02     ✓ proc    85.5%        1000          │     │  │
│  │  │ Zona 01       ⚠ no_data —            0             │     │  │
│  │  │ ...                                                  │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                            │  │
│  │  ┌─ Diagnósticos ────────────────────────────────────┐     │  │
│  │  │ ⚠ PI_TIMEOUT: Tag LFI_RB1_COR_ESC1 timeout       │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                            │  │
│  │  ┌─ Recorded (opcional) ─────────────────────────────┐     │  │
│  │  │ [Expandir]                                         │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Componentes novos necessários

| Componente | Responsabilidade |
|---|---|
| `CepAnalysisPage.tsx` | Página principal com estado e lógica |
| `CepAnalysisForm.tsx` | Formulário de configuração |
| `CepAnalysisTracking.tsx` | Acompanhamento assíncrono |
| `CepAnalysisResult.tsx` | Exibição do resultado |
| `CepVariableTable.tsx` | Tabela de resultados por variável |
| `CepDiagnosticsList.tsx` | Lista de diagnósticos |
| `CepRecordedPanel.tsx` | Painel de dados Recorded |
| `CepSummaryCards.tsx` | Cards de resumo geral |
| `CepConformityChart.tsx` | Gráfico de conformidade (ECharts) |

---

## 10. Componentes existentes reutilizados

| Componente | Uso |
|---|---|
| `PageHeader` | Cabeçalho da página |
| `DataFiltersPanel` | Filtros de equipamento/seção (adaptado) |
| `EChartsWrapper` | Gráficos |
| `ErrorAlert` | Erros de API |
| `FeedbackAlert` | Mensagens de sucesso/info |
| `LoadingState` | Estado de carregamento |
| `EmptyState` | Estado vazio |
| `StatusBadge` | Status da análise |
| `ConfirmModal` | Confirmação de cancelamento |
| `TagMultiSelect` | Seleção múltipla de variáveis |

---

## 11. Estados de cada componente

### CepAnalysisForm

| Estado | Descrição |
|---|---|
| `idle` | Formulário pronto para preenchimento |
| `validating` | Validação local em andamento |
| `submitting` | Envio da análise (aguardando 202) |
| `submitted` | Análise aceita (202 recebido) |
| `error` | Erro de validação ou envio |

### CepAnalysisTracking

| Estado | Descrição |
|---|---|
| `pending` | Aguardando início do processamento |
| `running` | Processamento em andamento |
| `completed` | Análise concluída |
| `failed` | Análise falhou |
| `cancelled` | Análise cancelada |
| `expired` | Operação expirada (404) |
| `error` | Erro de conexão |

### CepAnalysisResult

| Estado | Descrição |
|---|---|
| `loading` | Carregando resultado |
| `loaded` | Resultado carregado |
| `empty` | Resultado sem dados |
| `partial` | Resultado parcial (analysis_status=partial) |
| `error` | Erro ao carregar |

---

## 12. Regras do formulário

### Validações locais

| Campo | Regra | Erro |
|---|---|---|
| `start_time` | Obrigatório, com timezone | "Data inicial é obrigatória" |
| `end_time` | Obrigatório, > start_time | "Data final deve ser posterior à inicial" |
| `end_time - start_time` | ≤ 366 dias | "Período máximo é de 366 dias" |
| `variable_ids` | ≤ 24 se selecionados | "Máximo de 24 variáveis" |
| Pelo menos 1 variável | Filtros devem resultar em ≥1 | "Nenhuma variável encontrada para os filtros" |

### Comportamento

- Filtros são opcionais: sem filtros = todas as 24 variáveis ativas
- `include_recorded` default: `false`
- Timestamps devem incluir timezone (Z ou offset)
- Validação local antes do envio
- Resumo atualizado em tempo real conforme filtros

---

## 13. Regras de polling e encerramento

### Início do polling

- Após receber 202 com `query_id`
- Primeiro poll imediato
- Intervalo: 2 segundos

### Continuação

- Enquanto `query_status` for `pending` ou `running`
- Parar ao receber `completed`, `failed` ou `cancelled`
- Parar ao receber 404 (expirado)
- Parar ao receber erro de conexão (após 3 tentativas)

### Timeout do polling

- Máximo: 30 minutos
- Após timeout: mostrar mensagem de timeout
- Permitir consulta manual posterior

### Cancelamento do polling

- Ao desmontar componente
- Ao cancelar análise
- Ao receber estado terminal

---

## 14. Regras de cancelamento

### Quando permitido

- `query_status` = `pending` ou `running`
- Operação não expirada

### Fluxo

1. Mostrar `ConfirmModal` com mensagem
2. `POST /api/cep/analyze/{query_id}/cancel`
3. Se 200: atualizar estado para `cancelled`
4. Se 409: mostrar "Operação já finalizada"
5. Se 404: mostrar "Operação não encontrada ou expirada"

### Após cancelamento

- Parar polling
- Mostrar mensagem de cancelamento
- Permitir iniciar nova análise

---

## 15. Tratamento de cada código HTTP

### POST /analyze

| Código | Tratamento |
|---|---|
| 202 | Extrair `query_id`, iniciar polling |
| 400 | Mostrar erro de período inválido |
| 422 | Mostrar erro de validação (body, filtros, seleção) |
| 401 | Redirecionar para login |
| 500 | Mostrar erro genérico |

### GET /analyze/{query_id}

| Código | Tratamento |
|---|---|
| 200 | Processar conforme `query_status` |
| 404 | Marcar como expirado, parar polling |
| 401 | Redirecionar para login |
| 500 | Mostrar erro, continuar polling (até 3 tentativas) |

### POST /cancel

| Código | Tratamento |
|---|---|
| 200 | Atualizar estado para `cancelled` |
| 404 | Mostrar "Operação não encontrada" |
| 409 | Mostrar "Operação já finalizada" |
| 401 | Redirecionar para login |

---

## 16. Apresentação dos resultados

### 16.1 Resumo geral (CepSummaryCards)

| Card | Dado | Formato |
|---|---|---|
| Status | `analysis_status` | Badge: completed (verde), partial (amarelo), failed (vermelho) |
| Conformidade | `overall_pct` | Percentual ou "—" se null |
| Conformes | `conformant_variables` | Número |
| Não conformes | `non_conformant_variables` | Número |
| Sem dados | `no_data_variables` | Número |
| Erros | `failed_variables` | Número |

### 16.2 Tabela de variáveis (CepVariableTable)

| Coluna | Campo | Formato |
|---|---|---|
| Variável | `name` | Texto |
| Código | `code` | Texto |
| Status | `status` | Badge: processed (verde), no_data (cinza), error (vermelho) |
| Conformidade | `conformity_pct` | Percentual ou "—" se null |
| Total pontos | `total_points` | Número |
| Conformes | `conformant` | Número |
| Não conformes | `non_conformant` | Número |
| Sem dados | `no_data` | Número |

### 16.3 Diagnósticos (CepDiagnosticsList)

Para cada `CepDiagnostic`:
- Ícone de alerta (warning)
- `error_code` em destaque
- `tag_name` se disponível
- `message` descritivo
- `variable_ids` afetadas

### 16.4 Gráfico de conformidade (CepConformityChart)

- Pie chart ou bar chart com distribuição: conformes, não conformes, sem dados, erros
- Usar ECharts já existente
- Cores: verde (conforme), vermelho (não conforme), cinza (sem dados), laranja (erro)

### 16.5 Recorded (CepRecordedPanel)

- Seção expansível (colapsada por padrão)
- Somente quando `recorded_series` presente
- Para cada série: tag_name, quantidade de pontos, truncated
- Tabela de pontos (timestamp, value, good)
- Alerta se `recorded_total_limit_reached`
- Lista de tags não adquiridas se houver

---

## 17. Comportamento dos gráficos e tabelas

### Gráficos

- Biblioteca: ECharts (já existente)
- Wrapper: `EChartsWrapper`
- Responsivo: sim
- Tema: seguir padrão existente
- Tooltip: formato legível com timestamp e valor

### Tabelas

- Componente: Table do react-bootstrap
- Ordenação: por nome da variável (padrão)
- Filtro: busca por nome/código
- Paginação: não necessária (máximo 24 variáveis)

---

## 18. Responsividade

| Breakpoint | Layout |
|---|---|
| Desktop (≥1200px) | Sidebar fixa + conteúdo com cards lado a lado |
| Tablet (768-1199px) | Sidebar recolhível + cards empilhados |
| Mobile (<768px) | Sidebar oculta + conteúdo full-width |

- Formulário: campos empilhados em mobile
- Tabela: scroll horizontal em mobile
- Cards: 1 coluna em mobile, 2-3 em desktop
- Gráficos: responsivos via EChartsWrapper

---

## 19. Acessibilidade

- Labels associados a todos os inputs
- ARIA labels em botões e ícones
- Contraste mínimo WCAG AA
- Navegação por teclado
- Focus visible em elementos interativos
- Mensagens de erro associadas a campos
- Live regions para atualizações de polling

---

## 20. Critérios de aceitação testáveis

| # | Critério | Testável |
|---|---|---|
| 1 | Página acessível via menu lateral | Navegar para /analises/cep |
| 2 | Formulário aceita filtros opcionais | Enviar sem filtros |
| 3 | Validação de período | Enviar start >= end |
| 4 | Validação de timezone | Enviar timestamp sem Z |
| 5 | 202 recebido e polling iniciado | Mockar 202, verificar polling |
| 6 | Polling a cada 2s | Verificar intervalos |
| 7 | Cancelamento com confirmação | Clicar cancelar, confirmar modal |
| 8 | Resultado completo exibido | Mockar completed, verificar cards |
| 9 | Resultado parcial exibido | Mockar partial, verificar alerta |
| 10 | Diagnósticos exibidos | Mockar diagnostics, verificar lista |
| 11 | Recorded omitido quando false | Verificar ausência do painel |
| 12 | Recorded presente quando true | Mockar recorded, verificar painel |
| 13 | Erro 400 tratado | Mockar 400, verificar mensagem |
| 14 | Erro 422 tratado | Mockar 422, verificar mensagem |
| 15 | Erro 404 tratado | Mockar 404, verificar expiração |
| 16 | Erro 409 tratado | Mockar 409, verificar mensagem |
| 17 | Timeout do polling | Aguardar 30min ou mockar |
| 18 | Cancelamento do polling ao desmontar | Navegar para outra página |
| 19 | Responsividade mobile | Redimensionar viewport |
| 20 | Acessibilidade | Verificar labels e ARIA |

---

## 21. Casos de teste do frontend

| # | Cenário | Componente |
|---|---|---|
| 1 | Formulário renderiza corretamente | CepAnalysisForm |
| 2 | Filtros opcionais funcionam | CepAnalysisForm |
| 3 | Validação de período | CepAnalysisForm |
| 4 | Validação de timezone | CepAnalysisForm |
| 5 | Envio com sucesso (202) | CepAnalysisPage |
| 6 | Erro de validação (422) | CepAnalysisPage |
| 7 | Erro de período (400) | CepAnalysisPage |
| 8 | Polling inicia após 202 | CepAnalysisTracking |
| 9 | Polling para em completed | CepAnalysisTracking |
| 10 | Polling para em failed | CepAnalysisTracking |
| 11 | Polling para em cancelled | CepAnalysisTracking |
| 12 | Polling para em 404 | CepAnalysisTracking |
| 13 | Cancelamento com sucesso | CepAnalysisTracking |
| 14 | Cancelamento já finalizada (409) | CepAnalysisTracking |
| 15 | Resultado completo renderizado | CepAnalysisResult |
| 16 | Resultado parcial renderizado | CepAnalysisResult |
| 17 | overall_pct null exibido como "—" | CepSummaryCards |
| 18 | Tabela de variáveis | CepVariableTable |
| 19 | Diagnósticos renderizados | CepDiagnosticsList |
| 20 | Recorded omitido | CepRecordedPanel |
| 21 | Recorded com dados | CepRecordedPanel |
| 22 | Recorded truncado | CepRecordedPanel |
| 23 | Recorded com limite agregado | CepRecordedPanel |
| 24 | Gráfico de conformidade | CepConformityChart |
| 25 | Polling cancelado ao desmontar | CepAnalysisPage |

---

## 22. Arquivos que provavelmente serão criados

```
frontend/src/pages/CepAnalysisPage.tsx
frontend/src/components/CepAnalysisForm.tsx
frontend/src/components/CepAnalysisTracking.tsx
frontend/src/components/CepAnalysisResult.tsx
frontend/src/components/CepVariableTable.tsx
frontend/src/components/CepDiagnosticsList.tsx
frontend/src/components/CepRecordedPanel.tsx
frontend/src/components/CepSummaryCards.tsx
frontend/src/components/CepConformityChart.tsx
```

---

## 23. Arquivos que provavelmente serão alterados

```
frontend/src/App.tsx                    # Adicionar rota
frontend/src/layouts/MainLayout.tsx     # Adicionar item no menu
frontend/src/api/index.ts              # Adicionar cepApi
frontend/src/types/index.ts            # Adicionar tipos CEP
```

---

## 24. Riscos e decisões não resolvidas

| Risco | Impacto | Mitigação |
|---|---|---|
| Polling consome recursos | Baixo | Intervalo de 2s; parar em estados terminais |
| Resultado grande (recorded) | Médio | Seção expansível; paginação futura se necessário |
| Timeout de 30min longo | Baixo | Permitir consulta manual posterior |
| ECharts em mobile | Baixo | Wrapper já responsivo |
| Sessão expira durante polling | Médio | Tratar 401 e redirecionar |

---

## Resumo

| Aspecto | Valor |
|---|---|
| Framework | React 18 + TypeScript + Vite |
| UI | Bootstrap 5 + react-bootstrap |
| Gráficos | ECharts |
| Rota proposta | `/analises/cep` |
| Menu | Seção "Analises" do sidebar |
| Componentes reutilizados | 10 |
| Componentes novos | 9 |
| Endpoints | 3 (POST analyze, GET status, POST cancel) |
| Estados cobertos | 14 |
| Cenários de teste | 25 |
