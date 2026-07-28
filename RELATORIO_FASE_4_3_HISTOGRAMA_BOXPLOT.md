# Relatório da Fase 4.3 — Histograma e boxplot

Data: 17/07/2026

## Escopo

Implementação restrita ao frontend de duas visualizações estatísticas para
séries numéricas: Histograma e Boxplot. Os gráficos reutilizam exclusivamente
a última resposta já mantida em memória.

Backend, banco de dados, migrations, endpoints e dependências não foram
alterados. Dispersão, barras e valor único continuam fora do seletor.

O comando `git status --short` foi executado antes das alterações, mas o
sandbox apresentou `.git` como diretório vazio e respondeu que o projeto não é
um repositório Git. Nenhuma alteração existente foi descartada.

## Arquivos criados e alterados

Criados:

- `frontend/src/utils/statistics.ts`
- `frontend/src/components/HistogramChart.tsx`
- `frontend/src/components/BoxPlotChart.tsx`
- `frontend/tests/statistics.test.ts`
- `RELATORIO_FASE_4_3_HISTOGRAMA_BOXPLOT.md`

Alterados:

- `frontend/src/types/index.ts`
- `frontend/src/utils/chartData.ts`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/components/EChartsWrapper.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`

## Arquitetura

O contrato tipado agora aceita:

```typescript
type VisualizationType =
  | "automatic"
  | "line"
  | "states"
  | "histogram"
  | "boxplot";
```

`resolveVisualization` permanece como política central. Histograma e boxplot
recebem somente o grupo numérico já classificado após o filtro de qualidade e
marcam séries textuais como incompatíveis, sem removê-las da consulta.

O utilitário puro `statistics.ts` concentra filtragem de números finitos,
classes, quartis, bigodes, outliers e agrupamento por unidade. Os componentes
específicos apenas transformam esses resultados em opções do ECharts.

O carregamento modular do ECharts foi ampliado somente com `BarChart`,
`BoxplotChart` e `ScatterChart`; o scatter é usado exclusivamente para exibir
outliers do boxplot.

## Regra das classes do histograma

Cada tag numérica produz seu próprio histograma. A quantidade de classes é:

```text
ceil(sqrt(n)), limitada entre 1 e 50
```

As classes internas incluem o limite inferior e excluem o superior. A última
inclui o maior valor observado. O índice do máximo é fixado explicitamente na
última classe, evitando perda por ponto flutuante.

Os limites são calculados com os valores originais, sem arredondamento. Apenas
rótulos e tooltips são formatados. Valores constantes geram uma única classe,
sem divisão por zero. A soma das frequências permanece igual a `n`.

Cada gráfico identifica nome de exibição, nome da tag, unidade e quantidade. O
tooltip mostra intervalo, frequência e percentual, e a exportação de imagem
permanece disponível.

## Regra dos quartis e outliers

Os valores são ordenados e os quantis usam interpolação linear:

```text
position = (n - 1) * p
```

São calculados Q1, mediana e Q3. Com `IQR = Q3 - Q1`, os limites são
`Q1 - 1.5 * IQR` e `Q3 + 1.5 * IQR`. Os bigodes são o menor e o maior valor
observado dentro desses limites; os demais valores são exibidos como outliers.

Uma observação e valores constantes produzem cinco estatísticas iguais. Duas
ou três observações usam a mesma interpolação. Séries sem número válido não
produzem caixa vazia.

O tooltip informa nome, tag, unidade, quantidade, mínimo, Q1, mediana, Q3,
máximo e quantidade de outliers.

## Agrupamento por unidade

Boxplots com a mesma unidade são comparados no mesmo gráfico. Unidades
diferentes produzem gráficos separados. Unidade nula, vazia ou composta apenas
por espaços forma o grupo “Sem unidade”. Cada caixa usa o nome da tag no eixo X.

Histogramas nunca combinam distribuições: cada série recebe um gráfico próprio,
mesmo quando as unidades coincidem.

## Tratamento de qualidade e tipos

O filtro `Good=false` continua sendo aplicado por `buildChartDataGroups` antes
da classificação e antes dos cálculos estatísticos. Pontos removidos continuam
incrementando “Descartados”.

Somente valores JSON `number` finitos entram nos cálculos. Strings como
`"600"` e `"500.5"`, booleanos, `null`, `Infinity`, `-Infinity` e `NaN` são
excluídos e nunca convertidos.

Séries apenas ocultadas por incompatibilidade com a visualização não são
contabilizadas como descartadas.

## Incompatibilidades

No histograma e no boxplot, séries numéricas válidas continuam visíveis mesmo
quando textos estão presentes. As tags textuais são listadas em orientação
discreta, com o nome da visualização escolhida.

Quando não há série numérica compatível, nenhum gráfico vazio é criado; a
página orienta escolher Estados ou Automática. Séries individualmente mistas
continuam identificadas separadamente, preservando a regra anterior.

## Preservação dos dados, cards e CSV

Trocar entre linha, histograma, boxplot, estados e automático recalcula apenas a
apresentação local. Não ocorre nova chamada ao PI Web API, nem alteração de
tags, período, modo de consulta ou valores originais.

Os cards continuam usando o resumo da resposta completa. O CSV continua sendo
gerado de `query.timeSeries`, incluindo séries que a visualização atual apenas
oculta. O contador de descartados não muda ao trocar o seletor.

## Testes adicionados

Histograma:

- quantidade de classes pela raiz quadrada e máximo de 50;
- soma das frequências igual a `n`;
- constantes, uma observação, vazio, negativos e decimais;
- inclusão explícita do maior valor;
- exclusão de strings, booleanos, `null` e não finitos;
- qualidade ruim aplicada antes do cálculo;
- histogramas separados por série;
- tooltip com intervalo, frequência e percentual.

Boxplot:

- conjunto `[1, 2, 3, 4, 5]`;
- interpolação para duas e três observações;
- outlier no conjunto `[1, 2, 3, 4, 100]`;
- constantes, uma observação, negativos e vazio;
- exclusão de `"600"`, booleanos, `null` e não finitos;
- qualidade ruim aplicada antes do cálculo;
- bigodes observados e outliers separados;
- séries de mesma unidade juntas;
- unidades distintas separadas;
- grupo “Sem unidade”;
- tooltip completo e série scatter de outliers.

Integração:

- Histograma e Boxplot no seletor, sem tipos futuros;
- troca para ambos sem nova chamada à API;
- cards, CSV e descartados preservados;
- múltiplos histogramas e boxplots agrupados por unidade;
- séries textuais orientadas como incompatíveis;
- ausência de gráfico vazio sem números;
- `automatic`, `line` e `states` preservados;
- `"600"` textual e texto ruim filtrado antes da classificação;
- política central ampliada para os cinco modos.

Nenhum teste existente foi removido.

## Resultado exato dos testes

Comando:

```text
npm test -- --run
```

Resultado:

```text
Test Files  6 passed (6)
Tests       120 passed (120)
Duration    42.50s
```

A suíte mantém avisos preexistentes de atualizações React fora de `act(...)`,
sem falhas.

## Resultado exato do build

O comando `npm run build` parou na etapa `tsc -b` exclusivamente nos quatro
erros TypeScript antigos já documentados:

```text
tests/contract.test.tsx(2,35): error TS6133: 'fireEvent' is declared but its value is never read.
tests/errorBoundary.test.tsx(33,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(46,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(91,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
```

Nenhum erro novo da Fase 4.3 foi reportado. Conforme solicitado, o bundle foi
validado isoladamente:

```text
npx vite build
942 modules transformed
dist/assets/index-BhbY0Xu0.js  898.65 kB | gzip: 291.70 kB
built in 20.58s
```

Permanecem os avisos conhecidos sobre importação dinâmica/estática do mesmo
módulo e tamanho do chunk.

## Pendências

- corrigir em tarefa separada os quatro erros TypeScript preexistentes;
- validar histogramas e boxplots com séries reais de diferentes escalas;
- implementar dispersão, barras e valor único somente em fases futuras;
- avaliar divisão de chunks em uma tarefa de otimização, sem relação funcional
  com esta entrega.

## Roteiro de validação manual

1. Abrir “Visualização de Dados” e confirmar Automática como padrão.
2. Confirmar as opções Automática, Linha temporal, Estados, Histograma e
   Boxplot; confirmar ausência de Dispersão, Barras e Valor único.
3. Consultar duas tags numéricas e uma textual.
4. Escolher Histograma sem consultar novamente e confirmar um gráfico por tag
   numérica, com intervalos no eixo X e frequência no eixo Y.
5. Conferir nome, tag, unidade, `n`, tooltip com percentual e exportação.
6. Confirmar orientação com o nome da tag textual e “Descartados” inalterado.
7. Escolher Boxplot sem consultar novamente e confirmar agrupamento por unidade.
8. Conferir caixas, bigodes, outliers, nomes das tags e tooltip estatístico.
9. Consultar tags numéricas de unidades diferentes e confirmar gráficos
   separados; validar também uma tag sem unidade.
10. Alternar “Ignorar qualidade ruim”, consultar e conferir que pontos ruins
    não entram nas distribuições e aumentam “Descartados”.
11. Validar que `"600"` e `"500.5"` não entram em histograma ou boxplot.
12. Trocar entre os cinco modos e confirmar cards, período, tags e CSV intactos.
13. Consultar somente uma tag textual e escolher Histograma ou Boxplot;
    confirmar orientação sem gráfico vazio.
