# Relatório da Fase 5.3 — Métricas e parâmetros de análise

Data: 17/07/2026

## Escopo

Implementação restrita ao frontend de um seletor com 20 métricas estatísticas e
cartões de resultado calculados sobre a última resposta temporal em memória.
Backend, banco, migrations, endpoints, dependências, consulta ao PI, os oito
gráficos e o CSV original não foram alterados.

`git status --short` foi solicitado antes das mudanças, mas o sandbox apresentou
`.git` vazio e informou que o projeto não é um repositório Git. Nenhuma mudança
existente foi descartada.

## Arquivos criados e alterados

Criados:

- `frontend/src/utils/analysisMetrics.ts`;
- `frontend/src/components/MetricConfigurationPanel.tsx`;
- `frontend/src/components/MetricResults.tsx`;
- `frontend/tests/analysisMetrics.test.ts`;
- `RELATORIO_FASE_5_3_METRICAS.md`.

Alterados:

- `frontend/src/types/index.ts`;
- `frontend/src/components/DataFiltersPanel.tsx`;
- `frontend/src/pages/DataVisualizationPage.tsx`;
- `frontend/tests/dataVisualization.test.tsx`;
- `README.md`.

## Arquitetura

`AnalysisMetric` contém exatamente os 20 IDs aprovados. “Nenhuma métrica” é
representada por `{ kind: "none" }`, não pertence ao catálogo e não produz
cartão. `MetricConfiguration` é uma união discriminada para métricas simples,
especificação, controle, erro, capacidade do erro e erro fora de controle.
Campos numéricos ausentes usam `null`, nunca zero.

O catálogo central informa nome, descrição, categoria, mínimo de pontos,
requisitos e regra de unidade. `MetricResult` distingue `ok`,
`insufficientData`, `invalidConfiguration` e `calculationError`; somente `ok`
possui valor numérico. Resultados não finitos nunca atravessam o contrato.

`DataVisualizationPage` calcula os resultados com `useMemo`. A seleção de
métrica, limites, Real, Referência ou qualidade apenas recalcula a projeção
local. `query.timeSeries` continua alimentando gráficos e CSV sem mutação.

## Fórmulas e dados aceitos

- Contagem, total, média, mínimo e máximo usam números JSON finitos.
- O desvio-padrão é amostral, calculado por Welford com divisor `n - 1`.
- Cp e Cpk usam as fórmulas convencionais com LIE, LSE e desvio amostral.
- PC é o percentual dentro de `[LIE, LSE]`, incluindo os limites.
- OOC conta apenas valores `< LIC` ou `> LSC`; os limites são conformes.
- Erro é `Real - Referência`; MAE, MSE, RMSE e estatísticas assinadas usam os
  pares efetivamente encontrados.
- Cpk do erro aplica LIE/LSE à distribuição de erros.
- OOC MAE usa somente pares cujo valor Real está fora de LIC/LSC. Havendo pares
  e nenhum OOC, o resultado válido é zero com `oocCount = 0`.

Strings, inclusive `"600"` e `"500.5"`, booleanos, `null`, `NaN` e infinitos
não são convertidos. Quando “Ignorar qualidade ruim” está ativo, `Good=false`
é removido antes de qualquer cálculo.

## Pareamento e unidades

Real e Referência devem ser tags diferentes, estar presentes e possuir a mesma
unidade normalizada, ou ambas não possuir unidade. Os pares exigem o mesmo
instante UTC. Timestamps duplicados usam as filas estáveis já adotadas pela
dispersão; pontos sem par são ignorados e informados no cartão.

Contagem, Cp, Cpk, Cpk do erro e OOC são adimensionais; PC usa `%`; métricas de
valor e erro usam a unidade de origem; MSE usa a unidade ao quadrado. Sem unidade
de origem, o resultado permanece sem unidade.

## Interface

A seção de métrica fica após a configuração de séries e antes do modo de
consulta. Campos de Real/Referência, LIE/LSE e LIC/LSC aparecem apenas quando
necessários. Erros são exibidos com `role="alert"`, mas não bloqueiam a consulta
ao PI. Após a consulta, cada série com número finito produz um cartão nas
métricas individuais; métricas de erro produzem um cartão para o par explícito.

Os cartões mostram métrica, tag ou par, valor formatado, unidade, quantidade de
amostras/pares, ignorados e OOC quando aplicável. Estados insuficientes ou
inválidos são textuais, sem `NaN`, `Infinity` ou zero inventado.

## Testes

Os testes cobrem catálogo, configuração neutra, todas as famílias de fórmulas,
desvio amostral, Cp/Cpk/PC, limites inclusivos, qualidade, tipos incompatíveis,
pareamento UTC, duplicatas, pares ausentes, sete métricas básicas de erro, Cpk
do erro, OOC MAE, unidades, configurações inválidas, dados insuficientes e
ausência de não finitos.

A integração cobre 20 opções mais a opção neutra, cartões adicionais,
recalculo por qualidade sem nova chamada, preservação do gráfico, resumo e CSV,
e validação acessível que não bloqueia a consulta.

## Baseline anterior

```text
npm test -- --run
Test Files  10 passed (10)
Tests       214 passed (214)
Duration    41.49s
```

```text
npm run build
949 modules transformed
dist/assets/index-DRFK5yRp.js  921.04 kB | gzip: 297.74 kB
built in 25.54s
```

## Resultado final

```text
npm test -- --run
Test Files  11 passed (11)
Tests       236 passed (236)
Duration    62.67s
```

A suíte mantém avisos preexistentes de atualizações React fora de `act(...)`,
sem falhas.

```text
npm run build
952 modules transformed
dist/assets/index-C3VECiPn.js  935.83 kB | gzip: 301.57 kB
built in 21.06s
```

O build terminou com código zero. Permanecem os avisos conhecidos do Vite
sobre importação dinâmica/estática do mesmo módulo e chunk acima de 500 kB.

## Limitações e pendências

- Configuração e limites permanecem somente em memória.
- As métricas não criam cores, alarmes ou faixas nos gráficos.
- O cálculo considera toda a resposta recebida, que ainda pode estar limitada
  por `maxCount`; não representa dados que o PI não devolveu.
- Não houve validação com PI real.
- Filtros avançados, comparação entre períodos e demais modelos continuam fora
  desta fase.
