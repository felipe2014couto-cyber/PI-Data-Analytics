# Relatório — Fase 5.8 — Persistência versionada das configurações visuais

Data: 29/07/2026

## Resultado executivo

A estrutura versionada já existia no banco e foi consolidada para persistir o estado completo da página. A seleção e abertura de versões históricas foi concluída no frontend sem transformar uma simples abertura em nova versão. O bloqueio do `TestClient` foi diagnosticado e corrigido exclusivamente nas fixtures de teste; os testes integrados de backend passaram. A fase permanece **PARCIALMENTE CONCLUÍDA** porque a validação manual autenticada após reload não pôde ser realizada e a regressão frontend focada terminou com uma falha.

## Baseline anterior às alterações desta auditoria

- Modelos `VisualConfiguration` e `VisualConfigurationVersion`, migration 0004, JSON, índices e unicidade `(configuration_id, version)` já existiam.
- Criação da versão 1, atualização sequencial com `expected_version`, renomeação versionada, histórico, obtenção de versão, restauração e isolamento por proprietário já existiam.
- Cabeçalho compacto, pesquisa local, ações, histórico e exclusão confirmada já estavam implementados.
- O snapshot completo da barra e a normalização de documentos antigos haviam sido adicionados nas correções locais imediatamente anteriores.
- Baseline frontend focado: 72 testes aprovados, 0 falhos; execução final anterior de serialização/ações: 16 aprovados, 0 falhos.
- Baseline backend: teste isolado do schema aprovado; testes com `TestClient` bloqueavam na primeira requisição e atingiam timeout.

## Lacunas encontradas

1. O frontend não consumia `GET /visual-configurations/{id}/history/{version}`. Somente a versão corrente podia ser aberta diretamente.
2. O histórico permitia restaurar uma versão, mas restauração cria uma nova versão; isso não equivale a abrir uma fotografia histórica de forma imutável.
3. A criação era transacional no banco, mas não executava rollback explícito se `commit()` falhasse.
4. A cobertura de isolamento não exercitava todas as operações de histórico, versão específica, renomeação, restauração e exclusão por outro usuário.

## Estrutura persistida

O documento permanece em JSON com `schema_version: 1` e contém:

- `visual_rules`: regras por `seriesInstanceId`, limites, faixas, cores e seleção visual;
- `sidebar_state.filters`: período, timezone, modelo, equipamento, seção, tipo de variável, modo, intervalo, resolução, pontos, qualidade, visualização e filtros avançados;
- `selectedTagIds`, preservando seleção e ordem;
- `seriesAssignments`, preservando ordem, eixo e papel X/Y;
- `metricConfiguration`;
- `comparison`, incluindo contexto B.

Resultados do PI, pontos, StreamSet bruto, mensagens, erros, loading, busca, menus e modais não entram no documento.

## Versionamento e imutabilidade

- `Salvar nova` cria configuração e versão 1 na mesma transação.
- `Salvar alterações` usa o mesmo serializador tipado e cria a próxima versão.
- O avanço usa `UPDATE ... WHERE current_version = expected_version`; conflito retorna 409 antes de criar a versão.
- Histórico é ordenado de forma decrescente e snapshots anteriores não são atualizados.
- `Abrir` uma versão histórica é somente leitura e não chama update ou restore.
- `Restaurar` continua sendo ação distinta e cria uma nova versão corrente a partir do snapshot escolhido.
- Renomear permanece versionado, conforme o contrato documentado e implementado anteriormente.

## Compatibilidade

`normalizeVisualConfigurationDocument` aplica defaults atuais somente aos campos ausentes. Documentos antigos contendo apenas `visual_rules` continuam válidos, não são modificados e não geram salvamento automático. Presets permanecem identificadores relativos; períodos absolutos preservam datas e timezone `America/Sao_Paulo`.

## Propriedade e exclusão

Todas as operações usam `_owned(config_id)`, filtrando simultaneamente ID e usuário autenticado. Recurso inexistente e recurso de outro usuário retornam o mesmo 404. Exclusão usa o ID, exige confirmação no frontend e remove versões pela cascata ORM `all, delete-orphan` e FK `ON DELETE CASCADE`.

## Alterações desta auditoria

- Cliente frontend para obter versão específica.
- Seletor de versão no controle compacto do cabeçalho.
- Abertura de versão corrente ou histórica sem criar nova versão.
- Botão `Abrir` no histórico separado de `Restaurar`.
- Identificação exata da versão aberta.
- Proteção para ações mutáveis quando a seleção não corresponde à configuração aberta.
- Rollback explícito na falha da transação de criação inicial.
- Testes de abertura histórica, atomicidade e isolamento ampliado.

## Testes executados

- Diagnóstico mínimo, antes da correção: uma aplicação `FastAPI()` vazia bloqueou na primeira requisição usando `TestClient(app)` diretamente e bloqueou na entrada do contexto usando `with TestClient(app)`. A pilha parou em `anyio.from_thread` aguardando o portal; lifespan, banco, autenticação, middlewares e serviços externos não participavam desse caso mínimo.
- Verificação do mecanismo: `asyncio.run_coroutine_threadsafe()` também não despertou o loop padrão entre threads neste ambiente. O mesmo `TestClient` mínimo entrou no contexto e respondeu ao usar `backend_options={"use_uvloop": True}`.
- Backend específico completo: 7 aprovados, 0 falhos, 0 ignorados em `tests/test_visual_configurations.py`.
- Autenticação relacionada: 17 aprovados, 0 falhos, 0 ignorados em `tests/test_auth.py`.
- `python -m compileall -q app tests/test_visual_configurations.py`: aprovado.
- Frontend focado: 73 aprovados, 1 falho, 0 ignorados em 3 arquivos. Falhou `restaura configuração completa sem efeitos dependentes apagarem as tags`: após abrir a configuração, `equipment-select` permaneceu vazio em vez de `1`. A falha foi reproduzida isoladamente (1 falho, 56 não selecionados) e não foi alterada por estar fora do escopo autorizado para a correção do `TestClient`.
- `npm run build` (`tsc -b` + Vite): aprovado, 965 módulos.
- Lint: não existe comando de lint configurado.

Warnings conhecidos: avisos React `act(...)`, importação estática/dinâmica do mesmo módulo e bundle acima de 500 kB. Nenhum foi introduzido como erro bloqueante.

## Validação manual

Não realizada. Faltou um ambiente funcional com backend autenticado que permitisse criar v1/v2, abrir ambas após reload, repetir com período absoluto e conferir diretamente as linhas persistidas. Nenhuma consulta ao PI real foi usada.

## Limitações e pendências

1. Corrigir e revalidar a falha frontend focada de restauração de filtros dependentes, mediante autorização para ampliar o escopo além do bloqueio do `TestClient`.
2. Executar o roteiro manual completo com duas tags e regras distintas por série, para preset e período absoluto, incluindo reload completo.
3. Confirmar no banco, após esse roteiro manual, que as v1 e v2 do preset e do período absoluto possuem snapshots independentes e imutáveis.

## Estado do repositório

As alterações permanecem sem commit. `git status --short` contém arquivos modificados de backend/frontend e os novos arquivos de serialização, testes e este relatório. O resumo final exato foi coletado ao encerrar a execução e informado também na resposta ao usuário.

## Classificação final

**PARCIALMENTE CONCLUÍDA**

Os testes integrados do backend estão desbloqueados e aprovados, mas a fase não pode ser declarada concluída sem a validação manual obrigatória após reload e enquanto houver uma falha na regressão frontend focada.

## Continuação de 30/07/2026 — diagnóstico do `TestClient`

### Causa exata e ponto do bloqueio

O defeito não estava no lifespan, startup/shutdown do PI, autenticação, SQLAlchemy, fixtures de sessão, overrides ou endpoints. Uma aplicação FastAPI vazia reproduziu o bloqueio. O loop `asyncio` padrão deste ambiente não foi despertado por chamadas thread-safe entre threads; por isso o portal AnyIO criado pelo Starlette permanecia ocioso enquanto a thread do teste aguardava indefinidamente. Sem contexto, o bloqueio ocorria na primeira requisição em `starlette.testclient.TestClientTransport.handle_request`; com contexto, ocorria em `TestClient.__enter__`, antes do lifespan.

### Correção mínima

- `backend/tests/conftest.py`: o cliente compartilhado passou a usar o backend asyncio com `uvloop`.
- `backend/tests/test_visual_configurations.py`: a fixture local, que sobrescreve a compartilhada, recebeu a mesma opção.
- `backend/tests/test_auth.py`: a fixture própria dos testes de autenticação recebeu a mesma opção.

O `uvloop` já estava instalado pela dependência existente `uvicorn[standard]`; nenhuma versão foi alterada e nenhum pacote foi instalado. A mudança se limita à execução dos testes e não altera o comportamento de produção, autenticação ou propriedade.

### Consultas somente leitura no banco

O banco `backend/pi_analytics_data.db` foi aberto por URI SQLite com `mode=ro` e `PRAGMA query_only=ON`. Foram encontradas 1 configuração principal, versão atual 5, e 5 linhas de versão (operações `create`, `rename` e três `update`). As cinco linhas possuem cinco snapshots armazenados e dois conteúdos distintos. Essa leitura confirma linhas independentes e que há snapshots diferentes no banco existente, mas não comprova o roteiro manual solicitado para v1/v2 relativo e absoluto após reload.

### Validação manual

Não executada: não há nesta sessão uma interface de navegador autenticada nem credenciais fornecidas para realizar e observar o roteiro completo relativo e absoluto após reload. Não foi usado PI real, não foram inventados resultados e nenhum dado foi editado diretamente no banco.

### Verificações finais do worktree

- `git diff --check`: aprovado.
- `git status --short`: 15 arquivos rastreados modificados e 3 arquivos não rastreados; todos são alterações locais preservadas, sem commit ou push.
- `git diff --stat`: 15 arquivos rastreados, 498 inserções e 61 remoções. Como o relatório e outros dois arquivos são novos e ainda não rastreados, seus conteúdos não entram nessa estatística do Git.
