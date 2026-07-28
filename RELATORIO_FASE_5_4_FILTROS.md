# Relatório da Fase 5.4 — Filtros Avançados e Exclusões

## 1. Escopo

Implementação de filtros avançados **client-side** sobre a última resposta
temporal mantida em memória. Os filtros afetam os oito tipos de visualização,
as métricas da Fase 5.3 e um novo CSV filtrado. Os dados originais
(`query.timeSeries`) permanecem imutáveis.

## 2. Decisões

- Filtros aplicados localmente, sem nova consulta ao PI.
- Várias regras ativas combinadas por **E** lógico.
- Categorias: qualidade, numéricos, textuais, dias da semana, horário,
  exclusão de valores específicos.
- Sem expressões regulares.
- Botão original exporta CSV original; novo botão exporta CSV filtrado.
- Pontos removidos contabilizados por motivo, sem duplicação.
- Fuso: America/Sao_Paulo.
- Strings numericamente formatadas não são convertidas.

## 3. Arquivos criados e alterados

### Criados

- `frontend/src/utils/dataFilters.ts` — utilitário puro de filtragem
- `frontend/src/components/AdvancedFiltersPanel.tsx` — interface do painel
- `frontend/tests/dataFilters.test.ts` — testes unitários (48 testes)

### Alterados

- `frontend/src/types/index.ts` — tipos `DataFilterConfiguration`,
  `DataFilterRule`, `FilterApplicationSummary`, etc.
- `frontend/src/pages/DataVisualizationPage.tsx` — integração do pipeline
- `frontend/src/components/DataFiltersPanel.tsx` — slot `advancedFilters`
- `frontend/src/components/QuerySummary.tsx` — contadores dos filtros
- `frontend/tests/dataVisualization.test.tsx` — ajuste no teste de métricas

## 4. Contratos TypeScript

Incluídos em `frontend/src/types/index.ts`:

- `NumericFilterOperator` — 8 operadores
- `TextFilterOperator` — 5 operadores
- `Weekday` — 7 dias
- `QualityFilterConfiguration` — 3 flags booleanas
- `DataFilterRule` — união de 5 variantes (numeric, text, weekday, timeRange,
  excludeValue)
- `DataFilterConfiguration` — qualidade + lista de regras
- `FilterApplicationSummary` — contadores por categoria
- `FilterRuleResult` — remoções por regra
- `FilterApplicationResult` — projeção filtrada + sumário + erros

Nenhum `any`, `@ts-ignore` ou `@ts-expect-error` foi utilizado.

## 5. Ordem do pipeline

1. Qualidade (global)
2. Dias da semana (global)
3. Intervalo de horário (global)
4. Regras numéricas ou textuais (por tag, na ordem da lista)
5. Exclusões específicas (por tag)

Cada ponto é removido no máximo uma vez. A soma das categorias é igual ao
total removido.

## 6. Qualidade

- `excludeBad` — remove pontos com `good === false`
- `excludeQuestionable` — remove pontos com `questionable === true`
- `excludeSubstituted` — remove pontos com `substituted === true`
- Padrão: `excludeBad: true` (preserva o comportamento anterior de
  `ignoreBadQuality: true`)
- Flags independentes; ponto removido contado uma única vez.

## 7. Filtros numéricos

Aplicados apenas a valores JSON `number` finitos. Operadores:

- Igual, Diferente, Maior que, Maior ou igual, Menor que, Menor ou igual,
  Entre, Fora do intervalo.
- Igualdade exata (sem tolerância).
- `"600"` não é tratado como número.
- Booleano e null não são convertidos.

## 8. Filtros textuais

Aplicados apenas a valores JSON `string`. Operadores:

- Igual, Diferente, Contém, Começa com, Termina com.
- Opção de diferenciar maiúsculas/minúsculas (padrão: false).
- Números, booleanos e null não são convertidos para texto.
- `"600"` é string e pode ser filtrado textualmente.

## 9. Dias e horários

- Dias da semana em America/Sao_Paulo.
- Pelo menos um dia deve estar selecionado.
- Horário: formato HH:mm, limites inclusivos.
- Se início > fim, atravessa meia-noite (ex: 23:00–07:00).

## 10. Exclusões

- Valor exato por tag: número, string ou booleano.
- `600` numérico ≠ `"600"` textual.
- String respeita caseSensitive.
- Booleano aceita `true` ou `false`.

## 11. Escopo por tag

Regras numéricas, textuais e de exclusão são associadas a uma tag específica
pelo `tagId`. Não dependem da posição da série. Filtros de qualidade, dia da
semana e horário são globais.

## 12. Contadores

Preservados no `QuerySummary`:
- **Pontos recebidos**: total original da API
- **Descartados**: soma dos removidos pelo pipeline de filtros
- **Qualidade, Numérico, Texto, Data/horário, Exclusões** (exibidos no
  AdvancedFiltersPanel)

As séries ocultadas por visualização não são descartadas.

## 13. Integração com métricas

As 20 métricas da Fase 5.3 calculam sobre a projeção filtrada
(`filteredTimeSeries`). Métricas de erro também filtram as séries
individualmente antes de formar pares. Alterar filtros atualiza os cartões
sem nova chamada à API.

## 14. Integração com os oito gráficos

Os oito tipos (Automática, Linha, Estados, Histograma, Boxplot, Dispersão,
Barras, Valor único) recebem `filteredTimeSeries`. Se todos os pontos
compatíveis forem removidos, o gráfico exibe a mensagem "Nenhum valor
encontrado". Eixos manuais, X/Y, ordem, tooltips, zoom e exportação de imagem
são preservados.

## 15. CSV original

Botão `Baixar CSV original`:
- Usa `query.timeSeries`
- Ignora filtros locais
- Mantém esquema e todos os pontos recebidos

## 16. CSV filtrado

Botão `Baixar CSV filtrado`:
- Usa `filteredTimeSeries`
- Mesmo esquema do CSV original
- Preserva timestamps, qualidade e valores originais
- Nome: `dados_pi_filtrados_YYYY-MM-DD.csv`
- Desabilitado sem consulta concluída

## 17. Imutabilidade

`query.timeSeries` nunca é alterado. `applyDataFilters` produz uma nova
projeção sem modificar a entrada. Arrays, séries e pontos originais
permanecem intactos.

## 18. Desempenho

- Regras agrupadas por tag antes de percorrer os pontos.
- Cada ponto percorrido uma única vez.
- Uso de `useMemo` para projeções derivadas.
- Teste com 20.000 pontos executa em < 2s.

## 19. Acessibilidade

- Labels associados via `controlId`
- `aria-expanded` no botão recolhível
- `data-testid` em todos os controles
- Botões com nomes acessíveis
- Teclado funcional
- Sem dependência exclusiva de cor

## 20. Testes

- `frontend/tests/dataFilters.test.ts` — 48 testes unitários
  - Qualidade (5), Numéricos (10), Textuais (9), Dias/horários (3),
    Exclusões (6), Pipeline (10), Soma categorias (1)
- `frontend/tests/dataVisualization.test.tsx` — 43 testes de integração
  (ajustado para métricas com dados pré-filtrados)
- Total: 290 testes (48 novos + 242 existentes)

## 21. Baseline (antes das alterações)

- Testes: 242 passed, 11 files
- Build: concluído com código zero
- Git: sem repositório git

## 22. Resultado final dos testes

```
Test Files  12 passed (12)
Tests  290 passed (290)
```

## 23. Resultado final do build

```
✓ built in 16.63s
```

Código de saída: zero.

## 24. Warnings

- Nenhum warning de TypeScript.
- Nenhum warning de compilação.
- Aviso do Vite sobre tamanho do chunk (pré-existente, não introduzido).

## 25. Limitações

- Filtros são **client-side**: resultados limitados por `maxCount` da
  consulta original.
- Não há suporte a expressões regulares.
- Filtros não são persistidos (recarregar a página perde as regras).
- Não há drag-and-drop para reordenar regras.
- Não há Web Worker (não necessário dado o desempenho medido).

## 26. Pendências

- Nenhuma pendência para esta fase.

## 27. Roteiro de validação manual

1. Abrir a página de visualização de dados.
2. Selecionar equipamento, tag e consultar.
3. Clicar em "▼ Filtros" no painel lateral.
4. Verificar checkboxes de qualidade (padrão: excluir qualidade ruim ativo).
5. Adicionar regra numérica (ex: Temperatura > 20).
6. Verificar que o gráfico e as métricas refletem os pontos filtrados.
7. Adicionar regra textual (ex: Estado = "RUN").
8. Verificar que o CSV original contém todos os pontos.
9. Verificar que o CSV filtrado contém apenas os pontos restantes.
10. Desativar/remover regras e verificar que o gráfico é atualizado.
11. Clicar "Limpar filtros" e verificar retorno ao estado inicial.
12. Verificar que alterar filtros não dispara nova chamada à API.
