# Base Unidade: implementação e validação

A página mostra somente o gráfico. A UM selecionada aparece em uma faixa categórica acima das curvas, com cada faixa ocupando `[start,end)`. Em janelas largas, códigos podem ser abreviados para caber; tooltip e marcador mantêm a identificação completa. A faixa usa o mesmo eixo temporal e zoom. A UM continua no tooltip/marcador quando a faixa está oculta.

Média usa `average`, Mínimo usa `minimum`, Máximo usa `maximum`. As curvas permanecem constantes por UM. Null mantém lacuna, zero e negativos são preservados. STRING/DIGITAL não recebem agregados numéricos artificiais. O componente da tabela continua disponível como código independente, mas saiu da página.

## Persistência e contrato

Migration `20261004_production_units`: três tabelas derivadas. A migration foi aplicada no banco local. RECORDED, ingestão, backfill existente, CEP, CSV, PI Web API, filtros e Base Cíclica não foram alterados.

- `production_unit_segments`: ocorrência canônica `(um_tag_id,start_ts)`; equipamento, código/status, início/fim, motivo e timestamp de estado. Uma mesma UM pode reaparecer. `end_ts=NULL` significa ocorrência aberta. Um `QUERY_END` recortado nunca reabre uma ocorrência já fechada.
- `production_unit_tag_stats`: chave `(segment_id,tag_id)`; contagens base, AVG/MIN/MAX, primeiro/último e assinatura da fonte. Somente ocorrências completas recebem estatísticas. STRING/DIGITAL preservam primeiro/último do endpoint original.
- `production_unit_materializations`: equipamento, seção nullable, UM resolvida, janela registrada, metadados dos segmentos e versões da fonte. Bordas de consulta ficam como metadados, sem estatísticas parciais persistidas. Contagens das oito combinações fixas de qualidade permitem preservar o filtro de qualidade sem recalcular AVG/MIN/MAX. Nenhuma combinação de filtros dinâmicos é persistida.

O endpoint resolve a configuração atual da UM antes de acessar derivados. Uma materialização de outra seção ou outra tag UM não é reutilizada. A assinatura da cobertura RECORDED comprometida com a ingestão/backfill invalida dados alterados, inclusive reconciliação e histórico. Mudanças do tipo de dado também invalidam estatísticas. Escritas manuais em RECORDED fora do contrato de cobertura não são suportadas pelo mecanismo de invalidação.

Sem filtros de valor: usa estatísticas persistidas nos segmentos completos, calculando bordas recortadas e ocorrência aberta em runtime. Com filtros: reutiliza fronteiras válidas e mantém o SQL original de filtros. Janelas ainda não registradas, ou com derivados inválidos, usam o caminho RECORDED original. A resposta informa `strategy`, `precomputed_segments`, `runtime_segments` e `runtime_raw_sample_count` (amostras brutas das variáveis efetivamente processadas em runtime; não inclui eventos de contexto/UM ou leituras de índices).

## Atualização administrativa

Comandos executados a partir de `backend`, usando o ambiente virtual:

```bash
.venv/bin/alembic upgrade 20261004_production_units
.venv/bin/python -m app.commands.production_units rebuild --equipment 2 --tags 20 23 --start 2026-10-01T21:32:12Z --end 2026-10-02T21:32:12Z
.venv/bin/python -m app.commands.production_units refresh --materialization 1
.venv/bin/python -m app.commands.production_units refresh --materialization 1 --watch --interval 10
```

`--section` seleciona um escopo específico. O comando valida períodos até 31 dias e usa transação REPEATABLE READ e lock por equipamento. Watch segue somente períodos explicitamente registrados, em transações independentes da ingestão; nenhum novo processo permanente foi instalado nesta tarefa. Para novas janelas é necessário registrá-las explicitamente. Não foi executado backfill histórico completo.

Refresh identifica tags e trechos afetados por novas coberturas e recalcula ocorrências sobrepostas, preservando o restante. Eventos UM novos fecham a ocorrência anterior e abrem outra dentro da janela registrada. Alterações de sementes anteriores à janela e coberturas mescladas exigem fallback conservador para rebuild da janela registrada, limitado a 31 dias. Configurações UM obsoletas são sinalizadas, exigindo novo rebuild do escopo.

Os índices são a unicidade `(um_tag_id,start_ts)`, a chave `(segment_id,tag_id)` e a busca `(equipment_id,um_tag_id,start_ts,end_ts)`. Não foram adicionados índices ao RECORDED. `explain.json` registra planos reais: lookup de materialização 0,037 ms e estatísticas 0,038 ms. Com apenas 28 ocorrências/54 estatísticas, o planner escolheu scan/hash join; os índices mantêm identidade e buscas quando o volume cresce.

## Medições reais

RB1, equipamento 2, tag UM 29 (`LFI_RB1_CODIGO_UM_FORNO_ENT`, equipamento inteiro). Janela local: 01/10/2026 18:32:12–02/10/2026 18:32:12; UTC: 01/10 21:32:12–02/10 21:32:12.

| Consulta | Antes, mediana | Depois, mediana | Resultado |
|---|---:|---:|---|
| Velocidade (20) + Zona 03 (23), qualidade padrão | 340,932 ms | 82,753 ms | Iguais; 27 segmentos precomputed + 2 bordas runtime |
| FORNO, velocidade (20), filtro 25–32 | 347,971 ms | 293,470 ms | Iguais; filtros runtime e fronteiras persistidas |

A consulta principal contém 29 segmentos, 143.283 amostras das duas variáveis; após materialização apenas 4.072 amostras dessas variáveis foram processadas em runtime. Redução de tempo: 75,7%, aproximadamente 4,1 vezes mais rápida. Antes: 8 queries na primeira execução/7 nas seguintes; depois: 10, incluindo validação de cobertura e leitura dos derivados. As medições são do serviço e SQL locais, sem tempo HTTP/renderização e após materialização explícita da janela.

A medição inicial, antes da implementação, registrou 436/329/327 ms. `EXPLAIN ANALYZE` inicial: agregação 419,760 ms e 31.559 blocos em cache. O custo principal era agregar novamente as amostras RECORDED. Derivados inválidos continuam usando runtime até refresh; as medições de precomputed não representam uma janela fria ou obsoleta.

Contagens, fronteiras e valores categóricos foram comparados exatamente; estatísticas em ponto flutuante usaram tolerância absoluta/relativa `1e-12`. Exemplos reais:

- `600515A3000B`: velocidade AVG 37,79763124134014; Zona 03 AVG 992,6495747083336.
- `600436J8000B`: velocidade AVG 37,86541451119658; Zona 03 AVG 1001,3598400674163.

A tentativa de filtro de velocidade compartilhado pelas duas variáveis, na janela completa, falhou também no caminho original: PostgreSQL não conseguiu alocar segmento de memória compartilhada de 110 MB. O filtro gera aproximadamente 25 MB de intervalos de contexto. A validação real filtrada acima foi realizada com velocidade somente; a consulta filtrada com as duas variáveis não foi validada integralmente. Nenhuma alteração de configuração global ou lógica de filtro foi feita para contornar esse limite.

## Artefatos

- `benchmark.json` e `filtered-benchmark.json`: execuções individuais, estratégias, contagens e todos os resultados reais.
- `media.svg`, `min.svg`, `maximo.svg`: renderização real no motor ECharts com 29 faixas.
- `zoom.svg`: duas UMs com códigos completos.
- `echarts-data.json`: opções/arrays reais enviados ao ECharts para Média/Mínimo/Máximo; funções não são serializadas.
- `frontend-tests.log`, `backend-tests.log`, `build.log`: verificações finais.

A renderização foi validada via SVG/SSR do ECharts e testes de interação do frontend. Não foi realizada sessão manual autenticada no navegador.

## Arquivos desta entrega

Frontend: `DataVisualizationPage.tsx`, `TimeSeriesChart.tsx`, `EChartsWrapper.tsx`, `QuerySummary.tsx`, `api/index.ts`, `utils/productionUnitChart.ts`, `tests/productionUnitVisualization.test.tsx` e `tests/productionUnitRendering.test.ts`.

Backend: `models/__init__.py`, `models/production_unit.py`, `schemas/production_unit.py`, `services/production_unit_service.py`, `services/production_unit_store.py`, `commands/production_units.py`, `commands/production_unit_benchmark.py`, migration `20261004_production_units.py`, `tests/test_production_unit_store.py` e `tests/test_production_unit_migration.py`.

Validação: frontend focado 58 testes (incluindo requiredAnalysisTags: 13); backend focado 35. Frontend completo: 662 testes/43 arquivos. Backend completo: 844 passaram, 8 skips. Build passou; avisos existentes de tamanho de bundle/import dinâmico. `git diff --check` passou. Sem commit ou push.
