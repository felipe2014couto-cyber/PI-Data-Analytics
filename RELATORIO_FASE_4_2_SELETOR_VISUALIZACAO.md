# Relatório da Fase 4.2 — Seletor de visualização

Data: 16/07/2026

## Escopo

Implementação restrita ao frontend do seletor tipado de visualização e da
política que escolhe os gráficos já existentes. Backend, banco de dados,
migrations, endpoints, dependências e tipos futuros de gráfico não foram
alterados.

O comando `git status --short` foi executado antes das alterações, mas o
sandbox apresentou `.git` como diretório vazio e respondeu que o projeto não é
um repositório Git. Nenhuma mudança existente foi descartada ou sobrescrita.

## Arquivos alterados

- `frontend/src/types/index.ts`
- `frontend/src/utils/chartData.ts`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/components/TimeSeriesChart.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`
- `RELATORIO_FASE_4_2_SELETOR_VISUALIZACAO.md`

## Arquitetura adotada

O contrato explícito foi definido como:

```typescript
type VisualizationType = "automatic" | "line" | "states";
```

A função tipada `resolveVisualization` centraliza a decisão. Ela recebe os
grupos já classificados por `buildChartDataGroups` e retorna um plano pequeno
com gráfico numérico, gráfico textual, séries incompatíveis e séries textuais
excedentes. A página apenas renderiza esse plano e as orientações associadas.

Essa separação mantém a classificação e os dados consultados independentes da
visualização. Tipos futuros poderão ser incorporados à política sem criar
componentes vazios nem espalhar coerções ou comparações por toda a interface.

## Opções implementadas

O campo acessível “Visualização” usa o padrão Bootstrap existente e apresenta
somente:

- Automática (`automatic`), valor inicial;
- Linha temporal (`line`);
- Estados (`states`).

Histograma, boxplot, dispersão, barras e valor único não são exibidos nem foram
implementados.

## Comportamento do modo automatic

O comportamento anterior foi preservado: múltiplas séries numéricas ficam no
mesmo gráfico, uma série textual usa o gráfico de estados e ambos podem ser
mostrados simultaneamente. Mais de uma textual mantém o limite atual, séries
individualmente mistas continuam identificadas e não bloqueiam séries válidas.

O filtro de qualidade continua anterior à classificação. `null` não interfere
no tipo, e strings como `"600"` e `"500.5"` continuam estados textuais sem
conversão.

## Comportamento do modo line

Somente séries numéricas válidas são enviadas ao gráfico temporal. Múltiplas
séries permanecem juntas e conservam tooltip, legenda, zoom, amostragem e
exportação. Séries textuais não são convertidas nem enviadas ao eixo numérico.

Quando há textos, uma orientação discreta lista seus nomes e recomenda
“Estados” ou “Automática”. Se não houver série numérica, nenhum gráfico vazio é
renderizado.

## Comportamento do modo states

Somente uma série textual válida é enviada ao gráfico categórico. Foram
preservados `step: "end"`, categorias por primeira ocorrência, compactação de
estados consecutivos, extensão do último estado, tooltip, zoom, exportação e
preservação de strings numericamente formatadas.

Séries numéricas são apenas ocultadas da visualização e listadas em orientação.
Quando há várias séries textuais, a primeira é exibida e os nomes das excedentes
são informados explicitamente. Se só houver números, nenhum gráfico vazio é
renderizado e a orientação recomenda “Linha temporal” ou “Automática”.

## Incompatibilidades e alertas

Continuam distintos:

- falha real da consulta, apresentada como erro;
- série individual realmente mista, apresentada com o nome da tag;
- incompatibilidade com `line` ou `states`, apresentada como orientação;
- limite de uma série textual, com nomes das séries não exibidas.

Séries ocultadas pelo seletor não incrementam “Descartados”. Esse contador
continua reservado ao filtro de qualidade.

## Preservação dos contadores e CSV

A mudança do seletor atua somente sobre o plano de renderização calculado a
partir da última resposta em memória. Ela não chama novamente a API, não altera
filtros, período ou tags e não substitui `query.timeSeries`.

Os cards continuam usando o resultado completo de `buildChartDataGroups`, e o
CSV continua recebendo a resposta original. Portanto, séries incompatíveis com
o modo escolhido permanecem nos contadores e na exportação.

## Testes adicionados e ajustados

Foram cobertos:

- valor padrão `automatic`, label associado e três opções visíveis;
- ausência de tipos futuros no seletor;
- automático com números, textos e ambos simultaneamente;
- `line` com uma ou várias séries numéricas;
- `line` com números e textos e somente com textos;
- `states` com texto, texto e número, somente número e várias textuais;
- nomes das séries incompatíveis e excedentes;
- ausência de gráfico vazio quando não existe série compatível;
- troca do seletor sem nova chamada à API;
- preservação dos cards, CSV e contador de descartados;
- `"600"` preservado como string;
- qualidade filtrada antes da classificação;
- série realmente mista ainda identificada;
- política tipada `resolveVisualization` para os três modos.

Nenhum teste anterior foi removido.

## Resultado exato dos testes

Comando:

```text
npm test -- --run
```

Resultado:

```text
Test Files  5 passed (5)
Tests       103 passed (103)
Duration    23.40s
```

A suíte mantém avisos preexistentes de atualizações React fora de `act(...)`,
sem falhas.

## Resultado exato do build

O comando solicitado `npm run build` parou na etapa `tsc -b` somente nos
quatro erros preexistentes:

```text
tests/contract.test.tsx(2,35): error TS6133: 'fireEvent' is declared but its value is never read.
tests/errorBoundary.test.tsx(33,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(46,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(91,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
```

Nenhum erro da Fase 4.2 foi reportado. A geração isolada foi executada:

```text
npx vite build
939 modules transformed
dist/assets/index-D0B4wNH4.js  862.69 kB | gzip: 280.20 kB
built in 16.80s
```

Permanecem os avisos conhecidos do Vite sobre importação dinâmica/estática do
mesmo módulo e tamanho do chunk.

## Pendências

- corrigir em tarefa separada os quatro erros TypeScript antigos dos testes;
- validar visualmente os três modos com dados reais do PI;
- implementar tipos futuros somente nas fases correspondentes.

## Roteiro de validação manual

1. Abrir “Visualização de Dados” e confirmar “Automática” como seleção inicial.
2. Confirmar que o seletor contém somente Automática, Linha temporal e Estados.
3. Consultar uma tag numérica e uma textual e verificar os dois gráficos no
   modo automático.
4. Trocar para Linha temporal sem consultar novamente; confirmar apenas o
   gráfico numérico e a orientação com o nome da tag textual.
5. Trocar para Estados; confirmar apenas o gráfico categórico e a orientação
   com o nome da tag numérica.
6. Confirmar que período, filtros, tags, cards e botão CSV permanecem intactos.
7. Exportar o CSV e confirmar que ele ainda contém as séries numérica e textual.
8. Consultar somente texto e escolher Linha temporal; confirmar orientação sem
   gráfico vazio.
9. Consultar somente números e escolher Estados; confirmar orientação sem
   gráfico vazio.
10. Consultar duas tags textuais em Estados e confirmar o nome da excedente.
11. Validar `"600"` e `"500.5"` como estados, sem coerção.
12. Alternar o filtro de qualidade e confirmar que apenas `Good=false` aumenta
    “Descartados”, antes da classificação.
