# Relatório — troca obrigatória, configuração de autenticação e Fase 5.7

Data: 27/07/2026

## Resumo executivo

Foram implementadas, na ordem exigida, a troca obrigatória no primeiro login, a documentação para configuração permanente da autenticação e a persistência privada/versionada de `VisualRulesState`. Não houve alteração nos contratos ou chamadas do PI Web API.

## Etapa 1 — troca obrigatória no primeiro login

O usuário possui o booleano persistente `must_change_password`. A migration `0003_must_change_password` adiciona a coluna como `false` para registros já existentes e muda o default de banco para `true` depois do backfill. Todos os fluxos de criação da aplicação, inclusive CLI, definem explicitamente `true`.

Login e `/auth/me` retornam somente o indicador público. Enquanto ele estiver ativo, `get_current_user` retorna `403/PASSWORD_CHANGE_REQUIRED`; somente login, `/auth/me`, `/auth/change-password` e logout continuam disponíveis. A proteção está no backend e a guarda React também redireciona qualquer URL protegida para `/trocar-senha`, sem renderizar menus.

A tela dedicada exige senha atual, nova senha e confirmação, com limites de 5–128 caracteres e logout. A troca usa Argon2id, limpa a pendência, incrementa `auth_version`, invalida o token anterior e emite cookie/JWT novo. Reset administrativo volta a marcar a pendência e também incrementa a versão.

Usuários existentes: permanecem com `must_change_password=false`. Novos usuários e primeiro administrador via CLI: recebem `true`.

Testes específicos: backend 17 aprovados, 0 falhos, 13 warnings, 23,98 s; frontend de autenticação 11 aprovados, 0 falhos. Senhas, hashes, JWT, cookies e segredos não são devolvidos ou registrados.

**Status da Etapa 1: APROVADA.**

## Etapa 2 — configuração permanente da autenticação

O projeto já usa exclusivamente `pydantic-settings` e carrega ambiente/`backend/.env`; nenhum segundo mecanismo foi criado. O README documenta segredo estável externo com mínimo de 32 caracteres, expiração e `AUTH_COOKIE_SECURE=false` somente em HTTP local ou `true` em produção HTTPS. `.env.example` permanece sem segredo real. Nenhum segredo foi criado, alterado ou versionado.

**Status da Etapa 2: APROVADA.**

## Etapa 3 — persistência versionada

### Contrato e modelo

O documento persistido é `{schema_version: 1, visual_rules: VisualRulesState}`. Assim, limites, faixas, regras, seleção e correspondência por `seriesInstanceId` são preservados sem reinterpretação. O documento tem estrutura mínima validada e limite de 100.000 bytes; nome tem 1–100 e descrição até 500 caracteres.

`visual_configurations` possui UUID, `owner_id`, nome, descrição, versão atual e timestamps. `visual_configuration_versions` possui UUID, configuração, número sequencial, snapshot JSON completo, usuário responsável, operação e data. Há FK, índices, checks e unicidade `(configuration_id, version)`.

### Ownership e isolamento

O proprietário é sempre `get_current_user.id`, obtido após validar `sub`, usuário ativo, `auth_version` e troca de senha concluída. `owner_id` não existe nos schemas de entrada; payload extra é rejeitado. Todas as consultas filtram simultaneamente recurso e proprietário. Usuários, inclusive administradores, recebem 404 para recursos alheios, sem confirmação de existência.

### Operações e histórico

Foram implementados criar, listar, obter, atualizar, renomear, listar histórico, obter versão e restaurar. Criação gera versão 1. Atualização e renomeação criam nova versão. Restaurar copia o snapshot escolhido para uma nova versão atual; o histórico nunca é sobrescrito. Exclusão não foi implementada porque não foi prevista como obrigatória no escopo atual.

### Concorrência

Atualização, renomeação e restauração exigem `expected_version`. O avanço é feito com `UPDATE ... WHERE current_version = expected_version`; `rowcount != 1` gera 409 e nenhuma versão é criada. O frontend mantém o estado visual local e orienta reabrir quando encontra conflito.

### Frontend

O painel mínimo integrado à área de configuração visual permite salvar nova, listar, abrir, salvar alterações, renomear, consultar histórico e restaurar. Operações exibem carregamento/erro controlado. O estado só é substituído após abertura/restauração bem-sucedida; falhas de salvamento não descartam o trabalho atual. Não há autosave.

### Endpoints

- `POST/GET /api/visual-configurations`
- `GET/PUT /api/visual-configurations/{id}`
- `POST /api/visual-configurations/{id}/rename`
- `GET /api/visual-configurations/{id}/history`
- `GET /api/visual-configurations/{id}/history/{version}`
- `POST /api/visual-configurations/{id}/restore`

Todos exigem autenticação concluída e CSRF nas mutações.

## Migrations

- `0003_must_change_password.py`
- `0004_visual_configurations.py`

Validação da 0003: banco `/tmp/pads_stage1_retry_20260727_0905.db`; upgrade, conferência de usuário anterior com valor 0, downgrade para 0002 e novo upgrade: códigos 0. Uma primeira tentativa identificou downgrade SQLite incompatível; foi corrigido com batch e toda a validação foi repetida em banco novo.

Validação da 0004: banco `/tmp/pads_f57_final_20260727_0910.db`; upgrade head, conferência de tabelas/FKs/índices/unicidade, downgrade para 0003 e novo upgrade: códigos 0. Nenhum banco real recebeu downgrade.

## Testes e build

- Backend específico Fase 5.7: 3 aprovados, 0 falhos, 3 warnings, 6,45 s.
- Frontend específico combinado: 14 aprovados, 0 falhos; TypeScript aprovado.
- Backend completo: 207 aprovados, 0 falhos, 0 ignorados, 96 warnings, 74,36 s, código 0.
- Frontend completo final: 17 arquivos, 349 aprovados, 0 falhos, 50,29 s, código 0. Uma execução anterior teve uma falha intermitente de timing em teste legado; o teste passou isolado e a suíte completa foi repetida com sucesso. Permanecem warnings React `act(...)` já conhecidos.
- `npm run build`: TypeScript e Vite aprovados, 964 módulos, 22,76 s, código 0; warnings não bloqueantes de chunk.

## Regressão e consultas PI

As suítes completas preservaram consulta normal, comparação, Recorded, StreamSet, timestamps, tipos JSON, qualidade, cache, retry, cancelamento, métricas, CSV, gráficos, tooltip, séries textuais, limites, faixas, regras e contextos A/B. Testes monitoram separadamente APIs de persistência e PI.

Consultas adicionais ao PI durante login, troca, logout, criação/listagem/abertura/versionamento/renomeação/histórico/restauração: **0**.

## Arquivos alterados

- `README.md`
- `backend/alembic/versions/0003_must_change_password.py`
- `backend/alembic/versions/0004_visual_configurations.py`
- `backend/app/api/auth.py`, `deps.py`, `router.py`, `visual_configurations.py`
- `backend/app/core/exceptions.py`
- `backend/app/models/user.py`, `visual_configuration.py`, `__init__.py`
- `backend/app/schemas/auth.py`, `visual_configuration.py`
- `backend/app/services/user_service.py`, `visual_configuration_service.py`
- `backend/tests/conftest.py`, `test_auth.py`, `test_visual_configurations.py`
- `frontend/src/App.tsx`, `api/index.ts`, `auth/AuthContext.tsx`, `auth/ProtectedRoute.tsx`
- `frontend/src/components/VisualConfigurationsPanel.tsx`
- `frontend/src/pages/LoginPage.tsx`, `RequiredPasswordChangePage.tsx`, `DataVisualizationPage.tsx`
- `frontend/src/types/index.ts`
- `frontend/tests/auth.test.tsx`, `mocks/api.ts`, `visualConfigurations.test.tsx`
- este relatório e o relatório 5.7A.

## Limitações, pendências e riscos

Não há exclusão de configuração, compartilhamento ou acesso administrativo a configurações alheias. O snapshot cobre o contrato visual atual (`VisualRulesState`), não filtros, consulta, resultados ou métricas. O limite JSON é medido após serialização UTF-8. Antes de produção ainda é necessário configurar segredo estável fora do repositório, habilitar cookie Secure em HTTPS, aplicar migrations pelo processo operacional e criar o primeiro administrador autorizado.

Riscos conhecidos: configuração incorreta de HTTPS/CORS pode impedir cookies; o frontend precisa reabrir após 409; warnings de testes e tamanho de bundle são preexistentes/não bloqueantes.

## Status final separado

- Etapa 1 — troca obrigatória: **APROVADA**.
- Etapa 2 — configuração permanente: **APROVADA**.
- Etapa 3 — Fase 5.7: **APROVADA**.
