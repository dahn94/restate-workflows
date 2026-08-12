# Arquitetura do AVM — stack $0

> Documento de decisão. Rascunho para revisar. Ainda **não implementado**.
> Data: 2026-07-14.

## Contexto

AVM (Automated Valuation Model) para precificar imóveis. Volume estimado:
**~30 avaliações/dia**. Restrição dura: **custo $0**.

Característica decisiva do workflow: é **síncrono** — recebe os dados do imóvel,
calcula e devolve o preço em segundos. **Não** espera eventos externos, **não**
tem humano no meio, **não** é uma saga multi-passo de longa duração.

## Decisão: NÃO usar Restate / durable execution

Durable execution (Restate, Temporal, etc.) só compensa quando há espera longa
com humano/evento no meio, sagas com compensação, ou passos externos que
precisam ser exactly-once ao longo de horas/dias. **Nada disso se aplica aqui.**

Para um fluxo "entra → calcula → grava → sai" em segundos, durable execution é
over-engineering: adiciona peças, limites (100k actions/mês, retenção de 1 dia
no plano free) e um servidor a mais, sem benefício.

Retry de falha transitória se resolve com um laço de 3 tentativas. Auditoria se
resolve com um `insert`. Não precisa de journal.

> O exemplo `signup` na raiz do repo e o esqueleto em `avm/` foram feitos com
> Restate durante o aprendizado. Ficam como referência, mas **não** são o
> caminho para o AVM.

## Arquitetura escolhida

Separa os dois regimes de trabalho pelo que cada um faz de melhor:

```
   ┌─────────────────────────┐         ┌──────────────────────────┐
   │  ORACLE Always Free VM   │         │      AWS Lambda          │
   │  (sempre ligada, 24GB)   │         │   (inferência do AVM)    │
   │                          │ modelo  │                          │
   │  treina o modelo ────────┼────────▶│  recebe imóvel           │
   │  (batch, sem pressa)     │ treinado│  → carrega modelo        │
   │                          │         │  → prevê preço           │
   └─────────────────────────┘         │  → grava auditoria ──┐   │
                                        │  → devolve preço      │   │
                                        └───────────────────────┼───┘
                                                                ▼
                                                     ┌────────────────────┐
                                                     │ DynamoDB (auditoria)│
                                                     └────────────────────┘
```

### Componentes

| Componente | Papel | Custo |
|---|---|---|
| **Oracle Cloud Always Free VM** (4 vCPU ARM / 24 GB RAM, sempre ligada) | Treino do modelo (batch, sem pressa) | $0 pra sempre (always-free, não é trial) |
| **AWS Lambda** | Inferência: recebe imóvel → carrega modelo → prevê → grava auditoria → devolve preço | ~$0 (free tier 1M req/mês; 30/dia é trivial). Cold start ~1s é irrelevante para AVM |
| **DynamoDB** | Registro de auditoria das execuções concluídas | $0 pra sempre (free tier always-free: 25 GB, 25 WCU/RCU) |

- **Treino** mora na VM: aguenta trabalho pesado-ish, sem pressão de tempo.
- **Inferência** no Lambda: rápida, escala a zero, praticamente grátis no volume.
- **Auditoria** no Dynamo: mesma nuvem do Lambda, sem gambiarra cross-cloud.

## Ponto em aberto nº 1: como o modelo treinado chega no Lambda

O modelo produzido na Oracle precisa aparecer no Lambda de inferência. Opções,
do mais "$0 pra sempre" ao mais simples:

| Opção | Como funciona | Custo real |
|---|---|---|
| **Oracle Object Storage** (recomendada p/ $0 estrito) | VM sobe o modelo lá (always free, 10 GB); Lambda baixa no cold start e cacheia enquanto quente | $0 pra sempre; cross-cloud (creds + egress, mas egress Oracle é generoso) |
| **Bake no container image** | Modelo entra na imagem do Lambda; retreinou → rebuild + push | ECR ~centavos/mês após os 12 meses de free tier |
| **S3** | VM sobe no S3; Lambda lê | grátis 12 meses, depois ~$0,12/mês (5 GB) |

**Recomendação:** Oracle Object Storage para manter $0 pra sempre.

## Ponto em aberto nº 2: formato do modelo (impacta o peso do Lambda)

Se o AVM for uma **regressão** (linear, XGBoost, etc.), exportar o modelo para um
formato **portátil e leve** (ONNX, ou só os coeficientes num JSON para modelo
linear) deixa o Lambda de inferência **sem sklearn/container pesado** — roda com
numpy puro ou Python puro, vira um zip minúsculo, deploy trivial, sem imagem/ECR.

O peso do treino fica todo na Oracle; o Lambda fica magro.

> Decisão depende do **tipo de modelo** (linear? árvore/XGBoost? outro?) — a
> definir.

## Decisões pendentes (para amanhã)

- [ ] Confirmar o tipo do modelo (define o formato de export e as deps do Lambda).
- [ ] Escolher o mecanismo de entrega do modelo (Object Storage vs bake vs S3).
- [ ] Definir o shape da entrada (`endereco`, `area_m2`, `quartos`, ...) e da
      saída (`price`, `confidence`, ...).
- [ ] Definir esquema da tabela de auditoria no DynamoDB.
- [ ] Confirmar de onde vêm os "comparáveis" (fonte de dados / API).

## Por que isto é $0 honesto (sem asteriscos escondidos)

- Oracle VM: always-free (não é trial de 12 meses).
- Lambda: free tier de 1M req/mês cobre 30/dia com folga gigante.
- DynamoDB: free tier always-free (25 GB) cobre a auditoria.
- Único custo potencial (centavos): ECR/S3, **evitável** usando Oracle Object
  Storage + modelo leve.
