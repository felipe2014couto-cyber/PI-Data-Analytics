# Relatório da Fase 4.4 — Dispersão e barras

Data: 17/07/2026

## Escopo

Implementação restrita ao frontend de duas visualizações: Dispersão entre
exatamente duas séries numéricas e Barras para o último valor numérico válido
de cada tag. Ambas reutilizam a última resposta em memória.

Backend, banco, migrations, endpoints e dependências não foram alterados. Valor
único e regras de status não foram implementados.

`git status --short` foi executado antes das alterações, mas o sandbox
apresentou `.git` vazio e respondeu que o projeto não é um repositório Git.
Nenhuma alteração existente foi descartada.

## Arquivos criados e alterados

Criados:

- `frontend/src/utils/comparison.ts`
- `frontend/src/components/ScatterPlotChart.tsx`
- `frontend/src/components/LatestValuesBarChart.tsx`
- `frontend/tests/comparison.test.ts`
- `RELATORIO_FASE_4_4_DISPERSAO_BARRAS.md`

Alterados:

- `frontend/src/types/index.ts`
- `frontend/src/utils/chartData.ts`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`

`EChartsWrapper.tsx` foi apenas conferido: `BarChart` e `ScatterChart` já
estavam registrados desde a Fase 4.3 e não foram duplicados.

## Arquitetura

O tipo de visualização agora é:

```typescript
type VisualizationType =
  | "automatic"
  | "line"
  | "states"
  | "histogram"
  | "boxplot"
  | "scatter"
  | "bars";
```

`resolveVisualization` permanece como política central e entrega somente o
grupo numérico para dispersão e barras, listando séries textuais como
incompatíveis. A página controla apenas as condições de apresentação.

O utilitário puro `comparison.ts` concentra extração de observações numéricas,
alinhamento temporal, correlação de Pearson, seleção do último valor e
agrupamento por unidade. Ele recebe as séries originais completas da resposta,
sem utilizar amostragem do gráfico de linha.

## Regra de alinhamento temporal

Os timestamps válidos são convertidos por `Date.parse` para milissegundos UTC.
Somente observações com exatamente o mesmo instante normalizado são pareadas.
Não há pareamento por índice, posição ou proximidade.

Cada timestamp possui uma fila por série. Em timestamps repetidos, a primeira
ocorrência de X é associada à primeira de Y, a segunda à segunda, e assim por
diante, até o menor número disponível. Os timestamps coincidentes são
processados em ordem crescente.

Cada par preserva timestamp, valores originais, nomes, unidades e as flags
`good`, `questionable` e `substituted` dos dois pontos para o tooltip.

## Regra de correlação

A correlação de Pearson usa somente os pares efetivamente exibidos, sem
arredondar os valores de entrada. O numerador soma os produtos dos desvios e o
denominador usa a raiz do produto das duas somas quadráticas.

O resultado é limitado a `[-1, 1]` para proteger contra erro de ponto
flutuante. Menos de dois pares, variância zero ou resultado não finito produzem
“Correlação: indisponível”; `NaN` e `Infinity` nunca são apresentados.

O resumo acima do gráfico informa eixos X/Y, unidades, quantidade de pares e
correlação formatada com quatro casas. Nenhuma interpretação causal é atribuída.

## Comportamento com recorded

Em valores registrados, somente timestamps realmente coincidentes formam
pares. Se existirem menos de dois, a dispersão não é renderizada e a página
explica que não há coincidências suficientes, recomendando “Valores
interpolados”. Isso evita uma correlação enganosa entre amostras desencontradas.

## Comportamento com interpolated

Em valores interpolados, o mesmo alinhamento exato é aplicado. Como o backend
tende a retornar a grade temporal solicitada, esse modo é recomendado quando
as tags registradas não possuem instantes coincidentes. Nenhuma aproximação
adicional é realizada no frontend.

## Quantidade de séries na dispersão

A dispersão exige exatamente duas séries numéricas válidas, na ordem em que
aparecem na resposta da consulta: a primeira vai para X e a segunda para Y.

- nenhuma: orientar selecionar duas tags numéricas;
- uma: orientar selecionar mais uma;
- três ou mais: informar a quantidade e solicitar exatamente duas;
- exatamente duas com texto adicional: exibir a dispersão e listar o texto
  como incompatível.

Séries individualmente mistas continuam fora do gráfico e recebem o alerta
específico já existente.

## Regra do último valor

Para cada série, todos os pontos são inspecionados, sem assumir ordenação do
array. A barra usa o valor numérico finito com o maior timestamp válido.

Se o ponto mais recente for inválido ou `Good=false` com o filtro ativo, o
algoritmo retorna ao ponto válido anterior. Strings como `"600"`, booleanos,
`null`, `NaN` e infinitos nunca produzem barras. Séries sem observação numérica
válida são omitidas, sem barra vazia.

O tooltip preserva nome, tag, valor, unidade, timestamp individual e qualidade.

## Agrupamento por unidade

As barras são agrupadas por unidade de engenharia. Tags com a mesma unidade
ficam no mesmo gráfico; unidades distintas geram gráficos separados. Unidade
nula, vazia ou composta apenas por espaços forma o grupo “Sem unidade”.

Cada gráfico usa o título “Barras — último valor”, eixo X de tags, eixo Y
numérico da unidade, rótulos de valores e exportação de imagem.

## Tratamento da qualidade e tipos

Somente JSON `number` finito é aceito. Não há `Number`, `parseFloat`, `parseInt`
ou coerção equivalente. `"600"` e `"500.5"` permanecem textuais.

Quando “Ignorar qualidade ruim” está ativo, `Good=false` é removido antes da
classificação, do pareamento, da correlação e da escolha do último valor. Esses
pontos permanecem contabilizados como descartados. Séries apenas ocultadas por
incompatibilidade não aumentam esse contador.

## Incompatibilidades

Tags textuais são listadas em orientação discreta nos modos Dispersão e Barras,
sem bloquear séries numéricas válidas. Nenhuma série compatível resulta em
orientação, não em gráfico vazio.

Alertas de erro da API, série individual mista, incompatibilidade de tipo,
quantidade da dispersão e falta de coincidências temporais permanecem distintos.

## Preservação dos dados, cards e CSV

Trocar a visualização não chama novamente a API, não altera filtros, tags,
período ou modo recorded/interpolated. A resposta original permanece em
`query.timeSeries`.

Cards e CSV continuam representando a consulta completa. Séries incompatíveis
continuam nos dados e não são tratadas como descarte. Pareamento, correlação e
último valor usam todos os pontos válidos, independentemente da amostragem
visual da linha temporal.

## Testes

Dispersão e alinhamento:

- duas séries numéricas e eixos X/Y;
- timestamps iguais e equivalentes em fusos diferentes;
- timestamps não coincidentes excluídos;
- prova de ausência de pareamento por índice;
- pares ordenados e duplicatas pareadas estavelmente;
- filtro `Good=false` e exclusão de strings, `null`, booleanos e não finitos;
- nenhuma, uma, duas e três séries numéricas;
- duas numéricas com uma textual;
- menos de dois pares com recomendação de interpolação;
- tooltip com timestamp, tags, unidades, valores e qualidades;
- quantidade de pares e dados completos.

Correlação:

- positiva perfeita, negativa perfeita e próxima de zero;
- variância zero em X e em Y;
- menos de dois pares;
- limitação entre `-1` e `1`;
- ausência de `NaN` e `Infinity`.

Barras:

- maior timestamp em array fora de ordem;
- ponto mais recente ruim e fallback para o anterior;
- exclusão de `"600"`, `null`, booleanos e não finitos;
- uma entrada por série válida e nenhuma barra vazia;
- unidades iguais juntas, diferentes separadas e “Sem unidade”;
- tooltip com tag, valor, unidade, timestamp e qualidade.

Integração:

- Dispersão e Barras no seletor; Valor único ausente;
- troca sem nova chamada à API;
- cards, CSV e descartados preservados;
- orientação de textos incompatíveis e ausência de gráfico vazio;
- sete modos funcionando e políticas anteriores preservadas;
- `"600"` textual e qualidade anterior à classificação.

Nenhum teste anterior foi removido.

## Resultado exato dos comandos

Testes:

```text
npm test -- --run
Test Files  7 passed (7)
Tests       135 passed (135)
Duration    19.85s
```

A suíte mantém avisos preexistentes de atualizações React fora de `act(...)`,
sem falhas.

O comando `npm run build` parou exclusivamente nos quatro erros TypeScript
antigos já documentados:

```text
tests/contract.test.tsx(2,35): error TS6133: 'fireEvent' is declared but its value is never read.
tests/errorBoundary.test.tsx(33,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(46,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(91,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
```

Nenhum erro novo da Fase 4.4 foi reportado. O bundle isolado passou:

```text
npx vite build
945 modules transformed
dist/assets/index-Bpq4GYx_.js  904.95 kB | gzip: 293.25 kB
built in 29.17s
```

Permanecem os avisos conhecidos sobre importação dinâmica/estática do mesmo
módulo e tamanho do chunk.

## Pendências

- corrigir separadamente os quatro erros TypeScript preexistentes;
- validar dispersão com dados PI recorded e interpolated reais;
- validar barras com tags de escalas e unidades distintas;
- implementar Valor único e regras de status somente em fase futura;
- avaliar divisão de chunks em uma tarefa de otimização independente.

## Roteiro de validação manual

1. Abrir “Visualização de Dados” e confirmar as sete opções implementadas e a
   ausência de Valor único.
2. Consultar exatamente duas tags numéricas em Valores interpolados.
3. Escolher Dispersão sem consultar novamente e conferir X, Y, unidades, pares,
   correlação, tooltip, zoom e exportação.
4. Repetir em Valores registrados com tags sem coincidências e confirmar a
   orientação para usar interpolação.
5. Testar uma e três tags numéricas e conferir as orientações, sem escolha
   silenciosa de séries.
6. Acrescentar uma tag textual e confirmar que a dispersão continua visível e
   a incompatibilidade lista seu nome.
7. Escolher Barras — último valor e confirmar uma barra por tag válida.
8. Conferir que o maior timestamp foi usado, mesmo se a resposta estiver fora
   de ordem, e validar valor, timestamp e qualidade no tooltip.
9. Conferir gráficos separados por unidade e o grupo “Sem unidade”.
10. Alternar o filtro de qualidade, consultar e validar fallback para o valor
    anterior quando o mais recente for ruim.
11. Confirmar que `"600"`, `"500.5"`, booleanos e `null` não viram números.
12. Alternar os sete modos sem nova consulta e confirmar cards, filtros e CSV
    intactos.
