# Relatório da Fase 5.2 — Modelos, Máquina e eixos

Data: 17/07/2026

## 1. Escopo

Implementação exclusivamente no frontend da representação de Modelo, do
mapeamento Equipment → Máquina, das atribuições manuais de séries, dos eixos Y
principal/secundário, dos papéis X/Y da dispersão e da ordem visual.

Backend, banco, migrations, endpoints, dependências, consulta PI, CSV, filtros,
datas avançadas e os oito tipos de visualização foram preservados. Não houve
consulta autenticada ao PI real. O sandbox continuou apresentando `.git` vazio;
nenhuma alteração existente foi descartada.

## 2. Decisões de domínio

Modelo é o tipo de base analítica. Foram aprovados Base Unidade, Base Cíclica,
Base OEE, Base Paradas e Base Qualidade. A consulta direta atual às tags PI
pertence à Base Unidade. Os demais modelos não possuem contrato funcional nesta
etapa e aparecem desabilitados com a indicação acessível de disponibilidade
futura; eles não podem acionar a consulta comum.

Equipment representa Máquina. Não foi criada entidade, tabela, migration ou
endpoint Machine. IDs, catálogo, cascata e contratos continuam sendo os de
Equipment; somente o texto da interface de análise foi alterado.

## 3. Modelos analíticos aprovados

| Valor tipado | Texto | Situação |
| --- | --- | --- |
| `unit` | Base Unidade | funcional e padrão |
| `cyclic` | Base Cíclica | desabilitada |
| `oee` | Base OEE | desabilitada |
| `downtime` | Base Paradas | desabilitada |
| `quality` | Base Qualidade | desabilitada |

Somente Base Unidade está habilitada porque é a única com contrato aprovado e
compatível com `GET /api/time-series`. Não foi criado fallback que execute Base
Unidade sob o nome de outro modelo.

## 4. Arquivos criados e alterados

Criados:

- `frontend/src/utils/seriesAssignments.ts`;
- `frontend/src/components/SeriesAssignmentsPanel.tsx`;
- `frontend/tests/seriesAssignments.test.ts`;
- `RELATORIO_FASE_5_2_MODELOS_E_EIXOS.md`.

Alterados:

- `frontend/src/types/index.ts`;
- `frontend/src/utils/chartData.ts`;
- `frontend/src/components/DataFiltersPanel.tsx`;
- `frontend/src/pages/DataVisualizationPage.tsx`;
- `frontend/tests/visualization.test.ts`;
- `frontend/tests/dataVisualization.test.tsx`;
- `README.md`.

## 5. Contratos TypeScript

```typescript
type AnalysisModel = "unit" | "cyclic" | "oee" | "downtime" | "quality";
type SeriesAxis = "primary" | "secondary";
type ScatterRole = "none" | "x" | "y";

interface SeriesAssignment {
  tagId: number;
  order: number;
  lineAxis: SeriesAxis;
  scatterRole: ScatterRole;
}
```

As atribuições são estado de apresentação separado dos pontos do PI. A
identidade é exclusivamente `tagId`; nomes, posições do array e unidades não
servem como chave. `query.timeSeries` não é modificado.

## 6. Reconciliação das séries

`seriesAssignments.ts` centraliza criação, reconciliação, ordenação, mudança de
eixo, X/Y, validação e resolução visual. Uma tag nova recebe ordem e eixo
determinísticos; tags existentes preservam alterações manuais; uma removida é
excluída sem afetar as demais. A configuração não mantém órfãos e nomes
duplicados não interferem.

Atualizações do catálogo e respostas em outra ordem não sobrescrevem papéis. A
remoção de X ou Y limpa somente aquele papel. Uma referência interna registra
se a sugestão inicial de dispersão já ocorreu, impedindo substituição silenciosa
posterior.

## 7. Eixos principal e secundário

- principal à esquerda e secundário à direita;
- várias tags por eixo;
- mesma unidade obrigatória dentro de cada eixo;
- unidades distintas permitidas entre os dois eixos;
- ausência de unidade só é compatível com ausência de unidade;
- nenhuma conversão é feita;
- incompatibilidade é exibida junto aos controles e bloqueia linha/automática;
- incompatibilidade visual não incrementa “Descartados”.

A configuração inicial mantém a primeira unidade no principal, a segunda no
secundário e unidades iguais juntas. Mudanças manuais sobrevivem a troca de
visualização, resposta reordenada, nova consulta e filtro de qualidade.

## 8. Dispersão manual

O modo Dispersão mostra seletores associados para Eixo X e Eixo Y. Ambos exigem
tags numéricas distintas. Strings, booleanos, vazios e séries mistas não entram
nas opções válidas após a classificação real.

Na primeira resposta compatível, se o usuário nunca configurou os papéis, as
duas primeiras seleções numéricas são sugeridas como X/Y. Depois disso os papéis
são explícitos. Alterá-los recalcula somente pareamento e correlação locais, sem
API. A implementação existente de coincidência exata de timestamps e Pearson
foi mantida.

## 9. Ordenação

Cada série possui botões acessíveis “Mover … para cima/baixo”, com limites
desabilitados. A ordem controla legenda/linha, Estados, histogramas, ordem das
caixas dentro do grupo, barras, Valor único e a sugestão inicial da dispersão.

Não são alterados IDs enviados, timestamps, valores, qualidade, contadores ou o
CSV original. Não foi adicionada dependência de drag-and-drop.

## 10. Compatibilidade dos oito gráficos

- Automática: usa eixos atribuídos na linha e mantém Estados separado.
- Linha temporal: usa explicitamente principal/secundário.
- Estados: mantém uma série textual e `step: "end"`.
- Histograma: um gráfico por série, na ordem configurada.
- Boxplot: agrupamento por unidade preservado e ordem interna configurada.
- Dispersão: X/Y manuais.
- Barras: último número válido e ordem configurada dentro dos grupos.
- Valor único: números, strings e booleanos preservados e ordenados.

## 11. Consulta, cards, contadores e CSV

Modelo, eixo, X/Y e ordem são estado local e não chamam a API. A consulta
continua usando IDs atuais, período UTC da Fase 5.1, recorded/interpolated,
intervalo e maxCount. Cards e contadores continuam derivados da resposta
completa. O CSV continua recebendo diretamente `query.timeSeries`, não a
projeção ordenada ou visível.

## 12. Testes adicionados

`seriesAssignments.test.ts` possui 29 testes cobrindo criação, IDs, inclusão,
remoção, preservação, nomes duplicados, resposta reordenada, movimentos e
limites, eixos, compatibilidade de unidade, ausência de unidade, X/Y, remoção
sem substituição, não numéricos e imutabilidade.

Os testes de integração cobrem os cinco modelos, indisponibilidade explícita,
Máquina, ausência de Métrica, eixos manuais e validação, dispersão com resposta
invertida, remoção de papel, ordem sem API e preservação de cards, contadores e
CSV. Os testes de visualização verificam aplicação imutável de ordem/eixos.

## 13. Baseline

```text
npm test -- --run
Test Files  9 passed (9)
Tests       179 passed (179)
Duration    25.45s
```

```text
npm run build
947 modules transformed
dist/assets/index-CSeyfrd4.js  912.39 kB | gzip: 295.22 kB
built in 27.01s
```

## 14. Resultado final

```text
npm test -- --run
Test Files  10 passed (10)
Tests       214 passed (214)
Duration    54.29s
```

```text
npm run build
949 modules transformed
dist/assets/index-DRFK5yRp.js  921.04 kB | gzip: 297.74 kB
built in 26.73s
```

Ambos os comandos terminaram com código zero.

## 15. Warnings

No baseline permaneceram warnings conhecidos de atualizações React fora de
`act(...)`, importação dinâmica/estática do módulo de API e chunk acima de
500 kB. Nenhum foi ocultado por configuração.

## 16. Catálogo de métricas aprovado

Catálogo futuro: CP, CPK, CPK Erro, Contagem, Desvio Padrão, Desvio Padrão Erro,
Erro Absoluto Médio, Erro Quadrático Médio, Máximo, Máximo Erro, Média, Média
Erro, Mínimo, Mínimo Erro, OOC, OOC MAE Máximo, OOC MAE Média, PC, Raiz Erro
Quadrático Médio e Total.

Nenhuma métrica, seletor, cálculo, resultado ou contrato parcial foi
implementado nesta fase.

Dependências registradas:

- CP, CPK e OOC precisam da futura definição de limites;
- métricas com “Erro” precisam de série real e série de referência explícitas;
- o significado exato de PC ainda precisa ser confirmado.

## 17. Pendências

- definir contratos funcionais de Base Cíclica, OEE, Paradas e Qualidade;
- confirmar PC;
- implementar métricas somente na Fase 5.3, depois das dependências semânticas;
- validar manualmente eixos e dispersão com tags PI reais, sem alterar cadastro;
- avaliar divisão do chunk em otimização independente.

## 18. Roteiro de validação manual

1. Confirmar Base Unidade selecionada e quatro modelos futuros desabilitados.
2. Selecionar Máquina, Seção e tags pelos cadastros existentes.
3. Confirmar primeira unidade no principal e segunda no secundário.
4. Colocar unidades incompatíveis no mesmo eixo e conferir validação sem API.
5. Separá-las e consultar; validar eixo esquerdo/direito, legenda e tooltip.
6. Reordenar séries e conferir os oito modos sem nova consulta.
7. Em Dispersão, trocar X/Y e conferir resumo, pares e correlação.
8. Remover X ou Y e confirmar ausência de substituição automática.
9. Conferir cards, “Descartados”, período resolvido e CSV intactos.
10. Confirmar que não existe seletor ou resultado de Métrica.
