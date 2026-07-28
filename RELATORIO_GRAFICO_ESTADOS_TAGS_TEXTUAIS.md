# Relatório do gráfico de estados para tags textuais

Data: 16/07/2026

## Escopo

Implementação restrita ao frontend para visualizar uma única tag textual como
gráfico temporal de estados. Backend, banco de dados, migrations, endpoints,
dependências e demais tipos de gráfico não foram alterados.

O `git status --short` foi solicitado antes das mudanças, mas não pôde ser
obtido porque o sandbox desta sessão apresenta `.git` como diretório vazio. As
alterações foram feitas somente nos arquivos diretamente relacionados, sem
comandos de descarte ou sobrescrita de mudanças existentes.

## Causa da limitação anterior

O contrato TypeScript já aceitava `number | string | boolean | null`, porém
`buildChartData` enviava somente números finitos para o gráfico. Strings,
booleanos e valores nulos eram convertidos em lacunas, e o componente do gráfico
possuía apenas eixo Y numérico. Portanto, estados textuais chegavam corretamente
ao frontend, mas não tinham transformação ou visualização próprias.

## Arquivos alterados

- `frontend/src/utils/chartData.ts`
- `frontend/src/components/TimeSeriesChart.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`
- `RELATORIO_GRAFICO_ESTADOS_TAGS_TEXTUAIS.md`

`frontend/src/types/index.ts` não precisou ser alterado: `TimeSeriesPoint.value`
já estava corretamente tipado como `number | string | boolean | null`.

## Comportamento implementado

- Uma única série textual é exibida em eixo X temporal e eixo Y categórico.
- A linha usa `step: "end"`, preservando visualmente cada estado até a próxima
  mudança.
- Estados consecutivos iguais são compactados.
- O primeiro estado é mantido.
- Um ponto visual adicional no fim do período consultado prolonga o último
  estado até esse limite.
- Tooltip mostra timestamp, nome de exibição, nome da tag, estado original e
  qualidade.
- Zoom, legenda, exportação de imagem e responsividade continuam disponíveis.
- O caminho de construção do gráfico numérico mantém linha, eixos, zoom,
  tooltip, legenda, exportação e amostragem anteriores.
- Tags numéricas e uma tag textual podem ser consultadas juntas: o gráfico
  numérico aparece primeiro e o gráfico de estados aparece abaixo.

## Estratégia de detecção de tipos

A detecção usa exclusivamente o tipo JSON efetivamente recebido:

- número finito: `numeric`;
- string ou booleano: `textual`;
- presença simultânea de número e estado: `mixed`;
- somente valores nulos: `empty`.

Não são usados `Number`, `parseFloat`, `parseInt` ou coerções equivalentes.
Assim, `"600"` e `"500.5"` continuam strings e estados categóricos. Booleanos
são representados pelos estados `"true"` e `"false"`.

## Estratégia de categorias

As categorias são incluídas na ordem da primeira ocorrência após a aplicação do
filtro de qualidade. Não há ordenação alfabética. Um `Map` associa o texto
original ao índice categórico usado pelo ECharts, sem alterar o valor exibido.

Valores repetidos consecutivos não geram uma nova transição. O ponto sintético
do fim do período reutiliza a última categoria, o último texto e a última
qualidade, sem criar uma categoria adicional.

## Tratamento da qualidade

- `Good=true` não é descartado.
- Quando “Ignorar qualidade ruim” está ativo, `Good=false` é removido tanto do
  gráfico numérico quanto do gráfico de estados.
- O descarte é registrado na série e em `totalDroppedPoints`.
- Foi corrigida a soma global de descartados, que antes não era incrementada,
  embora o contador por série fosse.
- O tooltip textual usa as classificações existentes: OK, Substituído,
  Questionável e Ruim.

## Tratamento de valores null

`null` é ausência de valor: não participa da detecção de tipo, não cria a
categoria `"null"` e não cria transição de estado. O estado anterior permanece
visível até uma mudança textual válida ou até o fim do período.

## Tratamento de seleção mista

Números e textos em tags diferentes são permitidos e separados em gráficos
independentes. Nenhum valor é coagido entre os tipos.

Como esta entrega permite uma única série textual, a seleção de mais de uma
série exclusivamente textual mostra orientação para selecionar apenas uma tag
textual, mas não impede a exibição das séries numéricas válidas.

Uma tag individual que contenha simultaneamente valores numéricos e textuais é
identificada pelo nome, não é desenhada e não bloqueia outras séries válidas.

## Exibição simultânea de séries numéricas e textuais

### Causa do bloqueio anterior

O bloqueio usava `ChartBuildResult.valueKind`, que consolida todos os pontos da
resposta. Assim, uma tag exclusivamente numérica e outra exclusivamente textual
produziam globalmente `mixed`, embora nenhuma das duas fosse individualmente
mista. A página interpretava esse resultado agregado como erro e substituía
todos os gráficos por um alerta.

### Arquivos alterados neste ajuste

- `frontend/src/utils/chartData.ts`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`
- `RELATORIO_GRAFICO_ESTADOS_TAGS_TEXTUAIS.md`

### Estratégia de separação por série

`buildChartDataGroups` primeiro constrói o resultado completo, usado pelos
cards de resumo. Em seguida, consulta o `valueKind` de cada `ChartSeries` e
produz:

- um subconjunto contendo todas as séries `numeric`;
- um subconjunto independente para cada série `textual`;
- uma lista das séries individualmente `mixed`.

Cada subconjunto é reconstruído a partir dos dados originais. Com isso, o
gráfico numérico recalcula somente seus eixos e unidades, enquanto o gráfico de
estados possui somente suas próprias categorias. Os contadores do resumo não
usam os subconjuntos e continuam representando a consulta completa.

### Uma tag numérica e uma textual

São mostrados dois gráficos responsivos dentro do mesmo card. O primeiro recebe
somente a série numérica e é identificado por “Séries numéricas”. Abaixo, com
espaçamento `mb-4`, o gráfico categórico recebe somente a série textual e é
identificado por “Estados”. O antigo alerta global não é exibido. CSV, filtros e
cards de resumo permanecem disponíveis.

### Várias tags numéricas

Todas as séries numéricas continuam no mesmo gráfico temporal, preservando os
dois eixos por unidade, amostragem, qualidade, zoom, tooltip, legenda e
exportação existentes.

### Várias tags textuais

Como o limite atual continua sendo uma série textual por gráfico, duas ou mais
tags textuais geram uma orientação para selecionar somente uma. Se também
existirem tags numéricas válidas, o gráfico numérico continua visível.

### Série individual mista

Uma única tag que possua valores `number` e `string` recebe classificação
`mixed`. Ela não é enviada a nenhum eixo, seu nome é informado em alerta e as
demais séries numéricas ou textuais válidas continuam sendo desenhadas. Não há
conversão de valores.

### Testes adicionados neste ajuste

- separação de uma tag numérica e outra textual;
- garantia de que cada gráfico recebe apenas suas próprias séries;
- ausência do alerta global antigo;
- preservação de `"600"` como `string` no subconjunto textual;
- duas séries numéricas no mesmo subconjunto;
- limite de duas séries textuais;
- manutenção do gráfico numérico quando há várias séries textuais;
- identificação nominal de série individual mista;
- manutenção de outras séries quando uma é individualmente mista;
- qualidade aplicada individualmente aos dois grupos;
- contadores globais de pontos, tipos, descartados e séries;
- renderização isolada para consulta somente numérica ou somente textual.

### Resultado dos testes e builds deste ajuste

```text
npm test -- --run
Test Files  5 passed (5)
Tests       90 passed (90)
Duration    18.26s
```

```text
npm run build
Resultado: falha somente nos mesmos quatro erros TypeScript preexistentes em
tests/contract.test.tsx e tests/errorBoundary.test.tsx.
```

```text
npx vite build
939 modules transformed
dist/assets/index-DQ-pLEf0.js  860.78 kB | gzip: 279.69 kB
built in 23.35s
```

### Roteiro manual da exibição simultânea

1. Selecionar duas tags válidas: uma com valores JSON `number` e outra com
   valores JSON `string`.
2. Consultar um período com dados para ambas.
3. Confirmar “Séries numéricas” acima e “Estados” abaixo.
4. Confirmar que o primeiro gráfico contém somente a tag numérica e que o
   segundo preserva estados como `"600"` e `"500.5"`.
5. Validar zoom, tooltip, legenda e exportação em ambos.
6. Alternar “Ignorar qualidade ruim” e conferir ambos os gráficos e os cards.
7. Acrescentar uma segunda tag numérica e confirmar que ela aparece no primeiro
   gráfico.
8. Acrescentar uma segunda tag textual e confirmar a orientação, mantendo o
   gráfico numérico.
9. Se houver uma tag individualmente mista, confirmar o alerta nominal e a
   continuidade dos demais gráficos.

## Correção da classificação após o filtro de qualidade

### Causa encontrada

A classificação de cada série era atualizada antes do descarte por qualidade.
Por isso, um único valor textual com `Good=false` podia transformar uma série
numérica válida em `mixed`, mesmo quando “Ignorar qualidade ruim” removia esse
ponto do gráfico. O mesmo problema ocorria no sentido inverso, quando um número
ruim contaminava uma série textual.

### Arquivos alterados neste ajuste

- `frontend/src/utils/chartData.ts`
- `frontend/tests/visualization.test.ts`
- `frontend/tests/dataVisualization.test.tsx`
- `RELATORIO_GRAFICO_ESTADOS_TAGS_TEXTUAIS.md`

### Ordem anterior e ordem corrigida

Antes, cada ponto com timestamp válido incrementava o total recebido, tinha seu
tipo incorporado a `seriesValueKind` e somente depois era descartado quando
`Good=false`.

Agora a ordem é:

1. validar o timestamp e contar o ponto como recebido;
2. se o filtro estiver ativo e `Good=false`, contar o descarte e interromper o
   processamento desse ponto;
3. classificar somente os valores restantes;
4. contar números finitos como numéricos e somente strings ou booleanos como
   não numéricos;
5. manter `null` como ausência, sem tipo, categoria ou contador de valor.

Assim, o alerta `mixed` só existe quando números e textos válidos permanecem na
mesma série após o filtro. Strings não são convertidas: `"600"` permanece
`string` e continua sendo um estado categórico.

### Testes adicionados neste ajuste

- série numérica com texto ruim continua `numeric` e sem alerta;
- série textual com número ruim continua `textual` e preserva categorias;
- série realmente mista após o filtro continua `mixed`;
- contadores de recebidos, descartados, numéricos e não numéricos;
- `null` sem classificação, categoria ou contagem não numérica;
- `"600"` preservado explicitamente como `string`;
- gráficos numérico e textual simultâneos preservados;
- cenário de 1997 números bons e 3 strings ruins.

No cenário equivalente ao real, o resultado contém 2000 pontos recebidos,
1997 numéricos, 3 descartados e 0 não numéricos. A série permanece numérica, o
gráfico é construído e nenhum alerta de série mista é exibido.

### Resultados exatos deste ajuste

Testes direcionados:

```text
Test Files  2 passed (2)
Tests       53 passed (53)
Duration    12.47s
```

Suíte completa:

```text
npm test -- --run
Test Files  5 passed (5)
Tests       95 passed (95)
Duration    31.55s
```

O comando `npm run build` continua interrompido somente pelos mesmos quatro
erros TypeScript preexistentes em `tests/contract.test.tsx` e
`tests/errorBoundary.test.tsx`. A geração isolada do bundle foi confirmada:

```text
npx vite build
939 modules transformed
dist/assets/index-CZWUk694.js  860.78 kB | gzip: 279.70 kB
built in 20.89s
```

### Pendências deste ajuste

- corrigir separadamente os quatro erros TypeScript antigos para que o build
  agregado termine com código zero;
- validar o cenário com uma consulta real ao PI, sem alterar cadastros ou
  credenciais.

## Testes adicionados ou ampliados

Foram cobertos:

- série exclusivamente numérica e configuração anterior do gráfico numérico;
- string comum como estado;
- `"600"` e `"500.5"` como strings, incluindo verificação explícita de tipo;
- booleano como estado;
- `null` sem categoria;
- compactação de estados consecutivos repetidos;
- categorias na ordem da primeira ocorrência;
- primeiro estado e extensão do último até o fim do período;
- `Good=true` mantido;
- `Good=false` descartado quando solicitado;
- contagem de descartados por série e global;
- payload misto sem coerção;
- eixo Y categórico e `step: "end"`;
- alerta da página para resposta mista.
- separação simultânea por série, sem bloqueio global;
- séries individuais mistas sem bloqueio das séries válidas.
- classificação realizada somente após o descarte por qualidade.

## Resultado exato dos testes

Comando:

```text
npm test -- --run
```

Resultado final:

```text
Test Files  5 passed (5)
Tests       95 passed (95)
Duration    31.55s
```

A suíte emite avisos preexistentes de atualizações React não envolvidas em
`act(...)`; eles não causam falhas e não foram alterados por estarem fora do
escopo.

## Resultado exato do build

Comando solicitado:

```text
npm run build
```

Resultado: falha na etapa `tsc -b`, com os seguintes erros preexistentes e não
relacionados:

```text
tests/contract.test.tsx(2,35): error TS6133: 'fireEvent' is declared but its value is never read.
tests/errorBoundary.test.tsx(33,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(46,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
tests/errorBoundary.test.tsx(91,10): error TS2786: 'BuggyComponent' cannot be used as a JSX component.
```

Nenhum erro da implementação do gráfico de estados foi reportado pelo
TypeScript. Para validar separadamente a geração do bundle, também foi
executado:

```text
npx vite build
```

Resultado:

```text
939 modules transformed
dist/assets/index-CZWUk694.js  860.78 kB | gzip: 279.70 kB
built in 20.89s
```

O Vite manteve avisos já existentes sobre importação dinâmica/estática do mesmo
módulo e tamanho de chunk.

## Pendências

- Corrigir, em tarefa separada, os quatro erros TypeScript preexistentes nos
  testes para que o comando agregado `npm run build` finalize com código zero.
- Validar visualmente com dados reais do PI em diferentes quantidades de
  estados e períodos.
- Histogramas, boxplots, dispersão, barras e valor único permanecem fora desta
  entrega.

## Roteiro de validação manual com uma tag textual real

1. Iniciar backend e frontend e abrir “Visualização de Dados”.
2. Selecionar equipamento e uma única tag textual que possua estados conhecidos.
3. Usar modo “Valores registrados” e um período que contenha mudanças.
4. Consultar e confirmar eixo Y categórico e linha em degraus.
5. Verificar no tooltip o timestamp, a tag, estados como `P304I`, `P316B`,
   `600` ou `500.5` e a qualidade.
6. Confirmar que estados repetidos não geram transições extras e que o último
   permanece até o fim do período.
7. Alternar “Ignorar qualidade ruim” e conferir gráfico e contador de
   descartados.
8. Selecionar junto uma tag numérica e confirmar os dois gráficos simultâneos,
   sem conversão ou erro de renderização.
9. Selecionar uma segunda tag textual e confirmar que a orientação de limite
   não remove o gráfico numérico.
