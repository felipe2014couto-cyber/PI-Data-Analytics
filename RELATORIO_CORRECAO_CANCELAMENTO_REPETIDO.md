# Relatório de Correção — Cancelamento Repetido

## Problema

O frontend enviava repetidamente `POST /api/time-series/{query_id}/cancel` para o
mesmo `query_id` já finalizado. Isso ocorria porque o `handleCancel()` não tinha
proteção contra cliques múltiplos.

## Causa Raiz

`handleCancel()` em `DataVisualizationPage.tsx` (linha 452) chamava
`timeSeriesApi.cancelQuery(qid)` sem verificar se o cancelamento já havia sido
solicitado para aquele `query_id`. Cada clique no botão "Cancelar" disparava uma
nova requisição de cancelamento.

## Alterações Realizadas

### Backend — 1 arquivo alterado

| Arquivo | Linha | Alteração |
|---------|-------|-----------|
| `backend/app/api/time_series.py` | 74 | `logger.warning` → `logger.info` para cancelamento de consulta inexistente/finalizada |

### Frontend — 2 arquivos alterados

#### `frontend/src/pages/DataVisualizationPage.tsx`

| O quê | Detalhes |
|-------|----------|
| Novo estado `cancelling` | Rastreia se o cancelamento está em andamento (boolean) |
| Novo ref `cancelledQueryIdsRef` | `Set<string>` que armazena `query_id`s já cancelados |
| `handleCancel()` atualizado | Verifica `cancelledQueryIdsRef` antes de enviar POST; retorna imediatamente se já cancelado |
| `runQuery()` atualizado | Reseta `cancelling = false` ao iniciar nova consulta |
| AbortError tratado | Mostra "Consulta cancelada." na interface quando o cancelamento intencional ocorre |
| Sucesso limpa `queryIdRef` | `queryIdRef.current = null` ao finalizar normalmente — impede cancelamento de consulta concluída |
| Prop `cancelling` passada ao DataFiltersPanel | Habilita desabilitação do botão no componente filho |

#### `frontend/src/components/DataFiltersPanel.tsx`

| O quê | Detalhes |
|-------|----------|
| Prop `cancelling?: boolean` | Opcional, recebida do componente pai |
| Botão Cancelar `disabled={cancelling}` | Desabilitado imediatamente no primeiro clique |
| Texto dinâmico | Mostra "Cancelando..." enquanto `cancelling` é `true` |

### Testes — 2 arquivos alterados

#### `frontend/tests/mocks/api.ts`

Adicionado `cancelQuery: vi.fn()` ao `apiMock` e ao módulo mock.

#### `frontend/tests/dataVisualization.test.tsx`

7 novos testes no describe `cancelamento de consulta`:

| Teste | O que verifica |
|-------|----------------|
| `botao possui type='button'` | Botão tem `type="button"` |
| `um clique gera um POST e o botao fica desabilitado` | 1 clique → 1 POST, botão disabled, texto "Cancelando..." |
| `varios cliques rapidos geram somente um POST` | 3 cliques → 1 POST |
| `AbortError nao gera segundo POST` | AbortError não dispara novo POST |
| `consulta concluida nao pode ser cancelada` | Query completa → Cancel some, nova query → Cancel aparece |
| `cliques apos primeiro sao ignorados (sem novo POST)` | Clique após cancel → sem novo POST |
| `falha no endpoint ainda aborta o fetch local e mostra consulta cancelada` | POST falha, mas fetch local é abortado e UI mostra erro |

## Resultados

| Suite | Testes | Status |
|-------|--------|--------|
| Backend (pytest) | 173 | ✅ Todos passam |
| Frontend (vitest) | 297 | ✅ Todos passam |
| Frontend (tsc -b) | — | ✅ Compila sem erros |
| Frontend (vite build) | — | ✅ Build bem-sucedido |
