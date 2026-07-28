# Relatório da Fase 4.5 — Valor único

Data: 17/07/2026

## Escopo

Implementação frontend do oitavo modo, `singleValue`, sem alterações em
backend, banco, migrations, endpoints ou dependências. O modo reutiliza a
última resposta em memória e cria um cartão Bootstrap responsivo por série.

## Arquivos

Criados:

- `frontend/src/utils/singleValue.ts`;
- `frontend/src/components/SingleValueCards.tsx`;
- `frontend/tests/singleValue.test.tsx`;
- `RELATORIO_FASE_4_5_VALOR_UNICO.md`.

Alterados:

- `frontend/src/types/index.ts`;
- `frontend/src/utils/chartData.ts`;
- `frontend/src/components/DataFiltersPanel.tsx`;
- `frontend/src/pages/DataVisualizationPage.tsx`;
- `frontend/tests/visualization.test.ts`;
- `frontend/tests/dataVisualization.test.tsx`;
- `README.md`.

## Seleção do último valor

`latestDisplayableValue` percorre o array sem assumir ordenação, valida cada
timestamp, aplica o filtro `Good=false`, ignora valores ausentes ou não
exibíveis e mantém a observação com o maior instante. Se o ponto mais recente é
ruim e o filtro está ativo, ocorre fallback para o ponto exibível anterior. Não
é criado valor artificial.

## Tipos aceitos

São aceitos exclusivamente `number` finito, `string` e `boolean`, preservando o
tipo original. `null`, `NaN` e infinitos não são exibíveis. Não há `Number`,
`parseInt`, `parseFloat` ou coerção equivalente. Portanto, `600` permanece
número, enquanto `"600"` e `"500.5"` permanecem strings. Booleanos são exibidos
como `true` ou `false`.

Uma série historicamente mista é aceita somente neste modo: o cartão mostra o
tipo original do ponto mais recente. As políticas dos demais gráficos não
foram alteradas.

## Qualidade e cores

A prioridade é aplicada exclusivamente às flags do PI:

1. `Good=false`: Ruim, vermelho;
2. `Good=true` e `Questionable=true`: Questionável, âmbar;
3. `Good=true`, não questionável e `Substituted=true`: Substituído, azul;
4. bom sem as outras flags: Bom, verde;
5. sem observação: Sem dados, cinza.

Questionable prevalece visualmente sobre Substituted quando ambas são verdade,
mas as três flags continuam visíveis e independentes. O status textual está no
cabeçalho, de modo que a informação não depende apenas da cor.

## Filtro, múltiplas séries e dados originais

Com o filtro ativo, pontos ruins são removidos antes da seleção e permanecem no
contador global de descartados. Sem o filtro, o último ponto ruim pode aparecer
em vermelho. O modo aceita simultaneamente séries numéricas, textuais,
booleanas e mistas, sem limite de unidade, agrupamento ou incompatibilidade.

A troca de visualização não chama a API, não modifica os pontos, período, modo,
cards de resumo ou CSV. A exportação continua usando `query.timeSeries`.

## Testes

Foram cobertos maior timestamp fora de ordem, inteiro, decimal, strings comuns
e numericamente formatadas, booleanos, `null`, não finitos, todas as prioridades
de qualidade, flags simultâneas, fallback, ausência de dados, múltiplos cartões,
série mista, unidade, timestamp e integração sem nova consulta, preservando
resumo, CSV e descartados.

Resultado final da suíte frontend:

```text
Test Files  8 passed (8)
Tests       144 passed (144)
Duration    32.76s
```

Build:

```text
npm run build
947 modules transformed
dist/assets/index-CvXR8cOA.js  907.64 kB | gzip: 293.86 kB
built in 29.03s
```

## Validação manual

1. Consultar tags numéricas, textuais e booleanas.
2. Trocar para Valor único sem consultar novamente.
3. Conferir um cartão por tag, tipo original, unidade, timestamp e flags.
4. Validar `"600"` e `"500.5"` sem aspas e sem conversão.
5. Desativar o filtro e conferir um último ponto ruim em vermelho.
6. Ativar o filtro e conferir fallback e aumento de Descartados.
7. Validar Questionável em âmbar, Substituído em azul e ambas as flags.
8. Conferir cartão cinza para série sem valor e responsividade do grid.
