"""BaseIngestWorkflow: download durável do ITBI/IPTU/GeoSampa e montagem da base de SP.

Cada passo é um `ctx.run` (roda uma vez; no replay só é relido do journal). O journal guarda
apenas metadados pequenos (caminho, sha256, bytes), nunca o conteúdo dos arquivos (~500 MB).
A pausa entre downloads é `ctx.sleep` (durável: sobrevive a restart).
A data vem da entrada, nunca de datetime.now() (regra 2 do README).

Lógica testável sem Restate: avm.sources.ingest (pacote avm-caixa-cr12-2026).
Invocar: POST /BaseIngestWorkflow/sp-2026-10-20/run
  {"config": "<abs>/configs/sao_paulo_apartamentos.yaml", "data_referencia": "2026-10-20",
   "anos": [2024, 2025, 2026], "iptu_exercicio": 2026, "manifest": {}, "delay_s": 8.0,
   "tem_iptu": false, "tem_camadas": false}
"""
from datetime import date, timedelta

from restate import Workflow, WorkflowContext

from avm.sources.ingest import IngestOps, anos_a_baixar

base_ingest = Workflow("BaseIngestWorkflow")


@base_ingest.main()
async def run(ctx: WorkflowContext, req: dict) -> dict:
    ops = IngestOps(req["config"])
    data_ref = date.fromisoformat(req["data_referencia"])
    delay = timedelta(seconds=float(req.get("delay_s", 8.0)))

    urls = await ctx.run("listar arquivos ITBI", ops.listar_itbi)
    arquivos = []
    for ano in anos_a_baixar(req["anos"], req.get("manifest", {}), data_ref):
        meta = await ctx.run(f"baixar ITBI {ano}", ops.baixar_itbi, args=(ano, urls[str(ano)]))
        arquivos.append(meta)
        await ctx.sleep(delay)
    if not req.get("tem_iptu", False):
        arquivos.append(await ctx.run("baixar IPTU", ops.baixar_iptu, args=(req["iptu_exercicio"],)))
    if not req.get("tem_camadas", False):
        arquivos += await ctx.run("baixar camadas GeoSampa", ops.baixar_camadas)
    base = await ctx.run("montar base", ops.montar_base)
    return {**base, "arquivos": arquivos, "workflow_key": ctx.key()}
