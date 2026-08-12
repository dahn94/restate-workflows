"""Esqueleto do workflow de AVM (Automated Valuation Model) para precificação
de imóveis, com auditoria da execução concluída no DynamoDB.

Regras de ouro do Restate (por que o código é assim):
  1. Todo efeito colateral (chamar API, modelo, gravar no banco) vai dentro de
     `ctx.run(...)`. Ele roda UMA vez, o resultado fica no journal do Restate,
     e no replay é apenas relido — não re-executado.
  2. Nada de não-determinístico solto no corpo do handler (datetime.now(),
     uuid4(), random). No replay isso divergiria. Use os helpers do contexto:
       - ctx.key()  -> a key do workflow (bom ID de auditoria, determinístico)
       - ctx.uuid() -> UUID estável entre replays
       - ctx.time() -> timestamp determinístico
  3. DynamoDB = registro de NEGÓCIO da execução concluída (auditoria permanente).
     NÃO é o estado do workflow — quem cuida do estado/durabilidade é o Restate.

Rodar local:  hypercorn --bind 0.0.0.0:9080 app:app
Render:       hypercorn --bind 0.0.0.0:$PORT app:app
AWS Lambda:   handler = app.handler
"""
import os

import boto3
import restate
from restate import Workflow, WorkflowContext

# --- Infra -------------------------------------------------------------------
def _audit_table():
    # Lazy: só cria o cliente quando for gravar, não no import (senão a
    # descoberta do endpoint quebra se não houver região AWS configurada).
    return boto3.resource("dynamodb").Table(os.environ.get("AUDIT_TABLE", "avm_audit"))


# --- Passos (efeitos colaterais — cada um roda dentro de um ctx.run) ---------
def _fetch_comps(req: dict) -> list:
    """Buscar imóveis comparáveis (chamar sua fonte de dados / API)."""
    # TODO: implementar. Retorne a lista de comparáveis.
    raise NotImplementedError


def _price_model(req: dict, comps: list) -> dict:
    """Rodar o modelo de precificação sobre o imóvel + comparáveis."""
    # TODO: implementar. Retorne {"price": ..., "confidence": ..., ...}.
    raise NotImplementedError


def _save_audit(item: dict) -> None:
    """Gravar o registro da execução concluída no DynamoDB (auditoria).

    Idempotente: usa uma chave determinística (valuation_id), então reescrever
    o mesmo item numa retentativa é inofensivo (exactly-once de verdade).
    """
    _audit_table().put_item(Item=item)


# --- Workflow ----------------------------------------------------------------
avm = Workflow("AvmWorkflow")


@avm.main()
async def run(ctx: WorkflowContext, req: dict) -> dict:
    """Precifica um imóvel.

    req (exemplo): {"endereco": ..., "area_m2": ..., "quartos": ..., ...}
    retorna:       {"price": ..., "confidence": ..., ...}
    """
    # 1. Buscar comparáveis (durável, retentável)
    comps = await ctx.run("buscar comparáveis", _fetch_comps, args=(req,))

    # 2. Rodar o modelo (durável)
    result = await ctx.run("rodar modelo", _price_model, args=(req, comps))

    # 3. Execução concluída -> gravar registro de auditoria no DynamoDB.
    #    ctx.run garante: não duplica no replay, não perde num crash (retenta).
    await ctx.run(
        "gravar auditoria",
        _save_audit,
        args=({
            "valuation_id": ctx.key(),   # determinístico -> put idempotente
            "input": req,
            "result": result,
            "ts": ctx.time(),            # timestamp determinístico
        },),
    )

    return result


# --- Endpoint ----------------------------------------------------------------
# request_response: seguro atrás de proxy (Render) e obrigatório no Lambda.
app = restate.app(services=[avm], protocol="request_response")

# Entry point do AWS Lambda (mesmo app). Handler do Lambda = "app.handler".
from restate.aws_lambda import wrap_asgi_as_lambda_handler  # noqa: E402

handler = wrap_asgi_as_lambda_handler(app)
