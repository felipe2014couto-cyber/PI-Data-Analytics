# Relatório da Fase 5.1 — Mecanismo avançado de datas

Data: 17/07/2026

## Escopo

Implementação restrita ao frontend do mecanismo temporal com três modalidades:
período predefinido, absoluto e relativo. Backend, banco de dados, migrations,
endpoints, dependências e visualizações não foram alterados. Base cíclica não
foi criada, nem mesmo como opção vazia.

O `git status --short` foi solicitado antes das alterações, mas `.git` continua
aparecendo como diretório vazio no sandbox e o comando informou que o projeto
não é um repositório Git. Nenhuma alteração existente foi descartada.

## Arquivos criados e alterados

Criados:

- `frontend/src/utils/timePeriod.ts`;
- `frontend/tests/timePeriod.test.ts`;
- `RELATORIO_FASE_5_1_DATAS_AVANCADAS.md`.

Alterados:

- `frontend/src/types/index.ts`;
- `frontend/src/components/DataFiltersPanel.tsx`;
- `frontend/src/pages/DataVisualizationPage.tsx`;
- `frontend/tests/dataVisualization.test.tsx`;
- `README.md`.

## Contrato temporal

Foi introduzida uma união discriminada `TimePeriod`:

```typescript
type TimePeriod =
  | { kind: "preset"; preset: "PT15M" | "PT1H" | "PT8H" | "P1D" | "P7D" }
  | { kind: "absolute"; start: string; end: string; timezone: "America/Sao_Paulo" }
  | {
      kind: "relative";
      amount: number;
      unit: "minute" | "hour" | "day" | "week";
      reference: "now" | "startOfDay" | "endOfDay";
      timezone: "America/Sao_Paulo";
    };
```

O padrão real permanece `PT1H`. O resolvedor puro transforma qualquer variante
em `startTime` e `endTime` ISO UTC, além de registrar o fuso e o instante de
referência capturado.

## Semântica e fuso horário

O fuso oficial é `America/Sao_Paulo`, independente do fuso configurado no
navegador. Campos `datetime-local` são lidos como data civil desse fuso e
convertidos por `Intl.DateTimeFormat`, com validação de ida e volta. Datas
impossíveis, inclusive horários inexistentes em transições históricas de verão,
são recusadas.

Minutos e horas relativos representam duração exata. Dias e semanas subtraem
dias do calendário local; por isso, uma janela de um dia que atravessa uma
mudança de horário de verão pode ter 23 ou 25 horas reais. As referências são
“Agora”, “Início do dia” e “Fim do dia” no fuso oficial.

## Captura única e integração com a consulta

Ao clicar em **Consultar**, a página cria uma única instância de `Date` e a
entrega ao resolvedor. Os dois limites derivam desse mesmo instante. A API
continua recebendo exatamente `start_time` e `end_time` pelo contrato atual de
`GET /api/time-series`.

O período resolvido é armazenado no estado da consulta. Gráficos e cards usam
esse intervalo imutável, não uma nova avaliação do formulário. Editar período,
modo, tags ou visualização não chama a API e não apaga o último resultado; uma
nova resolução só ocorre em nova consulta.

## Interface e validação

O painel apresenta somente Predefinido, Absoluto e Relativo, com campos
condicionais e o fuso visível. Há resumo do intervalo, labels associados,
`aria-invalid`, mensagem inline com `role="alert"` e bloqueio do botão enquanto
o período é inválido.

São validados campos vazios, formato/data civil, quantidade relativa inteira e
maior ou igual a um, e limite final estritamente posterior ao inicial.

## Testes adicionados

O arquivo `timePeriod.test.ts` contém 31 testes para:

- os cinco presets e suas durações exatas;
- captura/referência e fuso do contrato;
- conversão absoluta para UTC e entrada com segundos;
- campos vazios, datas inválidas, limites iguais ou invertidos;
- horário civil inexistente na transição de verão de São Paulo;
- quantidades relativas inválidas;
- minutos, horas, início do dia e fim do dia;
- dia civil atravessando DST com duração real de 23 horas;
- semana como sete dias civis;
- formatação, imutabilidade e relógio inválido.

Os testes de integração cobrem o padrão de uma hora, as três opções visíveis,
ausência de Base cíclica, fuso apresentado, envio absoluto correto em UTC,
validação acessível e preservação do resultado sem nova chamada durante edição.

## Resultados dos comandos

Baseline anterior às alterações:

```text
npm test -- --run
Test Files  8 passed (8)
Tests       144 passed (144)
Duration    21.44s
```

```text
npm run build
947 modules transformed
dist/assets/index-CvXR8cOA.js  907.64 kB | gzip: 293.86 kB
built in 20.98s
```

Resultado final dos testes:

```text
npm test -- --run
Test Files  9 passed (9)
Tests       179 passed (179)
Duration    23.26s
```

A suíte mantém os avisos preexistentes de atualizações React fora de
`act(...)`, sem falhas.

Resultado final do build:

```text
npm run build
947 modules transformed
dist/assets/index-CSeyfrd4.js  912.39 kB | gzip: 295.22 kB
built in 22.25s
```

O build terminou com código zero. Permanecem os avisos conhecidos do Vite
sobre importação dinâmica/estática do mesmo módulo e chunk acima de 500 kB.

## Compatibilidade e pendências

- O endpoint e os parâmetros enviados ao backend permanecem inalterados.
- Recorded/interpolated, qualidade, CSV, cards e as oito visualizações foram
  preservados.
- Não houve consulta ao PI real.
- Base cíclica permanece pendente até existir regra formal de domínio.
- Continua recomendada uma validação manual do fuso em máquinas configuradas
  com outros timezones e dos três modos com dados reais, sem alterar credenciais.
