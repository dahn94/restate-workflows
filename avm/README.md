# AVM Workflow — esqueleto

Workflow de precificação de imóveis (AVM) com Restate, com auditoria da
execução concluída no DynamoDB.

## Separação de responsabilidades

| Papel | Quem cuida |
|-------|-----------|
| **Estado / durabilidade da execução** (onde parou, o que já rodou, retentativas) | **Restate** (journal, no Cloud) |
| **Registro de negócio da execução concluída** (auditoria permanente) | **DynamoDB** (via `ctx.run` no fim do workflow) |

Você **não** salva o estado do workflow no Dynamo — só o *produto* dele.

## As 3 regras que ditam a estrutura do código

1. Todo efeito colateral vai dentro de `ctx.run(...)` → roda uma vez, é
   journalado, e no replay é relido (não re-executado).
2. Nada de não-determinístico solto no handler. Use `ctx.key()`, `ctx.uuid()`,
   `ctx.time()` em vez de `uuid4()`/`datetime.now()`/`random`.
3. Auditoria idempotente: chave determinística (`ctx.key()`) no `put_item`.

## Preencher

- `_fetch_comps(req)` — buscar comparáveis
- `_price_model(req, comps)` — rodar o modelo, retornar o preço
- Ajustar o shape de `req` (entrada) e do resultado

## Deploy

- **Local:** `hypercorn --bind 0.0.0.0:9080 app:app`
- **Render:** start command `hypercorn --bind 0.0.0.0:$PORT app:app`
- **AWS Lambda:** handler = `app.handler` (empacotar como container image por
  causa das deps nativas do `restate-sdk`)

Depois do deploy, registrar a URL/ARN no Restate Cloud (Deployments → Register).

## IAM / credenciais

O código precisa de `dynamodb:PutItem` na tabela (`AUDIT_TABLE`, default
`avm_audit`). No Lambda → na role da função. No Render → via env vars AWS.
