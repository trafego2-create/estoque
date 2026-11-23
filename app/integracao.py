"""Porta de entrada para outros sistemas da empresa lerem o estoque (hoje: o Radar de Projetos).

Regras:
- o sistema que chama se identifica por uma chave no cabeçalho `X-Chave` (uma chave por
  sistema, em `CHAVES_INTEGRACAO`);
- **nunca** sai valor do equipamento, nota fiscal nem observação do item: isso fica só aqui;
- a única escrita permitida é registrar a entrega de um item a um colaborador, que é o que o
  Radar precisa para fechar um pedido de equipamento. O resto (cadastrar, devolver, baixar)
  continua sendo feito no Brabo Estoque, para ter um único lugar que manda.
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request

from . import config, dados, regras

router = APIRouter(prefix="/api/integracao")

# o que cada item mostra para fora (sem valor, sem nota fiscal, sem observação)
CAMPOS_PUBLICOS = (
    "id", "patrimonio", "tipo", "descricao", "marca", "modelo", "serie", "setor",
    "localizacao", "condicao", "status", "colaborador_id", "colaborador_nome",
    "colaborador_setor", "atualizado_em",
)


def quem_chama(req: Request) -> str:
    """Confere a chave do cabeçalho e devolve o nome do sistema que chamou."""
    chave = (req.headers.get("x-chave") or "").strip()
    if not chave:
        raise HTTPException(401, "Falta a chave de integração.")
    for nome, valor in config.chaves_integracao().items():
        if hmac.compare_digest(chave, valor):
            return nome
    raise HTTPException(401, "Chave de integração não reconhecida.")


def _item_publico(e: dict) -> dict:
    return {campo: e.get(campo) for campo in CAMPOS_PUBLICOS}


@router.get("/estoque")
async def estoque(req: Request):
    """Tudo o que o outro sistema precisa para mostrar o estoque numa tela de leitura."""
    quem_chama(req)
    itens = [_item_publico(e) for e in dados.equipamentos()]
    disponivel_por_tipo: dict[str, int] = {}
    for e in itens:
        if e["status"] == "em_estoque":
            disponivel_por_tipo[e["tipo"]] = disponivel_por_tipo.get(e["tipo"], 0) + 1
    return {
        "resumo": {**regras.resumo_vazio(), **dados.resumo()},
        "itens": itens,
        "disponivel_por_tipo": disponivel_por_tipo,
        "pessoas": [
            {"id": p["id"], "nome": p["nome"], "setor": p["setor"], "itens": p["itens"]}
            for p in dados.colaboradores()
        ],
        "movimentos": [
            {k: m.get(k) for k in ("id", "equipamento_id", "acao", "para_status", "setor",
                                   "observacao", "usuario", "criado_em", "patrimonio", "tipo",
                                   "descricao", "de_nome", "para_nome")}
            for m in dados.ultimos_movimentos(200)
        ],
        "url": config.URL_PUBLICA,
    }


@router.get("/estoque/{eid}/historico")
async def historico(eid: int, req: Request):
    quem_chama(req)
    if not dados.equipamento(eid):
        raise HTTPException(404, "Equipamento não encontrado.")
    return {"historico": dados.historico(eid)}


@router.post("/entregar")
async def entregar(req: Request):
    """Registra que um item saiu para um colaborador. Usado quando o Radar fecha um pedido.

    Aceita o item por `patrimonio` ou por `equipamento_id`, e `origem_id` para o mesmo
    pedido não mover o item duas vezes se a chamada for repetida.
    """
    sistema = quem_chama(req)
    corpo = await req.json()
    if not isinstance(corpo, dict):
        raise HTTPException(400, "Formato inesperado.")

    origem = regras.texto(corpo.get("origem_id"), 80)
    if origem and dados.movimento_por_origem(origem):
        return {"repetido": True}

    nome = regras.texto(corpo.get("colaborador_nome"), 160)
    if not nome:
        raise HTTPException(400, "Diga para qual colaborador o equipamento foi.")

    item = None
    if corpo.get("equipamento_id"):
        item = dados.equipamento(int(corpo["equipamento_id"]))
    elif regras.patrimonio(corpo.get("patrimonio")):
        item = dados.por_patrimonio(regras.patrimonio(corpo["patrimonio"]))
    if not item:
        raise HTTPException(404, "Equipamento não encontrado no estoque.")
    if item["status"] == "baixado":
        raise HTTPException(409, "Esse item está baixado: não pode ser entregue.")

    pessoa = dados.achar_ou_criar_colaborador(
        nome, regras.texto(corpo.get("setor"), 80))
    acao = "transferencia" if item["status"] == "com_colaborador" else "entrega"
    quem_registrou = regras.texto(corpo.get("por"), 120) or sistema
    novo = dados.movimentar(
        item["id"], acao, "com_colaborador", pessoa["id"],
        regras.texto(corpo.get("setor"), 80),
        regras.texto(corpo.get("observacao"), 1000) or f"Registrado pelo {sistema}",
        f"{sistema}:{quem_registrou}", origem)
    return {"equipamento": _item_publico(novo or {}), "acao": acao}
