# Diagnóstico e runbook da migração TimescaleDB

## Diagnóstico inicial

- Branch observada: `feature/pg18-coverage-roundrobin-backfill`.
- Commit observado: `df85ced` (`feat(visualizacao): ativa modelo Base Ciclica e refina regras de analise`).
- O worktree já continha alterações locais, inclusive a migration `e03e14f8ffdd_postgres_storage.py`, workers e ajustes do frontend; elas foram preservadas e somente os arquivos diretamente relacionados ao armazenamento temporal foram corrigidos.
- Não havia Compose/Dockerfile no repositório. O Compose novo está em `compose.timescale.yml`.
- `backend/.env` aponta para `postgresql+psycopg://pi_app:***@127.0.0.1:5432/pi_analytics`; a senha não é registrada.
- O cliente local é PostgreSQL `18.6`; a instância configurada em `127.0.0.1:5432` não respondeu durante o diagnóstico, portanto contagens, `MIN/MAX`, partições, jobs e `alembic_version` não puderam ser consultados sem inventar dados.
- A estrutura do código identificava `pi_samples` como tabela particionada nativa; cobertura em `pi_ingestion_coverage`; estado em `pi_ingestion_state`; jobs em `pi_backfill_jobs` e `pi_tag_deletion_jobs`.
- O endpoint tinha o critério incorreto `any(s.points for s in db_result.series)`, usava `date_bin`/média para o modo interpolated e engolia falhas do PI com `except` silencioso.
- A implementação de `recorded` e `interpolated` do PI já era distinta no provider; a nova camada mantém `RECORDED` e `INTERPOLATED_<interval>S` como modos de armazenamento distintos.
- Testes relevantes existentes: contrato de time-series, provider PI, planner de consultas, long-range, comparação, migrações e testes Vitest de `QuerySummary`.

## Resultado implementado

1. `pi_samples_timescale` é criada como hypertable de `ts`, com chunk inicial de um dia, chave `(tag_id, ts)` e todos os tipos/flags PI.
2. A migration `20260910_timescaledb_native` nunca renomeia, apaga ou sobrescreve `pi_samples`; copia dados com UPSERT e normalização explícita de modo.
3. O Compose fixa a imagem oficial `timescale/timescaledb-ha:pg18.4-ts2.27.1` no digest `sha256:7c253207091a191a9aea5d1dee8816512f3aca22d169905e0bc08795ffac9752`.
4. TimescaleDB `>= 2.18` usa exclusivamente Hypercore/columnstore, segmentado por `tag_id`, ordenado por `ts DESC`, com política de sete dias. A branch de compatibilidade para versões antigas usa somente a API tradicional.
5. Cobertura usa intervalos `[start, end)`, filtra modo e resolução, consolida intervalos adjacentes e só é gravada quando a resposta PI é completa.
6. Ingestão e backfill usam UPSERT idempotente, watermark por tag, advisory lock de líder, round-robin por rodada, T0 fixo, overlap de 30 segundos e retry transitório com jitter/`Retry-After`.
7. A consulta lê somente trechos cobertos do TimescaleDB, busca apenas lacunas no PI, mescla timestamps estavelmente e retorna `source` como `timescaledb`, `pi_web_api` ou `hybrid`.
8. Exclusão é assíncrona e a tabela legada continua fora do fluxo de deleção.

## Validação controlada

Em staging, configure `DATABASE_URL` para a nova instância e execute, nesta ordem:

```sql
SELECT version();
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';
SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'pi_samples_timescale';
SELECT show_chunks('pi_samples_timescale');
```

Depois valide o dump com `sha256sum -c`, restaure cadastros/dados, execute `alembic upgrade head`, gere a reconciliação por tag e só então faça a troca de configuração. O banco/volume vanilla deve permanecer intacto até o período de rollback terminar.
