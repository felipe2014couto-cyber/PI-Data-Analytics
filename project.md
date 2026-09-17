# PI Analytics Data

Sistema de analytics industrial que centraliza cadastros de ativos e séries
temporais do PI System em PostgreSQL/TimescaleDB. O frontend permite explorar
dados históricos, configurar filtros e visualizar tendências sem consultar o
PI Web API diretamente durante a navegação normal.

## Arquitetura

```text
PI System / PI Web API
        |
        v
Workers de ingestão e recarga histórica
        |
        v
PostgreSQL + TimescaleDB
  - cadastros
  - pi_samples_timescale (hypertable de amostras)
  - continuous aggregates para plotagem
        |
        v
FastAPI (/api)
        |
        v
React + Vite + ECharts
```

O PI Web API é a fonte industrial original. A aplicação persiste as amostras
no TimescaleDB de forma idempotente e usa esse banco para as consultas de
visualização. O backend não deve criar valores artificiais nem sobrescrever o
dado bruto durante a exibição.

## Componentes principais

| Camada | Tecnologia | Responsabilidade |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Pydantic | API, autenticação, regras de negócio e consultas históricas |
| Banco | PostgreSQL 18 + TimescaleDB | Cadastros, cobertura, amostras e aggregates de plotagem |
| Integração | HTTPX + PI Web API | Resolução, validação e coleta de tags PI |
| Workers | Python | Ingestão contínua, backfill, capacidade e exclusão assíncrona |
| Frontend | React 18, TypeScript, Vite, Bootstrap, ECharts | Filtros, gráficos, zoom, exportações e administração |

## Dados históricos

As amostras ficam em `pi_samples_timescale`, com chave temporal por tag. Para
reduzir o volume enviado ao gráfico, consultas recorded podem usar continuous
aggregates de plotagem, preservando primeiro, mínimo, máximo, último, média,
contagem e timestamps de borda quando disponíveis.

Aggregates usados pela seleção de resolução:

| Janela consultada | Fonte preferencial |
| --- | --- |
| Até 6 horas | `pi_recorded_plot_10s` |
| Até 2 dias | `pi_recorded_plot_1m` |
| Até 14 dias | `pi_recorded_plot_5m` |
| Até 31 dias | `pi_recorded_plot_hourly` |
| Acima de 31 dias | `pi_recorded_plot_daily` |

O planejador também aceita `target_points_per_tag` para escolher uma resolução
proporcional ao tamanho do gráfico. Quando existem poucas amostras qualificadas
e coverage completo, a consulta pode usar o dado recorded bruto; caso
contrário, escolhe um aggregate e aplica re-bucketing ponderado. A média usa
`sum(avg_value * sample_count) / sum(sample_count)`.

O backend mantém cache curto em memória para consultas TimescaleDB idênticas.
O cache não substitui a verificação de coverage e não grava nenhum dado novo.

## Fluxo de visualização e zoom

1. O usuário seleciona máquina, seção, tipo de variável e tags válidas.
2. O frontend envia `GET /api/time-series` com intervalo UTC, modo e IDs de
   tag repetidos (`tag_ids=20&tag_ids=23`).
3. O backend verifica a cobertura no TimescaleDB e consulta uma única fonte de
   dados adequada à resolução.
4. O gráfico ECharts exibe a resposta e preserva a consulta original em memória.
5. O zoom por arraste é visual e imediato; ao soltar o mouse, uma consulta de
   refinamento é feita apenas para o intervalo selecionado quando o conjunto
   atual não tem detalhe suficiente. Respostas antigas são ignoradas.
6. Restaurar zoom retorna ao resultado inicial em memória quando possível.

Lacunas reais não devem ser conectadas como medições intermediárias. Um zoom
mais profundo só deve ser aceito quando houver amostras/cobertura suficientes
na resolução solicitada.

## Estrutura relevante

```text
backend/
  app/api/                         # Rotas FastAPI
  app/services/database_time_series_service.py
                                    # Planejamento e leitura TimescaleDB
  app/workers/                      # ingestão, backfill, capacidade e exclusão
  app/models/                       # ORM
  alembic/versions/                 # migrations
  scripts/run_workers.py            # inicializador de workers
frontend/
  src/pages/DataVisualizationPage.tsx
  src/components/TimeSeriesChart.tsx
  src/components/EChartsWrapper.tsx
  src/api/                          # cliente HTTP
```

## Execução local/staging

Os arquivos de ambiente não devem ser versionados nem compartilhados, pois
contêm a URL do banco, segredos de autenticação e credenciais do PI.

### Migrations

```bash
cd backend
.venv/bin/python -m dotenv -f .env.staging run -- bash -c '
export APP_ENV=staging
exec .venv/bin/alembic upgrade head
'
```

### Backend

```bash
cd backend
.venv/bin/python -m dotenv -f .env.staging run -- bash -c '
export APP_ENV=staging
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
'
```

### Frontend

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

Na rede interna, o frontend deve apontar `VITE_API_BASE_URL` para a API
acessível na rede, por exemplo `http://SERVIDOR:8000/api`. A origem do
frontend precisa constar em `FRONTEND_ORIGIN` no ambiente do backend.

### Workers

```bash
cd backend
.venv/bin/python -m dotenv -f .env.staging run -- bash -c '
export APP_ENV=staging
exec .venv/bin/python -m scripts.run_workers --worker ingestion
'
```

Outras opções incluem `--worker backfill`, `--worker capacity` e `--worker
all`. Em staging/produção, prefira os serviços systemd já configurados em vez
de iniciar workers duplicados manualmente.

## Migrations e compatibilidade

O código ORM e o schema precisam estar na mesma revisão Alembic. Antes de
subir uma versão do backend, valide:

```bash
cd backend
.venv/bin/alembic current
.venv/bin/alembic heads
```

Se uma coluna referenciada pelo erro do backend não existir — por exemplo
`sections.process_type` — a correção é aplicar as migrations pendentes, e não
reiniciar repetidamente o servidor.

## Testes e build

```bash
# Backend
cd backend && .venv/bin/python -m pytest

# Frontend
cd frontend && npm test -- --run
npm run build
```

## Operação segura

- Não exponha `DATABASE_URL`, senhas do PI, cookies ou JWTs em commits, logs
  ou documentação.
- Antes de migrations ou reinícios, confira `git status`, a revisão Alembic e
  os serviços ativos.
- Não execute dois workers do mesmo tipo para a mesma base sem confirmar os
  locks e a configuração de concorrência.
- Para investigar uma consulta lenta, separe tempo de SQL, serialização,
  transferência HTTP e renderização; a duração exibida na interface não é
  necessariamente tempo de banco.
