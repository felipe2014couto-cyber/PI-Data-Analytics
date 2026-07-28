# RELATORIO — AJUSTE INTERMEDIARIO: PI Server Automatico nas Tags

## 1. Causa

O sistema possui um unico PI Data Archive (`PIMS`). O usuario precisava digitar manualmente o nome do servidor ao cadastrar cada nova tag PI, o que era redundante e propenso a erro (digitacao incorreta, servidor inexistente, validacao extra desnecessaria).

## 2. Comportamento anterior (Apos Ajuste Intermediario Original)

- Formulario "Nova tag PI" exibia um campo de texto editavel "PI Server".
- O usuario precisava digitar `PIMS` (ou outro valor) manualmente.
- O campo era `required` e tinha `maxLength={128}`.
- O estado inicial do formulario (`EMPTY_FORM`) deixava `pi_server` como string vazia (`""`).
- O payload de criacao usava `form.pi_server.trim()`.
- O payload de edicao usava `form.pi_server.trim()`.
- Nao havia validacao explicita de "PI Server obrigatorio" no `handleSubmit`, mas o campo `required` do HTML gerava bloqueio visual no navegador.

### Apos o Ajuste Visual

- O formulario exibia um bloco estatico com label "PI Server", o valor `PIMS` e o texto "Definido automaticamente." em formato somente leitura.
- O bloco ocupava metade da largura da linha (col-md-6), ao lado de "Nome da tag no PI".

## 3. Comportamento novo (Apos Ajuste Intermediario Original)

- O formulario "Nova tag PI" exibia um texto estatico com label "PI Server", o valor `PIMS` e "Definido automaticamente." em formato somente leitura.
- Ao abrir o modal de criacao, `PIMS` ja estava definido.
- Ao cancelar e reabrir, `PIMS` continuava definido.
- Apos salvar e limpar o formulario, `PIMS` continuava definido.
- Nao havia validacao manual de PI Server.
- O payload de criacao enviava `pi_server: "PIMS"` diretamente da constante.
- Na edicao:
  - O valor do servidor era exibido como texto estatico (nao editavel).
  - O valor ja cadastrado no registro era preservado.
  - Se o registro viesse com PI Server vazio ou ausente, utilizava `PIMS` como fallback.
- Nao modificava registros legados que possuissem outro valor de servidor.

### Apos o Ajuste Visual (Remocao Total)

- **Nenhuma** informacao de PI Server aparece no formulario (nem label, nem valor, nem texto auxiliar).
- O layout foi reorganizado: "Nome da tag no PI" agora ocupa a linha inteira (col-md-12).
- A automatizacao permanece no codigo: `DEFAULT_PI_SERVER` e usado no payload de criacao e como fallback na edicao.
- O usuario nao ve, nao digita e nao interage com PI Server em nenhum momento.
- O contrato do endpoint continua inalterado: `pi_server` e enviado como campo obrigatorio.

## 4. Arquivos criados e alterados

### Criados
| Arquivo | Descricao |
|---|---|
| `frontend/src/constants/pi.ts` | Constante central `DEFAULT_PI_SERVER = "PIMS"` |

### Alterados
| Arquivo | Descricao |
|---|---|
| `frontend/src/pages/PiTagsPage.tsx` | Importa constante; `EMPTY_FORM` usa `DEFAULT_PI_SERVER`; remove input editavel; ~~adiciona display estatico~~; **remove display estatico** (Ajuste Visual); "Nome da tag no PI" ocupa col-md-12; payload usa `DEFAULT_PI_SERVER` no create e fallback no update |
| `frontend/tests/mocks/api.ts` | `piTagFixture.pi_server` alterado de `"PISRV01"` para `"PIMS"`; `apiMock` ganha `updatePiTag`; `piTagsApi.update` mapeado para `apiMock.updatePiTag` |
| `frontend/tests/app.test.tsx` | 6 testes ~~adicionados~~ atualizados: verificam **ausencia** de PI Server no modal; importa `DEFAULT_PI_SERVER` |

### Nao alterados (confirmacao)
- `frontend/src/types/index.ts` — tipos `PiTagCreate`/`PiTagUpdate` mantidos com `pi_server` obrigatorio
- `frontend/src/api/index.ts` — funcoes da API preservadas
- `frontend/src/api/http.ts` — cliente HTTP inalterado
- `backend/` — nenhum arquivo alterado
- `frontend/package.json`, `frontend/package-lock.json` — intactos
- Banco de dados — sem migration, sem alteracao de registros

## 5. Constante utilizada

```typescript
// frontend/src/constants/pi.ts
export const DEFAULT_PI_SERVER = "PIMS" as const;
```

A string `"PIMS"` aparece **uma unica vez** no codigo de producao (na constante). Todos os demais usos referenciam a constante.

## 6. Payload enviado

### Criacao (`POST /api/pi-tags`)
```json
{
  "equipment_id": 1,
  "section_id": 1,
  "variable_type_id": 1,
  "pi_server": "PIMS",
  "pi_tag_name": "RB3.FURNO.TEMP",
  "display_name": "Temperatura do forno",
  "description": null,
  "engineering_unit": "C",
  "data_type": "NUMERIC",
  "active": true
}
```

### Atualizacao (`PUT /api/pi-tags/{id}`)
```json
{
  "equipment_id": 1,
  "section_id": 1,
  "variable_type_id": 1,
  "pi_server": "PIMS",
  "pi_tag_name": "RB3.FURNO.TEMP",
  "display_name": "Temperatura do forno",
  "description": null,
  "engineering_unit": "C",
  "data_type": "NUMERIC",
  "active": true
}
```

O contrato do endpoint permanece o mesmo: `pi_server` continua sendo enviado como campo obrigatorio.

## 7. Tratamento da criacao

`handleSubmit` — ramo `!editing`:

```typescript
const payload: PiTagCreate = {
  ...
  pi_server: DEFAULT_PI_SERVER,
  ...
};
```

O valor vem diretamente da constante, sem depender do estado do formulario.

## 8. Tratamento da edicao

`handleSubmit` — ramo `editing`:

```typescript
const update: PiTagUpdate = {
  ...
  pi_server: form.pi_server.trim() || DEFAULT_PI_SERVER,
  ...
};
```

- Preserva o valor ja cadastrado no registro (copiado do item para `form.pi_server` em `openEdit`).
- Fallback para `DEFAULT_PI_SERVER` apenas se o valor estiver vazio/ausente.

O `openEdit` continua copiando `item.pi_server` para o estado do formulario:
```typescript
pi_server: item.pi_server,
```

## 9. Preservacao de registros existentes

- Nenhuma migration ou script altera registros existentes.
- Nenhum endpoint foi modificado.
- A edicao preserva o valor ja salvo no banco.
- Tags com `pi_server = "LEGACY_SRV"`, `"PISRV01"` ou qualquer outro valor permanecem inalteradas.

## 10. Testes alterados/adicionados

### Testes atualizados em `tests/app.test.tsx`

| Nome do teste | O que verifica |
|---|---|
| `does not show PI Server label, input, or helper text in the create modal` | Modal de criacao **nao** contem "PI Server", `PIMS` nem "Definido automaticamente."; nao ha `<input>` editavel para PI Server |
| `sends DEFAULT_PI_SERVER in the create payload` | Payload de `createPiTag` contem `pi_server: DEFAULT_PI_SERVER` |
| `does not show PI Server info when canceling and reopening the modal` | Apos cancelar e reabrir, modal continua sem informacao de PI Server |
| `does not show PI Server info when editing a tag` | Modal de edicao nao exibe label, valor nem texto auxiliar de PI Server |
| `preserves legacy pi_server value in the update payload when editing` | Tag com `pi_server: "LEGACY_SRV"` preserva o valor no payload de update (nao troca para `PIMS`) |
| `keeps pi_server unchanged in update payload when editing display_name` | Ao editar `display_name`, o `pi_server` no payload de update permanece `DEFAULT_PI_SERVER` |

### Testes alterados

| Arquivo | Alteracao |
|---|---|
| `tests/mocks/api.ts` | `piTagFixture.pi_server` alterado de `"PISRV01"` para `"PIMS"` (reflete Data Archive real) |
| `tests/mocks/api.ts` | Adicionado `updatePiTag` a `apiMock` e `piTagsApi.update` mapeado |

### Testes removidos
Nenhum. Testes antigos foram substituidos por versoes que verificam ausencia visual.

## 11. Resultado exato dos testes

```
 Test Files  11 passed (11)
      Tests  242 passed (242)
```

- 236 testes pre-existentes continuam passando.
- 6 novos testes adicionados.
- 0 falhas.
- Nenhum teste removido.

## 12. Resultado exato do build

```
> pi-analytics-data-frontend@0.1.0 build
> tsc -b && vite build

vite v5.2.6 building for production...
transforming...
✓ 953 modules transformed.
✓ built in 22.56s
```

TypeScript compilation: sem erros.
Vite build: sem erros.
Warnings pre-existentes (chunk size, import misto) inalterados.

## 13. Warnings

- `(!) Some chunks are larger than 500 kB after minification` — pre-existente, fora do escopo.
- `(!) dynamically imported by ... but also statically imported by ...` — pre-existente, fora do escopo.
- Nenhum warning novo introduzido.

## 14. Pendencias

- Nenhuma pendencia tecnica identificada.
- Validacao contra o PI Web API (Fase 2) continua funcionando sem alteracoes.
- O valor `PIMS` e o mesmo `data_server` retornado por `GET /api/pi/health`, mas nao ha validacao cruzada entre os dois; caso o Data Archive mude de nome no futuro, a constante devera ser atualizada manualmente em `frontend/src/constants/pi.ts`.

## 15. Roteiro de validacao manual

1. Abrir "Tags PI" > clicar "Nova tag PI".
2. Verificar que **nao ha** label "PI Server", valor `PIMS` nem texto "Definido automaticamente."
3. Verificar que "Nome da tag no PI" ocupa a largura total do formulario.
4. Preencher equipamento, secao, tipo, nome da tag, nome amigavel.
5. Salvar.
6. Verificar na tabela que a tag foi criada com `PI Server = PIMS`.
7. Editar a tag recem-criada.
8. Verificar que **nao ha** nenhuma informacao de PI Server no modal de edicao.
9. Alterar nome amigavel e salvar.
10. Verificar que `PI Server` permanece `PIMS` na tabela.
11. Cancelar a edicao e abrir novamente — sem info de PI Server.
12. Abrir "Nova tag PI", cancelar, reabrir — sem info de PI Server.
13. (Se existir) Editar tag legada com outro PI Server — verificar que o valor original e preservado no banco (nao foi alterado para `PIMS`).
