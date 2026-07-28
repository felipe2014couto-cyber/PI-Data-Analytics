# Relatório da Fase 5.7A — Autenticação, identidade e usuários

## 1. Resumo executivo
Foi implementada autenticação local com Argon2id, JWT em cookie HttpOnly, identidade estável e administração de usuários. A persistência visual da Fase 5.7 não foi iniciada.

## 2. Objetivo
Fornecer identidade autenticada, estável e validada pelo backend para proteger a aplicação e preparar ownership futuro.

## 3. Escopo
Modelo, migration, segurança, autenticação, autorização admin/user, CLI, proteção das APIs, frontend e testes.

## 4. Estado anterior
Não havia modelo de usuário, autenticação, JWT, autorização ou tela de login.

## 5. Arquitetura encontrada
FastAPI, SQLAlchemy, SQLite/Alembic e pytest no backend; React, React Router, TypeScript, Vitest e Vite no frontend.

## 6. Arquivos inspecionados
Foram inspecionados relatórios 5.5, 5.6 e 5.7, configuração, banco, models, migrations, rotas, serviços, testes, cliente HTTP, roteamento e layout. Não foi encontrado `AGENTS.md`. O Git estava indisponível: `fatal: not a git repository (or any of the parent directories): .git`.

## 7. Modelo de usuário
`users`: UUID textual, username, normalized_username, password_hash, role, is_active, auth_version, created_at, updated_at e last_login_at.

## 8. Identificador estável
UUID gerado no backend e usado como `sub`; renomear não altera a identidade.

## 9. Normalização do nome
Trim, limite de 1–100, `casefold` e unicidade persistida de `normalized_username`.

## 10. Hash de senha
Argon2id por `argon2-cffi`; limites de 5–128 caracteres, sem trim e sem armazenamento/devolução da senha. A política mínima foi posteriormente ajustada de 12 para 5 caracteres no backend, CLI e frontend; não existe senha criada automaticamente.

## 11. Perfis
Enum restrito a `admin` e `user`; autorização final consulta o usuário atual no banco.

## 12. Ativação e desativação
Desativação preserva o registro, incrementa a versão e bloqueia login e sessões anteriores.

## 13. `auth_version`
Incrementada em mudanças de senha, reset administrativo, desativação e mudança de perfil; conferida em cada requisição.

## 14. Migration
`0002_local_users.py` cria somente a tabela, constraint de perfil, unicidade e índices necessários; não cria usuário padrão e possui downgrade.

## 15. Configuração JWT
PyJWT 2.13.0, HS256 explícito, `sub`, `iat`, `exp`, `jti` e `auth_version`; segredo externo com mínimo de 32 caracteres e falha segura.

## 16. Armazenamento seguro do token
JWT existe somente no cookie de sessão; não é retornado no corpo nem salvo em Web Storage.

## 17. Cookies
Sessão HttpOnly, SameSite=Lax, `Secure` configurável e path `/api`; CSRF não secreto usa path `/` para leitura pela SPA.

## 18. CSRF
Double-submit cookie/header nas mutações autenticadas de negócio, senha e administração.

## 19. CORS
Credenciais habilitadas somente com a lista explícita de origens já configurável; não foi introduzido wildcard.

## 20. Endpoints de autenticação
`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` e `PUT /api/auth/change-password`.

## 21. Endpoints administrativos
Listar, obter, criar, atualizar/renomear, redefinir senha, ativar e desativar em `/api/admin/users`; sem exclusão física.

## 22. Comando do primeiro administrador
`cd backend && source .venv/bin/activate && python -m app.cli create-admin --username <nome>`. A senha e confirmação são solicitadas ocultas; não há argumento nem senha padrão. Nenhum administrador real foi criado.

## 23. Proteção das rotas existentes
Health e login permanecem públicos. APIs de negócio e PI exigem usuário ativo; administração exige admin. Respostas esperadas: 401 sem identidade válida e 403 sem perfil.

## 24. Integração frontend
AuthContext restaura `/auth/me`, cliente envia cookies, inclui CSRF e trata 401 centralmente.

## 25. Tela de login
Solicita somente usuário/senha, sem cadastro/social, mostra erro indistinto e abre a aplicação após sucesso.

## 26. Gestão administrativa
Interface admin lista, cria, renomeia, altera perfil, ativa/desativa e redefine senha, com confirmações críticas.

## 27. Alteração de senha
Disponível no layout; exige senha atual, invalida o token e encerra localmente a sessão.

## 28. Proteção do último administrador
Validações transacionais impedem desativar ou rebaixar o último administrador ativo.

## 29. Tratamento de erros
401, 403 e 409 controlados; login inválido não diferencia usuário inexistente, senha incorreta ou conta inativa.

## 30. Segurança dos logs
Senhas, hashes, JWT, cookies e segredo não são registrados ou incluídos nas respostas.

## 31. Variáveis de ambiente
Documentadas sem valores secretos: `AUTH_JWT_SECRET`, `AUTH_JWT_EXPIRE_MINUTES`, `AUTH_COOKIE_SECURE`, nomes dos cookies.

## 32. Arquivos alterados
Backend: configuração, segurança, exceptions, model/schema/service/dependencies/rotas, router, CLI, migration, requirements e testes. Frontend: tipos, cliente/API, contexto/guarda, App/layout, páginas de login/admin, mocks e testes. `.env.example` também foi atualizado.

## 33. Resultado da migration
Banco temporário `/tmp/pads_f57a_migration_20260724.db`, sem credenciais. `alembic upgrade head`, `downgrade 0001` e novo `upgrade head`: códigos 0, sem falhas. Tabela, índices e unicidade conferidos. A duração não foi cronometrada separadamente. O banco configurado da aplicação não foi alterado.

## 34. Testes backend
`pytest -q`: 199 aprovados, 0 falhos, 0 ignorados, 90 warnings, 37,99 s, código 0. Os 12 testes específicos de autenticação também passaram.

## 35. Testes frontend
`npm test -- --run`: 16 arquivos, 343 aprovados, 0 falhos, 0 ignorados, 32,34 s, código 0. Permanecem warnings React `act(...)` já observados na suíte. Houve uma execução intermediária com falhas de timing; após adequação/repetição sem concorrência, a suíte final chegou ao resumo aprovado.

## 36. Build
`npm run build`: código 0, TypeScript e Vite concluídos em 22,20 s; apenas warnings de tamanho/chunk dinâmico.

## 37. Validação funcional
Fluxos de login/me/logout, criação, autorização, troca/reset de senha, invalidação, desativação/reativação, último admin e CSRF foram exercitados com banco e credenciais exclusivamente de teste. Teste manual em navegador e PI real: não executado — ambiente/credenciais reais não foram fornecidos.

## 38. Regressão PI
Suítes existentes de contrato, Recorded, StreamSet, cache, cancelamento, qualidade, tipos, métricas, CSV, gráficos, comparação e regras permaneceram aprovadas no backend/frontend.

## 39. Quantidade de consultas ao PI durante autenticação
Nos testes monitorados de login, logout, restauração e administração: **0 novas consultas ao PI**.

## 40. Limitações
Sessão é JWT de curta duração sem refresh complexo; logout remove o cookie local, sem lista global de revogação. Mudanças de segurança revogam imediatamente pela versão no banco.

## 41. Pendências
Somente operação: definir segredo forte, `AUTH_COOKIE_SECURE=true` em HTTPS e criar o primeiro admin por pessoa autorizada.

## 42. Riscos conhecidos
Configuração incorreta de HTTPS/origens impede cookies; o segredo deve ser estável e protegido. Warnings de testes React e dependências legadas não bloquearam as suítes.

## 43. Recomendação para retomada da Fase 5.7
Após configuração operacional do segredo e criação do primeiro admin, usar exclusivamente o `sub` validado pelo backend como owner; nunca aceitar owner informado pelo frontend.

## 44. Status final
**APROVADA**. As ações de configuração do ambiente são pré-deploy, não pendências de implementação. As pré-condições técnicas de identidade e ownership estão prontas para a retomada da Fase 5.7.

## Atualização da política mínima de senha
Em 24/07/2026, exclusivamente o mínimo de senha foi alterado de 12 para 5 caracteres; o máximo permanece 128. O serviço e o CLI usam a mesma validação central e, portanto, aceitam a senha informada interativamente com cinco caracteres sem criar senha padrão. Foram comprovados: aceitação de cinco caracteres, rejeição de quatro e de 129, criação do primeiro administrador pelo CLI, hash Argon2id e ausência de segredo/hash nas respostas e saídas verificadas. Testes afetados: backend `15 passed, 11 warnings` em 9,65 s; frontend `9 passed` em 10,94 s, com um warning React `act(...)` não relacionado. Nenhuma alteração foi feita em JWT, cookies, CSRF, perfis, migrations ou APIs.

## Atualização de 27/07/2026 — primeiro login

Foi adicionada a troca obrigatória no primeiro login por `must_change_password`. Contas anteriores à migration permanecem liberadas; novos usuários, reset administrativo e primeiro admin via CLI ficam pendentes. Enquanto pendente, somente identidade, troca e logout são permitidos; os demais endpoints retornam `PASSWORD_CHANGE_REQUIRED`. A troca limpa a pendência, incrementa `auth_version` e emite sessão nova. Testes específicos: backend 17/17 e frontend 11/11. Migration `0003_must_change_password` validada com upgrade/downgrade/upgrade em SQLite temporário. Status: **APROVADA**.
