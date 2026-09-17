# News — Relatório de Alterações

Data: 16/09/2026

## 1. Tags de classificação dinâmicas nas seções (substituindo o campo "Aço")

O campo textual simples `steel_code` foi substituído por um sistema de tags de classificação, permitindo: selecionar tags existentes, pesquisar pelo nome, criar tags diretamente no formulário, associar várias tags à mesma seção e remover uma associação sem excluir a tag global. Nomenclatura conforme solicitado: `classification_tags` e `section_classification_tags`.

### Backend — novos arquivos
- `app/models/classification_tag.py` — modelo `ClassificationTag` (nome único, 64 chars) e tabela de associação `SectionClassificationTag` (PK composta, FKs CASCADE).
- `app/repositories/classification_tag_repository.py` — CRUD, busca por nome, listagem com pesquisa (ILIKE), associação/desassociação, contagem de usos.
- `app/services/classification_tag_service.py` — nome normalizado (trim + maiúsculas), duplicidade 409, exclusão bloqueada quando em uso 409, ID inexistente 422.
- `app/api/classification_tags.py` — GET (com `?search=`), GET /{id}, POST 201, DELETE 204, com autenticação/CSRF.
- `alembic/versions/20260924_section_classification_tags.py` — cria as tabelas, migra `steel_code` existente para tags (sem duplicar) e remove a coluna; downgrade restaura a coluna e remove as tabelas. Validado com upgrade/downgrade/re-upgrade em SQLite.

### Backend — alterados
- `app/models/section.py` — sem `steel_code`; relacionamento `classification_tags` (selectin) e property `classification_tag_ids`.
- `app/models/__init__.py` — registro dos novos modelos.
- `app/schemas/section.py` — `classification_tag_ids` em Create (List) / Update (Optional, None não altera) / Response (validador extrai IDs do ORM).
- `app/services/section_service.py` — aplica associações no create/update; expire do relacionamento após commit.
- `app/repositories/section_repository.py` — filtro `classification_tag_id` via `any(...)`.
- `app/api/sections.py` — query param `classification_tag_id` no lugar de `steel_code`.
- `tests/test_sections.py` — 8 novos testes (criação, atualização, múltiplas tags, remoção sem excluir tag global, exclusão bloqueada, 422, duplicidade, filtros combinados).

### Frontend
- `src/types/index.ts` — `ClassificationTag`; `Section.classification_tag_ids: number[]`.
- `src/api/index.ts` — `classificationTagsApi` (list/get/create/remove); filtro `classification_tag_id`.
- `src/pages/SectionsPage.tsx` — campo "Aço" substituído por pesquisa de tags, checkboxes, criação inline (maiúsculas) e associação múltipla.
- `src/components/DataFiltersPanel.tsx` — filtro "Tag de classificação" (`classification-tag-filter`).
- `src/pages/DataVisualizationPage.tsx` — carrega tags no `loadLookups`; filtros Processo + Grupo + Tag em AND; "Limpar" reseta.
- `tests/mocks/api.ts` e `tests/sectionAttributes.test.tsx` — fixtures e 7 testes novos.

## 2. Timezone de Brasília (America/Sao_Paulo) na aba de Análise CEP

- `src/pages/CepAnalysisPage.tsx`:
  - `toIsoUtc` interpreta inputs `datetime-local` como horário civil de Brasília (`civilToUtc`, trata horário de verão), não mais como hora local do navegador.
  - `formatDatetime`/`formatOccurrenceDatetime` exibem em `America/Sao_Paulo` (antes UTC — datas 3h deslocadas).
  - Eixo X do gráfico de série CEP formatado em `America/Sao_Paulo` (dd/MM HH:mm).
- O gráfico de visualização (`TimeSeriesChart.tsx`) já usava `America/Sao_Paulo` e a resolução de período (`utils/timePeriod.ts`) já era baseada em Brasília — sem alteração necessária.

## 3. Correções de bugs menores
- `tests/mocks/api.ts` — removida chave duplicada `updateSection` que quebrava o tsc; deduplicação de fixtures.

## Verificação
- Backend: 565 passed, 6 skipped (suíte completa).
- Migration: upgrade/downgrade/re-upgrade validados com migração de dados steel_code → tags.
- Frontend: 476 testes / 26 arquivos passando; tsc limpo exceto 1 erro pré-existente em `src/components/TimeSeriesChart.tsx:435` (trabalho local não commitado anterior, impede `npm run build`) — recomendado resolver à parte.

## Observações
- `tests/deepZoom.test.tsx` falha apenas quando a suíte roda em paralelo com outra instância de vitest; isolado e sequencial passa 11/11. Não relacionado às mudanças.
- Downgrade da migration de tags não restaura os valores de `steel_code` (perda aceita; associações permanecem em `section_classification_tags`).
