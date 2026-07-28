# RELATÓRIO — FASE 5.6 — LIMITES, FAIXAS E REGRAS DE CORES

Data: 24/07/2026  
Status: **APROVADA**

## 1. Resumo executivo

Foi implementada configuração visual local de linhas de limite, faixas e regras de cores para séries numéricas. O recurso inicia desativado, usa `series_instance_id`, não altera respostas, métricas ou CSV e não realiza consultas ao PI durante alterações visuais.

## 2. Objetivo

Permitir análise visual por limites, regiões e cores no gráfico temporal existente, inclusive em comparações A/B, sem persistência e sem modificar os dados.

## 3. Pré-condição da Fase 5.5

`RELATORIO_FASE_5_5_COMPARACOES.md` registra **APROVADA**. O relatório técnico Recorded possui atualização posterior confirmando 187 testes backend e os cenários reais. Gate satisfeito.

## 4. Estado anterior

O gráfico já possuía identidade de instância, cor padrão e associação ao eixo Y, mas não tinha `markLine`, `markArea` nem regras condicionais. `git status --short` e `git diff --stat` não puderam operar porque o `.git` disponível não é reconhecido como repositório. As alterações existentes foram preservadas.

## 5. Arquitetura implementada

- Tipos explícitos para limites, faixas, regras e estado visual.
- Utilitário puro para parsing, validação, prioridade e correspondência.
- Painel especializado `VisualRulesPanel`.
- Integração mínima na página e no `TimeSeriesChart` existente.
- ECharts reutilizado; nenhuma dependência adicionada.
- Backend, banco, autenticação e contratos PI não foram alterados.

## 6. Estado das configurações

O estado reside apenas em `DataVisualizationPage`. Não há backend, banco, arquivo, URL, preset ou `localStorage`. Recarregar a página perde a configuração, comportamento esperado até a Fase 5.7.

## 7. Identidade das séries

Todas as configurações são indexadas por `series_instance_id`. No modo normal, a identidade compatível é `tag:<tag_id>`. O ID não depende de nome, WebID, índice ou posição.

## 8. Linhas de limite

Aceitam zero, negativos e decimais; possuem rótulo, cor, estilo sólido/tracejado/pontilhado, espessura e visibilidade. Entradas vazias, não numéricas e não finitas são rejeitadas. São renderizadas por `markLine` na própria série.

## 9. Faixas

Possuem inferior, superior, rótulo, cor, opacidade e visibilidade. A validação exige inferior menor que superior, detecta sobreposição e limita opacidade a 0,35. Lacunas são permitidas. Reordenação, remoção e limpeza são locais. A renderização usa `markArea` silenciosa no fundo.

## 10. Regras de cores

Operadores: `<`, `<=`, `>`, `>=`, `==`, Entre e Fora do intervalo. Somente `number` JSON finito participa. String, booleano, `null`, `undefined`, `NaN` e infinito não são coagidos. Pontos sem correspondência mantêm a cor padrão.

## 11. Prioridade das regras

A ordem visível é a prioridade. A primeira regra ativa e válida correspondente prevalece. Reordenar muda deterministicamente o resultado.

## 12. Integração com eixos

Limite e faixa pertencem à opção da própria série e, portanto, acompanham seu `yAxisIndex` 0 ou 1. Trocar a série entre eixo principal e secundário atualiza localmente. Não há conversão de unidade ou deslocamento automático.

## 13. Integração com comparações

Contextos A/B possuem mapas independentes. Teste com a mesma tag 7 confirmou limites 800 para `A-7` e 850 para `B-7`, sem colisão.

## 14. Séries não numéricas

O painel informa: “Limites numéricos não estão disponíveis para esta série.” Nenhuma regra numérica é oferecida. Dados textuais/digitais continuam intactos para gráfico, inspeção e CSV.

## 15. Tooltip

Mantém série, tag, valor, unidade, qualidade, tempo e timestamp original em comparação por período. Quando aplicável, acrescenta rótulo/cor da regra e rótulo da faixa.

## 16. Legenda

Permanece baseada na identidade/nome da série. Rótulos de regras não renomeiam a legenda.

## 17. Filtros

As regras são aplicadas sobre os pontos restantes no `ChartSeries`. O estado visual é separado do filtro e não é apagado quando uma série fica temporariamente fora da visualização.

## 18. Métricas

`calculateMetricResults` não recebe a configuração visual. Teste de regressão confirmou resultado idêntico antes/depois.

## 19. CSV

`buildTimeSeriesCsv` não recebe a configuração visual. Teste confirmou conteúdo idêntico e ausência de pontos artificiais.

## 20. Reset

É possível limpar separadamente limites, faixas ou regras, restaurar uma série e restaurar tudo. O reset geral exige confirmação na interface. Resultados, filtros, séries e eixos não são apagados.

## 21. Ausência de novas consultas

Teste integrado da página executou consulta inicial, ativação, seleção de série, adição de limite/faixa/regra, troca de eixo, troca de gráfico e reset. Contadores finais:

```text
Consultas antes das alterações visuais: 1
Consultas depois das alterações visuais: 1
Novas consultas ao PI: 0
Chamadas de comparação adicionais: 0
```

## 22. Arquivos alterados

- `frontend/src/types/index.ts`
- `frontend/src/utils/visualRules.ts`
- `frontend/src/components/VisualRulesPanel.tsx`
- `frontend/src/components/TimeSeriesChart.tsx`
- `frontend/src/components/DataFiltersPanel.tsx`
- `frontend/src/pages/DataVisualizationPage.tsx`
- `frontend/tests/visualRules.test.tsx`
- `frontend/tests/dataVisualization.test.tsx`
- `RELATORIO_FASE_5_6_LIMITES_FAIXAS_CORES.md`

Nenhum arquivo backend, migration ou dependência foi alterado.

## 23. Testes backend

- Execução no isolamento: bloqueio conhecido após 32 testes; interrompida pelo limite seguro de 180 s e não contabilizada como aprovação.
- Reexecução integral fora do isolamento: **187 aprovados, 0 falhos, 0 ignorados, 32,46 s, saída 0**.
- 80 warnings preexistentes: atalho `httpx(app=...)` e `datetime.utcnow()`.

## 24. Testes frontend

- Testes específicos: **29 aprovados**.
- Lote integrado página + regras: **81 aprovados**.
- Primeira suíte integral: 334 aprovados e um timeout flutuante em teste antigo de dispersão; não aceita como gate.
- Reexecução integral conclusiva: **335 aprovados, 15 arquivos, 0 falhos, 0 ignorados, 53,86 s, saída 0**.
- Warnings React `act(...)` preexistentes permanecem.

## 25. Build

`npm run build` final: **aprovado**, 958 módulos, 30,53 s de build Vite, saída 0. JS 986,58 kB, gzip 314,51 kB. Warnings não bloqueantes: importação estática/dinâmica da API e chunk acima de 500 kB. Após o ajuste final de marcadores, os 29 testes específicos foram repetidos e aprovados.

## 26. Validações funcionais

Validação funcional automatizada com dados determinísticos:

| Cenário | Série/identidade | Resultado |
|---|---|---|
| Desativado | `A-7` | opção serializável idêntica ao baseline |
| Limites | `B-7`, eixo 1 | zero/negativo/decimal aceitos; inválidos rejeitados |
| Faixas | `B-7`, eixo 1 | válida desenhada; inversão e sobreposição rejeitadas |
| Regras | `A-7` | sete operadores e fronteiras validados |
| Prioridade | `A-7` | primeira regra prevalece; reorder altera resultado |
| Tipos | `A-7` | string `"600"`, boolean, null e não finitos ignorados |
| Comparação | `A-7` / `B-7` | mesma tag com configurações independentes |
| Eixo | `tag:1` | troca principal/secundário sem consulta |
| Troca de gráfico | `tag:1` | estado retido, sem consulta |
| Textual | `T-1` | indisponibilidade discreta, sem erro |
| Tooltip | `A-7` | valor preservado; regra e faixa adicionadas |
| Métrica/CSV | `A-7` | resultados e dados idênticos |
| Reset | `tag:1` | configuração removida; resultado consultado preservado |

Não foi realizada inspeção manual com navegador real ou captura de tela; os componentes ECharts foram verificados pela opção produzida e pela integração React automatizada.

## 27. Limitações

- A biblioteca não colore segmentos individuais sem dividir ou fabricar dados. A linha original é preservada e a cor condicional é aplicada aos marcadores, que ficam visíveis quando há regra ativa.
- Linhas de limite e faixas são apresentadas no gráfico temporal numérico. Ao trocar para histogramas, boxplot, dispersão, barras ou valor único, a configuração é preservada e reaparece ao retornar ao gráfico temporal, mas esses overlays não são desenhados nesses tipos.
- A arquitetura atual não possui mínimo/máximo manual de eixo; portanto não houve integração adicional para esse caso. O `markLine`/`markArea` participa da extensão automática do ECharts.

## 28. Pendências

Nenhuma pendência obrigatória identificada para o escopo implementado. Inspeção visual manual em navegador pode ser adicionada como evidência complementar.

## 29. Riscos conhecidos

Exibir marcadores em séries muito volumosas com regras ativas pode aumentar custo de renderização. A configuração continua puramente visual e não aumenta chamadas ao PI.

## 30. Recomendação para a Fase 5.7

Persistir somente após definir schema versionado e ownership das configurações. Não usar o estado local atual como contrato de persistência sem migração explícita.

## 31. Status final

Todos os critérios obrigatórios executados terminaram com sucesso: **APROVADA**. A Fase 5.7 não foi iniciada.
