# Relatório da Fase 5.0 — Arquitetura da parametrização avançada

Data: 17/07/2026

## 1. Resumo executivo

Esta fase foi exclusivamente de auditoria e planejamento. Nenhum código,
endpoint, modelo, migration, dependência ou documentação anterior foi alterado.
Não houve consulta ao PI real nem leitura de `.env`.

A base atual é adequada para evoluir incrementalmente: existe um contrato
temporal estável, catálogo normalizado, oito visualizações e utilitários puros.
Entretanto, o estado de consulta, papéis de séries, filtros e apresentação ainda
estão concentrados em `DataVisualizationPage.tsx`; não há conceito persistido de
Modelo, Máquina separada, Métrica separada, usuário, permissão ou configuração
salva. A recomendação é primeiro formalizar período e papéis, preservando
`GET /api/time-series`, e somente depois introduzir filtros, comparações,
limites e persistência.

Os termos Modelo, Máquina, Métrica e Base cíclica não têm semântica confirmada.
As alternativas deste relatório são propostas, não decisões já tomadas.

## 2. Estado atual

### 2.1 Repositório e estrutura

`git status --short` respondeu `fatal: not a git repository`; `.git` não foi
recriado. A estrutura principal é:

```text
backend/
  alembic/versions/0001_initial.py
  app/{api,core,database,integrations/pi,models,repositories,schemas,services}
  tests/
frontend/
  src/{api,components,layouts,pages,styles,types,utils}
  tests/
```

O frontend oferece os scripts `dev`, `build`, `preview`, `test` e
`test:watch`. Não existe script de lint. Existe uma única migration,
`0001_initial.py`.

### 2.2 Banco, modelos e tabelas

| Tabela | Campos relevantes | Relações/ordem |
| --- | --- | --- |
| `equipments` | id, code, name, description, active, timestamps | 1:N com seções e tags; listagem por code |
| `sections` | equipment_id, code, name, description, active, timestamps | pertence a equipamento; código único por equipamento; listagem por equipment_id/code |
| `variable_types` | code, name, description, default_unit, active, timestamps | 1:N com tags; listagem por code |
| `pi_tags` | equipment_id, section_id, variable_type_id, servidor, nome PI, WebId, display_name, unidade, tipo, status, timestamps | pertence às três entidades; única por servidor/nome; listagem por servidor/nome |

`PiTag.data_type` aceita `NUMERIC` ou `NON_NUMERIC`. O status de validação é
`PENDING`, `VALID`, `INVALID` ou `ERROR`. A unidade temporal devolvida é
`PiTag.engineering_unit`; `VariableType.default_unit` é metadado cadastral e não
é usado como fallback na resposta temporal atual.

Não existem tabelas ou modelos para usuários, papéis, permissões, modelos de
máquina, configurações salvas, limites, filtros, comparações ou valores
históricos.

### 2.3 Endpoints atuais

- CRUD `/api/equipments` e `/api/equipments/{id}`;
- CRUD `/api/sections` e `/api/sections/{id}`;
- CRUD `/api/variable-types` e `/api/variable-types/{id}`;
- CRUD `/api/pi-tags` e `/api/pi-tags/{id}`;
- `POST /api/pi-tags/validate` e `POST /api/pi-tags/{id}/validate`;
- `GET /api/pi/health` e `GET /api/health`;
- `GET /api/time-series`.

As listagens oferecem busca, ativo e paginação; seções aceitam equipamento;
tags aceitam equipamento, seção, tipo de variável e status de validação.

## 3. Baseline de testes e build

Frontend:

```text
npm test -- --run
Test Files  8 passed (8)
Tests       144 passed (144)
Duration    16.35s
```

Permanecem warnings antigos de atualizações React fora de `act(...)`, sem
falhas.

```text
npm run build
947 modules transformed
dist/assets/index-CvXR8cOA.js  907.64 kB | gzip: 293.86 kB
built in 20.42s
```

O build terminou com código zero. O Vite avisou sobre importação dinâmica e
estática do mesmo módulo e chunk acima de 500 kB.

Backend direcionado:

```text
29 passed, 1 warning in 6.75s
```

O warning é um `DeprecationWarning` de event loop em teste de health. Nenhuma
migration foi executada.

## 4. Inventário do backend

### 4.1 Catálogo e relacionamentos

Equipamento contém seções e tags. Seção obrigatoriamente pertence ao mesmo
equipamento da tag. Tipo de variável é uma classificação independente ligada à
tag. Serviços validam referências e bloqueiam exclusão física quando existem
dependências. Tags são filtráveis por equipamento, seção e tipo.

Não existe campo de ordem configurável. A ordem de seleção recebida em
`tag_ids` é preservada ao remover duplicatas e ao carregar as tags. Já as
listagens cadastrais usam ordem própria de repositório.

### 4.2 Consulta temporal

`GET /api/time-series` recebe:

- `tag_ids`, repetidos ou CSV, preservando ordem e removendo duplicatas;
- `start_time` e `end_time` ISO 8601;
- `mode`: `recorded` ou `interpolated`;
- `interval`, obrigatório para interpolated;
- `max_count` por tag.

O serviço exige início anterior ao fim, tags ativas e no máximo
`PI_QUERY_MAX_TAGS` (padrão 10). `max_count` é limitado por
`PI_QUERY_MAX_POINTS_PER_TAG` (padrão 20.000). WebId pode ser resolvido e
armazenado durante a consulta. Falhas individuais retornam em `errors`, sem
invalidar necessariamente as demais séries.

A resposta contém período, modo, séries e erros. Cada série traz identificação
e contexto cadastral; cada ponto preserva timestamp, valor
`number|string|boolean|null` e Good, Questionable e Substituted.

### 4.3 Ausências relevantes

Não há endpoint para agregação, comparação, filtros avançados, limites,
configuração salva, autenticação ou autorização. Não há cache histórico local.
Recorded e interpolated são consultados diretamente no provedor PI.

## 5. Inventário do frontend

### 5.1 Estado e gatilhos

`DataVisualizationPage` mantém `FiltersState`, IDs selecionados e `QueryState`.
O estado inclui equipamento, seção, tipo de variável, preset, datas customizadas,
modo, intervalo, maxCount, qualidade e visualização.

Equipamento/seção/tipo filtram localmente o catálogo carregado. Alterar filtros
não chama a série temporal; somente “Consultar” executa a API. A troca de
visualização e do filtro de qualidade recalcula projeções locais com a última
resposta. Alterar o filtro de qualidade depois da consulta, portanto, não busca
novos pontos; apenas inclui/exclui os já recebidos.

As tags aparecem na ordem devolvida por `/pi-tags` (servidor/nome PI). A seleção
mantém a ordem de cliques em `selectedTagIds`; a resposta normalmente segue a
ordem de `tag_ids`. Não há controle manual explícito de ordenação.

### 5.2 Período e consulta

Presets: 15 minutos, 1 hora, 8 horas, 24 horas e 7 dias. Custom usa dois
`datetime-local`, interpretados no fuso do navegador e enviados em UTC. Recorded
e interpolated são controles explícitos; intervalos disponíveis vão de 1
segundo a 1 hora.

### 5.3 Transformação e dados completos

`query.timeSeries` permanece como fonte original e alimenta CSV, dispersão,
barras e Valor único. `buildChartDataGroups` aplica Good antes da classificação,
separa séries numéricas/textuais/mistas e gera projeções. A linha usa sampling
LTTB somente na configuração do ECharts; não há amostragem destrutiva do array.
Histograma e boxplot usam todos os números finitos da projeção; dispersão,
correlação, barras e Valor único percorrem as séries originais completas.

Unidades são obtidas de `TimeSeriesSeries.unit`. A linha possui slots para até
dois eixos por unidade; a página bloqueia consulta com mais de duas unidades,
exceto Valor único. Boxplot e barras agrupam por unidade. Histograma é por tag.

Na dispersão, as duas primeiras séries numéricas válidas tornam-se X e Y na
ordem da resposta; não há seleção manual. Pares exigem timestamps exatamente
iguais após normalização UTC.

### 5.4 Inventário funcional

| Recurso | Comportamento atual |
| --- | --- |
| Período | presets ou intervalo absoluto customizado |
| Equipamento/seção/tipo | filtros em cascata do catálogo |
| Tags | múltipla seleção de ativas VALID/PENDING |
| Recorded/interpolated | escolha explícita; interpolated exige intervalo |
| Quantidade | maxCount por tag, padrão frontend 2.000 |
| Qualidade | opção única para remover Good=false antes da classificação |
| CSV | dados originais completos, formato longo |
| Automática | numéricas e uma textual em gráficos separados |
| Linha | séries numéricas temporais |
| Estados | uma série textual categórica, step end |
| Histograma | um por série numérica |
| Boxplot | séries numéricas agrupadas por unidade |
| Dispersão | exatamente duas numéricas, alinhamento exato |
| Barras | último número finito por tag, agrupado por unidade |
| Valor único | último número/string/boolean por tag, inclusive série mista |

Inconsistência conhecida: o subtítulo da página permanece “Gráfico de linha com
consulta direta ao PI Web API” em todos os modos. Recomenda-se futuramente
“Análise configurável de dados do PI Web API”, sem alterar nesta fase.

## 6. Mapeamento da interface desejada

Legenda de cobertura: completa, parcial ou ausente.

| Campo desejado | Equivalente atual | Cobertura/lacuna | Frontend necessário | Backend/banco | Decisão pendente | Risco |
| --- | --- | --- | --- | --- | --- | --- |
| Seleção de data | preset/custom | parcial; apenas um período | editor temporal tipado | API atual pode servir | modos permitidos | médio |
| Lista de datas | nenhuma | ausente | lista de períodos | múltiplas consultas ou batch; sem banco | finalidade da lista | alto |
| Data relativa | presets | parcial | quantidade/unidade/referência | pode resolver no cliente; servidor para reprodutibilidade | referência e timezone | alto |
| Data absoluta | custom | parcial; sem timezone explícito | timezone e validação | contrato pode continuar UTC | timezone oficial | médio |
| Tipo de início/fim | implícito | ausente | união discriminada | talvez nenhum | semântica de cada tipo | alto |
| Dias/hora/data atual | duração/now implícitos | parcial | campos condicionais | nenhum inicialmente | arredondamento e calendário | médio |
| Base cíclica | nenhuma | ausente | editor após regra confirmada | provável resolvedor backend | conceito de ciclo | crítico |
| Modelo | nenhuma | ausente | seletor futuro | provável entidade/migration | não assumir Equipamento | crítico |
| Máquina | Equipamento é hipótese | parcial sem equivalência confirmada | seletor/hierarquia | possível reutilização ou entidade | significado corporativo | crítico |
| Seção | Section | completa no catálogo | preservar cascata | endpoints atuais | cardinalidade futura | baixo |
| Eixo Y | seleção implícita de tags | parcial | papéis por série | consulta atual serve | regras por unidade | alto |
| Eixo Y duplo | automático por unidade | parcial; não manual | atribuição primário/secundário | nenhum inicialmente | compatibilidade/unidades | alto |
| Eixo X dispersão | primeira série numérica | parcial | escolha explícita | nenhum inicialmente | ordem/persistência | alto |
| Valor | ponto da tag | parcial | papel/transformação | talvez agregação | significado na referência | médio |
| Métrica | Tipo de variável é hipótese | parcial | seletor conceitual | reutilizar ou nova entidade | definição de métrica | crítico |
| Unidade | tag/unit | parcial | unidade visual opcional | conversão exige backend/regra; banco se persistir | conversões autorizadas | alto |
| Tipo de visualização | seletor de oito modos | completa atual | integrar ao schema | nenhum | extensões futuras | baixo |
| Filtros do Y | Good=false | parcial | construtor tipado | servidor para volume | ordem e contadores | alto |
| Filtros opcionais/específicos | nenhum genérico | ausente | seções condicionais | possível query avançada | catálogo de filtros | alto |
| Comparar por | dispersão entre tags | parcial | plano de comparação | múltiplas consultas/batch | identidade e alinhamento | crítico |
| Parâmetros de análise | algoritmos fixos | parcial | editor por gráfico | backend para volume | defaults/métodos | alto |
| Limites | nenhuma regra operacional | ausente | editor/legenda | persistência futura | fonte e governança | crítico |
| Parâmetros visuais | opções fixas | parcial | contrato comum/específico | normalmente nenhum | permissões/defaults | médio |
| Exclusões | Good=false apenas | parcial | filtros por escopo | servidor para volume | efeito em CSV/contadores | alto |
| Configuração salva | nenhuma | ausente | salvar/carregar/versionar | endpoints+tabelas+auth | propriedade/compartilhamento | crítico |

## 7. Lacunas prioritárias

1. Semântica não confirmada de Modelo, Máquina, Métrica e Base cíclica.
2. Ausência de um `AnalysisConfiguration` tipado separado do estado da página.
3. Papéis de séries/eixos implícitos e dispersão dependente da ordem.
4. Um único contador “Descartados”, hoje reservado a Good=false.
5. Sem distinção formal entre filtro de cálculo, visual e exportação.
6. Sem execução backend para consultas compostas ou grandes agregações.
7. Sem identidade, autenticação e autorização para persistência.
8. Limite de unidades validado antes da consulta em quase todos os modos, em
   vez de ser validado pelo plano de eixos.

## 8. Arquitetura temporal proposta

Proposta TypeScript, não implementada:

```typescript
type TimezoneId = string;

type TimePeriod =
  | { kind: "preset"; preset: "PT15M" | "PT1H" | "PT8H" | "P1D" | "P7D" }
  | { kind: "absolute"; start: string; end: string; timezone: TimezoneId }
  | {
      kind: "relative";
      amount: number;
      unit: "minute" | "hour" | "day" | "week";
      reference: "now" | "startOfDay" | "endOfDay";
      startOffset: string;
      endOffset: string;
      timezone: TimezoneId;
    }
  | {
      kind: "cycle";
      anchor: string;
      cycleDuration: string;
      cyclePosition: { kind: "number"; value: number } | { kind: "current" };
      startOffset: string;
      endOffset: string;
      timezone: TimezoneId;
    };
```

Preset e absolute podem ser convertidos ao contrato atual. Relative deve ser
resolvido em instante absoluto antes da consulta e registrar a referência para
reprodutibilidade. Cycle é apenas uma forma estrutural proposta.

Perguntas sobre Base cíclica: qual é a âncora; ciclo tem duração fixa ou
calendário; quem define o número; há turnos/paradas; offsets atravessam ciclos;
o PI possui evento/atributo que determina o ciclo; timezone e horário de verão
afetam a regra?

## 9. Hierarquia proposta

| Alternativa | Vantagens | Riscos/impactos | Compatibilidade |
| --- | --- | --- | --- |
| Equipamento = Máquina | nenhuma migration; reutiliza CRUD | perde distinção se equipamento for agrupador/modelo | total se a semântica for confirmada |
| Modelo acima de Equipamento | hierarquia Modelo→Máquina(Equipamento)→Seção | nova tabela, FK, CRUD, migration e migração de dados | equipamentos existentes precisam modelo opcional/default |
| Máquina separada | preserva significado atual de Equipamento | nova entidade e redefinição de Section/PiTag; maior migração | exige estratégia de transição e endpoints novos |
| Tipo de variável = Métrica | reutiliza nome, default_unit e relação | tipo pode não representar fórmula/agregação | alta se “métrica” for apenas classificação |
| Métrica separada | suporta fórmula, agregação, unidade e governança | tabela/CRUD/FK e possível duplicidade conceitual | migração pode derivar de VariableType |
| Unidade somente na Tag | reflete fonte PI e contrato atual | inconsistências entre tags equivalentes | total |
| Unidade visual sobrescrita | permite rótulo/apresentação sem corromper origem | não pode implicar conversão silenciosa | aditiva na configuração, sem alterar tag |

Recomendação condicionada: se Máquina corresponder ao equipamento físico,
reutilizar Equipment como Máquina e adicionar Model acima dele é o caminho de
menor ruptura. Se Equipment hoje for um agrupador amplo, criar Machine é mais
correto. Não decidir antes de validar amostras reais do cadastro.

## 10. Papéis das séries e eixos

```typescript
type SeriesRole =
  | { kind: "primaryY"; axisId: string }
  | { kind: "secondaryY"; axisId: string }
  | { kind: "scatterX" }
  | { kind: "scatterY" }
  | { kind: "singleValue" }
  | { kind: "category" }
  | { kind: "filter" }
  | { kind: "comparison"; groupId: string };

interface SeriesAssignment {
  seriesId: string;
  tagId: number;
  roles: SeriesRole[];
  order: number;
}
```

Validador proposto:

- X e Y da dispersão devem ser tags distintas e numéricas;
- papéis category e eixos numéricos são incompatíveis;
- cada dispersão exige exatamente um X e um Y;
- unidades no mesmo eixo precisam ser iguais ou ter conversão explícita;
- secundário só existe em visualização que o suporte;
- Estados aceita uma série category por gráfico no contrato atual;
- ocultar uma série muda visibilidade, não descarte;
- resposta nova reconcilia IDs existentes, marca ausentes e adiciona novos sem
  sobrescrever atribuições manuais automaticamente.

## 11. Matriz por visualização

| Modo | Tipos e quantidade | Papéis/alinhamento | Y duplo | Parâmetros/filtros/exportação | null/texto/booleano |
| --- | --- | --- | --- | --- | --- |
| Automática | ≥1; numérico e uma textual | infere primário/category | atual automático, futuro manual | qualidade; imagem/CSV | null ausente; texto/boolean como estado |
| Linha | ≥1 numérica, sem máximo além da consulta | primaryY/secondaryY; tempo | sim | escala, linha, sampling; imagem/CSV | não compatíveis; null lacuna |
| Estados | 1 textual por gráfico | category; tempo, step | não | compactação/step; imagem/CSV | string/boolean; null ausência |
| Histograma | ≥1 numérica, um gráfico por série | valor→frequência | não | classes/agregação; imagem/CSV | excluídos sem coerção |
| Boxplot | ≥1 numérica | caixas por série/unidade | não | quartil/outlier; imagem/CSV | excluídos sem coerção |
| Dispersão | exatamente 2 numéricas | scatterX/scatterY; alinhamento temporal | não | correlação/tolerância; imagem/CSV | excluídos sem coerção |
| Barras | ≥1 numérica | último valor, grupos por unidade | não | seletor de último/agregação; imagem/CSV | excluídos sem coerção |
| Valor único | ≥1 número/string/boolean; série mista aceita | singleValue por tag | não | último valor/qualidade; CSV | null sem dados; texto/boolean preservados |

## 12. Arquitetura de filtros

```typescript
type DataFilter =
  | { kind: "quality"; good?: boolean[]; questionable?: boolean[]; substituted?: boolean[]; includeNull: boolean; includeNonFinite: boolean }
  | { kind: "number"; seriesId: string; operator: "gt"|"gte"|"lt"|"lte"|"between"|"outside"|"eq"|"neq"; values: number[] }
  | { kind: "text"; seriesId: string; operator: "eq"|"neq"|"contains"|"startsWith"|"endsWith"|"in"; values: string[]; caseSensitive: boolean }
  | { kind: "weekday"; days: number[]; timezone: string }
  | { kind: "timeRange"; start: string; end: string; timezone: string }
  | { kind: "shift"; shiftId: string }
  | { kind: "exclude"; target: "value"|"state"|"outlier"|"period"|"tag"|"badPoint"; payload: unknown };

interface AppliedFilter {
  filter: DataFilter;
  stage: "preCalculation" | "visualOnly";
  csv: "original" | "filtered";
}
```

Regex deve ser um operador separado apenas se houver caso confirmado, limite de
tamanho, timeout/engine seguro e proteção contra ReDoS.

Contadores propostos: `received`, `qualityExcluded`, `valueFiltered`,
`timeExcluded`, `outlierExcluded`, `visualHidden` e `displayed`. Somente
`qualityExcluded` equivale ao “Descartados” atual; filtros não devem ser
rotulados como qualidade ruim.

## 13. Comparações

- Mesma tag/períodos diferentes: múltiplas consultas, salvo novo endpoint batch.
- Máquinas/seções/tags diferentes no mesmo período: uma consulta atual pode
  servir se todas as tags couberem nos limites.
- Grupos/categorias: depende da futura hierarquia e pode exigir várias consultas.
- Ciclo atual/anterior: exige resolvedor de ciclos e normalmente duas janelas.
- Real/referência: uma consulta se referência for outra tag; cálculo/configuração
  adicional se for constante, fórmula ou limite.

Toda comparação precisa de `seriesInstanceId` que combine tag, contexto e
período; timezone explícito; política de unidade; alinhamento exato,
interpolação ou tolerância definida; orçamento global de tags/pontos; CSV com
identificador de período/grupo. Consultas paralelas devem compartilhar
cancelamento e apresentar falhas parciais.

## 14. Parâmetros de análise

| Parâmetro | Atual | Proposta de execução |
| --- | --- | --- |
| média/mínimo/máximo/soma/contagem/desvio | ausente como configuração | frontend em volume pequeno; backend em volume grande |
| mediana/percentis | mediana fixa no boxplot | método configurável; backend para grande volume |
| classes | `ceil(sqrt(n))`, máximo 50 | permitir auto ou inteiro validado |
| quartil | interpolação linear fixa | enum de método após decisão |
| outlier | 1,5×IQR fixo | estratégia e fator configuráveis |
| correlação | Pearson fixa | método e mínimo de pares; backend para grandes pares |
| tolerância temporal | zero/exata | duração explícita e algoritmo de pareamento |
| último valor | maior timestamp | manter; decidir empate e lookback |
| janela móvel | ausente | tamanho, unidade, centralização e bordas |
| agregação | apenas PI interpolated, sem agregação analítica | função+janela+preenchimento explícitos |

O backend deve assumir cálculos quando o payload completo exceder limites de
memória/latência, em comparações múltiplas ou quando reprodutibilidade auditável
for necessária. O frontend continua adequado para interação imediata em dados
já carregados.

## 15. Limites e cores

```typescript
interface LimitRule {
  id: string;
  scope: { kind: "tag"|"variableType"|"equipment"|"analysis"; id?: number };
  unit: string;
  ranges: Array<{
    lower?: number; upper?: number;
    lowerInclusive: boolean; upperInclusive: boolean;
    level: "info"|"warning"|"alarm";
    color: string; priority: number;
  }>;
  validFrom?: string;
  validTo?: string;
}
```

Mínimo/máximo podem ser representados como faixas abertas. Sobreposição deve
ser resolvida por prioridade explícita e validada. Conversão de unidade nunca é
implícita.

Qualidade PI, limite operacional, alarme, especificação e estado visual são
camadas independentes. As cores atuais do Valor único representam somente
qualidade e não devem ser reutilizadas para limites sem uma legenda/modo
específico e decisão sobre precedência.

## 16. Parâmetros visuais

Comuns: título, subtítulo, legenda, paleta, altura, casas decimais, unidade
visual, ordem, tooltip, zoom e exportação. De linha/Estados: espessura, símbolo,
tipo de linha, step, preenchimento e amostragem. De eixo: auto/manual,
mínimo/máximo, linear/log e papel primário/secundário. Histograma: rótulos de
classes. Boxplot: outliers. Dispersão: tamanho/cor de pontos e linha de
tendência. Barras: orientação/rótulos. Valor único: densidade, tamanho e camada
de cor.

Unidade visual sem conversão altera apenas rótulo e deve ser identificada como
tal; conversão exige fórmula validada e manutenção do valor original.

## 17. Persistência

| Opção | Benefícios | Limites/riscos |
| --- | --- | --- |
| estado React | simples e atual | perdido ao sair |
| URL | compartilhável/reproduzível | tamanho, dados sensíveis, versionamento |
| localStorage | sem backend | local ao navegador, sem governança |
| backend | compartilhamento e auditoria | exige auth, migration, CRUD e autorização |
| link compartilhado | colaboração | revogação, expiração, exposição |
| pública/privada | catálogo corporativo | papéis, aprovação e ownership |

Estrutura proposta: `schemaVersion`, `id`, `name`, `description`, `ownerId`,
`visibility`, `period`, `series`, `roles`, `visualization`, `filters`,
`analysis`, `limits`, `presentation`, timestamps e revisão.

Antes do backend: decidir identidade, login, proprietário, leitura/escrita,
compartilhamento, administradores, auditoria, versionamento, exclusão e política
para tags que deixaram de existir.

## 18. Impactos da API

Preservar: CRUDs atuais, health, validação PI e `GET /api/time-series` para
consultas simples.

Ampliar de forma retrocompatível: metadados de tags/hierarquia; opcionalmente
resposta com identificador de consulta e limites efetivos. Evitar adicionar
parâmetros ambíguos ao endpoint atual.

Possíveis novos contratos:

- `POST /api/analysis/query`: períodos, instâncias de série, filtros de cálculo,
  agregações e comparações; resposta versionada e parcial;
- `/api/models` ou `/api/machines`, somente após decisão de hierarquia;
- `/api/metrics`, somente se Tipo de variável não bastar;
- `/api/analysis-configurations`, dependente de persistência/auth;
- `/api/limit-rules`, dependente de governança e autorização.

Versão do schema deve ser explícita nos novos POSTs. O GET atual deve manter o
contrato para clientes existentes. Novos campos de resposta devem ser aditivos;
mudanças semânticas exigem `/api/v2` ou novo endpoint.

## 19. Desempenho

Limites atuais: 10 tags e 20.000 pontos por tag no backend; frontend solicita
2.000 por padrão. Recorded pode concentrar pontos irregularmente; interpolated
amplifica volume conforme grade. Comparações multiplicam consultas e memória.

Necessário antes de comparações avançadas: orçamento global de pontos,
cancelamento conjunto, paginação/streaming ou agregação server-side para volume,
telemetria de duração e testes de carga. Memoização dos planos puros deve usar
configuração e resposta como chaves estáveis.

Web Worker é recomendável apenas após medir bloqueio em estatísticas/filtragem;
cache backend depende de validade, segurança e carga do PI. Divisão de chunks é
otimização próxima, pois o bundle atual tem 907,64 kB (293,86 kB gzip), mas não
é bloqueador funcional. O sampling LTTB atual é apenas visual; cálculos devem
continuar em dados completos ou em agregados declarados.

## 20. UX proposta

Estrutura Bootstrap em accordion:

1. Parâmetros obrigatórios: período, hierarquia, séries/papéis, modo de consulta
   e visualização; sempre visíveis ou seção inicialmente aberta.
2. Filtros opcionais: qualidade, tempo e valor.
3. Filtros específicos: condicionais ao tipo/visualização.
4. Comparar por: visível quando comparação estiver ativa.
5. Parâmetros de análise: somente opções compatíveis com o gráfico.
6. Limites: somente quando camada de limites estiver habilitada.
7. Visualização: apresentação, eixos e exportação.
8. Exclusões: resumo por categoria e impacto no cálculo/CSV.

Seções fechadas devem mostrar resumo (“2 filtros ativos”, “Y: 3 séries”).
Validação inline deve apontar papel, tipo, unidade e período incompatíveis antes
da consulta. Desktop: painel lateral com resultado amplo; tablet: painel acima
ou offcanvas; móvel: uma coluna, ações fixas e accordions. Labels, descrições,
status textual, foco, teclado, `aria-expanded`, erros associados e contraste são
obrigatórios. Um resumo final da configuração antes de consultar evita um
formulário longo opaco.

## 21. Plano detalhado da Fase 5

### 5.1 Mecanismo avançado de datas

- Objetivo: união discriminada para preset/absolute/relative; ciclo apenas após decisão.
- Frontend: tipos, resolvedor, editor e testes de timezone/DST.
- Backend/banco: preservar GET; nenhum banco inicialmente.
- Arquivos prováveis: `types`, novo `utils/timePeriod`, `DataFiltersPanel`, página.
- Aceite: mesmas datas resolvem de forma determinística e contrato atual não regressa.
- Dependências/riscos: decisões de timezone, início/fim do dia e Base cíclica.

### 5.2 Hierarquia e papéis

- Objetivo: decidir Modelo/Máquina/Métrica e permitir atribuição manual de eixos.
- Frontend: catálogo hierárquico, `SeriesAssignment`, reconciliador e validação.
- Backend/banco: migration/CRUD somente se novas entidades forem aprovadas.
- Testes: compatibilidade, ordem, dispersão X/Y, unidades e resposta nova.
- Aceite: escolhas manuais não são substituídas silenciosamente.
- Risco: maior impacto em dados existentes; exige workshop de domínio.

### 5.3 Parâmetros de análise

- Objetivo: configurar classes, quartis, outliers, correlação, agregações e janela.
- Frontend: contratos e controles condicionais; utilitários parametrizados.
- Backend: endpoint de análise para volumes definidos por benchmark; sem banco obrigatório.
- Testes: métodos, bordas, não finitos e equivalência cliente/servidor.
- Aceite: defaults reproduzem a Fase 4.

### 5.4 Filtros opcionais e específicos

- Objetivo: pipeline tipado com estágio e efeito no CSV.
- Frontend: construtor, resumos e contadores separados.
- Backend: aplicar filtros pré-cálculo quando consulta server-side for usada.
- Banco: nenhum, salvo filtros salvos na 5.8.
- Aceite: ordem determinística e “Descartados” não mistura causas.
- Decisões: case sensitivity, regex, CSV original/filtrado.

### 5.5 Comparações

- Objetivo: períodos, tags e contextos com identidade explícita.
- Frontend: plano, múltiplos resultados, erros parciais e exportação identificada.
- Backend: `POST /analysis/query` ou batch após medir limites.
- Testes: timezone, alinhamento, unidades, cancelamento e maxCount global.
- Aceite: nenhuma associação por índice ou proximidade implícita.
- Dependência: 5.1 e 5.2; ciclo depende de regra confirmada.

### 5.6 Limites e regras de cores

- Objetivo: camada operacional separada da qualidade.
- Frontend: editor, legenda e precedência visível.
- Backend/banco: somente após definir governança; provável tabela/versionamento.
- Testes: inclusividade, sobreposição, prioridade, unidade e vigência.
- Aceite: cor sempre acompanhada de significado textual.

### 5.7 Parâmetros visuais

- Objetivo: contrato comum e extensões por gráfico.
- Frontend: painel e adapters ECharts/cartões.
- Backend/banco: nenhum até persistência.
- Testes: opções válidas, acessibilidade, exportação e responsividade.
- Aceite: defaults preservam todos os oito modos.

### 5.8 Persistência

- Objetivo: configuração versionada, inicialmente local/URL ou backend conforme decisão.
- Frontend: serialização, migração de schema e resolução de referências ausentes.
- Backend/banco: CRUD, migration, owner/visibility somente após autenticação.
- Testes: upgrade de versões, permissões, compartilhamento e concorrência.
- Aceite: configuração antiga abre sem alterar significado.

### 5.9 Validação, desempenho e documentação

- Objetivo: regressão, carga, bundle, acessibilidade e operação.
- Frontend/backend: testes E2E, benchmarks, telemetria e correções medidas.
- Banco: validar migrations e rollback se houver.
- Aceite: builds/testes, orçamento de desempenho, documentação e roteiro real PI.
- Riscos: ambiente backend com bloqueio conhecido da suíte completa.

## 22. Decisões pendentes do usuário

1. O que significam Modelo, Máquina e Métrica no domínio real?
2. Equipment corresponde exatamente a Máquina? Há exemplos reais da hierarquia?
3. Tipo de variável pode representar Métrica ou métrica envolve fórmula/agregação?
4. Qual é a regra formal de Base cíclica e sua fonte de âncora?
5. Qual timezone oficial e como tratar horário de verão?
6. Data relativa é resolvida no navegador, servidor ou ambos?
7. Eixo Y duplo aceita unidades diferentes ou somente conversíveis?
8. Como atribuir e persistir X/Y da dispersão e ordem das séries?
9. Quais filtros afetam cálculo, apenas visualização e CSV?
10. CSV deve continuar original por padrão ou permitir versão filtrada separada?
11. Quais métodos estatísticos e defaults são exigidos pelo negócio?
12. Quem cria/aprova limites e qual camada prevalece visualmente?
13. Configurações precisam ser privadas, públicas, compartilháveis ou versionadas?
14. Qual modelo de autenticação, papéis e auditoria será adotado?
15. Qual orçamento aceitável de tags, pontos, latência e consultas simultâneas?

## 23. Riscos

- Modelar hierarquia antes de esclarecer conceitos pode criar migrations caras.
- Datas relativas/cíclicas sem timezone e regra de referência não são reproduzíveis.
- Filtros client-side sobre dados truncados por maxCount podem produzir análise parcial.
- Múltiplas comparações podem exceder limites do PI e memória do navegador.
- Conversão ou agrupamento implícito de unidades pode gerar conclusão incorreta.
- Persistência sem autenticação expõe configurações e não define ownership.
- Cores de qualidade confundidas com alarmes podem induzir interpretação operacional.
- Concentração contínua na página aumentará acoplamento e custo de teste.
- O bundle já merece divisão futura; novos editores podem ampliá-lo.

## 24. Critérios de aceite desta auditoria

- estado, modelos, endpoints, filtros e oito modos inventariados;
- fatos separados de hipóteses e recomendações;
- tabela de referência e matriz de visualizações incluídas;
- contratos temporais, papéis, filtros, limites e persistência propostos sem implementação;
- impactos de frontend, backend e banco identificados;
- baseline executado sem migrations ou PI real;
- decisões pendentes e riscos explicitados;
- somente este relatório foi criado.

## 25. Ordem recomendada

1. Workshop curto para fechar Modelo/Máquina/Métrica, Base cíclica, timezone e
   semântica de filtros/CSV.
2. Fase 5.1 sem banco, preservando o endpoint atual.
3. Fase 5.2, incluindo decisão de migration antes de qualquer CRUD novo.
4. Fases 5.3 e 5.4 com defaults compatíveis com a Fase 4.
5. Fase 5.5 somente após orçamento de desempenho e papéis estáveis.
6. Fase 5.6 após governança de limites e cores.
7. Fase 5.7 sobre contratos já estabilizados.
8. Fase 5.8 depois da decisão de autenticação/autorização.
9. Fase 5.9 com validação integrada, carga, acessibilidade e documentação.

A primeira decisão recomendada não é técnica: confirmar a ontologia do domínio
e a semântica temporal. Isso evita que as fases seguintes codifiquem como fato
uma equivalência que hoje é apenas hipótese.
